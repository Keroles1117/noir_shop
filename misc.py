from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from typing import Optional
from pydantic import BaseModel, field_validator
from app.db.database import get_db
from app.db.models.models import Category, Brand, Coupon, Review, Product, User, Address, Notification
from app.api.v1.dependencies.auth import get_current_user, require_admin
from app.services.file_service import upload_category_image, upload_brand_logo
from app.core.security import security_utils
import uuid, re
from datetime import datetime, timezone

# ══════════════════════════════════════════════════════════════════════════════
#  CATEGORIES
# ══════════════════════════════════════════════════════════════════════════════

categories_router = APIRouter(prefix="/categories", tags=["Categories"])


class CategoryCreate(BaseModel):
    name_en: str
    name_ar: Optional[str] = None
    description_en: Optional[str] = None
    description_ar: Optional[str] = None
    parent_id: Optional[str] = None
    sort_order: int = 0
    meta_title: Optional[str] = None
    meta_description: Optional[str] = None


def _slug(name: str) -> str:
    slug = name.lower().strip()
    slug = re.sub(r'[^\w\s-]', '', slug)
    return re.sub(r'[\s_]+', '-', slug).strip('-')


@categories_router.get("")
async def list_categories(
    include_inactive: bool = False,
    db: AsyncSession = Depends(get_db),
):
    query = select(Category).options(selectinload(Category.children))
    if not include_inactive:
        query = query.where(Category.is_active == True)
    query = query.order_by(Category.sort_order)
    result = await db.execute(query)
    cats = result.scalars().all()

    def fmt(c):
        return {
            "id": c.id, "name_en": c.name_en, "name_ar": c.name_ar,
            "slug": c.slug, "image_url": c.image_url, "parent_id": c.parent_id,
            "sort_order": c.sort_order, "is_active": c.is_active,
            "meta_title": c.meta_title, "meta_description": c.meta_description,
            "children": [fmt(ch) for ch in (c.children or [])],
        }

    return [fmt(c) for c in cats if not c.parent_id]


@categories_router.post("", status_code=201)
async def create_category(
    data: CategoryCreate,
    image: Optional[UploadFile] = File(None),
    current_user=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    cat_id = str(uuid.uuid4())
    image_url = None
    if image and image.filename:
        image_url = await upload_category_image(image, cat_id)

    # Ensure unique slug
    base_slug = _slug(data.name_en)
    slug = base_slug
    counter = 1
    while True:
        r = await db.execute(select(Category).where(Category.slug == slug))
        if not r.scalar_one_or_none():
            break
        slug = f"{base_slug}-{counter}"
        counter += 1

    cat = Category(id=cat_id, slug=slug, image_url=image_url, **data.model_dump())
    db.add(cat)
    await db.commit()
    await db.refresh(cat)
    return cat


@categories_router.put("/{cat_id}")
async def update_category(
    cat_id: str,
    name_en: Optional[str] = Form(None),
    name_ar: Optional[str] = Form(None),
    description_en: Optional[str] = Form(None),
    description_ar: Optional[str] = Form(None),
    sort_order: Optional[int] = Form(None),
    is_active: Optional[bool] = Form(None),
    image: Optional[UploadFile] = File(None),
    current_user=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Category).where(Category.id == cat_id))
    cat = result.scalar_one_or_none()
    if not cat:
        raise HTTPException(404, "Category not found")

    for field, val in {"name_en": name_en, "name_ar": name_ar,
                       "description_en": description_en, "description_ar": description_ar,
                       "sort_order": sort_order, "is_active": is_active}.items():
        if val is not None:
            setattr(cat, field, val)

    if image and image.filename:
        cat.image_url = await upload_category_image(image, cat_id)

    await db.commit()
    await db.refresh(cat)
    return cat


@categories_router.delete("/{cat_id}")
async def delete_category(cat_id: str, current_user=Depends(require_admin), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Category).where(Category.id == cat_id))
    cat = result.scalar_one_or_none()
    if not cat:
        raise HTTPException(404, "Category not found")
    await db.delete(cat)
    await db.commit()
    return {"message": "Category deleted"}


