from aiogram.types import (
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)
from services.i18n_service import I18nService
from core.config import settings


async def get_phone_request_kb(lang: str = "ru") -> ReplyKeyboardMarkup:
    """Клавиатура запроса телефона."""
    btn_phone = await I18nService.tr("📱 Поделиться контактом", lang)
    btn_skip = await I18nService.tr("Пропустить шаг", lang)
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=btn_phone, request_contact=True)],
            [KeyboardButton(text=btn_skip)]
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    )


async def get_address_request_kb(lang: str = "ru") -> ReplyKeyboardMarkup:
    """Клавиатура запроса адреса с геопозицией."""
    btn_geo = await I18nService.tr("📍 Поделиться геопозицией", lang)
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=btn_geo, request_location=True)]],
        resize_keyboard=True,
        one_time_keyboard=True
    )


async def get_profile_edit_kb(lang: str = "ru") -> InlineKeyboardMarkup:
    """Инлайн-кнопки профиля пользователя."""
    b_fn = await I18nService.tr("✏️ Изменить Имя", lang)
    b_ln = await I18nService.tr("✏️ Изменить Фамилию", lang)
    b_addr = await I18nService.tr("🏠 Изменить Адрес", lang)
    b_ph = await I18nService.tr("📱 Изменить Телефон", lang)
    b_lang = await I18nService.tr("🌐 Сменить язык", lang)
    b_tz = await I18nService.tr("🕒 Сменить часовой пояс", lang)

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=b_fn, callback_data="edit_first_name")],
            [InlineKeyboardButton(text=b_ln, callback_data="edit_last_name")],
            [InlineKeyboardButton(text=b_addr, callback_data="edit_address")],
            [InlineKeyboardButton(text=b_ph, callback_data="edit_phone")],
            [InlineKeyboardButton(text=b_lang, callback_data="change_lang")],
            [InlineKeyboardButton(text=b_tz, callback_data="change_tz")]
        ]
    )


async def get_admin_main_kb(is_super_admin: bool = False, lang: str = "ru") -> InlineKeyboardMarkup:
    """Главное меню админ-панели."""
    b_find = await I18nService.tr("🔍 Найти пользователя", lang)
    b_excel = await I18nService.tr("📥 Выгрузить всех в Excel", lang)
    b_last = await I18nService.tr("👥 Последние зарегистрированные", lang)
    b_mail = await I18nService.tr("📬 Конструктор умных рассылок", lang)
    b_group = await I18nService.tr("🏷 Управление группами", lang)
    b_stats = await I18nService.tr("📊 Статистика очереди", lang)


    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=b_find, callback_data="admin_find_user")],
            [InlineKeyboardButton(text=b_excel, callback_data="admin_export_users_excel")],
            [InlineKeyboardButton(text=b_last, callback_data="admin_last_users")],
            [InlineKeyboardButton(text=b_mail, callback_data="admin_mailings_menu")],
            [InlineKeyboardButton(text=b_group, callback_data="admin_groups_menu")],
            [InlineKeyboardButton(text=b_stats, callback_data="admin_queue_stats")]
        ]
    )


