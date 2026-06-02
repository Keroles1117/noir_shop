from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from datetime import datetime, timezone
from typing import Optional
from app.db.models.models import Order, OrderItem, OrderHistory, Product, Coupon, User, OrderStatus, PaymentStatus
from app.db.database import get_db
from app.api.v1.dependencies.auth import get_current_user, require_admin
from app.services.email_service import send_order_confirmation, send_order_status_update
from app.services.payment_service import process_stripe_payment, process_paypal_payment
from app.schemas.orders import OrderCreate, OrderStatusUpdate
import uuid
import random
import string

router = APIRouter(prefix="/orders", tags=["Orders"])


def generate_order_number():
    prefix = "NOIR"
    timestamp = datetime.now().strftime("%y%m%d")
    random_part = ''.join(random.choices(string.digits, k=6))
    return f"{prefix}-{timestamp}-{random_part}"


@router.post("", status_code=201)
async def create_order(
    data: OrderCreate,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    # Validate products and calculate totals
    subtotal = 0.0
    order_items = []

    for item in data.items:
        product_result = await db.execute(
            select(Product).where(Product.id == item.product_id)
        )
        product = product_result.scalar_one_or_none()
        if not product:
            raise HTTPException(status_code=404, detail=f"Product {item.product_id} not found")
        if product.track_inventory and product.stock_quantity < item.quantity:
            raise HTTPException(
                status_code=400,
                detail=f"Insufficient stock for {product.name_en}"
            )
        item_total = product.price * item.quantity
        subtotal += item_total
        order_items.append({
            "product": product,
            "quantity": item.quantity,
            "unit_price": product.price,
            "total_price": item_total,
            "variant": item.variant
        })

    # Apply coupon
    discount_amount = 0.0
    coupon = None
    if data.coupon_code:
        coupon_result = await db.execute(
            select(Coupon).where(
                Coupon.code == data.coupon_code.upper(),
                Coupon.is_active == True
            )
        )
        coupon = coupon_result.scalar_one_or_none()
        if not coupon:
            raise HTTPException(status_code=400, detail="Invalid coupon code")
        if coupon.expires_at and coupon.expires_at < datetime.now(timezone.utc):
            raise HTTPException(status_code=400, detail="Coupon has expired")
        if coupon.usage_limit and coupon.usage_count >= coupon.usage_limit:
            raise HTTPException(status_code=400, detail="Coupon usage limit reached")
        if subtotal < coupon.min_purchase:
            raise HTTPException(
                status_code=400,
                detail=f"Minimum purchase of {coupon.min_purchase} required"
            )

        if coupon.type == "percentage":
            discount_amount = subtotal * (coupon.value / 100)
            if coupon.max_discount:
                discount_amount = min(discount_amount, coupon.max_discount)
        elif coupon.type == "fixed":
            discount_amount = min(coupon.value, subtotal)

    shipping_cost = data.shipping_cost or 0.0
    tax_amount = round((subtotal - discount_amount) * 0.0, 2)  # Set tax rate per region
    total = round(subtotal - discount_amount + shipping_cost + tax_amount, 2)

    # Create order
    order = Order(
        id=str(uuid.uuid4()),
        order_number=generate_order_number(),
        user_id=current_user.id,
        coupon_id=coupon.id if coupon else None,
        payment_method=data.payment_method,
        subtotal=subtotal,
        discount_amount=discount_amount,
        shipping_cost=shipping_cost,
        tax_amount=tax_amount,
        total=total,
        currency=data.currency or "USD",
        shipping_address=data.shipping_address.dict(),
        billing_address=data.billing_address.dict() if data.billing_address else None,
        notes=data.notes,
        status=OrderStatus.PENDING,
        payment_status=PaymentStatus.PENDING,
    )
    db.add(order)
    await db.flush()

    # Create order items & reduce stock
    for item_data in order_items:
        order_item = OrderItem(
            id=str(uuid.uuid4()),
            order_id=order.id,
            product_id=item_data["product"].id,
            product_name=item_data["product"].name_en,
            product_image=item_data["product"].images[0].url if item_data["product"].images else None,
            sku=item_data["product"].sku,
            variant=item_data["variant"],
            quantity=item_data["quantity"],
            unit_price=item_data["unit_price"],
            total_price=item_data["total_price"],
        )
        db.add(order_item)
        if item_data["product"].track_inventory:
            item_data["product"].stock_quantity -= item_data["quantity"]
            item_data["product"].sales_count += item_data["quantity"]

    # Add initial history
    history = OrderHistory(
        id=str(uuid.uuid4()),
        order_id=order.id,
        status="created",
        note="Order placed successfully",
        created_by=current_user.id
    )
    db.add(history)

    # Update coupon usage
    if coupon:
        coupon.usage_count += 1

    await db.commit()
    await db.refresh(order)

    # Process payment if not COD
    if data.payment_method == "stripe" and data.payment_intent_id:
        success = await process_stripe_payment(order, data.payment_intent_id)
        if success:
            order.payment_status = PaymentStatus.PAID
            order.status = OrderStatus.CONFIRMED
            await db.commit()

    # Send confirmation email
    background_tasks.add_task(
        send_order_confirmation,
        current_user.email,
        order.order_number,
        order.total
    )

    return order


@router.get("/my-orders")
async def get_my_orders(
    page: int = 1,
    per_page: int = 10,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    query = select(Order).where(Order.user_id == current_user.id)
    total_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = total_result.scalar()

    result = await db.execute(
        query.order_by(Order.created_at.desc())
        .offset((page - 1) * per_page).limit(per_page)
    )
    return {
        "items": result.scalars().all(),
        "total": total,
        "page": page,
        "per_page": per_page
    }


@router.get("/track/{order_number}")
async def track_order(order_number: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Order).where(Order.order_number == order_number)
    )
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return {
        "order_number": order.order_number,
        "status": order.status,
        "tracking_number": order.tracking_number,
        "carrier": order.carrier,
        "estimated_delivery": order.estimated_delivery,
        "history": order.history
    }


@router.put("/{order_id}/status")
async def update_order_status(
    order_id: str,
    data: OrderStatusUpdate,
    background_tasks: BackgroundTasks,
    current_user=Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    old_status = order.status
    order.status = data.status
    if data.tracking_number:
        order.tracking_number = data.tracking_number
    if data.carrier:
        order.carrier = data.carrier
    if data.estimated_delivery:
        order.estimated_delivery = data.estimated_delivery

    history = OrderHistory(
        id=str(uuid.uuid4()),
        order_id=order.id,
        status=data.status,
        note=data.note or f"Status updated from {old_status} to {data.status}",
        created_by=current_user.id
    )
    db.add(history)
    await db.commit()

    # Notify customer
    user_result = await db.execute(select(User).where(User.id == order.user_id))
    user = user_result.scalar_one_or_none()
    if user:
        background_tasks.add_task(
            send_order_status_update,
            user.email,
            order.order_number,
            data.status
        )

    return order


@router.get("/admin/all")
async def admin_get_all_orders(
    page: int = 1,
    per_page: int = 20,
    status: Optional[str] = None,
    current_user=Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    query = select(Order)
    if status:
        query = query.where(Order.status == status)
    query = query.order_by(Order.created_at.desc())

    total_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = total_result.scalar()

    result = await db.execute(query.offset((page - 1) * per_page).limit(per_page))
    return {
        "items": result.scalars().all(),
        "total": total,
        "page": page,
        "per_page": per_page
    }
