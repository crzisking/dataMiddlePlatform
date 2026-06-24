"""全局配置：从环境变量 / .env 读取，按前缀分组。"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # 继承 BaseSettings：实例化时父类会自动读 .env + 环境变量，按字段名填值并做类型校验。
    # model_config 是 pydantic 的保留名，框架自动识别，无需手动调用。
    model_config = SettingsConfigDict(
        env_file=".env",  # 从项目根目录的 .env 读取
        env_file_encoding="utf-8",  # 显式 UTF-8：Windows 默认 GBK，含中文注释会乱码
        extra="ignore",  # .env 里多出的、类里没声明的键忽略（默认是 forbid 会报错）
        case_sensitive=False,  # 大小写不敏感：.env 的 PG_HOST 自动对应字段 pg_host
    )

    # 下方每个字段 = 一个配置项；「= 值」是兜底默认，仅当 .env/环境变量都没有时才生效。

    # 应用
    app_name: str = "data-middle-platform"
    app_env: str = "dev"
    app_debug: bool = True
    app_host: str = "0.0.0.0"
    app_port: int = 8000

    # PostgreSQL（向量库 + 元数据）
    pg_host: str = "127.0.0.1"
    pg_port: int = 5432
    pg_user: str = "postgres"
    pg_password: str = "changeme"
    pg_database: str = "data_platform"

    # SQL Server（业务数据，只读；P5 启用）
    mssql_host: str = ""
    mssql_port: int = 1433
    mssql_user: str = ""
    mssql_password: str = ""
    mssql_database: str = ""

    # MinIO
    minio_endpoint: str = "192.168.120.198:9000"
    minio_access_key: str = ""
    minio_secret_key: str = ""
    minio_bucket: str = "temp"
    minio_secure: bool = False

    # LLM：通义千问（DashScope OpenAI 兼容）
    qwen_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    qwen_api_key: str = ""
    qwen_default_model: str = "qwen-plus"

    # LLM：DeepSeek
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    deepseek_api_key: str = ""
    deepseek_default_model: str = "deepseek-chat"

    # Embedding
    embedding_model: str = "text-embedding-v3"
    embedding_dim: int = 1024

    # 上传限制（白名单可配置：逗号分隔的扩展名；大小单位 MB）
    upload_max_mb: int = 100
    upload_allowed_exts: str = "pdf,doc,docx,xls,xlsx,txt,md"

    @property
    def upload_max_bytes(self) -> int:
        return self.upload_max_mb * 1024 * 1024

    @property
    def allowed_exts(self) -> set[str]:
        """白名单扩展名集合（小写、去点）。"""
        parts = self.upload_allowed_exts.split(",")
        return {e.strip().lower().lstrip(".") for e in parts if e.strip()}

    # 同一个 PG，三种连接串：散落的 host/port/... 拼成各组件要的格式（.env 里放不了这种拼装）。
    # 之所以分三个，是因为用它们的库各认各的格式：
    @property
    def pg_dsn(self) -> str:
        """SQLAlchemy 异步引擎用（postgresql+psycopg = 走 psycopg3 异步驱动）。"""
        return (
            f"postgresql+psycopg://{self.pg_user}:{self.pg_password}"
            f"@{self.pg_host}:{self.pg_port}/{self.pg_database}"
        )

    @property
    def pg_dsn_sync(self) -> str:
        """Alembic 迁移用：迁移是一次性脚本，用同步连接更简单可靠（无需异步事件循环）。"""
        return (
            f"postgresql+psycopg://{self.pg_user}:{self.pg_password}"
            f"@{self.pg_host}:{self.pg_port}/{self.pg_database}"
        )

    @property
    def pg_conninfo(self) -> str:
        """procrastinate 用：要原生 libpq 连接串（不带 +psycopg 这种 SQLAlchemy 方言前缀）。"""
        return (
            f"postgresql://{self.pg_user}:{self.pg_password}"
            f"@{self.pg_host}:{self.pg_port}/{self.pg_database}"
        )


# lru_cache 无参 = 单例：配置只解析一次（读文件有成本），全项目共享同一份。
@lru_cache
def get_settings() -> Settings:
    return Settings()


# 模块级单例，其他文件直接 `from app.core.config import settings` 使用。
settings = get_settings()
