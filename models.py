from sqlalchemy import (
    Column, Integer, String, Float, Boolean, DateTime, Text,
    ForeignKey, Enum, JSON, Table, UniqueConstraint, Index
)
from sqlalchemy.orm import relationship, DeclarativeBase
from sqlalchemy.sql import func
import uuid, enum as pyenum


class Base(DeclarativeBase):
    pass


def gen_uuid():
    return str(uuid.uuid4())


# ── Enums ──────────────────────────────────────────────────────────────────────

class UserRole(str, pyenum.Enum):
    SUPER_ADMIN = "super_admin"
    ADMIN = "admin"
    STORE_MANAGER = "store_manager"
    CUSTOMER = "customer"


class OrderStatus(str, pyenum.Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    PROCESSING = "processing"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"


class PaymentStatus(str, pyenum.Enum):
    PENDING = "pending"
    PAID = "paid"
    FAILED = "failed"
    REFUNDED = "refunded"


class PaymentMethod(str, pyenum.Enum):
    COD = "cod"
    STRIPE = "stripe"
    PAYPAL = "paypal"


class ProductStatus(str, pyenum.Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    DRAFT = "draft"
    OUT_OF_STOCK = "out_of_stock"


class CouponType(str, pyenum.Enum):
    PERCENTAGE = "percentage"
    FIXED = "fixed"
    FREE_SHIPPING = "free_shipping"


# ── Association Tables ─────────────────────────────────────────────────────────

product_tags = Table(
    "product_tags", Base.metadata,
    Column("product_id", String, ForeignKey("products.id", ondelete="CASCADE")),
    Column("tag_id", String, ForeignKey("tags.id", ondelete="CASCADE"))
)

wishlist_items = Table(
    "wishlist_items", Base.metadata,
    Column("user_id", String, ForeignKey("users.id", ondelete="CASCADE")),
    Column("product_id", String, ForeignKey("products.id", ondelete="CASCADE"))
)


# ── User ───────────────────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=gen_uuid)
    email = Column(String(255), unique=True, nullable=False, index=True)
    username = Column(String(100), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    first_name = Column(String(100))
    last_name = Column(String(100))
    phone = Column(String(20))
    avatar_url = Column(String(500))
    role = Column(Enum(UserRole), default=UserRole.CUSTOMER, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    is_verified = Column(Boolean, default=False, nullable=False)
    verification_token = Column(String(255))
    reset_token = Column(String(255))
    reset_token_expires = Column(DateTime(timezone=True))
    preferred_language = Column(String(5), default="en")
    preferred_currency = Column(String(3), default="USD")
    last_login = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    addresses = relationship("Address", back_populates="user", cascade="all, delete-orphan")
    orders = relationship("Order", back_populates="user")
    reviews = relationship("Review", back_populates="user")
    wishlist = relationship("Product", secondary=wishlist_items)
    notifications = relationship("Notification", back_populates="user", cascade="all, delete-orphan")
    refresh_tokens = relationship("RefreshToken", back_populates="user", cascade="all, delete-orphan")


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token = Column(String(600), unique=True, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    is_revoked = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="refresh_tokens")


class Address(Base):
    __tablename__ = "addresses"

    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    label = Column(String(50), default="Home")
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    phone = Column(String(20))
    address_line1 = Column(String(255), nullable=False)
    address_line2 = Column(String(255))
    city = Column(String(100), nullable=False)
    state = Column(String(100))
    postal_code = Column(String(20))
    country = Column(String(100), nullable=False)
    is_default = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="addresses")


# ── Category & Brand ───────────────────────────────────────────────────────────

class Category(Base):
    __tablename__ = "categories"

    id = Column(String, primary_key=True, default=gen_uuid)
    name_en = Column(String(200), nullable=False)
    name_ar = Column(String(200))
    slug = Column(String(200), unique=True, nullable=False)
    description_en = Column(Text)
    description_ar = Column(Text)
    image_url = Column(String(500))
    parent_id = Column(String, ForeignKey("categories.id"))
    sort_order = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    meta_title = Column(String(255))
    meta_description = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    parent = relationship("Category", remote_side="Category.id", back_populates="children")
    children = relationship("Category", back_populates="parent")
    products = relationship("Product", back_populates="category")


class Brand(Base):
    __tablename__ = "brands"

    id = Column(String, primary_key=True, default=gen_uuid)
    name = Column(String(200), nullable=False)
    slug = Column(String(200), unique=True, nullable=False)
    description = Column(Text)
    logo_url = Column(String(500))
    website = Column(String(255))
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    products = relationship("Product", back_populates="brand")


class Tag(Base):
    __tablename__ = "tags"

    id = Column(String, primary_key=True, default=gen_uuid)
    name = Column(String(100), unique=True, nullable=False)
    slug = Column(String(100), unique=True, nullable=False)


# ── Product ────────────────────────────────────────────────────────────────────

class Product(Base):
    __tablename__ = "products"

    id = Column(String, primary_key=True, default=gen_uuid)
    category_id = Column(String, ForeignKey("categories.id"))
    brand_id = Column(String, ForeignKey("brands.id"))
    name_en = Column(String(500), nullable=False)
    name_ar = Column(String(500))
    slug = Column(String(500), unique=True, nullable=False)
    description_en = Column(Text)
    description_ar = Column(Text)
    short_description_en = Column(String(500))
    short_description_ar = Column(String(500))
    sku = Column(String(100), unique=True)
    price = Column(Float, nullable=False)
    old_price = Column(Float)
    cost_price = Column(Float)
    stock_quantity = Column(Integer, default=0, nullable=False)
    low_stock_threshold = Column(Integer, default=5)
    track_inventory = Column(Boolean, default=True)
    weight = Column(Float)
    dimensions = Column(JSON)
    status = Column(Enum(ProductStatus), default=ProductStatus.ACTIVE, nullable=False)
    is_featured = Column(Boolean, default=False)
    is_new = Column(Boolean, default=True)
    is_bestseller = Column(Boolean, default=False)
    views_count = Column(Integer, default=0)
    sales_count = Column(Integer, default=0)
    average_rating = Column(Float, default=0.0)
    reviews_count = Column(Integer, default=0)
    meta_title = Column(String(255))
    meta_description = Column(Text)
    attributes = Column(JSON, default={})
    variants = Column(JSON, default=[])
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    category = relationship("Category", back_populates="products")
    brand = relationship("Brand", back_populates="products")
    images = relationship("ProductImage", back_populates="product", cascade="all, delete-orphan", order_by="ProductImage.sort_order")
    tags = relationship("Tag", secondary=product_tags)
    reviews = relationship("Review", back_populates="product")
    order_items = relationship("OrderItem", back_populates="product")

    __table_args__ = (
        Index("idx_product_status", "status"),
        Index("idx_product_featured", "is_featured"),
        Index("idx_product_category", "category_id"),
        Index("idx_product_slug", "slug"),
    )


class ProductImage(Base):
    __tablename__ = "product_images"

    id = Column(String, primary_key=True, default=gen_uuid)
    product_id = Column(String, ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    url = Column(String(500), nullable=False)
    thumbnail_url = Column(String(500))
    alt_text = Column(String(255))
    sort_order = Column(Integer, default=0)
    is_primary = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    product = relationship("Product", back_populates="images")


# ── Review ─────────────────────────────────────────────────────────────────────

class Review(Base):
    __tablename__ = "reviews"

    id = Column(String, primary_key=True, default=gen_uuid)
    product_id = Column(String, ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    rating = Column(Integer, nullable=False)
    title = Column(String(255))
    body = Column(Text)
    is_verified_purchase = Column(Boolean, default=False)
    is_approved = Column(Boolean, default=True)
    helpful_count = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    product = relationship("Product", back_populates="reviews")
    user = relationship("User", back_populates="reviews")

    __table_args__ = (
        UniqueConstraint("product_id", "user_id", name="uq_review_product_user"),
    )


# ── Coupon ─────────────────────────────────────────────────────────────────────

class Coupon(Base):
    __tablename__ = "coupons"

    id = Column(String, primary_key=True, default=gen_uuid)
    code = Column(String(50), unique=True, nullable=False)
    name = Column(String(200))
    type = Column(Enum(CouponType), nullable=False)
    value = Column(Float, nullable=False)
    min_purchase = Column(Float, default=0)
    max_discount = Column(Float)
    usage_limit = Column(Integer)
    usage_count = Column(Integer, default=0)
    per_user_limit = Column(Integer, default=1)
    is_active = Column(Boolean, default=True)
    starts_at = Column(DateTime(timezone=True))
    expires_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    orders = relationship("Order", back_populates="coupon")


# ── Order ──────────────────────────────────────────────────────────────────────

class Order(Base):
    __tablename__ = "orders"

    id = Column(String, primary_key=True, default=gen_uuid)
    order_number = Column(String(50), unique=True, nullable=False, index=True)
    user_id = Column(String, ForeignKey("users.id"))
    coupon_id = Column(String, ForeignKey("coupons.id"))
    status = Column(Enum(OrderStatus), default=OrderStatus.PENDING, nullable=False)
    payment_status = Column(Enum(PaymentStatus), default=PaymentStatus.PENDING, nullable=False)
    payment_method = Column(Enum(PaymentMethod), nullable=False)
    payment_intent_id = Column(String(255))
    paypal_order_id = Column(String(255))
    subtotal = Column(Float, nullable=False)
    discount_amount = Column(Float, default=0)
    shipping_cost = Column(Float, default=0)
    tax_amount = Column(Float, default=0)
    total = Column(Float, nullable=False)
    currency = Column(String(3), default="USD")
    shipping_address = Column(JSON, nullable=False)
    billing_address = Column(JSON)
    notes = Column(Text)
    tracking_number = Column(String(100))
    carrier = Column(String(100))
    estimated_delivery = Column(DateTime(timezone=True))
    delivered_at = Column(DateTime(timezone=True))
    ip_address = Column(String(50))
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    user = relationship("User", back_populates="orders")
    coupon = relationship("Coupon", back_populates="orders")
    items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")
    history = relationship("OrderHistory", back_populates="order", cascade="all, delete-orphan", order_by="OrderHistory.created_at")

    __table_args__ = (
        Index("idx_order_user", "user_id"),
        Index("idx_order_status", "status"),
        Index("idx_order_payment_status", "payment_status"),
    )


class OrderItem(Base):
    __tablename__ = "order_items"

    id = Column(String, primary_key=True, default=gen_uuid)
    order_id = Column(String, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False)
    product_id = Column(String, ForeignKey("products.id"))
    product_name = Column(String(500), nullable=False)
    product_image = Column(String(500))
    sku = Column(String(100))
    variant = Column(JSON)
    quantity = Column(Integer, nullable=False)
    unit_price = Column(Float, nullable=False)
    total_price = Column(Float, nullable=False)

    order = relationship("Order", back_populates="items")
    product = relationship("Product", back_populates="order_items")


class OrderHistory(Base):
    __tablename__ = "order_history"

    id = Column(String, primary_key=True, default=gen_uuid)
    order_id = Column(String, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False)
    status = Column(String(50), nullable=False)
    note = Column(Text)
    created_by = Column(String, ForeignKey("users.id"))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    order = relationship("Order", back_populates="history")


# ── Notification ───────────────────────────────────────────────────────────────

class Notification(Base):
    __tablename__ = "notifications"

    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    type = Column(String(50), nullable=False)
    title = Column(String(255), nullable=False)
    message = Column(Text)
    data = Column(JSON)
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="notifications")


# ── ShippingZone ───────────────────────────────────────────────────────────────

class ShippingZone(Base):
    __tablename__ = "shipping_zones"

    id = Column(String, primary_key=True, default=gen_uuid)
    name = Column(String(100), nullable=False)
    countries = Column(JSON, default=[])  # list of ISO country codes
    base_cost = Column(Float, nullable=False)
    per_kg_cost = Column(Float, default=0)
    free_above = Column(Float)
    estimated_days_min = Column(Integer, default=3)
    estimated_days_max = Column(Integer, default=7)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# ── Analytics ──────────────────────────────────────────────────────────────────

class DailyAnalytics(Base):
    __tablename__ = "daily_analytics"

    id = Column(String, primary_key=True, default=gen_uuid)
    date = Column(String(10), unique=True, nullable=False)  # YYYY-MM-DD
    page_views = Column(Integer, default=0)
    unique_visitors = Column(Integer, default=0)
    orders_count = Column(Integer, default=0)
    revenue = Column(Float, default=0)
    new_customers = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
