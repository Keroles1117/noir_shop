from app.core.config import settings
from loguru import logger
from fastapi import HTTPException


# ── Stripe ─────────────────────────────────────────────────────────────────────

async def create_stripe_payment_intent(amount: float, currency: str, order_id: str, customer_email: str) -> dict:
    """Create Stripe PaymentIntent and return client_secret."""
    if not settings.STRIPE_SECRET_KEY:
        raise HTTPException(500, "Stripe not configured")

    import stripe
    stripe.api_key = settings.STRIPE_SECRET_KEY

    try:
        intent = stripe.PaymentIntent.create(
            amount=int(amount * 100),  # Stripe uses cents
            currency=currency.lower(),
            metadata={"order_id": order_id, "store": "sadoon"},
            receipt_email=customer_email,
            description=f"Sadoon Store — Order {order_id}",
        )
        return {
            "client_secret": intent.client_secret,
            "payment_intent_id": intent.id,
        }
    except stripe.error.StripeError as e:
        logger.error(f"Stripe error: {e}")
        raise HTTPException(400, f"Payment error: {e.user_message}")


async def confirm_stripe_payment(payment_intent_id: str) -> bool:
    """Verify payment intent is succeeded."""
    if not settings.STRIPE_SECRET_KEY:
        return False

    import stripe
    stripe.api_key = settings.STRIPE_SECRET_KEY

    try:
        intent = stripe.PaymentIntent.retrieve(payment_intent_id)
        return intent.status == "succeeded"
    except stripe.error.StripeError as e:
        logger.error(f"Stripe verify error: {e}")
        return False


async def handle_stripe_webhook(payload: bytes, sig_header: str) -> dict:
    """Validate and parse Stripe webhook."""
    if not settings.STRIPE_WEBHOOK_SECRET:
        raise HTTPException(400, "Webhook secret not configured")

    import stripe
    stripe.api_key = settings.STRIPE_SECRET_KEY

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, settings.STRIPE_WEBHOOK_SECRET)
    except stripe.error.SignatureVerificationError:
        raise HTTPException(400, "Invalid webhook signature")

    return {"type": event.type, "data": event.data.object}


async def create_stripe_refund(payment_intent_id: str, amount: float = None) -> bool:
    """Create a refund for a payment."""
    import stripe
    stripe.api_key = settings.STRIPE_SECRET_KEY

    try:
        params = {"payment_intent": payment_intent_id}
        if amount:
            params["amount"] = int(amount * 100)
        stripe.Refund.create(**params)
        return True
    except stripe.error.StripeError as e:
        logger.error(f"Stripe refund error: {e}")
        return False


# ── PayPal ─────────────────────────────────────────────────────────────────────

async def _get_paypal_token() -> str:
    import httpx, base64

    credentials = base64.b64encode(
        f"{settings.PAYPAL_CLIENT_ID}:{settings.PAYPAL_CLIENT_SECRET}".encode()
    ).decode()

    base_url = "https://api-m.paypal.com" if settings.PAYPAL_MODE == "live" else "https://api-m.sandbox.paypal.com"

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{base_url}/v1/oauth2/token",
            headers={"Authorization": f"Basic {credentials}", "Content-Type": "application/x-www-form-urlencoded"},
            data="grant_type=client_credentials",
        )
        resp.raise_for_status()
        return resp.json()["access_token"]


async def create_paypal_order(amount: float, currency: str, order_id: str) -> dict:
    """Create PayPal order and return approval URL."""
    if not settings.PAYPAL_CLIENT_ID:
        raise HTTPException(500, "PayPal not configured")

    import httpx

    base_url = "https://api-m.paypal.com" if settings.PAYPAL_MODE == "live" else "https://api-m.sandbox.paypal.com"
    token = await _get_paypal_token()

    payload = {
        "intent": "CAPTURE",
        "purchase_units": [{
            "reference_id": order_id,
            "amount": {"currency_code": currency, "value": f"{amount:.2f}"},
            "description": f"Sadoon Store — Order {order_id}",
        }],
        "application_context": {
            "return_url": f"{settings.SITE_URL}/checkout/success",
            "cancel_url": f"{settings.SITE_URL}/checkout/cancel",
            "brand_name": "Sadoon Store",
            "landing_page": "NO_PREFERENCE",
        },
    }

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{base_url}/v2/checkout/orders",
                json=payload,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()

        approval_url = next(link["href"] for link in data["links"] if link["rel"] == "approve")
        return {"paypal_order_id": data["id"], "approval_url": approval_url}
    except Exception as e:
        logger.error(f"PayPal create order error: {e}")
        raise HTTPException(400, "Failed to create PayPal order")


async def capture_paypal_order(paypal_order_id: str) -> bool:
    """Capture (confirm) a PayPal order after user approval."""
    import httpx

    base_url = "https://api-m.paypal.com" if settings.PAYPAL_MODE == "live" else "https://api-m.sandbox.paypal.com"
    token = await _get_paypal_token()

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{base_url}/v2/checkout/orders/{paypal_order_id}/capture",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            )
            data = resp.json()
        return data.get("status") == "COMPLETED"
    except Exception as e:
        logger.error(f"PayPal capture error: {e}")
        return False


# ── Shipping Calculator ─────────────────────────────────────────────────────────

async def calculate_shipping(country_code: str, subtotal: float, weight_kg: float = 0) -> dict:
    """Calculate shipping cost based on country and order value."""
    from sqlalchemy import select
    from app.db.models.models import ShippingZone
    from app.db.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(ShippingZone).where(ShippingZone.is_active == True))
        zones = result.scalars().all()

    # Find matching zone
    matched_zone = None
    fallback_zone = None

    for zone in zones:
        if not zone.countries:  # International/fallback
            fallback_zone = zone
        elif country_code.upper() in zone.countries:
            matched_zone = zone
            break

    zone = matched_zone or fallback_zone
    if not zone:
        return {"cost": 25.0, "free": False, "days_min": 10, "days_max": 21, "zone": "International"}

    # Check free shipping threshold
    if zone.free_above and subtotal >= zone.free_above:
        return {
            "cost": 0.0,
            "free": True,
            "days_min": zone.estimated_days_min,
            "days_max": zone.estimated_days_max,
            "zone": zone.name,
        }

    # Calculate cost with weight
    cost = zone.base_cost + (weight_kg * zone.per_kg_cost)

    return {
        "cost": round(cost, 2),
        "free": False,
        "days_min": zone.estimated_days_min,
        "days_max": zone.estimated_days_max,
        "zone": zone.name,
    }


def calculate_tax(subtotal: float, country_code: str) -> float:
    """Calculate tax based on country."""
    tax_rates = {
        "SA": 0.15,  # Saudi Arabia 15%
        "AE": 0.05,  # UAE 5%
        "US": 0.08,  # US avg 8%
        "GB": 0.20,  # UK 20%
        "DE": 0.19,  # Germany 19%
        "FR": 0.20,  # France 20%
    }
    rate = tax_rates.get(country_code.upper(), settings.TAX_RATE)
    return round(subtotal * rate, 2)
