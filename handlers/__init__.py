from aiogram import Dispatcher
from handlers.registration import router as registration_router
from handlers.user import router as user_router
from handlers.admin import router as admin_router
from handlers.mailing import router as mailing_router

def register_all_handlers(dp: Dispatcher):
    """Регистрируем роутеры в строгом порядке приоритета."""
    dp.include_router(registration_router)
    dp.include_router(admin_router)
    dp.include_router(user_router)
    dp.include_router(mailing_router)