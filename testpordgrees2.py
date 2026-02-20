import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

print("🔍 DATABASE_URL:", DATABASE_URL)

try:
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    print("✅ Conexão com PostgreSQL OK — banco existe")
except Exception as e:
    print("❌ Falha ao conectar no PostgreSQL")
    print(type(e).__name__, e)
