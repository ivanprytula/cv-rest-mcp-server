from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Import every ORM model module for its side effect of registering the table
# on Base.metadata -- autogenerate only sees tables whose module has actually
# been imported somewhere. Add future models (e.g. a Revision row) here too.
import services.portfolio.auth.refresh_token_row  # noqa: F401,E402
import services.portfolio.auth.user_row  # noqa: F401,E402
import services.portfolio.documents.document_row  # noqa: F401,E402
import services.portfolio.gaps.job_posting_row  # noqa: F401,E402
import services.portfolio.revisions.revision_row  # noqa: F401,E402
from services.portfolio.db import Base
from services.portfolio.settings import settings


# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging. disable_existing_loggers=False
# because fileConfig's default (True) silently disables every logger that
# already exists at call time -- including the app's own module loggers and,
# in tests, pytest's caplog handler -- breaking log capture/output for the
# rest of the process for any code that runs after a migration.
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# Autogenerate target: every Base-registered model across the app.
target_metadata = Base.metadata

# Programmatic runs (db_migrations.upgrade_head, used by the app lifespan and
# the test fixture) set `sqlalchemy.url` directly on the Config object before
# invoking Alembic — that value wins. CLI runs (`alembic revision
# --autogenerate`, `alembic upgrade head` from a terminal) never set it, so
# they fall back to DATABASE_URL via settings, swapping in the sync driver
# Alembic needs (the one place that swap happens — settings.sync_database_url).
_UNSET_INI_URL = "driver://user:pass@localhost/dbname"
if config.get_main_option("sqlalchemy.url") == _UNSET_INI_URL and settings.database_url:
    config.set_main_option("sqlalchemy.url", settings.sync_database_url)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
