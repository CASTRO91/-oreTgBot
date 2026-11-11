# CoreTgBot

Модульное масштабируемое ядро (SDK) для разработки высоконагруженных Telegram-ботов на Python.

## Основной стек
- **Python 3.12+**
- **aiogram 3.x**
- **SQLAlchemy 2.0 (Async)**
- **Alembic**
- **Pydantic Settings**

## Возможности платформы
- 🚀 **Встроенная очередь задач** с динамическим пулом асинхронных воркеров (`DynamicWorkerPool`).
- 🛡 **Ролевая модель доступа (RBAC / ACL)**: гибкое управление правами пользователей и администраторов.
- 🌍 **Мультиязычность и геосервисы**: учет часовых поясов, тихого времени для рассылок и автоперевод.
- 📬 **Отложенные и цикличные рассылки** (Cron, точное время, фильтрация по группам и пользователям).
- 🧹 **Retention Service**: автоматическая очистка устаревших задач и аудита.
- 🚦 **In-Memory Rate Limiting** с защитой от спама и утечек памяти.

## Быстрый старт

1. Склонируйте репозиторий:
```bash
git clone https://github.com/CASTRO91/-oreTgBot.git
cd -oreTgBot
```

2. Создайте и активируйте виртуальное окружение:
```bash
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# или для Windows:
# .venv\Scripts\activate
```

3. Установите зависимости:
```bash
pip install -r requirements.txt
```

4. Настройте конфигурацию:
```bash
cp .env.example .env
# Заполните BOT_TOKEN и ADMIN_ID в .env
```

5. Запустите бота:
```bash
python main.py
```
