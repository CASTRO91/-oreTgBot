from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession
from core.config import settings

from utils.states import RegistrationStates, ProfileEditStates
from utils.keyboards import get_phone_request_kb, get_profile_edit_kb
from services.user_service import UserService
from database.models.user import User

from services.geo_service import GeoService
from services.i18n_service import I18nService
from utils.keyboards import get_address_request_kb, get_timezone_selection_kb

router = Router(name="registration_router")


# --- СЦЕНАРИЙ РЕГИСТРАЦИИ ---
from utils.validators import InputValidator
from services.geo_service import GeoService
from services.i18n_service import I18nService
from core.config import settings


@router.message(RegistrationStates.waiting_for_first_name)
async def process_first_name(message: types.Message, state: FSMContext) -> None:
    is_valid, err_msg = InputValidator.validate_name(message.text or "")
    if not is_valid:
        await message.answer(err_msg)
        return

    await state.update_data(first_name=message.text.strip())
    await state.set_state(RegistrationStates.waiting_for_last_name)
    text = await I18nService.tr("Отлично! Теперь введите вашу <b>Фамилию</b>:", "ru")
    await message.answer(text, parse_mode="HTML")


@router.message(RegistrationStates.waiting_for_last_name)
async def process_last_name(message: types.Message, state: FSMContext) -> None:
    is_valid, err_msg = InputValidator.validate_name(message.text or "")
    if not is_valid:
        await message.answer(err_msg)
        return

    await state.update_data(last_name=message.text.strip())
    await state.set_state(RegistrationStates.waiting_for_address)

    text = await I18nService.tr(
        "Введите ваш <b>Адрес</b> (город, улица, дом) или нажмите кнопку <b>📍 Поделиться геопозицией</b> ниже:",
        "ru"
    )
    await message.answer(text, parse_mode="HTML", reply_markup=await get_address_request_kb())


@router.message(RegistrationStates.waiting_for_address, F.location | F.text)
async def process_address(message: types.Message, state: FSMContext) -> None:
    lat, lon = None, None
    address_text = ""

    if message.location:
        lat = message.location.latitude
        lon = message.location.longitude
        # Определяем часовой пояс
        user_tz = GeoService.get_timezone_from_coordinates(lat, lon)

        await message.answer("🔄 <i>Определяем ваш адрес по спутникам...</i>", parse_mode="HTML")
        # ОБРАТНОЕ ГЕОКОДИРОВАНИЕ: Координаты -> Реальный адрес
        address_text = await GeoService.reverse_geocode(lat, lon)
    else:
        # Валидация текста адреса
        is_valid, err_msg = InputValidator.validate_address(message.text or "")
        if not is_valid:
            await message.answer(err_msg)
            return

        raw_text = message.text.strip()
        address_text, user_tz, lat, lon = await GeoService.geocode_text_address(raw_text)

    await state.update_data(
        address=address_text,
        latitude=lat,
        longitude=lon,
        timezone=user_tz
    )
    await state.set_state(RegistrationStates.waiting_for_phone)
    text = await I18nService.tr(
        "Остался последний шаг. Отправьте ваш <b>номер телефона</b> с помощью кнопки ниже или нажмите «Пропустить шаг»:",
        "ru"
    )
    await message.answer(text, parse_mode="HTML", reply_markup=await get_phone_request_kb())


@router.message(RegistrationStates.waiting_for_phone, F.contact | (F.text == "Пропустить шаг"))
async def process_phone(message: types.Message, state: FSMContext, session: AsyncSession) -> None:
    phone = message.contact.phone_number if message.contact else None
    data = await state.get_data()

    user = await UserService.register_user(
        session=session,
        telegram_id=message.from_user.id,
        username=message.from_user.username,
        first_name=data["first_name"],
        last_name=data["last_name"],
        address=data["address"],
        phone=phone,
        timezone=data.get("timezone", settings.DEFAULT_TIMEZONE),
        latitude=data.get("latitude"),
        longitude=data.get("longitude")
    )

    await state.clear()

    # ПЕРЕДАЕМ И address, И timezone В ФОРМАТТЕР:
    success_text = I18nService.get_text(
        "reg_complete",
        "ru",
        address=user.address,
        timezone=user.timezone
    )

    await message.answer(
        success_text,
        parse_mode="HTML",
        reply_markup=types.ReplyKeyboardRemove()
    )

# --- СЦЕНАРИЙ ИЗМЕНЕНИЯ ДАННЫХ ПРОФИЛЯ ---