# ══════════════════════════════════════════════════════════════════════════════
#  BRANDS
# ══════════════════════════════════════════════════════════════════════════════

brands_router = APIRouter(prefix="/brands", tags=["Brands"])


@brands_router.get("")
async def list_brands(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Brand).where(Brand.is_active == True).order_by(Brand.name))
    brands = result.scalars().all()
    return [{"id": b.id, "name": b.name, "slug": b.slug, "logo_url": b.logo_url,
             "website": b.website, "description": b.description} for b in brands]


@brands_router.post("", status_code=201)
async def create_brand(
    name: str = Form(...),
    description: Optional[str] = Form(None),
    website: Optional[str] = Form(None),
    logo: Optional[UploadFile] = File(None),
    current_user=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    brand_id = str(uuid.uuid4())
    logo_url = None
    if logo and logo.filename:
        logo_url = await upload_brand_logo(logo, brand_id)

    base_slug = _slug(name)
    slug = base_slug
    counter = 1
    while True:
        r = await db.execute(select(Brand).where(Brand.slug == slug))
        if not r.scalar_one_or_none():
            break
        slug = f"{base_slug}-{counter}"
        counter += 1

    brand = Brand(id=brand_id, name=name, slug=slug, description=description,
                  website=website, logo_url=logo_url)
    db.add(brand)
    await db.commit()
    await db.refresh(brand)
    return brand


@brands_router.delete("/{brand_id}")
async def delete_brand(brand_id: str, current_user=Depends(require_admin), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Brand).where(Brand.id == brand_id))
    brand = result.scalar_one_or_none()
    if not brand:
        raise HTTPException(404, "Brand not found")
    await db.delete(brand)
    await db.commit()
    return {"message": "Brand deleted"}


# ══════════════════════════════════════════════════════════════════════════════
#  COUPONS
# ══════════════════════════════════════════════════════════════════════════════

coupons_router = APIRouter(prefix="/coupons", tags=["Coupons"])


class CouponCreate(BaseModel):
    code: str
    name: Optional[str] = None
    type: str  # percentage | fixed | free_shipping
    value: float
    min_purchase: float = 0
    max_discount: Optional[float] = None
    usage_limit: Optional[int] = None
    per_user_limit: int = 1
    starts_at: Optional[str] = None
    expires_at: Optional[str] = None

    @field_validator("code")
    @classmethod
    def validate_code(cls, v):
        return v.upper().strip()

    @field_validator("value")
    @classmethod
    def validate_value(cls, v):
        if v <= 0:
            raise ValueError("Value must be positive")
        return round(v, 2)

    @field_validator("type")
    @classmethod
    def validate_type(cls, v):
        if v not in ("percentage", "fixed", "free_shipping"):
            raise ValueError("Type must be: percentage, fixed, or free_shipping")
        if v == "percentage" and v > 100:
            raise ValueError("Percentage cannot exceed 100")
        return v


@coupons_router.get("")
async def list_coupons(current_user=Depends(require_admin), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Coupon).order_by(Coupon.created_at.desc()))
    coupons = result.scalars().all()
    return [{
        "id": c.id, "code": c.code, "name": c.name, "type": c.type.value,
        "value": c.value, "min_purchase": c.min_purchase, "usage_count": c.usage_count,
        "usage_limit": c.usage_limit, "is_active": c.is_active,
        "expires_at": c.expires_at.isoformat() if c.expires_at else None,
    } for c in coupons]


