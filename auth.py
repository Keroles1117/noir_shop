from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timezone, timedelta
from app.db.models.models import User, RefreshToken, UserRole
from app.core.security import security_utils, get_client_ip
from app.core.config import settings
from app.db.database import get_db
from app.schemas.auth import (
    UserRegister, UserLogin, TokenResponse, UserResponse,
    PasswordReset, PasswordResetConfirm, RefreshTokenRequest
)
from app.services.email_service import send_verification_email, send_password_reset_email
from app.utils.validators import validate_email_format
import secrets
import uuid

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/register", response_model=UserResponse, status_code=201)
async def register(
    data: UserRegister,
    background_tasks: BackgroundTasks,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    # Check existing email
    result = await db.execute(select(User).where(User.email == data.email.lower()))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")

    # Validate password
    if not security_utils.validate_password_strength(data.password):
        raise HTTPException(
            status_code=400,
            detail="Password must be 8+ characters with uppercase, lowercase, and digit"
        )

    # Create user
    verification_token = secrets.token_urlsafe(32)
    user = User(
        id=str(uuid.uuid4()),
        email=data.email.lower(),
        username=data.username.lower(),
        hashed_password=security_utils.hash_password(data.password),
        first_name=security_utils.sanitize_input(data.first_name),
        last_name=security_utils.sanitize_input(data.last_name),
        phone=data.phone,
        role=UserRole.CUSTOMER,
        verification_token=verification_token,
        preferred_language=data.preferred_language or "en",
        preferred_currency=data.preferred_currency or "USD",
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    # Send verification email
    background_tasks.add_task(send_verification_email, user.email, verification_token)

    return user


@router.post("/login", response_model=TokenResponse)
async def login(
    data: UserLogin,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(User).where(User.email == data.email.lower()))
    user = result.scalar_one_or_none()

    if not user or not security_utils.verify_password(data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is disabled")

    # Create tokens
    token_data = {"sub": user.id, "role": user.role}
    access_token = security_utils.create_access_token(token_data)
    refresh_token_str = security_utils.create_refresh_token(token_data)

    # Store refresh token
    refresh_token = RefreshToken(
        id=str(uuid.uuid4()),
        user_id=user.id,
        token=refresh_token_str,
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)
    )
    db.add(refresh_token)

    # Update last login
    user.last_login = datetime.now(timezone.utc)
    await db.commit()

    return {
        "access_token": access_token,
        "refresh_token": refresh_token_str,
        "token_type": "bearer",
        "user": user
    }


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(
    data: RefreshTokenRequest,
    db: AsyncSession = Depends(get_db)
):
    payload = security_utils.decode_token(data.refresh_token)
    if payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid token type")

    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.token == data.refresh_token,
            RefreshToken.is_revoked == False
        )
    )
    token_obj = result.scalar_one_or_none()
    if not token_obj:
        raise HTTPException(status_code=401, detail="Token revoked or invalid")

    user_result = await db.execute(select(User).where(User.id == payload["sub"]))
    user = user_result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found")

    token_data = {"sub": user.id, "role": user.role}
    new_access_token = security_utils.create_access_token(token_data)
    new_refresh_token = security_utils.create_refresh_token(token_data)

    # Rotate refresh token
    token_obj.is_revoked = True
    new_token = RefreshToken(
        id=str(uuid.uuid4()),
        user_id=user.id,
        token=new_refresh_token,
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)
    )
    db.add(new_token)
    await db.commit()

    return {
        "access_token": new_access_token,
        "refresh_token": new_refresh_token,
        "token_type": "bearer",
        "user": user
    }


@router.post("/logout")
async def logout(
    data: RefreshTokenRequest,
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(RefreshToken).where(RefreshToken.token == data.refresh_token)
    )
    token_obj = result.scalar_one_or_none()
    if token_obj:
        token_obj.is_revoked = True
        await db.commit()
    return {"message": "Logged out successfully"}


@router.post("/verify-email/{token}")
async def verify_email(token: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.verification_token == token))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=400, detail="Invalid verification token")
    user.is_verified = True
    user.verification_token = None
    await db.commit()
    return {"message": "Email verified successfully"}


@router.post("/forgot-password")
async def forgot_password(
    data: PasswordReset,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(User).where(User.email == data.email.lower()))
    user = result.scalar_one_or_none()
    if user:
        reset_token = secrets.token_urlsafe(32)
        user.reset_token = reset_token
        user.reset_token_expires = datetime.now(timezone.utc) + timedelta(hours=2)
        await db.commit()
        background_tasks.add_task(send_password_reset_email, user.email, reset_token)
    # Always return success (don't reveal if email exists)
    return {"message": "If this email is registered, you will receive reset instructions"}


@router.post("/reset-password")
async def reset_password(data: PasswordResetConfirm, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(User).where(
            User.reset_token == data.token,
            User.reset_token_expires > datetime.now(timezone.utc)
        )
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")

    if not security_utils.validate_password_strength(data.new_password):
        raise HTTPException(status_code=400, detail="Password does not meet requirements")

    user.hashed_password = security_utils.hash_password(data.new_password)
    user.reset_token = None
    user.reset_token_expires = None
    await db.commit()
    return {"message": "Password reset successfully"}
