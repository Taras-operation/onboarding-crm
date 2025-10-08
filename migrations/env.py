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

# 🧠 Вказуємо правильний шлях до alembic.ini (на рівень вище)
alembic_ini_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'alembic.ini')
if os.path.exists(alembic_ini_path):
    fileConfig(alembic_ini_path)
else:
    print(f"⚠️ Warning: alembic.ini not found at {alembic_ini_path}")

# 🗂️ Підключаємо metadata
target_metadata = db.metadata


def run_migrations_offline():
    """Run migrations in 'offline' mode."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    """Run migrations in 'online' mode."""
    config.set_main_option('sqlalchemy.url', app.config['SQLALCHEMY_DATABASE_URI'])
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
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