from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, update
from sqlalchemy.orm import selectinload
from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel, field_validator
from app.db.database import get_db
from app.db.models.models import (
    Order, OrderItem, OrderHistory, Product, Coupon, User,
    OrderStatus, PaymentStatus, PaymentMethod
)
from app.api.v1.dependencies.auth import get_current_user, require_admin
from app.services.email_service import send_order_confirmation, send_order_status_update
from app.services.payment_service import (
    create_stripe_payment_intent, confirm_stripe_payment,
    create_paypal_order, capture_paypal_order,
    calculate_shipping, calculate_tax
)
import uuid, random, string

router = APIRouter(prefix="/orders", tags=["Orders"])


# ── Schemas ────────────────────────────────────────────────────────────────────

class AddressIn(BaseModel):
    first_name: str
    last_name: str
    phone: Optional[str] = None
    address_line1: str
    address_line2: Optional[str] = None
    city: str
    state: Optional[str] = None
    postal_code: Optional[str] = None
    country: str

    @field_validator("first_name", "last_name", "address_line1", "city", "country")
    @classmethod
    def not_empty(cls, v):
        if not v or not v.strip():
            raise ValueError("Required field")
        return v.strip()


class OrderItemIn(BaseModel):
    product_id: str
    quantity: int
    variant: Optional[dict] = None

    @field_validator("quantity")
    @classmethod
    def valid_qty(cls, v):
        if v < 1:
            raise ValueError("Quantity must be at least 1")
        if v > 50:
            raise ValueError("Maximum 50 per item")
        return v


class OrderCreate(BaseModel):
    items: list[OrderItemIn]
    shipping_address: AddressIn
    billing_address: Optional[AddressIn] = None
    payment_method: str
    payment_intent_id: Optional[str] = None
    paypal_order_id: Optional[str] = None
    coupon_code: Optional[str] = None
    notes: Optional[str] = None
    currency: str = "USD"

    @field_validator("items")
    @classmethod
    def validate_items(cls, v):
        if not v:
            raise ValueError("Cart is empty")
        if len(v) > 50:
            raise ValueError("Too many items")
        return v

    @field_validator("payment_method")
    @classmethod
    def validate_payment(cls, v):
        valid = ["cod", "stripe", "paypal"]
        if v not in valid:
            raise ValueError(f"Payment method must be one of: {valid}")
        return v


class OrderStatusUpdate(BaseModel):
    status: str
    note: Optional[str] = None
    tracking_number: Optional[str] = None
    carrier: Optional[str] = None
    estimated_delivery: Optional[str] = None


# ── Helper ─────────────────────────────────────────────────────────────────────

def generate_order_number() -> str:
    ts = datetime.now().strftime("%y%m%d")
    rnd = ''.join(random.choices(string.digits + string.ascii_uppercase, k=6))
    return f"SDN-{ts}-{rnd}"


def _format_order(order: Order) -> dict:
    return {
        "id": order.id,
        "order_number": order.order_number,
        "status": order.status.value,
        "payment_status": order.payment_status.value,
        "payment_method": order.payment_method.value,
        "subtotal": order.subtotal,
        "discount_amount": order.discount_amount,
        "shipping_cost": order.shipping_cost,
        "tax_amount": order.tax_amount,
        "total": order.total,
        "currency": order.currency,
        "shipping_address": order.shipping_address,
        "billing_address": order.billing_address,
        "notes": order.notes,
        "tracking_number": order.tracking_number,
        "carrier": order.carrier,
        "estimated_delivery": order.estimated_delivery.isoformat() if order.estimated_delivery else None,
        "created_at": order.created_at.isoformat(),
        "updated_at": order.updated_at.isoformat() if order.updated_at else None,
        "items": [
            {
                "id": item.id,
                "product_id": item.product_id,
                "product_name": item.product_name,
                "product_image": item.product_image,
                "sku": item.sku,
                "variant": item.variant,
                "quantity": item.quantity,
                "unit_price": item.unit_price,
                "total_price": item.total_price,
            }
            for item in (order.items or [])
        ],
        "history": [
            {
                "status": h.status,
                "note": h.note,
                "created_at": h.created_at.isoformat(),
            }
            for h in (order.history or [])
        ],
    }


# ── Create Order ───────────────────────────────────────────────────────────────

