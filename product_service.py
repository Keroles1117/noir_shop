from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.db.models.models import Product, Review
from loguru import logger
import re, uuid


async def generate_slug(name: str, db: AsyncSession, existing_id: str = None) -> str:
    """Generate unique URL slug from product name."""
    # Convert to slug
    slug = name.lower().strip()
    slug = re.sub(r'[^\w\s-]', '', slug)
    slug = re.sub(r'[\s_-]+', '-', slug)
    slug = slug.strip('-')

    # Ensure uniqueness
    base_slug = slug
    counter = 1
    while True:
        query = select(Product).where(Product.slug == slug)
        if existing_id:
            query = query.where(Product.id != existing_id)
        result = await db.execute(query)
        if not result.scalar_one_or_none():
            break
        slug = f"{base_slug}-{counter}"
        counter += 1

    return slug


async def update_product_rating(product_id: str, db: AsyncSession):
    """Recalculate and update product average rating."""
    result = await db.execute(
        select(func.avg(Review.rating), func.count(Review.id))
        .where(Review.product_id == product_id, Review.is_approved == True)
    )
    avg_rating, count = result.one()

    product_result = await db.execute(select(Product).where(Product.id == product_id))
    product = product_result.scalar_one_or_none()
    if product:
        product.average_rating = round(float(avg_rating or 0), 1)
        product.reviews_count = count or 0
        await db.flush()


def format_product_response(product: Product, lang: str = "en") -> dict:
    """Format product for API response with correct language."""
    primary_image = None
    images = []

    for img in (product.images or []):
        img_data = {"id": img.id, "url": img.url, "thumbnail_url": img.thumbnail_url,
                    "alt_text": img.alt_text, "is_primary": img.is_primary}
        if img.is_primary:
            primary_image = img_data
        images.append(img_data)

    if not primary_image and images:
        primary_image = images[0]

    discount_pct = None
    if product.old_price and product.old_price > product.price:
        discount_pct = round((1 - product.price / product.old_price) * 100)

    return {
        "id": product.id,
        "slug": product.slug,
        "name": product.name_ar if lang == "ar" and product.name_ar else product.name_en,
        "name_en": product.name_en,
        "name_ar": product.name_ar,
        "description": product.description_ar if lang == "ar" and product.description_ar else product.description_en,
        "short_description": product.short_description_ar if lang == "ar" and product.short_description_ar else product.short_description_en,
        "price": product.price,
        "old_price": product.old_price,
        "discount_percent": discount_pct,
        "currency": "USD",
        "sku": product.sku,
        "stock_quantity": product.stock_quantity,
        "in_stock": product.stock_quantity > 0 or not product.track_inventory,
        "is_featured": product.is_featured,
        "is_new": product.is_new,
        "is_bestseller": product.is_bestseller,
        "status": product.status,
        "average_rating": product.average_rating,
        "reviews_count": product.reviews_count,
        "views_count": product.views_count,
        "sales_count": product.sales_count,
        "primary_image": primary_image,
        "images": images,
        "category": {"id": product.category.id, "name": product.category.name_ar if lang == "ar" and product.category.name_ar else product.category.name_en} if product.category else None,
        "brand": {"id": product.brand.id, "name": product.brand.name, "logo": product.brand.logo_url} if product.brand else None,
        "attributes": product.attributes,
        "variants": product.variants,
        "meta_title": product.meta_title or product.name_en,
        "meta_description": product.meta_description,
        "created_at": product.created_at.isoformat() if product.created_at else None,
        "updated_at": product.updated_at.isoformat() if product.updated_at else None,
    }
