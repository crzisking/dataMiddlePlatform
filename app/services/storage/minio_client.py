"""MinIO 对象存储封装：上传原件的存取（P2 上传链路使用）。"""

from functools import lru_cache

from minio import Minio

from app.core.config import settings


@lru_cache
def get_minio() -> Minio:
    return Minio(
        endpoint=settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
    )


def ensure_bucket(bucket: str | None = None) -> str:
    """确保 bucket 存在，返回 bucket 名。"""
    client = get_minio()
    bucket = bucket or settings.minio_bucket
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)
    return bucket
