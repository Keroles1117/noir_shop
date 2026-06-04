import aiosmtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from jinja2 import Environment, BaseLoader
from app.core.config import settings
from loguru import logger


# ── Email Templates ────────────────────────────────────────────────────────────

BASE_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{{ subject }}</title>
<style>
  body { margin:0; padding:0; background:#f5f5f5; font-family:'Helvetica Neue',Arial,sans-serif; }
  .wrapper { max-width:600px; margin:40px auto; }
  .header { background:#0a0a0a; padding:32px 40px; text-align:center; }
  .header h1 { color:#fff; font-size:32px; letter-spacing:8px; margin:0; font-weight:300; }
  .header h1 span { color:#c9a96e; }
  .body { background:#ffffff; padding:40px; }
  .footer { background:#0a0a0a; padding:20px 40px; text-align:center; }
  .footer p { color:#555; font-size:12px; margin:4px 0; }
  .btn { display:inline-block; background:#c9a96e; color:#0a0a0a; padding:14px 32px;
         text-decoration:none; font-weight:600; font-size:13px; letter-spacing:2px;
         text-transform:uppercase; margin:24px 0; }
  .divider { border:none; border-top:1px solid #f0f0f0; margin:24px 0; }
  h2 { color:#0a0a0a; font-size:22px; margin-top:0; }
  p { color:#444; line-height:1.7; font-size:15px; }
  .gold { color:#c9a96e; }
  .order-table { width:100%; border-collapse:collapse; margin:20px 0; }
  .order-table th { background:#f9f9f9; padding:10px 12px; text-align:left; font-size:12px;
                    letter-spacing:1px; text-transform:uppercase; color:#888; }
  .order-table td { padding:12px; border-bottom:1px solid #f0f0f0; font-size:14px; color:#333; }
  .total-row td { font-weight:600; color:#0a0a0a; background:#fafafa; }
</style>
</head>
<body>
<div class="wrapper">
  <div class="header">
    <h1>SA<span>D</span>OON</h1>
  </div>
  <div class="body">
    {% block content %}{% endblock %}
  </div>
  <div class="footer">
    <p>© {{ year }} Sadoon Store. All rights reserved.</p>
    <p>Luxury Fashion — sadoon-store.com</p>
  </div>
</div>
</body>
</html>
"""

VERIFY_TEMPLATE = """
<h2>Welcome to Sadoon Store 🖤</h2>
<p>Hello <strong>{{ name }}</strong>,</p>
<p>Thank you for creating an account. Please verify your email address to start shopping.</p>
<p style="text-align:center;">
  <a href="{{ url }}" class="btn">Verify Email Address</a>
</p>
<hr class="divider">
<p style="font-size:13px;color:#888;">If the button doesn't work, copy this link:<br>
<a href="{{ url }}" style="color:#c9a96e;word-break:break-all;">{{ url }}</a></p>
<p style="font-size:13px;color:#888;">This link expires in 24 hours.</p>
"""

RESET_TEMPLATE = """
<h2>Reset Your Password</h2>
<p>Hello <strong>{{ name }}</strong>,</p>
<p>We received a request to reset your password. Click below to choose a new one:</p>
<p style="text-align:center;">
  <a href="{{ url }}" class="btn">Reset Password</a>
</p>
<hr class="divider">
<p style="font-size:13px;color:#888;">This link expires in 2 hours. If you didn't request this, ignore this email.</p>
"""

ORDER_CONFIRM_TEMPLATE = """
<h2>Order Confirmed ✓</h2>
<p>Hello <strong>{{ name }}</strong>,</p>
<p>Thank you for your order! We've received it and will notify you when it ships.</p>
<p><strong class="gold">Order Number: {{ order_number }}</strong></p>
<table class="order-table">
  <thead>
    <tr><th>Product</th><th>Qty</th><th>Price</th></tr>
  </thead>
  <tbody>
    {% for item in items %}
    <tr>
      <td>{{ item.product_name }}</td>
      <td>{{ item.quantity }}</td>
      <td>${{ "%.2f"|format(item.unit_price) }}</td>
    </tr>
    {% endfor %}
    <tr class="total-row">
      <td colspan="2">Total</td>
      <td>${{ "%.2f"|format(total) }}</td>
    </tr>
  </tbody>
</table>
<p>Payment Method: <strong>{{ payment_method|upper }}</strong></p>
<hr class="divider">
<p style="font-size:13px;color:#888;">Questions? Contact us at support@sadoon-store.com</p>
"""

ORDER_STATUS_TEMPLATE = """
<h2>Order Update</h2>
<p>Hello <strong>{{ name }}</strong>,</p>
<p>Your order <strong class="gold">{{ order_number }}</strong> has been updated:</p>
<p style="font-size:20px;text-align:center;padding:20px;background:#f9f9f9;">
  <strong>{{ status|upper }}</strong>
</p>
{% if tracking_number %}
<p>Tracking Number: <strong>{{ tracking_number }}</strong></p>
{% if carrier %}<p>Carrier: {{ carrier }}</p>{% endif %}
{% endif %}
{% if note %}<p>{{ note }}</p>{% endif %}
"""

jinja_env = Environment(loader=BaseLoader())


def _render(template_str: str, **kwargs) -> str:
    from datetime import datetime
    tmpl = jinja_env.from_string(template_str)
    return tmpl.render(year=datetime.now().year, **kwargs)


async def _send_email(to_email: str, subject: str, html_body: str) -> bool:
    """Send email via SMTP (works with SendGrid, Mailgun, Gmail)."""
    if not settings.SMTP_PASSWORD:
        logger.warning(f"[EMAIL] SMTP not configured. Would send to {to_email}: {subject}")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{settings.EMAILS_FROM_NAME} <{settings.EMAILS_FROM_EMAIL}>"
    msg["To"] = to_email
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        await aiosmtplib.send(
            msg,
            hostname=settings.SMTP_HOST,
            port=settings.SMTP_PORT,
            username=settings.SMTP_USER,
            password=settings.SMTP_PASSWORD,
            start_tls=True,
        )
        logger.info(f"✅ Email sent to {to_email}: {subject}")
        return True
    except Exception as e:
        logger.error(f"❌ Email send failed to {to_email}: {e}")
        return False


# ── Public Functions ───────────────────────────────────────────────────────────

async def send_verification_email(email: str, name: str, token: str):
    url = f"{settings.SITE_URL}/verify-email?token={token}"
    html = _render(VERIFY_TEMPLATE, name=name, url=url)
    await _send_email(email, "Verify Your Sadoon Store Account", html)


async def send_password_reset_email(email: str, name: str, token: str):
    url = f"{settings.SITE_URL}/reset-password?token={token}"
    html = _render(RESET_TEMPLATE, name=name, url=url)
    await _send_email(email, "Reset Your Password — Sadoon Store", html)


async def send_order_confirmation(email: str, name: str, order_number: str, items: list, total: float, payment_method: str):
    html = _render(ORDER_CONFIRM_TEMPLATE, name=name, order_number=order_number,
                   items=items, total=total, payment_method=payment_method)
    await _send_email(email, f"Order Confirmed — {order_number}", html)


async def send_order_status_update(email: str, name: str, order_number: str, status: str,
                                   tracking_number: str = None, carrier: str = None, note: str = None):
    html = _render(ORDER_STATUS_TEMPLATE, name=name, order_number=order_number,
                   status=status, tracking_number=tracking_number, carrier=carrier, note=note)
    await _send_email(email, f"Order Update — {order_number}", html)
