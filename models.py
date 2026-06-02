from sqlalchemy import (
    Column, Integer, String, Float, Boolean, DateTime, Text,
    ForeignKey, Enum, JSON, Table, UniqueConstraint, Index
)
from sqlalchemy.orm import relationship, DeclarativeBase
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import UUID
import uuid
import enum


class Base(DeclarativeBase):
    pass


def gen_uuid():
    return str(uuid.uuid4())


# ─── Enums ────────────────────────────────────────────────────────────────────

class UserRole(str, enum.Enum):
    SUPER_ADMIN = "super_admin"
    ADMIN = "admin"
    STORE_MANAGER = "store_manager"
    CUSTOMER = "customer"


class OrderStatus(str, enum.Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    PROCESSING = "processing"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"


class PaymentStatus(str, enum.Enum):
    PENDING = "pending"
    PAID = "paid"
    FAILED = "failed"
    REFUNDED = "refunded"


class PaymentMethod(str, enum.Enum):
    COD = "cod"
    STRIPE = "stripe"
    PAYPAL = "paypal"


class ProductStatus(str, enum.Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    OUT_OF_STOCK = "out_of_stock"
    DRAFT = "draft"


class CouponType(str, enum.Enum):
    PERCENTAGE = "percentage"
    FIXED = "fixed"
    FREE_SHIPPING = "free_shipping"


class NotificationType(str, enum.Enum):
    ORDER = "order"
    STOCK = "stock"
    REVIEW = "review"
    SYSTEM = "system"


# ─── Association Tables ───────────────────────────────────────────────────────

product_tags = Table(
    "product_tags", Base.metadata,
    Column("product_id", String, ForeignKey("products.id")),
    Column("tag_id", String, ForeignKey("tags.id"))
)

wishlist_items = Table(
    "wishlist_items", Base.metadata,
    Column("user_id", String, ForeignKey("users.id")),
    Column("product_id", String, ForeignKey("products.id"))
)


# ─── Store ────────────────────────────────────────────────────────────────────

class Store(Base):
    __tablename__ = "stores"

    id = Column(String, primary_key=True, default=gen_uuid)
    name = Column(String(200), nullable=False)
    slug = Column(String(200), unique=True, nullable=False)
    description = Column(Text)
    logo_url = Column(String(500))
    banner_url = Column(String(500))
    owner_id = Column(String, ForeignKey("users.id"))
    is_active = Column(Boolean, default=True)
    settings = Column(JSON, default={})
    subscription_plan = Column(String(50), default="free")
    subscription_expires_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    owner = relationship("User", back_populates="stores")
    products = relationship("Product", back_populates="store")
    orders = relationship("Order", back_populates="store")


# ─── User ─────────────────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=gen_uuid)
    email = Column(String(255), unique=True, nullable=False, index=True)
    username = Column(String(100), unique=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    first_name = Column(String(100))
    last_name = Column(String(100))
    phone = Column(String(20))
    avatar_url = Column(String(500))
    role = Column(Enum(UserRole), default=UserRole.CUSTOMER)
    is_active = Column(Boolean, default=True)
    is_verified = Column(Boolean, default=False)
    verification_token = Column(String(255))
    reset_token = Column(String(255))
    reset_token_expires = Column(DateTime(timezone=True))
    preferred_language = Column(String(5), default="en")
    preferred_currency = Column(String(3), default="USD")
    last_login = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    stores = relationship("Store", back_populates="owner")
    addresses = relationship("Address", back_populates="user")
    orders = relationship("Order", back_populates="user")
    reviews = relationship("Review", back_populates="user")
    wishlist = relationship("Product", secondary=wishlist_items)
    notifications = relationship("Notification", back_populates="user")
    refresh_tokens = relationship("RefreshToken", back_populates="user")

    __table_args__ = (
        Index("idx_user_email", "email"),
    )


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    token = Column(String(500), unique=True, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    is_revoked = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="refresh_tokens")


class Address(Base):
    __tablename__ = "addresses"

    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
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


# ─── Category & Brand ─────────────────────────────────────────────────────────

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

    parent = relationship("Category", remote_side="Category.id")
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


# ─── Product ──────────────────────────────────────────────────────────────────

class Product(Base):
    __tablename__ = "products"

    id = Column(String, primary_key=True, default=gen_uuid)
    store_id = Column(String, ForeignKey("stores.id"))
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
    barcode = Column(String(100))
    price = Column(Float, nullable=False)
    old_price = Column(Float)
    cost_price = Column(Float)
    stock_quantity = Column(Integer, default=0)
    low_stock_threshold = Column(Integer, default=5)
    track_inventory = Column(Boolean, default=True)
    weight = Column(Float)
    dimensions = Column(JSON)
    status = Column(Enum(ProductStatus), default=ProductStatus.ACTIVE)
    is_featured = Column(Boolean, default=False)
    is_new = Column(Boolean, default=True)
    is_bestseller = Column(Boolean, default=False)
    views_count = Column(Integer, default=0)
    sales_count = Column(Integer, default=0)
    average_rating = Column(Float, default=0.0)
    reviews_count = Column(Integer, default=0)
    meta_title = Column(String(255))
    meta_description = Column(Text)
    og_image = Column(String(500))
    structured_data = Column(JSON)
    attributes = Column(JSON, default={})
    variants = Column(JSON, default=[])
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    store = relationship("Store", back_populates="products")
    category = relationship("Category", back_populates="products")
    brand = relationship("Brand", back_populates="products")
    images = relationship("ProductImage", back_populates="product", cascade="all, delete-orphan")
    tags = relationship("Tag", secondary=product_tags)
    reviews = relationship("Review", back_populates="product")
    order_items = relationship("OrderItem", back_populates="product")

    __table_args__ = (
        Index("idx_product_status", "status"),
        Index("idx_product_featured", "is_featured"),
        Index("idx_product_category", "category_id"),
    )


class ProductImage(Base):
    __tablename__ = "product_images"

    id = Column(String, primary_key=True, default=gen_uuid)
    product_id = Column(String, ForeignKey("products.id"), nullable=False)
    url = Column(String(500), nullable=False)
    thumbnail_url = Column(String(500))
    alt_text = Column(String(255))
    sort_order = Column(Integer, default=0)
    is_primary = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    product = relationship("Product", back_populates="images")


# ─── Review ───────────────────────────────────────────────────────────────────

class Review(Base):
    __tablename__ = "reviews"

    id = Column(String, primary_key=True, default=gen_uuid)
    product_id = Column(String, ForeignKey("products.id"), nullable=False)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    rating = Column(Integer, nullable=False)
    title = Column(String(255))
    body = Column(Text)
    is_verified_purchase = Column(Boolean, default=False)
    is_approved = Column(Boolean, default=True)
    helpful_count = Column(Integer, default=0)
    images = Column(JSON, default=[])
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    product = relationship("Product", back_populates="reviews")
    user = relationship("User", back_populates="reviews")

    __table_args__ = (
        UniqueConstraint("product_id", "user_id", name="uq_review_product_user"),
    )


# ─── Coupon ───────────────────────────────────────────────────────────────────

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
    applicable_products = Column(JSON, default=[])
    applicable_categories = Column(JSON, default=[])
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    orders = relationship("Order", back_populates="coupon")


# ─── Order ────────────────────────────────────────────────────────────────────

class Order(Base):
    __tablename__ = "orders"

    id = Column(String, primary_key=True, default=gen_uuid)
    order_number = Column(String(50), unique=True, nullable=False)
    store_id = Column(String, ForeignKey("stores.id"))
    user_id = Column(String, ForeignKey("users.id"))
    coupon_id = Column(String, ForeignKey("coupons.id"))
    status = Column(Enum(OrderStatus), default=OrderStatus.PENDING)
    payment_status = Column(Enum(PaymentStatus), default=PaymentStatus.PENDING)
    payment_method = Column(Enum(PaymentMethod), nullable=False)
    payment_intent_id = Column(String(255))
    subtotal = Column(Float, nullable=False)
    discount_amount = Column(Float, default=0)
    shipping_cost = Column(Float, default=0)
    tax_amount = Column(Float, default=0)
    total = Column(Float, nullable=False)
    currency = Column(String(3), default="USD")
    exchange_rate = Column(Float, default=1.0)
    shipping_address = Column(JSON, nullable=False)
    billing_address = Column(JSON)
    notes = Column(Text)
    tracking_number = Column(String(100))
    carrier = Column(String(100))
    estimated_delivery = Column(DateTime(timezone=True))
    delivered_at = Column(DateTime(timezone=True))
    cancelled_at = Column(DateTime(timezone=True))
    cancellation_reason = Column(Text)
    ip_address = Column(String(50))
    user_agent = Column(String(500))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    store = relationship("Store", back_populates="orders")
    user = relationship("User", back_populates="orders")
    coupon = relationship("Coupon", back_populates="orders")
    items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")
    history = relationship("OrderHistory", back_populates="order", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_order_user", "user_id"),
        Index("idx_order_status", "status"),
    )


class OrderItem(Base):
    __tablename__ = "order_items"

    id = Column(String, primary_key=True, default=gen_uuid)
    order_id = Column(String, ForeignKey("orders.id"), nullable=False)
    product_id = Column(String, ForeignKey("products.id"), nullable=False)
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
    order_id = Column(String, ForeignKey("orders.id"), nullable=False)
    status = Column(String(50), nullable=False)
    note = Column(Text)
    created_by = Column(String, ForeignKey("users.id"))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    order = relationship("Order", back_populates="history")


# ─── Notification ─────────────────────────────────────────────────────────────

class Notification(Base):
    __tablename__ = "notifications"

    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    type = Column(Enum(NotificationType), nullable=False)
    title = Column(String(255), nullable=False)
    message = Column(Text)
    data = Column(JSON)
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="notifications")


# ─── Subscription Plan ────────────────────────────────────────────────────────

class SubscriptionPlan(Base):
    __tablename__ = "subscription_plans"

    id = Column(String, primary_key=True, default=gen_uuid)
    name = Column(String(100), nullable=False)
    slug = Column(String(100), unique=True, nullable=False)
    price_monthly = Column(Float, nullable=False)
    price_yearly = Column(Float)
    features = Column(JSON, default=[])
    max_products = Column(Integer, default=100)
    max_orders_per_month = Column(Integer)
    commission_rate = Column(Float, default=0)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# ─── Analytics ────────────────────────────────────────────────────────────────

class Analytics(Base):
    __tablename__ = "analytics"

    id = Column(String, primary_key=True, default=gen_uuid)
    store_id = Column(String, ForeignKey("stores.id"))
    date = Column(DateTime(timezone=True), nullable=False)
    page_views = Column(Integer, default=0)
    unique_visitors = Column(Integer, default=0)
    orders_count = Column(Integer, default=0)
    revenue = Column(Float, default=0)
    conversion_rate = Column(Float, default=0)
    data = Column(JSON, default={})

    __table_args__ = (
        UniqueConstraint("store_id", "date", name="uq_analytics_store_date"),
    )