async def get_admin_user_manage_kb(
        target_id: int,
        is_admin: bool,
        is_banned: bool,
        lang: str = "ru"
) -> InlineKeyboardMarkup:
    """Панель управления найденным пользователем."""
    buttons = []

    # Смена роли (только для обычных админов/пользователей, создателя нельзя снять)
    if target_id != settings.ADMIN_ID:
        role_raw = "🔻 Снять админа" if is_admin else "👑 Сделать админом"
        role_text = await I18nService.tr(role_raw, lang)
        role_action = "demote_admin" if is_admin else "promote_admin"
        buttons.append([InlineKeyboardButton(text=role_text, callback_data=f"{role_action}:{target_id}")])

    btn_msg = await I18nService.tr("✉️ Написать сейчас", lang)
    btn_mailings = await I18nService.tr("📬 Рассылки пользователя", lang)
    btn_groups = await I18nService.tr("👥 Управление группами", lang)

    buttons.append([InlineKeyboardButton(text=btn_msg, callback_data=f"admin_direct_msg:{target_id}")])
    buttons.append([InlineKeyboardButton(text=btn_mailings, callback_data=f"user_mailings:{target_id}")])
    buttons.append([InlineKeyboardButton(text=btn_groups, callback_data=f"user_groups:{target_id}")])

    if target_id != settings.ADMIN_ID:
        ban_raw = "🟢 Разблокировать" if is_banned else "🔴 Заблокировать"
        ban_text = await I18nService.tr(ban_raw, lang)
        ban_action = "unban" if is_banned else "ban"
        buttons.append([InlineKeyboardButton(text=ban_text, callback_data=f"{ban_action}:{target_id}")])

    btn_acl = await I18nService.tr("⚙️ Настроить права (ACL)", lang)
    buttons.append([InlineKeyboardButton(text=btn_acl, callback_data=f"manage_perms:{target_id}")])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def get_user_permissions_kb(
        target_id: int,
        all_permissions: list,
        user_perm_ids: set[int],
        lang: str = "ru"
) -> InlineKeyboardMarkup:
    """Интерактивный список прав ACL."""
    buttons = []
    for perm in all_permissions:
        if perm.is_system:
            continue

        has_perm = perm.id in user_perm_ids
        icon = "✅" if has_perm else "❌"
        action = "revoke" if has_perm else "grant"

        # Переводим описание права на язык админа
        translated_desc = await I18nService.tr(perm.description, lang)
        btn_text = f"{icon} {translated_desc}"
        callback = f"toggle_perm:{target_id}:{perm.code}:{action}"
        buttons.append([InlineKeyboardButton(text=btn_text, callback_data=callback)])

    back_text = await I18nService.tr("⬅️ Назад к пользователю", lang)
    buttons.append([InlineKeyboardButton(text=back_text, callback_data=f"back_to_user:{target_id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_language_selection_kb() -> InlineKeyboardMarkup:
    """Выбор языка интерфейса (названия на родных языках)."""
    buttons = []
    row = []
    for code, name in I18nService.LANGUAGES.items():
        row.append(InlineKeyboardButton(text=name, callback_data=f"set_lang:{code}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text="⬅️ Back / Назад", callback_data="back_to_profile")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_timezone_selection_kb() -> InlineKeyboardMarkup:
    """Сетка мировых часовых поясов."""
    timezones = [
        ("UTC-8 (Los Angeles)", "America/Los_Angeles"),
        ("UTC-5 (New York)", "America/New_York"),
        ("UTC-3 (Buenos Aires)", "America/Argentina/Buenos_Aires"),
        ("UTC+0 (London)", "Europe/London"),
        ("UTC+1 (Berlin, Rome, Paris)", "Europe/Berlin"),
        ("UTC+2 (Kyiv, Vilnius)", "Europe/Kyiv"),
        ("UTC+3 (Minsk, Moscow)", "Europe/Minsk"),
        ("UTC+4 (Baku, Dubai)", "Asia/Dubai"),
        ("UTC+5 (Astana, Tashkent)", "Asia/Tashkent"),
        ("UTC+6 (Almaty, Omsk)", "Asia/Almaty"),
        ("UTC+7 (Bangkok)", "Asia/Bangkok"),
        ("UTC+8 (Shanghai, Beijing)", "Asia/Shanghai"),
        ("UTC+9 (Tokyo, Seoul)", "Asia/Tokyo"),
        ("UTC+10 (Sydney)", "Australia/Sydney")
    ]
    buttons = [[InlineKeyboardButton(text=title, callback_data=f"set_tz:{tz_code}")] for title, tz_code in timezones]
    buttons.append([InlineKeyboardButton(text="⬅️ Back / Назад", callback_data="back_to_profile")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def get_mailing_target_kb(lang: str = "ru") -> InlineKeyboardMarkup:
    """
    Назначение: Выбор целевой аудитории рассылки с переводом.
    """
    b_all = await I18nService.tr("📢 Всем пользователям", lang)
    b_user = await I18nService.tr("👤 Конкретному пользователю", lang)
    b_group = await I18nService.tr("👥 Определенной группе", lang)
    b_self = await I18nService.tr("🎯 Отправить только себе", lang)
    b_cancel = await I18nService.tr("❌ Отмена", lang)

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=b_all, callback_data="target:ALL")],
            [InlineKeyboardButton(text=b_user, callback_data="target:USER")],
            [InlineKeyboardButton(text=b_group, callback_data="target:GROUP")],
            [InlineKeyboardButton(text=b_self, callback_data="target:SELF")],
            [InlineKeyboardButton(text=b_cancel, callback_data="cancel_action")]
        ]
    )


async def get_schedule_type_kb(lang: str = "ru") -> InlineKeyboardMarkup:
    """
    Назначение: Выбор типа расписания отправки с переводом.
    """
    b_delay = await I18nService.tr("⏱ Через промежуток времени", lang)
    b_exact = await I18nService.tr("📅 В точную дату и время", lang)
    b_cron = await I18nService.tr("🔄 Повторять циклично (Cron)", lang)
    b_cancel = await I18nService.tr("❌ Отмена", lang)

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=b_delay, callback_data="sched:DELAY")],
            [InlineKeyboardButton(text=b_exact, callback_data="sched:EXACT")],
            [InlineKeyboardButton(text=b_cron, callback_data="sched:RECURRENT")],
            [InlineKeyboardButton(text=b_cancel, callback_data="cancel_action")]
        ]
    )


