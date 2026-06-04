from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timezone, timedelta
from app.db.database import get_db
from app.db.models.models import User, RefreshToken, UserRole
from app.core.security import security_utils, get_client_ip
from app.core.config import settings
from app.services.email_service import send_verification_email, send_password_reset_email
from slowapi import Limiter
from slowapi.util import get_remote_address
import secrets, uuid, re
from pydantic import BaseModel, EmailStr, field_validator

router = APIRouter(prefix="/auth", tags=["Authentication"])
limiter = Limiter(key_func=get_remote_address)


# ── Schemas ────────────────────────────────────────────────────────────────────

class RegisterInput(BaseModel):
    email: EmailStr
    username: str
    password: str
    first_name: str
    last_name: str
    phone: str | None = None
    preferred_language: str = "en"
    preferred_currency: str = "USD"

    @field_validator("username")
    @classmethod
    def validate_username(cls, v):
        if not re.match(r'^[a-zA-Z0-9_]{3,30}$', v):
            raise ValueError("Username must be 3-30 characters: letters, numbers, underscore only")
        return v.lower()

    @field_validator("password")
    @classmethod
    def validate_password(cls, v):
        ok, msg = security_utils.validate_password_strength(v)
        if not ok:
            raise ValueError(msg)
        return v


class LoginInput(BaseModel):
    email: EmailStr
    password: str


class RefreshInput(BaseModel):
    refresh_token: str


class ResetRequestInput(BaseModel):
    email: EmailStr


class ResetConfirmInput(BaseModel):
    token: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def validate_password(cls, v):
        ok, msg = security_utils.validate_password_strength(v)
        if not ok:
            raise ValueError(msg)
        return v


class ChangePasswordInput(BaseModel):
    current_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def validate_password(cls, v):
        ok, msg = security_utils.validate_password_strength(v)
        if not ok:
            raise ValueError(msg)
        return v


# ── Register ───────────────────────────────────────────────────────────────────

@router.post("/register", status_code=201)
@limiter.limit("10/minute")
async def register(
    request: Request,
    data: RegisterInput,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    # Check email uniqueness
    result = await db.execute(select(User).where(User.email == data.email.lower()))
    if result.scalar_one_or_none():
        raise HTTPException(400, "Email already registered")

    # Check username uniqueness
    result = await db.execute(select(User).where(User.username == data.username.lower()))
    if result.scalar_one_or_none():
        raise HTTPException(400, "Username already taken")

    verification_token = secrets.token_urlsafe(32)
    user = User(
        id=str(uuid.uuid4()),
        email=data.email.lower(),
        username=data.username.lower(),
        hashed_password=security_utils.hash_password(data.password),
        first_name=security_utils.sanitize(data.first_name),
        last_name=security_utils.sanitize(data.last_name),
        phone=data.phone,
        role=UserRole.CUSTOMER,
        verification_token=verification_token,
        preferred_language=data.preferred_language,
        preferred_currency=data.preferred_currency,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    full_name = f"{user.first_name} {user.last_name}"
    background_tasks.add_task(send_verification_email, user.email, full_name, verification_token)

    return {
        "message": "Account created successfully. Please verify your email.",
        "user_id": user.id,
        "email": user.email,
    }


# ── Login ──────────────────────────────────────────────────────────────────────

@router.post("/login")
@limiter.limit("5/minute")
async def login(
    request: Request,
    data: LoginInput,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.email == data.email.lower()))
    user = result.scalar_one_or_none()

    if not user or not security_utils.verify_password(data.password, user.hashed_password):
        raise HTTPException(401, "Invalid email or password")
    if not user.is_active:
        raise HTTPException(403, "Account is disabled. Contact support.")

    token_data = {"sub": user.id, "role": user.role.value}
    access_token = security_utils.create_access_token(token_data)
    refresh_token_str = security_utils.create_refresh_token(token_data)

    # Store refresh token
    db.add(RefreshToken(
        id=str(uuid.uuid4()),
        user_id=user.id,
        token=refresh_token_str,
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS),
    ))
    user.last_login = datetime.now(timezone.utc)
    await db.commit()

    return {
        "access_token": access_token,
        "refresh_token": refresh_token_str,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "email": user.email,
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "role": user.role.value,
            "avatar_url": user.avatar_url,
            "is_verified": user.is_verified,
            "preferred_language": user.preferred_language,
            "preferred_currency": user.preferred_currency,
        },
    }


# ── Refresh Token ──────────────────────────────────────────────────────────────

@router.post("/refresh")
async def refresh(data: RefreshInput, db: AsyncSession = Depends(get_db)):
    payload = security_utils.decode_token(data.refresh_token)
    if payload.get("type") != "refresh":
        raise HTTPException(401, "Invalid token type")

    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.token == data.refresh_token,
            RefreshToken.is_revoked == False,
        )
    )
    token_obj = result.scalar_one_or_none()
    if not token_obj:
        raise HTTPException(401, "Token invalid or revoked")

    user_result = await db.execute(select(User).where(User.id == payload["sub"]))
    user = user_result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(401, "User not found")

    token_data = {"sub": user.id, "role": user.role.value}
    new_access = security_utils.create_access_token(token_data)
    new_refresh = security_utils.create_refresh_token(token_data)

    # Rotate tokens
    token_obj.is_revoked = True
    db.add(RefreshToken(
        id=str(uuid.uuid4()),
        user_id=user.id,
        token=new_refresh,
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS),
    ))
    await db.commit()

    return {"access_token": new_access, "refresh_token": new_refresh, "token_type": "bearer"}


# ── Logout ─────────────────────────────────────────────────────────────────────

@router.post("/logout")
async def logout(data: RefreshInput, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(RefreshToken).where(RefreshToken.token == data.refresh_token))
    token_obj = result.scalar_one_or_none()
    if token_obj:
        token_obj.is_revoked = True
        await db.commit()
    return {"message": "Logged out successfully"}


# ── Verify Email ───────────────────────────────────────────────────────────────

@router.get("/verify-email/{token}")
async def verify_email(token: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.verification_token == token))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(400, "Invalid or expired verification link")
    user.is_verified = True
    user.verification_token = None
    await db.commit()
    return {"message": "Email verified successfully. You can now log in."}


# ── Forgot Password ────────────────────────────────────────────────────────────

@router.post("/forgot-password")
@limiter.limit("3/minute")
async def forgot_password(
    request: Request,
    data: ResetRequestInput,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.email == data.email.lower()))
    user = result.scalar_one_or_none()
    if user:
        reset_token = secrets.token_urlsafe(32)
        user.reset_token = reset_token
        user.reset_token_expires = datetime.now(timezone.utc) + timedelta(hours=2)
        await db.commit()
        full_name = f"{user.first_name} {user.last_name}"
        background_tasks.add_task(send_password_reset_email, user.email, full_name, reset_token)

    # Always return success — don't reveal whether email exists
    return {"message": "If this email is registered, you will receive reset instructions."}


# ── Reset Password ─────────────────────────────────────────────────────────────

@router.post("/reset-password")
async def reset_password(data: ResetConfirmInput, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(User).where(
            User.reset_token == data.token,
            User.reset_token_expires > datetime.now(timezone.utc),
        )
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(400, "Invalid or expired reset link")

    user.hashed_password = security_utils.hash_password(data.new_password)
    user.reset_token = None
    user.reset_token_expires = None
    await db.commit()

    # Revoke all refresh tokens for security
    from sqlalchemy import update
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user.id)
        .values(is_revoked=True)
    )
    await db.commit()

    return {"message": "Password reset successfully. Please log in with your new password."}
