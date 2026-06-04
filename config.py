from pydantic_settings import BaseSettings
from typing import List
import secrets


class Settings(BaseSettings):
    APP_NAME: str = "Sadoon Store"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    SECRET_KEY: str = secrets.token_urlsafe(64)
    ALLOWED_HOSTS: List[str] = ["sadoon-store.com", "www.sadoon-store.com", "localhost"]
    CORS_ORIGINS: List[str] = ["http://localhost:3000", "https://sadoon-store.com"]
    SITE_URL: str = "https://sadoon-store.com"
    SITE_NAME: str = "Sadoon — Luxury Fashion"

    DATABASE_URL: str = "postgresql+asyncpg://sadoon_user:password@db:5432/sadoon_db"
    DATABASE_POOL_SIZE: int = 10
    DATABASE_MAX_OVERFLOW: int = 20

    REDIS_URL: str = "redis://redis:6379/0"
    CELERY_BROKER_URL: str = "redis://redis:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://redis:6379/2"

    JWT_SECRET_KEY: str = secrets.token_urlsafe(64)
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    SMTP_HOST: str = "smtp.sendgrid.net"
    SMTP_PORT: int = 587
    SMTP_USER: str = "apikey"
    SMTP_PASSWORD: str = ""
    EMAILS_FROM_EMAIL: str = "noreply@sadoon-store.com"
    EMAILS_FROM_NAME: str = "Sadoon Store"

    UPLOAD_DIR: str = "uploads"
    MAX_UPLOAD_SIZE: int = 10 * 1024 * 1024
    ALLOWED_IMAGE_TYPES: List[str] = ["image/jpeg", "image/png", "image/webp"]
    USE_S3: bool = False
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    AWS_BUCKET_NAME: str = ""
    AWS_REGION: str = "us-east-1"
    AWS_CDN_URL: str = ""

    STRIPE_SECRET_KEY: str = ""
    STRIPE_PUBLISHABLE_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""
    PAYPAL_CLIENT_ID: str = ""
    PAYPAL_CLIENT_SECRET: str = ""
    PAYPAL_MODE: str = "sandbox"

    RATE_LIMIT_PER_MINUTE: int = 60
    RATE_LIMIT_LOGIN: str = "5/minute"
    RATE_LIMIT_RESET: str = "3/minute"

    SUPER_ADMIN_EMAIL: str = "admin@sadoon-store.com"
    SUPER_ADMIN_PASSWORD: str = "ChangeMe@2025!"

    LOCAL_SHIPPING_COST: float = 5.00
    INTERNATIONAL_SHIPPING_COST: float = 25.00
    FREE_SHIPPING_THRESHOLD: float = 200.00
    TAX_RATE: float = 0.15

    DEFAULT_CURRENCY: str = "USD"
    SUPPORTED_CURRENCIES: List[str] = ["USD", "EUR", "GBP", "SAR", "AED"]
    DEFAULT_LANGUAGE: str = "en"
    SUPPORTED_LANGUAGES: List[str] = ["en", "ar"]

    BACKUP_DIR: str = "backups"
    BACKUP_RETENTION_DAYS: int = 30

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
