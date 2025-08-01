from sqlalchemy import create_engine, MetaData, Table
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.sql import text

# 1️⃣ Пути к базам
sqlite_url = "sqlite:///instance/onboarding.db"
PG_URL = "postgresql://onboarding_crm_db_user:AAqgiBr6bVfD7CaN3QqWTGE83CT3WiVO@dpg-d2521t2dbo4c73a7v1gg-a.oregon-postgres.render.com/onboarding_crm_db"

# 2️⃣ Подключаем движки
sqlite_engine = create_engine(sqlite_url)
pg_engine = create_engine(PG_URL)

sqlite_metadata = MetaData()
sqlite_metadata.reflect(bind=sqlite_engine)

# 3️⃣ Создаём таблицы в Postgres
for table_name, table in sqlite_metadata.tables.items():
    try:
        print(f"🛠 Создаю таблицу {table_name} в Postgres (если отсутствует)")
        table_pg = table.to_metadata(MetaData())
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
            col_names = ",".join(columns)
            placeholders = ",".join([f":{col}" for col in columns])
            insert_query = text(f'INSERT INTO {table_name} ({col_names}) VALUES ({placeholders})')
            for row in rows:
                pg_conn.execute(insert_query, dict(zip(columns, row)))
            print(f"✅ Перенесено {len(rows)} строк из {table_name}")
        else:
            print(f"ℹ Таблица {table_name} пуста, пропускаю")
    except SQLAlchemyError as e:
        print(f"⚠ Ошибка при переносе данных из {table_name}: {e}")

pg_conn.commit()
sqlite_conn.close()
pg_conn.close()

print("🎉 Перенос завершён успешно!")