@coupons_router.post("/validate")
async def validate_coupon(data: dict, db: AsyncSession = Depends(get_db)):
    code = data.get("code", "").upper()
    subtotal = float(data.get("subtotal", 0))

    result = await db.execute(select(Coupon).where(Coupon.code == code, Coupon.is_active == True))
    coupon = result.scalar_one_or_none()
    if not coupon:
        raise HTTPException(400, "Invalid coupon code")
    if coupon.expires_at and coupon.expires_at < datetime.now(timezone.utc):
        raise HTTPException(400, "Coupon has expired")
    if coupon.usage_limit and coupon.usage_count >= coupon.usage_limit:
        raise HTTPException(400, "Coupon usage limit reached")
    if subtotal < (coupon.min_purchase or 0):
        raise HTTPException(400, f"Minimum purchase ${coupon.min_purchase:.2f} required")

    discount = 0.0
    if coupon.type.value == "percentage":
        discount = min(subtotal * coupon.value / 100, coupon.max_discount or float('inf'))
    elif coupon.type.value == "fixed":
        discount = min(coupon.value, subtotal)

    return {
        "valid": True, "code": coupon.code, "type": coupon.type.value,
        "value": coupon.value, "discount_amount": round(discount, 2),
        "message": f"Coupon applied! You save ${discount:.2f}",
    }


@coupons_router.post("", status_code=201)
async def create_coupon(data: CouponCreate, current_user=Depends(require_admin), db: AsyncSession = Depends(get_db)):
    from app.db.models.models import CouponType
    r = await db.execute(select(Coupon).where(Coupon.code == data.code))
    if r.scalar_one_or_none():
        raise HTTPException(400, "Coupon code already exists")

    coupon = Coupon(
        id=str(uuid.uuid4()), code=data.code, name=data.name,
        type=CouponType(data.type), value=data.value, min_purchase=data.min_purchase,
        max_discount=data.max_discount, usage_limit=data.usage_limit,
        per_user_limit=data.per_user_limit,
        starts_at=datetime.fromisoformat(data.starts_at) if data.starts_at else None,
        expires_at=datetime.fromisoformat(data.expires_at) if data.expires_at else None,
    )
    db.add(coupon)
    await db.commit()
    await db.refresh(coupon)
    return coupon


@coupons_router.delete("/{coupon_id}")
async def delete_coupon(coupon_id: str, current_user=Depends(require_admin), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Coupon).where(Coupon.id == coupon_id))
    coupon = result.scalar_one_or_none()
    if not coupon:
        raise HTTPException(404, "Coupon not found")
    await db.delete(coupon)
    await db.commit()
    return {"message": "Coupon deleted"}


# ══════════════════════════════════════════════════════════════════════════════
#  REVIEWS
# ══════════════════════════════════════════════════════════════════════════════

reviews_router = APIRouter(prefix="/reviews", tags=["Reviews"])


class ReviewCreate(BaseModel):
    product_id: str
    rating: int
    title: Optional[str] = None
    body: Optional[str] = None

    @field_validator("rating")
    @classmethod
    def validate_rating(cls, v):
        if not 1 <= v <= 5:
            raise ValueError("Rating must be between 1 and 5")
        return v


@reviews_router.get("/product/{product_id}")
async def get_product_reviews(
    product_id: str,
    page: int = 1,
    per_page: int = 10,
    db: AsyncSession = Depends(get_db),
):
    query = (
        select(Review)
        .options(selectinload(Review.user))
        .where(Review.product_id == product_id, Review.is_approved == True)
        .order_by(Review.created_at.desc())
    )
    total_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = total_result.scalar()
    result = await db.execute(query.offset((page - 1) * per_page).limit(per_page))
    reviews = result.scalars().all()

    avg_result = await db.execute(
        select(func.avg(Review.rating)).where(Review.product_id == product_id, Review.is_approved == True)
    )
    avg = avg_result.scalar() or 0

    return {
        "average_rating": round(float(avg), 1),
        "total": total,
        "page": page,
        "items": [{
            "id": r.id, "rating": r.rating, "title": r.title, "body": r.body,
            "is_verified_purchase": r.is_verified_purchase,
            "created_at": r.created_at.isoformat(),
            "user": {"name": f"{r.user.first_name} {r.user.last_name[0]}.", "avatar": r.user.avatar_url} if r.user else None,
        } for r in reviews],
    }


