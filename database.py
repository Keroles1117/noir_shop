from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from app.core.config import settings
from app.db.models.models import Base
from loguru import logger


engine = create_async_engine(
    settings.DATABASE_URL,
    pool_size=settings.DATABASE_POOL_SIZE,
    max_overflow=settings.DATABASE_MAX_OVERFLOW,
    echo=settings.DEBUG,
    pool_pre_ping=True,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await _seed_super_admin()
    await _seed_shipping_zones()
    logger.info("✅ Database initialized")


async def _seed_super_admin():
    from sqlalchemy import select
    from app.db.models.models import User, UserRole
    from app.core.security import security_utils
    import uuid

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.email == settings.SUPER_ADMIN_EMAIL))
        if not result.scalar_one_or_none():
            admin = User(
                id=str(uuid.uuid4()),
                email=settings.SUPER_ADMIN_EMAIL,
                username="sadoon_admin",
                hashed_password=security_utils.hash_password(settings.SUPER_ADMIN_PASSWORD),
                first_name="Sadoon",
                last_name="Admin",
                role=UserRole.SUPER_ADMIN,
                is_active=True,
                is_verified=True,
            )
            db.add(admin)
            await db.commit()
            logger.info(f"✅ Super admin seeded: {settings.SUPER_ADMIN_EMAIL}")


async def _seed_shipping_zones():
    from sqlalchemy import select
    from app.db.models.models import ShippingZone
    import uuid

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(ShippingZone).limit(1))
        if result.scalar_one_or_none():
            return

        zones = [
            ShippingZone(id=str(uuid.uuid4()), name="Local", countries=["US", "CA"],
                         base_cost=5.00, free_above=200.0, estimated_days_min=3, estimated_days_max=7),
            ShippingZone(id=str(uuid.uuid4()), name="Middle East", countries=["SA", "AE", "KW", "QA", "BH", "OM", "JO"],
                         base_cost=15.00, free_above=300.0, estimated_days_min=5, estimated_days_max=10),
            ShippingZone(id=str(uuid.uuid4()), name="Europe", countries=["GB", "DE", "FR", "IT", "ES", "NL"],
                         base_cost=20.00, free_above=400.0, estimated_days_min=7, estimated_days_max=14),
            ShippingZone(id=str(uuid.uuid4()), name="International", countries=[],
                         base_cost=30.00, free_above=500.0, estimated_days_min=10, estimated_days_max=21),
        ]
        db.add_all(zones)
        await db.commit()
        logger.info("✅ Shipping zones seeded")
