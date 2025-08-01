from sqlalchemy import create_engine, MetaData, Table
from sqlalchemy.exc import SQLAlchemyError

# 1️⃣ Пути к базам
sqlite_url = "sqlite:///instance/onboarding.db"  # локальный SQLite
postgres_url = "postgresql://onboarding_crm_db_user:AAqgiBr6bVfD7CaN3QqWTGE83CT3WiVO@dpg-d2521t2dbo4c73a7v1gg-a/onboarding_crm_db"  # Render Postgres

# 2️⃣ Подключаем движки
sqlite_engine = create_engine(sqlite_url)
pg_engine = create_engine(postgres_url)

sqlite_metadata = MetaData()
sqlite_metadata.reflect(bind=sqlite_engine)

# 3️⃣ Создаём таблицы в Postgres, если их нет
for table_name, table in sqlite_metadata.tables.items():
    try:
        print(f"🛠 Создаю таблицу {table_name} в Postgres (если отсутствует)")
        table_pg = Table(table_name, MetaData())
        for c in table.columns:
            table_pg.append_column(c.copy())
        table_pg.create(bind=pg_engine, checkfirst=True)
    except SQLAlchemyError as e:
        print(f"⚠ Ошибка при создании таблицы {table_name}: {e}")

# 4️⃣ Перенос данных
sqlite_conn = sqlite_engine.connect()
pg_conn = pg_engine.connect()

for table_name in sqlite_metadata.tables:
    try:
        rows = sqlite_conn.execute(f"SELECT * FROM {table_name}").fetchall()
        if rows:
            columns = sqlite_metadata.tables[table_name].columns.keys()
            placeholders = ",".join([f"%s" for _ in columns])
            insert_query = f'INSERT INTO {table_name} ({",".join(columns)}) VALUES ({placeholders})'
            for row in rows:
                pg_conn.execute(insert_query, tuple(row))
            print(f"✅ Перенесено {len(rows)} строк из {table_name}")
        else:
            print(f"ℹ Таблица {table_name} пуста, пропускаю")
    except SQLAlchemyError as e:
        print(f"⚠ Ошибка при переносе данных из {table_name}: {e}")

pg_conn.commit()
sqlite_conn.close()
pg_conn.close()

print("🎉 Перенос завершён успешно!")