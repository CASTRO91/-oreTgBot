import html
from aiogram import Router, types, F
from aiogram import Bot
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.user import User, UserRole
from database.models.permission import Permission, UserPermission
from utils.states import RegistrationStates
from utils.keyboards import get_profile_edit_kb, get_language_selection_kb, get_timezone_selection_kb
from services.i18n_service import I18nService
from services.user_service import UserService
from services.media_relay_service import MediaRelayService
from utils.states import SupportStates
from utils.keyboards import get_about_kb





router = Router(name="user_router")


@router.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext, db_user: User | None) -> None:
    if db_user:
        welcome_text = await I18nService.tr(
            "👋 С возвращением, <b>{first_name}</b>!\nИспользуйте /profile для просмотра профиля.",
            db_user.language_code,
            first_name=db_user.first_name
        )
        await message.answer(welcome_text, parse_mode="HTML")
        return

    # Для нового юзера определяем язык Telegram
    tg_lang = message.from_user.language_code or "ru"
    user_lang = tg_lang if tg_lang in I18nService.LANGUAGES else "ru"

    await state.set_state(RegistrationStates.waiting_for_first_name)
    reg_welcome = await I18nService.tr(
        "👋 <b>Добро пожаловать в систему!</b>\n\nДля начала работы необходимо зарегистрироваться.\nВведите ваше <b>Имя</b>:",
        user_lang
    )
    await message.answer(reg_welcome, parse_mode="HTML")


@router.message(Command("admin"))
async def cmd_admin_denied(message: types.Message, db_user: User) -> None:
    """Для пользователей без прав администратора: сообщение о запрете доступа."""
    lang = db_user.language_code
    msg = await I18nService.tr("⛔️ У вас нет доступа к админ-панели.", lang)
    await message.answer(msg)


@router.message(Command("profile"))
async def cmd_profile(message: types.Message, db_user: User) -> None:
    lang = db_user.language_code
    phone_display = db_user.phone or await I18nService.tr("не указан", lang)
    username_display = f"@{db_user.username}" if db_user.username else await I18nService.tr("нет", lang)

    title = await I18nService.tr("👤 <b>Ваш Профиль</b>", lang)
    lbl_id = await I18nService.tr("ID", lang)
    lbl_fn = await I18nService.tr("Имя", lang)
    lbl_ln = await I18nService.tr("Фамилия", lang)
    lbl_un = await I18nService.tr("Юзернейм", lang)
    lbl_addr = await I18nService.tr("Адрес", lang)
    lbl_phone = await I18nService.tr("Телефон", lang)
    lbl_role = await I18nService.tr("Роль", lang)
    lbl_lang = await I18nService.tr("Язык", lang)
    lbl_tz = await I18nService.tr("Часовой пояс", lang)

    geo_display = ""
    if db_user.latitude and db_user.longitude:
        lbl_maps = await I18nService.tr("Открыть в Картах", lang)
        geo_display = f"\n▫️ <b>GPS:</b> <a href='https://maps.google.com/?q={db_user.latitude},{db_user.longitude}'>📍 {lbl_maps}</a>"

    text = (
        f"{title}\n\n"
        f"▫️ <b>{lbl_id}:</b> <code>{db_user.telegram_id}</code>\n"
        f"▫️ <b>{lbl_fn}:</b> {html.escape(db_user.first_name)}\n"
        f"▫️ <b>{lbl_ln}:</b> {html.escape(db_user.last_name)}\n"
        f"▫️ <b>{lbl_un}:</b> {username_display}\n"
        f"▫️ <b>{lbl_addr}:</b> {html.escape(db_user.address)}{geo_display}\n"
        f"▫️ <b>{lbl_phone}:</b> {phone_display}\n"
        f"▫️ <b>{lbl_role}:</b> <code>{db_user.role.value}</code>\n"
        f"▫️ <b>{lbl_lang}:</b> <code>{db_user.language_code.upper()}</code>\n"
        f"▫️ <b>{lbl_tz}:</b> <code>{db_user.timezone}</code>"
    )

    kb = await get_profile_edit_kb(lang)
    await message.answer(text, reply_markup=kb, parse_mode="HTML")


