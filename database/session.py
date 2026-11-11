from pathlib import Path
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import event
from core.config import settings

# ЖЕСТКИЙ АБСОЛЮТНЫЙ ПУТЬ К КОРНЮ ПРОЕКТА
ROOT_DIR = Path(__file__).resolve().parent.parent
REAL_DB_FILE = ROOT_DIR / "core_database.db"

# Если в конфиге SQLite — принудительно перенаправляем на абсолютный файл в корне
db_url = settings.DB_URL
if db_url.startswith("sqlite"):
    db_url = f"sqlite+aiosqlite:///{REAL_DB_FILE.as_posix()}"

engine = create_async_engine(db_url, echo=False)

if db_url.startswith("sqlite"):
    @event.listens_for(engine.sync_engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False
)

async def get_db_session() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session