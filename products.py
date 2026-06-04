from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_, and_, update
from sqlalchemy.orm import selectinload
from typing import Optional, List
from app.db.database import get_db
from app.db.models.models import Product, ProductImage, Category, Brand, ProductStatus
from app.api.v1.dependencies.auth import get_current_user, require_admin, get_current_user_optional
from app.services.file_service import upload_product_image, delete_file
from app.services.product_service import generate_slug, update_product_rating, format_product_response
import uuid

router = APIRouter(prefix="/products", tags=["Products"])


def _load_options():
    return (
        selectinload(Product.images),
        selectinload(Product.category),
        selectinload(Product.brand),
        selectinload(Product.tags),
    )


# ── List Products ──────────────────────────────────────────────────────────────

@router.get("")
async def list_products(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    category_id: Optional[str] = None,
    brand_id: Optional[str] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    min_rating: Optional[float] = None,
    in_stock: Optional[bool] = None,
    is_featured: Optional[bool] = None,
    is_new: Optional[bool] = None,
    is_bestseller: Optional[bool] = None,
    search: Optional[str] = None,
    sort: str = "created_at",
    order: str = "desc",
    lang: str = "en",
    db: AsyncSession = Depends(get_db),
):
    query = (
        select(Product)
        .where(Product.status == ProductStatus.ACTIVE)
        .options(*_load_options())
    )

    if category_id:
        query = query.where(Product.category_id == category_id)
    if brand_id:
        query = query.where(Product.brand_id == brand_id)
    if min_price is not None:
        query = query.where(Product.price >= min_price)
    if max_price is not None:
        query = query.where(Product.price <= max_price)
    if min_rating is not None:
        query = query.where(Product.average_rating >= min_rating)
    if in_stock is True:
        query = query.where(Product.stock_quantity > 0)
    if is_featured is not None:
        query = query.where(Product.is_featured == is_featured)
    if is_new is not None:
        query = query.where(Product.is_new == is_new)
    if is_bestseller is not None:
        query = query.where(Product.is_bestseller == is_bestseller)
    if search:
        term = f"%{search}%"
        query = query.where(
            or_(
                Product.name_en.ilike(term),
                Product.name_ar.ilike(term),
                Product.description_en.ilike(term),
                Product.sku.ilike(term),
            )
        )

    # Sorting
    sort_map = {
        "price": Product.price, "created_at": Product.created_at,
        "rating": Product.average_rating, "sales": Product.sales_count,
        "views": Product.views_count, "name": Product.name_en,
    }
    sort_col = sort_map.get(sort, Product.created_at)
    query = query.order_by(sort_col.desc() if order == "desc" else sort_col.asc())

    # Count
    count_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = count_result.scalar()

    # Paginate
    result = await db.execute(query.offset((page - 1) * per_page).limit(per_page))
    products = result.scalars().all()

    return {
        "items": [format_product_response(p, lang) for p in products],
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": max(1, (total + per_page - 1) // per_page),
    }


# ── Get Single Product ─────────────────────────────────────────────────────────

@router.get("/{slug_or_id}")
async def get_product(
    slug_or_id: str,
    lang: str = "en",
    db: AsyncSession = Depends(get_db),
):
    query = (
        select(Product)
        .options(*_load_options(), selectinload(Product.reviews))
        .where(
            or_(Product.slug == slug_or_id, Product.id == slug_or_id),
            Product.status == ProductStatus.ACTIVE,
        )
    )
    result = await db.execute(query)
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(404, "Product not found")

    # Increment view count
    await db.execute(
        update(Product).where(Product.id == product.id).values(views_count=Product.views_count + 1)
    )
    await db.commit()
    await db.refresh(product)

    data = format_product_response(product, lang)

    # Add SEO structured data
    data["structured_data"] = {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": product.name_en,
        "description": product.description_en or "",
        "sku": product.sku,
        "offers": {
            "@type": "Offer",
            "price": product.price,
            "priceCurrency": "USD",
            "availability": "https://schema.org/InStock" if product.stock_quantity > 0 else "https://schema.org/OutOfStock",
        },
        "aggregateRating": {
            "@type": "AggregateRating",
            "ratingValue": product.average_rating,
            "reviewCount": product.reviews_count,
        } if product.reviews_count > 0 else None,
    }

    return data