@router.message(Command("help"))
async def cmd_help(message: types.Message, session: AsyncSession, db_user: User) -> None:
    lang = db_user.language_code

    # 1. Базовые команды для всех
    h_title = await I18nService.tr("📖 <b>Справочник доступных вам команд:</b>\n", lang)
    h_start = await I18nService.tr("▫️ /start — Перезапуск бота / Главное меню", lang)
    h_profile = await I18nService.tr("▫️ /profile — Просмотр и редактирование данных профиля", lang)
    h_help = await I18nService.tr("▫️ /help — Показать эту персональную справку", lang)

    help_lines = [h_title, h_start, h_profile, h_help]

    # Достаем все персональные права пользователя из БД
    stmt = (
        select(Permission.description, Permission.code)
        .join(UserPermission, UserPermission.permission_id == Permission.id)
        .where(UserPermission.user_id == db_user.telegram_id)
    )
    user_custom_perms = dict((await session.execute(stmt)).all())

    # 2. Персональные функции из ACL (если выданы обычному пользователю)
    if user_custom_perms and db_user.role == UserRole.USER:
        lbl_custom = await I18nService.tr("\n<b>⚡️ Ваши персональные функции (ACL):</b>", lang)
        help_lines.append(lbl_custom)
        for code, desc in user_custom_perms.items():
            t_desc = await I18nService.tr(desc, lang)
            help_lines.append(f"▫️ <code>{code}</code> — {t_desc}")

    # 3. Блок Администратора
    if db_user.role in [UserRole.ADMIN, UserRole.SUPER_ADMIN]:
        lbl_admin = await I18nService.tr("\n<b>🛡 Команды Администратора:</b>", lang)
        a_panel = await I18nService.tr("▫️ /admin — Панель управления и фоновые рассылки", lang)
        a_find = await I18nService.tr("▫️ /find_user [id/ник/имя] — Быстрый поиск пользователя", lang)
        a_last = await I18nService.tr("▫️ /last_users [число] — Показать последних зарегистрированных", lang)
        help_lines.extend([lbl_admin, a_panel, a_find, a_last])

    # 4. Блок Создателя (SUPER_ADMIN)
    if db_user.role == UserRole.SUPER_ADMIN:
        lbl_sa = await I18nService.tr("\n<b>👑 Функции Создателя (SuperAdmin):</b>", lang)
        sa_roles = await I18nService.tr("▫️ Назначение/Снятие админов (в карточке поиска пользователя)", lang)
        sa_acl = await I18nService.tr("▫️ Выдача/Отзыв индивидуальных прав доступа (ACL)", lang)
        sa_alerts = await I18nService.tr("▫️ Получение системных алертов о критических сбоях задач", lang)
        help_lines.extend([lbl_sa, sa_roles, sa_acl, sa_alerts])

    # 5. ДОПОЛНИТЕЛЬНЫЕ ДЕЙСТВИЯ: Показываем админам ИЛИ тем, у кого есть право 'TASK_SYSTEM_CALC'!
    has_calc_perm = "TASK_SYSTEM_CALC" in user_custom_perms
    if db_user.role in [UserRole.ADMIN, UserRole.SUPER_ADMIN] or has_calc_perm:
        lbl_extra = await I18nService.tr("\n<b>⚙️ Дополнительные действия:</b>", lang)
        extra_cmd = await I18nService.tr("▫️ /do_work — Отправить тестовую фоновую задачу в очередь", lang)
        help_lines.extend([lbl_extra, extra_cmd])

    await message.answer("\n".join(help_lines), parse_mode="HTML")


@router.callback_query(F.data == "change_lang")
async def cb_open_lang_menu(cb: types.CallbackQuery, db_user: User) -> None:
    txt = await I18nService.tr("Выберите язык интерфейса:", db_user.language_code)
    await cb.message.edit_text(txt, reply_markup=get_language_selection_kb())
    await cb.answer()


@router.callback_query(F.data.startswith("set_lang:"))
async def cb_apply_language(cb: types.CallbackQuery, session: AsyncSession, db_user: User) -> None:
    selected_lang = cb.data.split(":")[1]
    await UserService.update_profile(session, db_user.telegram_id, language_code=selected_lang)
    db_user.language_code = selected_lang

    alert_txt = await I18nService.tr("✅ Язык успешно изменен!", selected_lang)
    await cb.answer(alert_txt, show_alert=True)
    await cmd_profile(cb.message, db_user)


@router.callback_query(F.data == "change_tz")
async def cb_open_tz_menu(cb: types.CallbackQuery, db_user: User) -> None:
    txt = await I18nService.tr("Выберите ваш часовой пояс из списка:", db_user.language_code)
    await cb.message.edit_text(txt, reply_markup=get_timezone_selection_kb())
    await cb.answer()


@router.callback_query(F.data.startswith("set_tz:"))
async def cb_set_timezone(cb: types.CallbackQuery, session: AsyncSession, db_user: User) -> None:
    selected_tz = cb.data.split(":")[1]
    await UserService.update_profile(session, db_user.telegram_id, timezone=selected_tz)

    txt = await I18nService.tr(
        "✅ Часовой пояс изменен на: <code>{timezone}</code>",
        db_user.language_code,
        timezone=selected_tz
    )
    await cb.message.edit_text(txt, parse_mode="HTML")
    await cb.answer()


@router.callback_query(F.data == "back_to_profile")
async def cb_back_to_profile(cb: types.CallbackQuery, db_user: User) -> None:
    await cmd_profile(cb.message, db_user)
    await cb.answer()


