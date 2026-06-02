from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_, and_
from typing import Optional, List
from app.db.models.models import Product, ProductImage, Category, Brand, Tag, UserRole
from app.db.database import get_db
from app.api.v1.dependencies.auth import get_current_user, require_admin
from app.services.file_service import save_product_image
from app.services.product_service import generate_slug, update_product_stats
from python_slugify import slugify
import uuid

router = APIRouter(prefix="/products", tags=["Products"])


@router.get("")
async def list_products(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    category: Optional[str] = None,
    brand: Optional[str] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    is_featured: Optional[bool] = None,
    is_new: Optional[bool] = None,
    is_bestseller: Optional[bool] = None,
    search: Optional[str] = None,
    sort: str = "created_at",
    order: str = "desc",
    lang: str = "en",
    db: AsyncSession = Depends(get_db)
):
    query = select(Product).where(Product.status == "active")

    if category:
        query = query.where(Product.category_id == category)
    if brand:
        query = query.where(Product.brand_id == brand)
    if min_price is not None:
        query = query.where(Product.price >= min_price)
    if max_price is not None:
        query = query.where(Product.price <= max_price)
    if is_featured is not None:
        query = query.where(Product.is_featured == is_featured)
    if is_new is not None:
        query = query.where(Product.is_new == is_new)
    if is_bestseller is not None:
        query = query.where(Product.is_bestseller == is_bestseller)
    if search:
        search_term = f"%{search}%"
        query = query.where(
            or_(
                Product.name_en.ilike(search_term),
                Product.name_ar.ilike(search_term),
                Product.description_en.ilike(search_term)
            )
        )

    # Sorting
    sort_col = getattr(Product, sort, Product.created_at)
    if order == "desc":
        query = query.order_by(sort_col.desc())
    else:
        query = query.order_by(sort_col.asc())

    # Count total
    count_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = count_result.scalar()

    # Paginate
    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    products = result.scalars().all()

    return {
        "items": products,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page
    }


@router.get("/{slug}")
async def get_product(slug: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Product).where(Product.slug == slug))
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    # Increment view count
    product.views_count += 1
    await db.commit()

    return product


@router.post("", status_code=201)
async def create_product(
    name_en: str = Form(...),
    name_ar: Optional[str] = Form(None),
    description_en: Optional[str] = Form(None),
    description_ar: Optional[str] = Form(None),
    price: float = Form(...),
    old_price: Optional[float] = Form(None),
    stock_quantity: int = Form(0),
    category_id: Optional[str] = Form(None),
    brand_id: Optional[str] = Form(None),
    sku: Optional[str] = Form(None),
    is_featured: bool = Form(False),
    is_new: bool = Form(True),
    images: List[UploadFile] = File([]),
    current_user=Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    slug = await generate_slug(name_en, db)
    product = Product(
        id=str(uuid.uuid4()),
        name_en=name_en,
        name_ar=name_ar,
        slug=slug,
        description_en=description_en,
        description_ar=description_ar,
        price=price,
        old_price=old_price,
        stock_quantity=stock_quantity,
        category_id=category_id,
        brand_id=brand_id,
        sku=sku or str(uuid.uuid4())[:8].upper(),
        is_featured=is_featured,
        is_new=is_new,
    )
    db.add(product)
    await db.flush()

    # Handle images
    for i, image in enumerate(images):
        url = await save_product_image(image, product.id)
        img = ProductImage(
            id=str(uuid.uuid4()),
            product_id=product.id,
            url=url,
            sort_order=i,
            is_primary=(i == 0)
        )
        db.add(img)

    await db.commit()
    await db.refresh(product)
    return product


@router.put("/{product_id}")
async def update_product(
    product_id: str,
    current_user=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    **kwargs
):
    result = await db.execute(select(Product).where(Product.id == product_id))
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    for key, value in kwargs.items():
        if hasattr(product, key) and value is not None:
            setattr(product, key, value)

    await db.commit()
    return product


@router.delete("/{product_id}")
async def delete_product(
    product_id: str,
    current_user=Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Product).where(Product.id == product_id))
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    await db.delete(product)
    await db.commit()
    return {"message": "Product deleted"}


@router.get("/{product_id}/related")
async def get_related_products(
    product_id: str,
    limit: int = 8,
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Product).where(Product.id == product_id))
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    related = await db.execute(
        select(Product).where(
            and_(
                Product.category_id == product.category_id,
                Product.id != product_id,
                Product.status == "active"
            )
        ).limit(limit)
    )
    return related.scalars().all()