# ── Related Products ───────────────────────────────────────────────────────────

@router.get("/{product_id}/related")
async def get_related_products(
    product_id: str,
    limit: int = Query(8, ge=1, le=20),
    lang: str = "en",
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Product).where(Product.id == product_id))
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(404, "Product not found")

    related_result = await db.execute(
        select(Product)
        .options(*_load_options())
        .where(
            and_(
                Product.category_id == product.category_id,
                Product.id != product_id,
                Product.status == ProductStatus.ACTIVE,
            )
        )
        .limit(limit)
    )
    return [format_product_response(p, lang) for p in related_result.scalars().all()]


# ── Create Product (Admin) ─────────────────────────────────────────────────────

@router.post("", status_code=201)
async def create_product(
    name_en: str = Form(...),
    name_ar: Optional[str] = Form(None),
    description_en: Optional[str] = Form(None),
    description_ar: Optional[str] = Form(None),
    short_description_en: Optional[str] = Form(None),
    short_description_ar: Optional[str] = Form(None),
    price: float = Form(...),
    old_price: Optional[float] = Form(None),
    cost_price: Optional[float] = Form(None),
    stock_quantity: int = Form(0),
    low_stock_threshold: int = Form(5),
    track_inventory: bool = Form(True),
    category_id: Optional[str] = Form(None),
    brand_id: Optional[str] = Form(None),
    sku: Optional[str] = Form(None),
    weight: Optional[float] = Form(None),
    is_featured: bool = Form(False),
    is_new: bool = Form(True),
    meta_title: Optional[str] = Form(None),
    meta_description: Optional[str] = Form(None),
    images: List[UploadFile] = File(default=[]),
    current_user=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    if price < 0:
        raise HTTPException(400, "Price cannot be negative")
    if stock_quantity < 0:
        raise HTTPException(400, "Stock cannot be negative")

    slug = await generate_slug(name_en, db)
    product_id = str(uuid.uuid4())

    product = Product(
        id=product_id,
        name_en=name_en,
        name_ar=name_ar,
        slug=slug,
        description_en=description_en,
        description_ar=description_ar,
        short_description_en=short_description_en,
        short_description_ar=short_description_ar,
        price=round(price, 2),
        old_price=round(old_price, 2) if old_price else None,
        cost_price=round(cost_price, 2) if cost_price else None,
        stock_quantity=stock_quantity,
        low_stock_threshold=low_stock_threshold,
        track_inventory=track_inventory,
        category_id=category_id or None,
        brand_id=brand_id or None,
        sku=sku or str(uuid.uuid4())[:8].upper(),
        weight=weight,
        is_featured=is_featured,
        is_new=is_new,
        status=ProductStatus.ACTIVE,
        meta_title=meta_title or name_en,
        meta_description=meta_description,
    )
    db.add(product)
    await db.flush()

    # Upload images
    for i, image_file in enumerate(images):
        if image_file.filename:
            img_data = await upload_product_image(image_file, product_id)
            db.add(ProductImage(
                id=str(uuid.uuid4()),
                product_id=product_id,
                url=img_data["url"],
                thumbnail_url=img_data["thumbnail_url"],
                sort_order=i,
                is_primary=(i == 0),
            ))

    await db.commit()

    result = await db.execute(
        select(Product).options(*_load_options()).where(Product.id == product_id)
    )
    return format_product_response(result.scalar_one(), "en")


# ── Update Product (Admin) ─────────────────────────────────────────────────────

@router.put("/{product_id}")
async def update_product(
    product_id: str,
    name_en: Optional[str] = Form(None),
    name_ar: Optional[str] = Form(None),
    description_en: Optional[str] = Form(None),
    description_ar: Optional[str] = Form(None),
    price: Optional[float] = Form(None),
    old_price: Optional[float] = Form(None),
    stock_quantity: Optional[int] = Form(None),
    category_id: Optional[str] = Form(None),
    brand_id: Optional[str] = Form(None),
    is_featured: Optional[bool] = Form(None),
    is_new: Optional[bool] = Form(None),
    is_bestseller: Optional[bool] = Form(None),
    status: Optional[str] = Form(None),
    meta_title: Optional[str] = Form(None),
    meta_description: Optional[str] = Form(None),
    new_images: List[UploadFile] = File(default=[]),
    current_user=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Product).options(*_load_options()).where(Product.id == product_id)
    )
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(404, "Product not found")

    # Update fields
    fields = {"name_en": name_en, "name_ar": name_ar, "description_en": description_en,
              "description_ar": description_ar, "category_id": category_id, "brand_id": brand_id,
              "is_featured": is_featured, "is_new": is_new, "is_bestseller": is_bestseller,
              "meta_title": meta_title, "meta_description": meta_description}

    for key, val in fields.items():
        if val is not None:
            setattr(product, key, val)

    if price is not None:
        if price < 0:
            raise HTTPException(400, "Price cannot be negative")
        product.price = round(price, 2)
    if old_price is not None:
        product.old_price = round(old_price, 2)
    if stock_quantity is not None:
        if stock_quantity < 0:
            raise HTTPException(400, "Stock cannot be negative")
        product.stock_quantity = stock_quantity
    if status:
        try:
            product.status = ProductStatus(status)
        except ValueError:
            raise HTTPException(400, f"Invalid status. Valid: {[s.value for s in ProductStatus]}")
    if name_en and name_en != product.name_en:
        product.slug = await generate_slug(name_en, db, existing_id=product_id)

    # Upload new images
    current_count = len(product.images)
    for i, image_file in enumerate(new_images):
        if image_file.filename:
            img_data = await upload_product_image(image_file, product_id)
            db.add(ProductImage(
                id=str(uuid.uuid4()),
                product_id=product_id,
                url=img_data["url"],
                thumbnail_url=img_data["thumbnail_url"],
                sort_order=current_count + i,
                is_primary=(current_count == 0 and i == 0),
            ))

    await db.commit()
    result = await db.execute(
        select(Product).options(*_load_options()).where(Product.id == product_id)
    )
    return format_product_response(result.scalar_one(), "en")


