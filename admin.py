from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, cast, Date
from datetime import datetime, timedelta, timezone
from app.db.models.models import Order, User, Product, OrderStatus, PaymentStatus
from app.db.database import get_db
from app.api.v1.dependencies.auth import require_admin

router = APIRouter(prefix="/admin/dashboard", tags=["Admin Dashboard"])


@router.get("/stats")
async def get_dashboard_stats(
    current_user=Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    now = datetime.now(timezone.utc)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    this_month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    last_month_start = (this_month_start - timedelta(days=1)).replace(day=1)

    # Total revenue
    revenue_result = await db.execute(
        select(func.sum(Order.total)).where(
            Order.payment_status == PaymentStatus.PAID
        )
    )
    total_revenue = revenue_result.scalar() or 0

    # This month revenue
    month_revenue_result = await db.execute(
        select(func.sum(Order.total)).where(
            Order.payment_status == PaymentStatus.PAID,
            Order.created_at >= this_month_start
        )
    )
    month_revenue = month_revenue_result.scalar() or 0

    # Last month revenue
    last_month_revenue_result = await db.execute(
        select(func.sum(Order.total)).where(
            Order.payment_status == PaymentStatus.PAID,
            Order.created_at >= last_month_start,
            Order.created_at < this_month_start
        )
    )
    last_month_revenue = last_month_revenue_result.scalar() or 0

    revenue_growth = 0
    if last_month_revenue > 0:
        revenue_growth = ((month_revenue - last_month_revenue) / last_month_revenue) * 100

    # Orders
    total_orders_result = await db.execute(select(func.count(Order.id)))
    total_orders = total_orders_result.scalar() or 0

    today_orders_result = await db.execute(
        select(func.count(Order.id)).where(Order.created_at >= today)
    )
    today_orders = today_orders_result.scalar() or 0

    pending_orders_result = await db.execute(
        select(func.count(Order.id)).where(Order.status == OrderStatus.PENDING)
    )
    pending_orders = pending_orders_result.scalar() or 0

    # Customers
    total_customers_result = await db.execute(select(func.count(User.id)))
    total_customers = total_customers_result.scalar() or 0

    new_customers_result = await db.execute(
        select(func.count(User.id)).where(User.created_at >= this_month_start)
    )
    new_customers = new_customers_result.scalar() or 0

    # Products
    total_products_result = await db.execute(select(func.count(Product.id)))
    total_products = total_products_result.scalar() or 0

    low_stock_result = await db.execute(
        select(func.count(Product.id)).where(
            Product.stock_quantity <= Product.low_stock_threshold
        )
    )
    low_stock = low_stock_result.scalar() or 0

    return {
        "revenue": {
            "total": round(total_revenue, 2),
            "this_month": round(month_revenue, 2),
            "last_month": round(last_month_revenue, 2),
            "growth_percent": round(revenue_growth, 1)
        },
        "orders": {
            "total": total_orders,
            "today": today_orders,
            "pending": pending_orders
        },
        "customers": {
            "total": total_customers,
            "new_this_month": new_customers
        },
        "products": {
            "total": total_products,
            "low_stock": low_stock
        }
    }


@router.get("/revenue-chart")
async def get_revenue_chart(
    period: str = "30days",
    current_user=Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    now = datetime.now(timezone.utc)
    if period == "7days":
        start_date = now - timedelta(days=7)
        date_format = "%Y-%m-%d"
    elif period == "30days":
        start_date = now - timedelta(days=30)
        date_format = "%Y-%m-%d"
    elif period == "12months":
        start_date = now - timedelta(days=365)
        date_format = "%Y-%m"
    else:
        start_date = now - timedelta(days=30)
        date_format = "%Y-%m-%d"

    result = await db.execute(
        select(
            cast(Order.created_at, Date).label("date"),
            func.sum(Order.total).label("revenue"),
            func.count(Order.id).label("orders")
        ).where(
            Order.created_at >= start_date,
            Order.payment_status == PaymentStatus.PAID
        ).group_by(cast(Order.created_at, Date))
        .order_by(cast(Order.created_at, Date))
    )
    rows = result.all()
    return [{"date": str(r.date), "revenue": round(r.revenue, 2), "orders": r.orders} for r in rows]


@router.get("/top-products")
async def get_top_products(
    limit: int = 10,
    current_user=Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(Product).order_by(Product.sales_count.desc()).limit(limit)
    )
    return result.scalars().all()


@router.get("/recent-orders")
async def get_recent_orders(
    limit: int = 10,
    current_user=Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(Order).order_by(Order.created_at.desc()).limit(limit)
    )
    return result.scalars().all()


@router.get("/order-status-distribution")
async def get_order_status_distribution(
    current_user=Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(Order.status, func.count(Order.id).label("count"))
        .group_by(Order.status)
    )
    return [{"status": r.status, "count": r.count} for r in result.all()]
