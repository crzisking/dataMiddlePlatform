"""Alembic 迁移环境（同步执行，DSN 与模型元数据从 app 注入）。"""

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context
from app.core.config import settings
from app.models import Base  # noqa: F401  确保所有模型被导入

config = context.config
config.set_main_option("sqlalchemy.url", settings.pg_dsn_sync)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def include_name(name: str | None, type_: str, parent_names: dict) -> bool:
    """只比对我们自己模型里的表，忽略其它表(比如 procrastinate 队列自己建的表)。

    否则 autogenerate 会把"库里有、模型里没有"的 procrastinate 表当成
    "要删除的表"，生成误删它们的迁移——非常危险。
    """
    if type_ == "table":
        return name in target_metadata.tables
    return True


def run_migrations_offline() -> None:
    context.configure(
        url=settings.pg_dsn_sync,
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        include_name=include_name,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            include_name=include_name,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
