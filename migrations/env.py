from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context
import os
import sys

# 🧭 Додаємо корінь проєкту до системного шляху
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# 🧩 Імпортуємо app з run.py та db з проєкту
from run import app
from onboarding_crm import db

# 📄 Alembic Config object
config = context.config

# 🧠 Логін конфіг (опційно)
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 🗂️ Підключаємо metadata
target_metadata = db.metadata


def run_migrations_offline():
    """Run migrations in 'offline' mode."""
    url = app.config['SQLALCHEMY_DATABASE_URI']
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    """Run migrations in 'online' mode."""
    url = app.config['SQLALCHEMY_DATABASE_URI']
    connectable = engine_from_config(
        {"sqlalchemy.url": url},
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with app.app_context():
        with connectable.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                compare_type=True,
            )

            with context.begin_transaction():
                context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()