from logging.config import fileConfig
from sqlalchemy import pool
from alembic import context
import os
import sys

# 🧭 Додаємо корінь проєкту до системного шляху
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# 🧩 Імпортуємо Flask app і SQLAlchemy db
from run import app
from onboarding_crm import db

# 📄 Alembic Config object
config = context.config

# 🧠 Налаштування логів, якщо файл alembic.ini існує
alembic_ini_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'alembic.ini')
if os.path.exists(alembic_ini_path):
    fileConfig(alembic_ini_path)
else:
    print(f"⚠️ Warning: alembic.ini not found at {alembic_ini_path}")

# 📦 Підключення metadata для autogenerate
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
    with app.app_context():
        connectable = db.engine  # Використовуємо Flask SQLAlchemy engine

        with connectable.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                compare_type=True,  # Важливо для оновлення типів колонок
            )

            with context.begin_transaction():
                context.run_migrations()


# 🔁 Вибір режиму: online або offline
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()