@router.callback_query(F.data == "edit_first_name")
async def start_edit_fn(cb: types.CallbackQuery, state: FSMContext):
    await state.set_state(ProfileEditStates.waiting_for_new_first_name)
    await cb.message.answer("Введите новое <b>Имя</b>:", parse_mode="HTML")
    await cb.answer()


@router.message(ProfileEditStates.waiting_for_new_first_name)
async def save_new_fn(message: types.Message, state: FSMContext, session: AsyncSession) -> None:
    is_valid, err_msg = InputValidator.validate_name(message.text or "")
    if not is_valid:
        await message.answer(err_msg)
        return
    await UserService.update_profile(session, message.from_user.id, first_name=message.text.strip())
    await state.clear()
    await message.answer("✅ Имя успешно обновлено!")


@router.callback_query(F.data == "edit_last_name")
async def start_edit_ln(cb: types.CallbackQuery, state: FSMContext):
    await state.set_state(ProfileEditStates.waiting_for_new_last_name)
    await cb.message.answer("Введите новую <b>Фамилию</b>:", parse_mode="HTML")
    await cb.answer()


@router.message(ProfileEditStates.waiting_for_new_last_name)
async def save_new_ln(message: types.Message, state: FSMContext, session: AsyncSession):
    await UserService.update_profile(session, message.from_user.id, last_name=message.text.strip())
    await state.clear()
    await message.answer("✅ Фамилия успешно обновлена!")


# --- РЕДАКТИРОВАНИЕ АДРЕСА ИЗ ПРОФИЛЯ ---

@router.callback_query(F.data == "edit_address")
async def start_edit_addr(cb: types.CallbackQuery, state: FSMContext) -> None:
    """
    Назначение: Запрос нового адреса с клавиатурой геолокации.
    """
    await state.set_state(ProfileEditStates.waiting_for_new_address)
    await cb.message.answer(
        "🏠 Введите новый <b>Адрес</b> текстом или нажмите кнопку <b>📍 Поделиться геопозицией</b> ниже:",
        reply_markup=await get_address_request_kb(),
        parse_mode="HTML"
    )
    await cb.answer()


@router.message(ProfileEditStates.waiting_for_new_address, F.location | F.text)
async def save_new_addr(message: types.Message, state: FSMContext, session: AsyncSession) -> None:
    """
    Назначение: Сохранение обновленного адреса (текстом или через обратное геокодирование) с пересчетом таймзоны.
    """
    lat, lon = None, None
    address_text = ""
    user_tz = None

    if message.location:
        lat = message.location.latitude
        lon = message.location.longitude
        # 1. Считаем часовой пояс по новым координатам
        user_tz = GeoService.get_timezone_from_coordinates(lat, lon)

        await message.answer("🔄 <i>Определяем ваш новый адрес по спутникам...</i>", parse_mode="HTML")
        # 2. Вычисляем человеческий адрес через OpenStreetMap
        address_text = await GeoService.reverse_geocode(lat, lon)
    else:
        # Валидация текста
        is_valid, err_msg = InputValidator.validate_address(message.text or "")
        if not is_valid:
            await message.answer(err_msg)
            return

        raw_text = message.text.strip()
        address_text, user_tz, lat, lon = await GeoService.geocode_text_address(raw_text)

    # Обновляем профиль в БД (адрес, координаты и часовой пояс)
    update_data = {
        "address": address_text,
        "latitude": lat,
        "longitude": lon
    }
    if user_tz:
        update_data["timezone"] = user_tz

    await UserService.update_profile(session, message.from_user.id, **update_data)
    await state.clear()

    await message.answer(
        f"✅ <b>Адрес успешно обновлен!</b>\n"
        f"▫️ <b>Новый адрес:</b> {address_text}\n"
        f"▫️ <b>Часовой пояс:</b> <code>{user_tz}</code>",
        parse_mode="HTML",
        reply_markup=types.ReplyKeyboardRemove()
    )


@router.callback_query(F.data == "edit_phone")
async def start_edit_phone(cb: types.CallbackQuery, state: FSMContext):
    await state.set_state(ProfileEditStates.waiting_for_new_phone)
    await cb.message.answer("Отправьте новый <b>Телефон</b>:", reply_markup=await get_phone_request_kb(), parse_mode="HTML")
    await cb.answer()


@router.message(ProfileEditStates.waiting_for_new_phone, F.contact | (F.text == "Пропустить шаг"))
async def save_new_phone(message: types.Message, state: FSMContext, session: AsyncSession):
    phone = message.contact.phone_number if message.contact else None
    await UserService.update_profile(session, message.from_user.id, phone=phone)
    await state.clear()
    await message.answer("✅ Телефон обновлен!", reply_markup=types.ReplyKeyboardRemove())