@router.post("", status_code=201)
async def create_order(
    data: OrderCreate,
    background_tasks: BackgroundTasks,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # ── Validate products & calculate subtotal ──────────────────────────────
    subtotal = 0.0
    order_items_data = []
    total_weight = 0.0

    for item in data.items:
        result = await db.execute(
            select(Product)
            .options(selectinload(Product.images))
            .where(Product.id == item.product_id)
        )
        product = result.scalar_one_or_none()
        if not product:
            raise HTTPException(404, f"Product {item.product_id} not found")
        if product.status.value != "active":
            raise HTTPException(400, f"'{product.name_en}' is not available")
        if product.track_inventory and product.stock_quantity < item.quantity:
            raise HTTPException(
                400,
                f"Only {product.stock_quantity} units available for '{product.name_en}'"
            )

        item_total = round(product.price * item.quantity, 2)
        subtotal += item_total
        total_weight += (product.weight or 0) * item.quantity

        primary_img = next((i.url for i in product.images if i.is_primary), None)
        if not primary_img and product.images:
            primary_img = product.images[0].url

        order_items_data.append({
            "product": product,
            "quantity": item.quantity,
            "unit_price": product.price,
            "total_price": item_total,
            "variant": item.variant,
            "primary_image": primary_img,
        })

    subtotal = round(subtotal, 2)

    # ── Apply coupon ────────────────────────────────────────────────────────
    discount_amount = 0.0
    coupon = None
    if data.coupon_code:
        result = await db.execute(
            select(Coupon).where(
                Coupon.code == data.coupon_code.upper(),
                Coupon.is_active == True,
            )
        )
        coupon = result.scalar_one_or_none()
        if not coupon:
            raise HTTPException(400, "Invalid coupon code")
        if coupon.expires_at and coupon.expires_at < datetime.now(timezone.utc):
            raise HTTPException(400, "This coupon has expired")
        if coupon.usage_limit and coupon.usage_count >= coupon.usage_limit:
            raise HTTPException(400, "Coupon usage limit reached")
        if subtotal < (coupon.min_purchase or 0):
            raise HTTPException(400, f"Minimum order of ${coupon.min_purchase:.2f} required for this coupon")

        if coupon.type.value == "percentage":
            discount_amount = subtotal * (coupon.value / 100)
            if coupon.max_discount:
                discount_amount = min(discount_amount, coupon.max_discount)
        elif coupon.type.value == "fixed":
            discount_amount = min(coupon.value, subtotal)
        elif coupon.type.value == "free_shipping":
            discount_amount = 0  # Applied to shipping below

        discount_amount = round(discount_amount, 2)

    # ── Calculate shipping ──────────────────────────────────────────────────
    country_code = data.shipping_address.country
    shipping_info = await calculate_shipping(country_code, subtotal - discount_amount, total_weight)
    shipping_cost = 0.0 if coupon and coupon.type.value == "free_shipping" else shipping_info["cost"]

    # ── Calculate tax ───────────────────────────────────────────────────────
    taxable_amount = subtotal - discount_amount
    tax_amount = calculate_tax(taxable_amount, country_code)

    # ── Final total ─────────────────────────────────────────────────────────
    total = round(subtotal - discount_amount + shipping_cost + tax_amount, 2)

    # ── Create Order ────────────────────────────────────────────────────────
    order = Order(
        id=str(uuid.uuid4()),
        order_number=generate_order_number(),
        user_id=current_user.id,
        coupon_id=coupon.id if coupon else None,
        payment_method=PaymentMethod(data.payment_method),
        status=OrderStatus.PENDING,
        payment_status=PaymentStatus.PENDING,
        subtotal=subtotal,
        discount_amount=discount_amount,
        shipping_cost=shipping_cost,
        tax_amount=tax_amount,
        total=total,
        currency=data.currency,
        shipping_address=data.shipping_address.model_dump(),
        billing_address=data.billing_address.model_dump() if data.billing_address else None,
        notes=data.notes,
        ip_address=request.client.host if request.client else None,
    )
    db.add(order)
    await db.flush()

    # ── Add items & reduce stock ────────────────────────────────────────────
    for item_data in order_items_data:
        db.add(OrderItem(
            id=str(uuid.uuid4()),
            order_id=order.id,
            product_id=item_data["product"].id,
            product_name=item_data["product"].name_en,
            product_image=item_data["primary_image"],
            sku=item_data["product"].sku,
            variant=item_data["variant"],
            quantity=item_data["quantity"],
            unit_price=item_data["unit_price"],
            total_price=item_data["total_price"],
        ))
        if item_data["product"].track_inventory:
            await db.execute(
                update(Product)
                .where(Product.id == item_data["product"].id)
                .values(
                    stock_quantity=Product.stock_quantity - item_data["quantity"],
                    sales_count=Product.sales_count + item_data["quantity"],
                )
            )

    # ── History ─────────────────────────────────────────────────────────────
    db.add(OrderHistory(
        id=str(uuid.uuid4()),
        order_id=order.id,
        status="created",
        note=f"Order placed via {data.payment_method.upper()}",
        created_by=current_user.id,
    ))

    # ── Update coupon ───────────────────────────────────────────────────────
    if coupon:
        coupon.usage_count += 1

    # ── Process Stripe payment ──────────────────────────────────────────────
    if data.payment_method == "stripe" and data.payment_intent_id:
        is_paid = await confirm_stripe_payment(data.payment_intent_id)
        if is_paid:
            order.payment_status = PaymentStatus.PAID
            order.payment_intent_id = data.payment_intent_id
            order.status = OrderStatus.CONFIRMED
            db.add(OrderHistory(
                id=str(uuid.uuid4()),
                order_id=order.id,
                status="confirmed",
                note="Payment confirmed via Stripe",
            ))

    # ── Process PayPal payment ──────────────────────────────────────────────
    elif data.payment_method == "paypal" and data.paypal_order_id:
        is_captured = await capture_paypal_order(data.paypal_order_id)
        if is_captured:
            order.payment_status = PaymentStatus.PAID
            order.paypal_order_id = data.paypal_order_id
            order.status = OrderStatus.CONFIRMED
            db.add(OrderHistory(
                id=str(uuid.uuid4()),
                order_id=order.id,
                status="confirmed",
                note="Payment captured via PayPal",
            ))

    await db.commit()

    # ── Reload with relations ───────────────────────────────────────────────
    result = await db.execute(
        select(Order)
        .options(selectinload(Order.items), selectinload(Order.history))
        .where(Order.id == order.id)
    )
    order = result.scalar_one()

    # ── Send confirmation email ─────────────────────────────────────────────
    background_tasks.add_task(
        send_order_confirmation,
        current_user.email,
        f"{current_user.first_name} {current_user.last_name}",
        order.order_number,
        order.items,
        order.total,
        data.payment_method,
    )

    return _format_order(order)


# ── Stripe Payment Intent ──────────────────────────────────────────────────────

@router.post("/payment/stripe/create-intent")
async def stripe_create_intent(
    data: dict,
    current_user: User = Depends(get_current_user),
):
    amount = data.get("amount")
    currency = data.get("currency", "USD")
    order_id = data.get("order_id", "pending")

    if not amount or float(amount) <= 0:
        raise HTTPException(400, "Invalid amount")

    result = await create_stripe_payment_intent(float(amount), currency, order_id, current_user.email)
    return result


# ── PayPal Create Order ────────────────────────────────────────────────────────

@router.post("/payment/paypal/create-order")
async def paypal_create_order(
    data: dict,
    current_user: User = Depends(get_current_user),
):
    amount = data.get("amount")
    currency = data.get("currency", "USD")
    order_id = data.get("order_id", "pending")

    result = await create_paypal_order(float(amount), currency, order_id)
    return result


# ── Stripe Webhook ─────────────────────────────────────────────────────────────

@router.post("/webhooks/stripe")
async def stripe_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    from app.services.payment_service import handle_stripe_webhook

    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    event = await handle_stripe_webhook(payload, sig_header)
    event_type = event.get("type")
    obj = event.get("data", {})

    if event_type == "payment_intent.succeeded":
        payment_intent_id = obj.get("id")
        order_result = await db.execute(
            select(Order).where(Order.payment_intent_id == payment_intent_id)
        )
        order = order_result.scalar_one_or_none()
        if order:
            order.payment_status = PaymentStatus.PAID
            order.status = OrderStatus.CONFIRMED
            db.add(OrderHistory(
                id=str(uuid.uuid4()),
                order_id=order.id,
                status="confirmed",
                note="Payment confirmed via Stripe webhook",
            ))
            await db.commit()

    elif event_type == "payment_intent.payment_failed":
        payment_intent_id = obj.get("id")
        order_result = await db.execute(
            select(Order).where(Order.payment_intent_id == payment_intent_id)
        )
        order = order_result.scalar_one_or_none()
        if order:
            order.payment_status = PaymentStatus.FAILED
            await db.commit()

    return {"received": True}


# ── My Orders ──────────────────────────────────────────────────────────────────

@router.get("/my-orders")
async def my_orders(
    page: int = 1,
    per_page: int = 10,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = (
        select(Order)
        .options(selectinload(Order.items), selectinload(Order.history))
        .where(Order.user_id == current_user.id)
        .order_by(Order.created_at.desc())
    )

    total_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = total_result.scalar()

    result = await db.execute(query.offset((page - 1) * per_page).limit(per_page))
    orders = result.scalars().all()

    return {
        "items": [_format_order(o) for o in orders],
        "total": total,
        "page": page,
        "per_page": per_page,
    }


# ── Track Order ────────────────────────────────────────────────────────────────

@router.get("/track/{order_number}")
async def track_order(order_number: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Order)
        .options(selectinload(Order.history))
        .where(Order.order_number == order_number.upper())
    )
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(404, "Order not found")

    return {
        "order_number": order.order_number,
        "status": order.status.value,
        "payment_status": order.payment_status.value,
        "tracking_number": order.tracking_number,
        "carrier": order.carrier,
        "estimated_delivery": order.estimated_delivery.isoformat() if order.estimated_delivery else None,
        "shipping_address": order.shipping_address,
        "history": [{"status": h.status, "note": h.note, "created_at": h.created_at.isoformat()}
                    for h in order.history],
    }


# ── Admin: All Orders ──────────────────────────────────────────────────────────

@router.get("/admin/all")
async def admin_all_orders(
    page: int = 1,
    per_page: int = 20,
    status: Optional[str] = None,
    payment_status: Optional[str] = None,
    search: Optional[str] = None,
    current_user=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    query = (
        select(Order)
        .options(selectinload(Order.items), selectinload(Order.history))
        .order_by(Order.created_at.desc())
    )
    if status:
        query = query.where(Order.status == status)
    if payment_status:
        query = query.where(Order.payment_status == payment_status)
    if search:
        query = query.where(Order.order_number.ilike(f"%{search}%"))

    total_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = total_result.scalar()

    result = await db.execute(query.offset((page - 1) * per_page).limit(per_page))
    orders = result.scalars().all()

    return {
        "items": [_format_order(o) for o in orders],
        "total": total,
        "page": page,
        "per_page": per_page,
    }


# ── Admin: Update Order Status ─────────────────────────────────────────────────

@router.put("/admin/{order_id}/status")
async def admin_update_status(
    order_id: str,
    data: OrderStatusUpdate,
    background_tasks: BackgroundTasks,
    current_user=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    valid_statuses = [s.value for s in OrderStatus]
    if data.status not in valid_statuses:
        raise HTTPException(400, f"Invalid status. Valid: {valid_statuses}")

    result = await db.execute(
        select(Order)
        .options(selectinload(Order.items), selectinload(Order.history))
        .where(Order.id == order_id)
    )
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(404, "Order not found")

    old_status = order.status.value
    order.status = OrderStatus(data.status)

    if data.tracking_number:
        order.tracking_number = data.tracking_number
    if data.carrier:
        order.carrier = data.carrier
    if data.estimated_delivery:
        from datetime import datetime
        order.estimated_delivery = datetime.fromisoformat(data.estimated_delivery)
    if data.status == "delivered":
        order.delivered_at = datetime.now(timezone.utc)

    db.add(OrderHistory(
        id=str(uuid.uuid4()),
        order_id=order.id,
        status=data.status,
        note=data.note or f"Status updated: {old_status} → {data.status}",
        created_by=current_user.id,
    ))
    await db.commit()

    # Notify customer
    user_result = await db.execute(select(User).where(User.id == order.user_id))
    customer = user_result.scalar_one_or_none()
    if customer:
        background_tasks.add_task(
            send_order_status_update,
            customer.email,
            f"{customer.first_name} {customer.last_name}",
            order.order_number,
            data.status,
            data.tracking_number,
            data.carrier,
            data.note,
        )

    result = await db.execute(
        select(Order)
        .options(selectinload(Order.items), selectinload(Order.history))
        .where(Order.id == order_id)
    )
    return _format_order(result.scalar_one())


# ── Shipping Calculator ────────────────────────────────────────────────────────

@router.post("/calculate-shipping")
async def calc_shipping(data: dict):
    country_code = data.get("country_code", "US")
    subtotal = float(data.get("subtotal", 0))
    weight = float(data.get("weight_kg", 0))
    info = await calculate_shipping(country_code, subtotal, weight)
    tax = calculate_tax(subtotal, country_code)
    return {**info, "tax_amount": tax, "tax_rate": f"{tax / subtotal * 100:.1f}%" if subtotal else "0%"}