@router.message(Command("about"))
async def cmd_about(message: types.Message, db_user: User) -> None:
    """
    Назначение: Отображение информации о платформе и кнопок связи.
    """
    lang = db_user.language_code
    title = await I18nService.tr("ℹ️ <b>О платформе CoreTgBot</b>", lang)
    desc = await I18nService.tr(
        "Масштабируемое многозадачное ядро с очередями задач, "
        "автоматическим распределением нагрузки и мультиязычностью.\n\n"
        "▫️ Версия ядра: <code>v2.1 Enterprise</code>\n"
        "▫️ Архитектура: <code>Asyncio / SQLAlchemy 2.0 / WAL</code>\n\n"
        "Выберите действие:",
        lang
    )

    # Захардкоженный контакт разработчика (SuperAdmin)
    dev_contact = "Dzmitry_T"  # Твой телеграм юзернейм
    kb = await get_about_kb(developer_username=dev_contact, lang=lang)

    await message.answer(f"{title}\n\n{desc}", reply_markup=kb, parse_mode="HTML")


# --- ОБРАЩЕНИЕ К АДМИНИСТРАЦИИ (/support) ---

@router.message(Command("support"))
@router.callback_query(F.data == "support_start")
async def cmd_support_start(event: types.Message | types.CallbackQuery, state: FSMContext, db_user: User) -> None:
    """
    Назначение: Старт диалога отправки сообщения администрации.
    """
    lang = db_user.language_code
    await state.set_state(SupportStates.waiting_for_message)

    prompt = await I18nService.tr(
        "✍️ <b>Напишите ваше сообщение для администрации:</b>\n"
        "Опишите вопрос, предложение или проблему, и вам ответят в ближайшее время.",
        lang
    )

    if isinstance(event, types.CallbackQuery):
        await event.message.answer(prompt, parse_mode="HTML")
        await event.answer()
    else:
        await event.answer(prompt, parse_mode="HTML")


@router.message(SupportStates.waiting_for_message)
async def process_support_message(message: types.Message, state: FSMContext, session: AsyncSession, bot: Bot,
                                  db_user: User) -> None:
    """
    Назначение: Прием любого медиа (текст, фото, видео, аудио, голосовые, кружочки, файлы)
    от пользователя и безопасная доставка ВСЕМ администраторам бота с кнопкой ответа.
    """
    lang = db_user.language_code
    await state.clear()

    # 1. Достаем всех администраторов и супер-админа
    stmt = select(User.telegram_id).where(
        User.role.in_([UserRole.ADMIN, UserRole.SUPER_ADMIN]),
        User.is_banned == False
    )
    admin_ids = list((await session.execute(stmt)).scalars().all())

    # 2. Формируем карточку тикета для админа
    sender_uname = f"@{message.from_user.username}" if message.from_user.username else f"#{message.from_user.id}"
    ticket_head = (
        f"📩 <b>Новое обращение от пользователя!</b>\n\n"
        f"▫️ <b>От:</b> {html.escape(db_user.first_name)} {html.escape(db_user.last_name)} ({sender_uname})\n"
        f"▫️ <b>ID:</b> <code>{message.from_user.id}</code>\n"
        f"▫️ <b>Язык:</b> <code>{db_user.language_code.upper()}</code>"
    )

    # Кнопка для админа: ответить в 1 клик
    kb_reply = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="✉️ Ответить пользователю",
                                    callback_data=f"admin_direct_msg:{message.from_user.id}")]
    ])

    # 3. Пересылаем медиа или текст каждому админу через MediaRelayService
    sent_count = 0
    for adm_id in admin_ids:
        success = await MediaRelayService.relay_message(
            bot=bot,
            message=message,
            target_chat_id=adm_id,
            header_text=ticket_head,
            reply_markup=kb_reply
        )
        if success:
            sent_count += 1

    # 4. Подтверждение пользователю
    confirm_msg = await I18nService.tr(
        "✅ <b>Ваше сообщение успешно передано администрации!</b>\n"
        "Мы свяжемся с вами в этом чате при необходимости.",
        lang
    )
    await message.answer(confirm_msg, parse_mode="HTML")


# --- ПЕРЕХВАТ НЕАВТОРИЗОВАННЫХ КЛИКОВ ПО АДМИНСКИМ КНОПКАМ ---
@router.callback_query(F.data.startswith((
    "admin_", "builder_", "target:", "delay:", "cron:", "sched:",
    "del_", "toggle_mail:", "edit_mail_text:", "mail_cat:", "user_mailings:",
    "view_mailing:", "manage_perms:", "toggle_perm:", "promote_admin:",
    "demote_admin:", "ban:", "unban:", "user_groups:", "toggle_group:",
    "create_group_", "view_group:", "set_group:"
)))
async def cb_admin_unauthorized_fallback(cb: types.CallbackQuery, db_user: User) -> None:
    """
    Перехват кликов по админским кнопкам от пользователей без прав администратора.
    Срабатывает только для не-админов, так как админ-роутеры отклонили запрос.
    """
    lang = db_user.language_code
    denied_msg = await I18nService.tr("⛔️ Недостаточно прав.", lang)
    await cb.answer(denied_msg, show_alert=True)