async def get_quick_delays_kb(lang: str = "ru") -> InlineKeyboardMarkup:
    """
    Назначение: Быстрый выбор популярных задержек отправки.
    """
    m_5 = await I18nService.tr("+5 мин", lang)
    m_15 = await I18nService.tr("+15 мин", lang)
    m_30 = await I18nService.tr("+30 мин", lang)
    h_1 = await I18nService.tr("+1 час", lang)
    h_3 = await I18nService.tr("+3 часа", lang)
    d_1 = await I18nService.tr("+1 день", lang)
    b_custom = await I18nService.tr("✍️ Ввести число минут вручную", lang)

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=m_5, callback_data="delay:5"),
                InlineKeyboardButton(text=m_15, callback_data="delay:15"),
                InlineKeyboardButton(text=m_30, callback_data="delay:30")
            ],
            [
                InlineKeyboardButton(text=h_1, callback_data="delay:60"),
                InlineKeyboardButton(text=h_3, callback_data="delay:180"),
                InlineKeyboardButton(text=d_1, callback_data="delay:1440")
            ],
            [InlineKeyboardButton(text=b_custom, callback_data="delay:custom")]
        ]
    )


async def get_quick_cron_kb(lang: str = "ru") -> InlineKeyboardMarkup:
    """
    Назначение: Быстрый выбор популярных циклических расписаний с переводом.
    """
    c_daily = await I18nService.tr("Каждый день в 10:00", lang)
    c_monday = await I18nService.tr("Каждый понедельник в 09:00", lang)
    c_monthly = await I18nService.tr("1-го числа каждого месяца в 12:00", lang)
    c_may = await I18nService.tr("Каждый год 2 мая в 10:00", lang)
    c_custom = await I18nService.tr("✍️ Ввести Cron-выражение вручную", lang)

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=c_daily, callback_data="cron:0 10 * * *")],
            [InlineKeyboardButton(text=c_monday, callback_data="cron:0 9 * * 1")],
            [InlineKeyboardButton(text=c_monthly, callback_data="cron:0 12 1 * *")],
            [InlineKeyboardButton(text=c_may, callback_data="cron:0 10 2 5 *")],
            [InlineKeyboardButton(text=c_custom, callback_data="cron:custom")]
        ]
    )