@reviews_router.post("", status_code=201)
async def create_review(
    data: ReviewCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.db.models.models import OrderItem, OrderStatus
    # Check duplicate
    r = await db.execute(
        select(Review).where(Review.product_id == data.product_id, Review.user_id == current_user.id)
    )
    if r.scalar_one_or_none():
        raise HTTPException(400, "You have already reviewed this product")

    # Check if verified purchase
    purchase_check = await db.execute(
        select(OrderItem)
        .join(OrderItem.order)
        .where(
            OrderItem.product_id == data.product_id,
            OrderItem.order.has(user_id=current_user.id),
        )
    )
    is_verified = purchase_check.scalar_one_or_none() is not None

    review = Review(
        id=str(uuid.uuid4()),
        product_id=data.product_id,
        user_id=current_user.id,
        rating=data.rating,
        title=security_utils.sanitize(data.title) if data.title else None,
        body=security_utils.sanitize(data.body) if data.body else None,
        is_verified_purchase=is_verified,
    )
    db.add(review)
    await db.flush()
    await db.commit()

    # Update product rating
    from app.services.product_service import update_product_rating
    async with db.begin_nested():
        await update_product_rating(data.product_id, db)
    await db.commit()

    return {"message": "Review submitted successfully", "id": review.id}


@reviews_router.delete("/{review_id}")
async def delete_review(
    review_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Review).where(Review.id == review_id))
    review = result.scalar_one_or_none()
    if not review:
        raise HTTPException(404, "Review not found")
    if review.user_id != current_user.id and current_user.role.value not in ("admin", "super_admin"):
        raise HTTPException(403, "Not authorized")
    await db.delete(review)
    await db.commit()
    return {"message": "Review deleted"}


# ══════════════════════════════════════════════════════════════════════════════
#  USERS / PROFILE
# ══════════════════════════════════════════════════════════════════════════════

users_router = APIRouter(prefix="/users", tags=["Users"])


class ProfileUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None
    preferred_language: Optional[str] = None
    preferred_currency: Optional[str] = None


class AddressCreate(BaseModel):
    label: str = "Home"
    first_name: str
    last_name: str
    phone: Optional[str] = None
    address_line1: str
    address_line2: Optional[str] = None
    city: str
    state: Optional[str] = None
    postal_code: Optional[str] = None
    country: str
    is_default: bool = False


@users_router.get("/me")
async def get_profile(current_user: User = Depends(get_current_user)):
    return {
        "id": current_user.id, "email": current_user.email, "username": current_user.username,
        "first_name": current_user.first_name, "last_name": current_user.last_name,
        "phone": current_user.phone, "avatar_url": current_user.avatar_url,
        "role": current_user.role.value, "is_verified": current_user.is_verified,
        "preferred_language": current_user.preferred_language,
        "preferred_currency": current_user.preferred_currency,
        "last_login": current_user.last_login.isoformat() if current_user.last_login else None,
        "created_at": current_user.created_at.isoformat(),
    }


@users_router.put("/me")
async def update_profile(
    data: ProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    valid_langs = ["en", "ar"]
    valid_currencies = ["USD", "EUR", "GBP", "SAR", "AED"]

    if data.preferred_language and data.preferred_language not in valid_langs:
        raise HTTPException(400, f"Language must be one of: {valid_langs}")
    if data.preferred_currency and data.preferred_currency not in valid_currencies:
        raise HTTPException(400, f"Currency must be one of: {valid_currencies}")

    for field, val in data.model_dump(exclude_none=True).items():
        setattr(current_user, field, security_utils.sanitize(str(val)) if isinstance(val, str) else val)

    await db.commit()
    return {"message": "Profile updated"}


@users_router.get("/me/addresses")
async def get_addresses(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Address).where(Address.user_id == current_user.id).order_by(Address.is_default.desc())
    )
    return result.scalars().all()


