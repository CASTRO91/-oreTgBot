from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path

# 1. Вычисляем корень и путь к БД
BASE_DIR = Path(__file__).resolve().parent.parent
DB_FILE = BASE_DIR / "core_database.db"

# Для Windows SQLite нужно 4 слэша при абсолютном пути
DB_PATH_STR = DB_FILE.as_posix()
if not DB_PATH_STR.startswith("/"):
    DB_PATH_STR = f"/{DB_PATH_STR}"

SQLITE_URL = f"sqlite+aiosqlite:///{DB_PATH_STR}"


class Settings(BaseSettings):
    BOT_TOKEN: str
    ADMIN_ID: int

    # База данных со строгой аннотацией : str
    DB_URL: str = SQLITE_URL


    # --- НАСТРОЙКИ ДИНАМИЧЕСКОГО ПУЛА ВОРКЕРОВ ---
    MIN_WORKERS: int = 3  # Минимальное число дежурных воркеров
    MAX_WORKERS: int = 20  # Максимальный потолок при пиках нагрузки
    WORKER_IDLE_TIMEOUT: float = 20.0  # Секунды простоя до откисания доп. воркера
    MAX_TASKS_PER_WORKER: int = 100  # Лимит задач до мягкого перезапуска (очистка памяти)
    MAX_WORKER_LIFETIME: float = 3600.0  # Время жизни воркера в секундах (1 час)

    # Опрос очереди и повторы
    POLL_INTERVAL: float = 1.0
    DEFAULT_MAX_ATTEMPTS: int = 2

    # --- НАСТРОЙКИ УМНОГО СПЯЩЕГО РЕЖИМА (SMART IDLE) ---
    POLL_MIN_INTERVAL: float = 1.0  # Начальный сон при отсутствии задач (сек)
    POLL_MAX_INTERVAL: float = 15.0  # Максимальный сон в глубоком простое (сек)
    POLL_BACKOFF_FACTOR: float = 1.5  # Множитель увеличения задержки сна

    # --- НАСТРОЙКИ АВТООЧИСТКИ (RETENTION POLICY) ---
    RETENTION_DAYS_TASKS: int = 7  # Сколько дней хранить завершенные задачи
    RETENTION_DAYS_LOGS: int = 30  # Сколько дней хранить логи действий
    CLEANUP_INTERVAL_HOURS: int = 24  # Как часто запускать уборщик (в часах)

    # Безопасность
    RATE_LIMIT_DELAY: float = 0.5

    # --- НАСТРОЙКИ ЧАСОВЫХ ПОЯСОВ И РАССЫЛОК ---
    DEFAULT_TIMEZONE: str = "Europe/Minsk"  # Дефолтный часовой пояс (Минск)
    DEFAULT_LANGUAGE: str = "ru"  # Дефолтный язык платформы
    QUIET_HOURS_START: int = 22  # Начало тихих часов (22:00)
    QUIET_HOURS_END: int = 9  # Окончание тихих часов (09:00)
    SCHEDULER_CHECK_INTERVAL: float = 15.0  # Частота проверки рассылок планировщиком (сек)

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


settings = Settings()