async def get_mailing_manage_kb(mailing_id: int, is_active: bool, lang: str = "ru") -> InlineKeyboardMarkup:
    """
    Назначение: Управление рассылкой (пауза, редактирование, удаление).
    """
    b_edit = await I18nService.tr("✏️ Изменить текст", lang)
    status_raw = "⏸ Приостановить" if is_active else "▶️ Возобновить"
    status_btn = await I18nService.tr(status_raw, lang)
    action = "pause" if is_active else "resume"
    b_del = await I18nService.tr("🗑 Удалить рассылку", lang)
    b_back = await I18nService.tr("⬅️ Назад к рассылкам", lang)

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=b_edit, callback_data=f"edit_mail_text:{mailing_id}")],
            [InlineKeyboardButton(text=status_btn, callback_data=f"toggle_mail:{mailing_id}:{action}")],
            [InlineKeyboardButton(text=b_del, callback_data=f"del_mail:{mailing_id}")],
            [InlineKeyboardButton(text=b_back, callback_data="admin_mailings_list")]
        ]
    )

async def get_mailings_categories_kb(lang: str = "ru") -> InlineKeyboardMarkup:
    """Клавиатура разделения рассылок по категориям."""
    b_all = await I18nService.tr("📢 Рассылки для ВСЕХ", lang)
    b_groups = await I18nService.tr("👥 Рассылки для ГРУПП", lang)
    b_users = await I18nService.tr("👤 Персональные рассылки", lang)
    b_del_center = await I18nService.tr("🗑 ЦЕНТР УДАЛЕНИЯ РАССЫЛОК", lang)
    b_back = await I18nService.tr("⬅️ Назад в меню", lang)

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=b_all, callback_data="mail_cat:ALL")],
            [InlineKeyboardButton(text=b_groups, callback_data="mail_cat:GROUP")],
            [InlineKeyboardButton(text=b_users, callback_data="mail_cat:USER")],
            [InlineKeyboardButton(text=b_del_center, callback_data="mail_delete_hub")],
            [InlineKeyboardButton(text=b_back, callback_data="admin_mailings_menu")]
        ]
    )

async def get_mailings_delete_hub_kb(lang: str = "ru") -> InlineKeyboardMarkup:
    """Клавиатура безопасного удаления рассылок по типам."""
    d_all = await I18nService.tr("🗑 Удалить рассылки для ВСЕХ", lang)
    d_groups = await I18nService.tr("👥 Удалить рассылки ГРУПП...", lang)
    d_users = await I18nService.tr("👤 Удалить ВСЕ персональные", lang)
    d_nuke = await I18nService.tr("💣 УДАЛИТЬ АБСОЛЮТНО ВСЕ РАССЫЛКИ", lang)
    b_back = await I18nService.tr("⬅️ Назад", lang)

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=d_all, callback_data="del_batch:ALL")],
            [InlineKeyboardButton(text=d_groups, callback_data="del_batch_groups_menu")],
            [InlineKeyboardButton(text=d_users, callback_data="del_batch:USER")],
            [InlineKeyboardButton(text=d_nuke, callback_data="del_nuke_prompt")],
            [InlineKeyboardButton(text=b_back, callback_data="admin_mailings_list")]
        ]
    )

async def get_about_kb(developer_username: str, lang: str = "ru") -> InlineKeyboardMarkup:
    """
    Назначение: Клавиатура раздела /about с кнопками связи.
    """
    from services.i18n_service import I18nService
    b_admin = await I18nService.tr("✉️ Написать администрации", lang)
    b_dev = await I18nService.tr("👨‍💻 Связаться с разработчиком", lang)

    # Кнопка связи с разработчиком открывает tg://user?id или URL профиля
    dev_url = f"https://t.me/{developer_username.replace('@', '')}"

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=b_admin, callback_data="support_start")],
            [InlineKeyboardButton(text=b_dev, url=dev_url)]
        ]
    )