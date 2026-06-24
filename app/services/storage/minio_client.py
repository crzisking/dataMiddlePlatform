"""连接 MinIO(对象存储)，用来存放上传的原始文件。

对象存储可以简单理解成"一个放文件的大网盘"：每个文件叫一个 object，
用一个 key(类似文件路径)来定位，文件分门别类放在 bucket(桶)里。
"""

from functools import lru_cache

from minio import Minio

from app.core.config import settings


# lru_cache 让这个函数只真正建一次 client，之后都复用同一个(建连接有开销)。
@lru_cache
def get_minio() -> Minio:
    """创建并返回 MinIO 客户端(全项目复用一个)。"""
    return Minio(
        endpoint=settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,  # True=用 https，False=用 http
    )


def ensure_bucket(bucket: str | None = None) -> str:
    """确保桶(bucket)存在：不存在就创建。返回桶名。

    不传参数时用配置里的默认桶。存文件前先调它，避免桶不存在导致上传失败。
    """
    client = get_minio()
    bucket = bucket or settings.minio_bucket
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)
    return bucket