# ── Delete Product (Admin) ─────────────────────────────────────────────────────

@router.delete("/{product_id}")
async def delete_product(
    product_id: str,
    current_user=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Product).options(selectinload(Product.images)).where(Product.id == product_id)
    )
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(404, "Product not found")

    for img in product.images:
        await delete_file(img.url)

    await db.delete(product)
    await db.commit()
    return {"message": "Product deleted successfully"}


# ── Delete Product Image (Admin) ───────────────────────────────────────────────

@router.delete("/{product_id}/images/{image_id}")
async def delete_product_image(
    product_id: str,
    image_id: str,
    current_user=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ProductImage).where(
            ProductImage.id == image_id, ProductImage.product_id == product_id
        )
    )
    img = result.scalar_one_or_none()
    if not img:
        raise HTTPException(404, "Image not found")

    await delete_file(img.url)
    await db.delete(img)
    await db.commit()
    return {"message": "Image deleted"}


# ── Set Primary Image (Admin) ──────────────────────────────────────────────────

@router.patch("/{product_id}/images/{image_id}/set-primary")
async def set_primary_image(
    product_id: str,
    image_id: str,
    current_user=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    # Unset all primary
    await db.execute(
        update(ProductImage)
        .where(ProductImage.product_id == product_id)
        .values(is_primary=False)
    )
    # Set new primary
    await db.execute(
        update(ProductImage)
        .where(ProductImage.id == image_id, ProductImage.product_id == product_id)
        .values(is_primary=True)
    )
    await db.commit()
    return {"message": "Primary image updated"}
