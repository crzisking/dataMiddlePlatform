"""全局配置：把 .env / 环境变量里的设置读进来，供全项目使用。

设计要点：所有"会变的值"（数据库密码、各种密钥、地址）都放在 .env 里，
代码只通过这里的 settings 对象去拿，绝不把密钥写死在代码里。
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # 这个类继承自 BaseSettings。当我们创建它的实例时，父类会自动去读 .env
    # 和系统环境变量，按"字段名"对号入座地把值填进下面每个字段，并按声明的
    # 类型做转换+校验（比如把 .env 里的字符串 "5432" 转成整数）。
    #
    # model_config 是 pydantic 约定的"保留名字"，框架会自动找它当配置，
    # 我们不用手动调用它——只要名字叫 model_config 就行。
    model_config = SettingsConfigDict(
        env_file=".env",  # 去项目根目录的 .env 读
        env_file_encoding="utf-8",  # 指定 UTF-8：Windows 默认是 GBK，.env 里有中文会乱码
        extra="ignore",  # .env 里有、但这里没声明的键，忽略掉（默认行为是直接报错）
        case_sensitive=False,  # 不区分大小写：.env 写 PG_HOST 能对上字段 pg_host
    )

    # 下面每个字段就是一个配置项。等号后面的值是"兜底默认值"，
    # 只有当 .env 和环境变量里都没有这一项时才会用到它。

    # —— 应用本身 ——
    app_name: str = "data-middle-platform"
    app_env: str = "dev"
    app_debug: bool = True
    app_host: str = "0.0.0.0"
    app_port: int = 8000

    # —— PostgreSQL：存向量和中台自己的元数据 ——
    pg_host: str = "127.0.0.1"
    pg_port: int = 5432
    pg_user: str = "postgres"
    pg_password: str = "changeme"
    pg_database: str = "data_platform"

    # —— SQL Server：业务数据(只读)，给 TextToSQL 用，P5 才启用 ——
    mssql_host: str = ""
    mssql_port: int = 1433
    mssql_user: str = ""
    mssql_password: str = ""
    mssql_database: str = ""
    # 查询超时(秒)：TextToSQL 执行业务查询时的护栏之一，防止一条慢 SQL 拖垮连接。
    mssql_timeout: int = 30
    # TDS 协议版本。业务库是 SQL Server 2008 R2，pymssql 自带的新版 FreeTDS 用 7.1~7.4
    # 跟它做 TLS 握手会失败(老库的 TLS 跟新 OpenSSL 谈不拢)，只有 7.0 能连上。
    # 代价：7.0 不认 2008 的新类型(date/datetime2)，会把它们降级成字符串返回——
    # 值是对的，对"只读结果转文本喂模型"的 TextToSQL 来说够用。
    # 若将来换成 pyodbc + ODBC Driver 17，这个配置就不再用得上。
    mssql_tds_version: str = "7.0"

    # —— MinIO：存上传的原始文件 ——
    minio_endpoint: str = "192.168.120.198:9000"
    minio_access_key: str = ""
    minio_secret_key: str = ""
    minio_bucket: str = "temp"
    minio_secure: bool = False

    # —— 大模型：通义千问（走 DashScope 的 OpenAI 兼容接口）——
    qwen_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    qwen_api_key: str = ""
    qwen_default_model: str = "qwen-plus"

    # —— 大模型：DeepSeek ——
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    deepseek_api_key: str = ""
    deepseek_default_model: str = "deepseek-chat"

    # —— 可暴露给前端的对话模型白名单（逗号分隔）——
    # 从厂商官网/接口查到要用的模型名填这里，不写死在代码里：厂商 /models 会返回上百个
    # 混杂模型(图像/语音/第三方等)，不能直接全暴露，所以由运维在这里挑出要用的几个。
    # 改了无需动代码，重启生效。模型名→厂商的路由也按这两个列表自动建（见 llm/client.py）。
    qwen_models: str = "qwen-plus,qwen-max,qwen-turbo"
    deepseek_models: str = "deepseek-chat,deepseek-reasoner"

    # —— 向量化模型 ——
    embedding_model: str = "text-embedding-v3"
    embedding_dim: int = 1024

    # —— 重排序(rerank)：混合检索后用通义 rerank 模型对候选再精排，可配开关 ——
    rerank_enabled: bool = False  # 默认关；开了会多一次 API 调用、增加延迟，但更准
    rerank_model: str = "gte-rerank-v2"
    # 通义 rerank 是 DashScope 原生接口(非 OpenAI 兼容)，单独一个地址
    dashscope_rerank_url: str = (
        "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank"
    )

    # —— 上传限制（白名单和大小都能通过 .env 改）——
    upload_max_mb: int = 100
    # 只允许这几种"能解析出文字"的格式。注意没放 doc/xls：
    # 它们是老二进制格式，目前解析不了，放进来只会让用户传上去后失败。
    upload_allowed_exts: str = "pdf,docx,xlsx,txt,md"

    # 文档类型受控词表（逗号分隔）：上传/筛选下拉的来源，由 /meta/doc-types 返回。
    # 受控好处：分类统一、便于过滤/将来权限。改它只改 .env、不动代码（同模型白名单思路）。
    doc_types: str = "通用,SOP,工艺,质量,设备手册,制度"

    # —— 上线硬化（P8）——
    # LLM / embedding 调用的重试与超时：通义/DeepSeek 偶发 429 限流 / 超时，openai SDK 会按
    # max_retries 自动重试 + 指数退避（覆盖 B2 上游容错、C1 瞬时失败重试）。
    llm_max_retries: int = 3
    llm_timeout: int = 60  # 单次 LLM 请求超时（秒），防一个卡住的请求拖很久
    # 同时处理的请求数上限：超过直接返回 503，保护本机和上游不被打爆。
    # 目标并发 200~300，先留余量设 400，压测后再调（B1）。
    max_concurrent_requests: int = 400
    # DB 连接池：请求大多在等 LLM、用 DB 很短，池子不必太大但要够并发借用（C2）。
    db_pool_size: int = 20
    db_max_overflow: int = 20  # 池满后还能临时多开这么多，超出才排队
    db_statement_timeout_ms: int = 30000  # 单条 SQL 超时（毫秒），防慢查询挂住连接

    @property
    def upload_max_bytes(self) -> int:
        """把"多少 MB"换算成"多少字节"，方便和文件实际大小比较。"""
        return self.upload_max_mb * 1024 * 1024

    @property
    def allowed_exts(self) -> set[str]:
        """把逗号分隔的白名单字符串，拆成一个扩展名集合（小写、去掉前面的点）。"""
        parts = self.upload_allowed_exts.split(",")
        return {e.strip().lower().lstrip(".") for e in parts if e.strip()}

    @property
    def doc_type_list(self) -> list[str]:
        """文档类型受控词表（从逗号分隔的 doc_types 解析）。"""
        return [t.strip() for t in self.doc_types.split(",") if t.strip()]

    @property
    def qwen_model_list(self) -> list[str]:
        """通义可暴露模型名列表（从逗号分隔的 qwen_models 解析）。"""
        return [m.strip() for m in self.qwen_models.split(",") if m.strip()]

    @property
    def deepseek_model_list(self) -> list[str]:
        """DeepSeek 可暴露模型名列表（从逗号分隔的 deepseek_models 解析）。"""
        return [m.strip() for m in self.deepseek_models.split(",") if m.strip()]

    # 下面三个属性：把 .env 里散开的 host/port/user/... 拼成一整串连接字符串。
    # 为什么要三个：连库的不同工具，认的连接串格式不一样，各拼一个给它们。
    @property
    def pg_dsn(self) -> str:
        """给 SQLAlchemy 异步引擎用。前缀 postgresql+psycopg 表示走 psycopg3 异步驱动。"""
        return (
            f"postgresql+psycopg://{self.pg_user}:{self.pg_password}"
            f"@{self.pg_host}:{self.pg_port}/{self.pg_database}"
        )

    @property
    def pg_dsn_sync(self) -> str:
        """给 Alembic 数据库迁移用。迁移是一次性脚本，用同步连接更简单稳妥。"""
        return (
            f"postgresql+psycopg://{self.pg_user}:{self.pg_password}"
            f"@{self.pg_host}:{self.pg_port}/{self.pg_database}"
        )

    @property
    def mssql_configured(self) -> bool:
        """SQL Server 是否已配齐连接信息。没配齐时 TextToSQL 相关功能直接跳过，
        不去尝试连接（避免一堆连不上的报错）。host + 库名都填了才算配好。"""
        return bool(self.mssql_host and self.mssql_database)

    @property
    def pg_conninfo(self) -> str:
        """给 procrastinate(任务队列)用。它要的是最原始的连接串，不带 +psycopg 前缀。"""
        return (
            f"postgresql://{self.pg_user}:{self.pg_password}"
            f"@{self.pg_host}:{self.pg_port}/{self.pg_database}"
        )


# @lru_cache 不带参数 = 让这个函数只真正执行一次，之后每次调用都返回同一个结果。
# 这样配置只会被解析一次（读文件有成本），全项目共享同一份 Settings。
@lru_cache
def get_settings() -> Settings:
    return Settings()


# 模块级单例：别的文件直接 `from app.core.config import settings` 就能用。
settings = get_settings()