@users_router.post("/me/addresses", status_code=201)
async def add_address(
    data: AddressCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if data.is_default:
        from sqlalchemy import update as sql_update
        await db.execute(
            sql_update(Address).where(Address.user_id == current_user.id).values(is_default=False)
        )

    addr = Address(id=str(uuid.uuid4()), user_id=current_user.id, **data.model_dump())
    db.add(addr)
    await db.commit()
    await db.refresh(addr)
    return addr


@users_router.delete("/me/addresses/{address_id}")
async def delete_address(
    address_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Address).where(Address.id == address_id, Address.user_id == current_user.id)
    )
    addr = result.scalar_one_or_none()
    if not addr:
        raise HTTPException(404, "Address not found")
    await db.delete(addr)
    await db.commit()
    return {"message": "Address deleted"}


@users_router.get("/me/wishlist")
async def get_wishlist(
    lang: str = "en",
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy.orm import selectinload
    result = await db.execute(
        select(User)
        .options(selectinload(User.wishlist).selectinload(Product.images))
        .where(User.id == current_user.id)
    )
    user = result.scalar_one()
    from app.services.product_service import format_product_response
    return [format_product_response(p, lang) for p in user.wishlist]


@users_router.post("/me/wishlist/{product_id}")
async def toggle_wishlist(
    product_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy.orm import selectinload
    result = await db.execute(
        select(User).options(selectinload(User.wishlist)).where(User.id == current_user.id)
    )
    user = result.scalar_one()

    prod_result = await db.execute(select(Product).where(Product.id == product_id))
    product = prod_result.scalar_one_or_none()
    if not product:
        raise HTTPException(404, "Product not found")

    is_in_wishlist = any(p.id == product_id for p in user.wishlist)
    if is_in_wishlist:
        user.wishlist = [p for p in user.wishlist if p.id != product_id]
        action = "removed"
    else:
        user.wishlist.append(product)
        action = "added"

    await db.commit()
    return {"action": action, "product_id": product_id}


@users_router.get("/me/notifications")
async def get_notifications(
    page: int = 1,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Notification)
        .where(Notification.user_id == current_user.id)
        .order_by(Notification.created_at.desc())
        .offset((page - 1) * 20).limit(20)
    )
    notifs = result.scalars().all()
    unread = sum(1 for n in notifs if not n.is_read)
    return {"items": notifs, "unread_count": unread}


@users_router.post("/me/notifications/mark-read")
async def mark_notifications_read(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import update as sql_update
    await db.execute(
        sql_update(Notification)
        .where(Notification.user_id == current_user.id, Notification.is_read == False)
        .values(is_read=True)
    )
    await db.commit()
    return {"message": "All notifications marked as read"}


# ── Admin: List Users ──────────────────────────────────────────────────────────

@users_router.get("/admin/all")
async def admin_list_users(
    page: int = 1,
    per_page: int = 20,
    search: Optional[str] = None,
    current_user=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    query = select(User).order_by(User.created_at.desc())
    if search:
        term = f"%{search}%"
        query = query.where(
            User.email.ilike(term) | User.username.ilike(term) |
            User.first_name.ilike(term) | User.last_name.ilike(term)
        )
    total_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = total_result.scalar()
    result = await db.execute(query.offset((page - 1) * per_page).limit(per_page))
    users = result.scalars().all()
    return {
        "items": [{
            "id": u.id, "email": u.email, "username": u.username,
            "first_name": u.first_name, "last_name": u.last_name,
            "role": u.role.value, "is_active": u.is_active, "is_verified": u.is_verified,
            "last_login": u.last_login.isoformat() if u.last_login else None,
            "created_at": u.created_at.isoformat(),
        } for u in users],
        "total": total, "page": page, "per_page": per_page,
    }


@users_router.patch("/admin/{user_id}/toggle-active")
async def admin_toggle_user(
    user_id: str,
    current_user=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(404, "User not found")
    if user.role.value == "super_admin":
        raise HTTPException(403, "Cannot modify super admin")
    user.is_active = not user.is_active
    await db.commit()
    return {"message": f"User {'activated' if user.is_active else 'deactivated'}", "is_active": user.is_active}
