import os, uuid, asyncio
from pathlib import Path
from fastapi import UploadFile, HTTPException
from PIL import Image
import io
import aiofiles
from app.core.config import settings
from loguru import logger


THUMB_SIZE = (400, 500)
MEDIUM_SIZE = (800, 1000)
MAX_SIZE = (1600, 2000)


def _get_upload_path(subfolder: str) -> Path:
    path = Path(settings.UPLOAD_DIR) / subfolder
    path.mkdir(parents=True, exist_ok=True)
    return path


async def _compress_and_save(file_bytes: bytes, save_path: Path, max_size: tuple, quality: int = 85) -> str:
    """Compress image and save to disk."""
    loop = asyncio.get_event_loop()

    def process():
        img = Image.open(io.BytesIO(file_bytes))
        # Convert to RGB if needed (e.g. PNG with alpha)
        if img.mode in ("RGBA", "P", "LA"):
            background = Image.new("RGB", img.size, (255, 255, 255))
            if img.mode == "RGBA":
                background.paste(img, mask=img.split()[3])
            else:
                background.paste(img)
            img = background
        elif img.mode != "RGB":
            img = img.convert("RGB")

        img.thumbnail(max_size, Image.LANCZOS)
        img.save(str(save_path), format="JPEG", quality=quality, optimize=True)
        return str(save_path)

    return await loop.run_in_executor(None, process)


async def upload_product_image(file: UploadFile, product_id: str) -> dict:
    """Upload product image, create thumbnail and medium versions."""
    # Validate type
    if file.content_type not in settings.ALLOWED_IMAGE_TYPES:
        raise HTTPException(400, f"Invalid file type. Allowed: {settings.ALLOWED_IMAGE_TYPES}")

    # Read file
    contents = await file.read()
    if len(contents) > settings.MAX_UPLOAD_SIZE:
        raise HTTPException(400, f"File too large. Max {settings.MAX_UPLOAD_SIZE // 1024 // 1024}MB")

    # Generate unique filename
    file_id = str(uuid.uuid4())
    base_path = _get_upload_path(f"products/{product_id}")

    # Paths
    original_path = base_path / f"{file_id}_original.jpg"
    medium_path = base_path / f"{file_id}_medium.jpg"
    thumb_path = base_path / f"{file_id}_thumb.jpg"

    # Save all sizes
    await _compress_and_save(contents, original_path, MAX_SIZE, quality=90)
    await _compress_and_save(contents, medium_path, MEDIUM_SIZE, quality=85)
    await _compress_and_save(contents, thumb_path, THUMB_SIZE, quality=80)

    # Upload to S3 if configured
    if settings.USE_S3:
        url = await _upload_to_s3(str(original_path), f"products/{product_id}/{file_id}_original.jpg")
        thumb_url = await _upload_to_s3(str(thumb_path), f"products/{product_id}/{file_id}_thumb.jpg")
        # Clean up local files
        original_path.unlink(missing_ok=True)
        medium_path.unlink(missing_ok=True)
        thumb_path.unlink(missing_ok=True)
    else:
        base_url = "/uploads"
        url = f"{base_url}/products/{product_id}/{file_id}_original.jpg"
        thumb_url = f"{base_url}/products/{product_id}/{file_id}_thumb.jpg"

    logger.info(f"✅ Image uploaded for product {product_id}: {url}")
    return {"url": url, "thumbnail_url": thumb_url}


async def upload_category_image(file: UploadFile, category_id: str) -> str:
    if file.content_type not in settings.ALLOWED_IMAGE_TYPES:
        raise HTTPException(400, "Invalid file type")

    contents = await file.read()
    file_id = str(uuid.uuid4())
    base_path = _get_upload_path(f"categories")
    save_path = base_path / f"{category_id}_{file_id}.jpg"

    await _compress_and_save(contents, save_path, (800, 600), quality=85)

    if settings.USE_S3:
        return await _upload_to_s3(str(save_path), f"categories/{category_id}_{file_id}.jpg")

    return f"/uploads/categories/{category_id}_{file_id}.jpg"


async def upload_brand_logo(file: UploadFile, brand_id: str) -> str:
    if file.content_type not in settings.ALLOWED_IMAGE_TYPES:
        raise HTTPException(400, "Invalid file type")

    contents = await file.read()
    file_id = str(uuid.uuid4())
    base_path = _get_upload_path("brands")
    save_path = base_path / f"{brand_id}_{file_id}.jpg"

    await _compress_and_save(contents, save_path, (400, 400), quality=90)

    if settings.USE_S3:
        return await _upload_to_s3(str(save_path), f"brands/{brand_id}_{file_id}.jpg")

    return f"/uploads/brands/{brand_id}_{file_id}.jpg"


async def delete_file(file_url: str):
    """Delete a local file."""
    if settings.USE_S3:
        # Delete from S3
        return
    try:
        local_path = Path(file_url.lstrip("/"))
        if local_path.exists():
            local_path.unlink()
    except Exception as e:
        logger.error(f"Failed to delete file {file_url}: {e}")


async def _upload_to_s3(local_path: str, s3_key: str) -> str:
    """Upload file to AWS S3 and return CDN URL."""
    import boto3
    from botocore.exceptions import ClientError

    try:
        s3_client = boto3.client(
            "s3",
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            region_name=settings.AWS_REGION,
        )
        s3_client.upload_file(
            local_path, settings.AWS_BUCKET_NAME, s3_key,
            ExtraArgs={"ContentType": "image/jpeg", "ACL": "public-read"}
        )
        cdn_base = settings.AWS_CDN_URL or f"https://{settings.AWS_BUCKET_NAME}.s3.amazonaws.com"
        return f"{cdn_base}/{s3_key}"
    except ClientError as e:
        logger.error(f"S3 upload failed: {e}")
        raise HTTPException(500, "Failed to upload file to storage")
