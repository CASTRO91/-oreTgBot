import html
from datetime import datetime, timedelta
from aiogram import Router, types, F
from aiogram.fsm.context import FSMContext
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.user import User, UserRole
from database.models.mailing import ScheduledMailing, ScheduleType, TargetType, MediaType
from database.models.base import utc_now
from database.models.group import Group
from services.scheduler_service import SchedulerService
from services.group_service import GroupService
from services.i18n_service import I18nService
from utils.states import MailingBuilderStates, MailingEditStates
from middlewares.acl import AdminRoleFilter
from utils.keyboards import (
    get_mailing_target_kb,
    get_schedule_type_kb,
    get_quick_delays_kb,
    get_quick_cron_kb,
    get_mailing_manage_kb,
    get_mailings_categories_kb,
    get_mailings_delete_hub_kb
)

router = Router(name="mailing_router")
router.message.filter(AdminRoleFilter())
router.callback_query.filter(AdminRoleFilter())


# --- ГЛАВНОЕ МЕНЮ РАССЫЛОК ---

@router.callback_query(F.data == "admin_mailings_menu")
async def cb_mailings_menu(cb: types.CallbackQuery, db_user: User) -> None:
    lang = db_user.language_code
    if db_user.role not in [UserRole.ADMIN, UserRole.SUPER_ADMIN]:
        await cb.answer(await I18nService.tr("⛔️ Недостаточно прав.", lang), show_alert=True)
        return

    btn_create = await I18nService.tr("➕ Создать новую рассылку", lang)
    btn_list = await I18nService.tr("📋 Список активных рассылок", lang)
    btn_back = await I18nService.tr("⬅️ Назад в админку", lang)

    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text=btn_create, callback_data="builder_start")],
        [types.InlineKeyboardButton(text=btn_list, callback_data="admin_mailings_list")],
        [types.InlineKeyboardButton(text=btn_back, callback_data="admin_back_main")]
    ])

    title = await I18nService.tr("📬 <b>Управление отложенными и цикличными рассылками</b>", lang)
    await cb.message.edit_text(title, reply_markup=kb, parse_mode="HTML")
    await cb.answer()


# --- СТАРТ КОНСТРУКТОРА РАССЫЛОК ---

@router.callback_query(F.data == "builder_start")
async def cb_builder_start(cb: types.CallbackQuery, state: FSMContext, db_user: User) -> None:
    lang = db_user.language_code
    await state.set_state(MailingBuilderStates.waiting_for_target)

    title = await I18nService.tr("🎯 <b>Шаг 1: Выберите получателей рассылки:</b>", lang)
    # СТАВИМ AWAIT И ПЕРЕДАЕМ lang:
    kb = await get_mailing_target_kb(lang)

    await cb.message.edit_text(title, reply_markup=kb, parse_mode="HTML")
    await cb.answer()


@router.callback_query(MailingBuilderStates.waiting_for_target, F.data.startswith("target:"))
async def cb_builder_target_chosen(cb: types.CallbackQuery, state: FSMContext, session: AsyncSession,
                                   db_user: User) -> None:
    lang = db_user.language_code
    target = cb.data.split(":")[1]

    if target == "SELF":
        await state.update_data(target_type=TargetType.USER, target_id=cb.from_user.id)
    elif target == "ALL":
        await state.update_data(target_type=TargetType.ALL, target_id=None)
    elif target == "USER":
        await state.set_state(MailingBuilderStates.waiting_for_user_id)
        msg = await I18nService.tr("Введите <b>Telegram ID</b> пользователя для рассылки:", lang)
        await cb.message.edit_text(msg, parse_mode="HTML")
        await cb.answer()
        return
    elif target == "GROUP":
        groups = await GroupService.get_all_groups(session)
        if not groups:
            warn = await I18nService.tr("Сначала создайте хотя бы одну группу в разделе 'Управление группами'!", lang)
            await cb.answer(warn, show_alert=True)
            return

        buttons = [[types.InlineKeyboardButton(text=f"👥 {g.name}", callback_data=f"set_group:{g.id}")] for g in groups]
        cancel_txt = await I18nService.tr("❌ Отмена", lang)
        buttons.append([types.InlineKeyboardButton(text=cancel_txt, callback_data="cancel_action")])

        await state.set_state(MailingBuilderStates.waiting_for_group_id)
        msg_choose = await I18nService.tr("Выберите группу получателей:", lang)
        await cb.message.edit_text(msg_choose, reply_markup=types.InlineKeyboardMarkup(inline_keyboard=buttons))
        await cb.answer()
        return

    # Переход к вводу контента
    await state.set_state(MailingBuilderStates.waiting_for_content)
    text_prompt = await I18nService.tr(
        "✍️ <b>Шаг 2: Отправьте сообщение для рассылки.</b>\n\n"
        "Вы можете отправить <b>текст</b>, либо <b>фото/видео/документ с подписью</b>.\n"
        "Поддерживаются шаблоны подстановки:\n"
        "▫️ <code>{first_name}</code> — Имя получателя\n"
        "▫️ <code>{last_name}</code> — Фамилия\n"
        "▫️ <code>{username}</code> — Юзернейм\n"
        "▫️ <code>{address}</code> — Адрес",
        lang
    )
    await cb.message.edit_text(text_prompt, parse_mode="HTML")
    await cb.answer()


@router.message(MailingBuilderStates.waiting_for_user_id)
async def process_target_user_id(message: types.Message, state: FSMContext, db_user: User) -> None:
    lang = db_user.language_code
    if not message.text or not message.text.isdigit():
        await message.answer(await I18nService.tr("⚠️ Введите корректный числовой Telegram ID:", lang))
        return

    await state.update_data(target_type=TargetType.USER, target_id=int(message.text))
    await state.set_state(MailingBuilderStates.waiting_for_content)

    text_prompt = await I18nService.tr(
        "✍️ <b>Шаг 2: Отправьте сообщение для рассылки</b> (текст или медиафайл с подписью).\n"
        "Доступны переменные: <code>{first_name}</code>, <code>{username}</code>, <code>{address}</code>",
        lang
    )
    await message.answer(text_prompt, parse_mode="HTML")


@router.callback_query(MailingBuilderStates.waiting_for_group_id, F.data.startswith("set_group:"))
async def process_target_group_id(cb: types.CallbackQuery, state: FSMContext, db_user: User) -> None:
    lang = db_user.language_code
    group_id = int(cb.data.split(":")[1])
    await state.update_data(target_type=TargetType.GROUP, target_id=group_id)
    await state.set_state(MailingBuilderStates.waiting_for_content)

    msg = await I18nService.tr("✍️ <b>Шаг 2: Отправьте контент рассылки</b> (текст или медиафайл с подписью):", lang)
    await cb.message.edit_text(msg, parse_mode="HTML")
    await cb.answer()


# --- ПРИЕМ КОНТЕНТА (ТЕКСТ ИЛИ МЕДИА) ---

@router.message(MailingBuilderStates.waiting_for_content, F.text | F.photo | F.video | F.document)
async def process_mailing_content(message: types.Message, state: FSMContext, db_user: User) -> None:
    lang = db_user.language_code
    media_type = MediaType.NONE
    file_id = None
    content_text = ""

    if message.photo:
        media_type = MediaType.PHOTO
        file_id = message.photo[-1].file_id
        content_text = message.caption or ""
    elif message.video:
        media_type = MediaType.VIDEO
        file_id = message.video.file_id
        content_text = message.caption or ""
    elif message.document:
        media_type = MediaType.DOCUMENT
        file_id = message.document.file_id
        content_text = message.caption or ""
    else:
        content_text = message.text or ""

    if not content_text and media_type != MediaType.NONE:
        content_text = "<i>(Media)</i>"

    await state.update_data(
        content_text=content_text,
        media_type=media_type,
        media_file_id=file_id,
        title=content_text[:30] if content_text else "Рассылка"
    )

    await state.set_state(MailingBuilderStates.waiting_for_schedule_type)

    prompt = await I18nService.tr("⏰ <b>Шаг 3: Выберите тип расписания отправки:</b>", lang)
    kb = await get_schedule_type_kb(lang)
    await message.answer(prompt, reply_markup=kb, parse_mode="HTML")


# --- ВЫБОР РАСПИСАНИЯ ---

@router.callback_query(MailingBuilderStates.waiting_for_schedule_type, F.data.startswith("sched:"))
async def cb_schedule_type(cb: types.CallbackQuery, state: FSMContext, db_user: User) -> None:
    lang = db_user.language_code
    sched_type = cb.data.split(":")[1]

    if sched_type == "DELAY":
        txt = await I18nService.tr("⏱ Выберите время задержки отправки:", lang)
        kb = await get_quick_delays_kb(lang)
        await cb.message.edit_text(txt, reply_markup=kb, parse_mode="HTML")
        await cb.answer()
    elif sched_type == "RECURRENT":
        txt = await I18nService.tr("🔄 Выберите периодичность повторения:", lang)
        kb = await get_quick_cron_kb(lang)
        await cb.message.edit_text(txt, reply_markup=kb, parse_mode="HTML")
        await cb.answer()
    elif sched_type == "EXACT":
        await state.set_state(MailingBuilderStates.waiting_for_exact_datetime)
        txt = await I18nService.tr(
            "📅 Введите точную дату и время запуска в формате:\n"
            "<code>YYYY-MM-DD HH:MM</code> (например: <code>2026-10-25 14:30</code>)\n"
            "<i>(Время указывается по серверному времени UTC)</i>",
            lang
        )
        await cb.message.edit_text(txt, parse_mode="HTML")
        await cb.answer()


# Финализация: DELAY
@router.callback_query(F.data.startswith("delay:"))
async def process_delay_choice(cb: types.CallbackQuery, state: FSMContext, session: AsyncSession,
                               db_user: User) -> None:
    lang = db_user.language_code
    val = cb.data.split(":")[1]
    if val == "custom":
        await state.set_state(MailingBuilderStates.waiting_for_delay)
        txt = await I18nService.tr("Введите задержку в <b>минутах</b> (целое число):", lang)
        await cb.message.edit_text(txt, parse_mode="HTML")
        await cb.answer()
        return

    minutes = int(val)
    run_at = utc_now() + timedelta(minutes=minutes)
    await finalize_mailing_creation(cb.message, state, session, ScheduleType.ONCE, run_at=run_at, lang=lang)
    await cb.answer()


@router.message(MailingBuilderStates.waiting_for_delay)
async def process_custom_delay(message: types.Message, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    lang = db_user.language_code
    if not message.text or not message.text.isdigit():
        await message.answer(await I18nService.tr("⚠️ Введите число минут цифрами:", lang))
        return
    run_at = utc_now() + timedelta(minutes=int(message.text))
    await finalize_mailing_creation(message, state, session, ScheduleType.ONCE, run_at=run_at, lang=lang)


# Финализация: EXACT
@router.message(MailingBuilderStates.waiting_for_exact_datetime)
async def process_exact_datetime(message: types.Message, state: FSMContext, session: AsyncSession,
                                 db_user: User) -> None:
    lang = db_user.language_code
    try:
        # Парсим время, которое админ ввел по СВОЕМУ часовому поясу (например, Минск)
        local_dt = datetime.strptime(message.text.strip(), "%Y-%m-%d %H:%M")

        # Привязываем к часовому поясу админа
        admin_tz = pytz.timezone(db_user.timezone)
        localized_dt = admin_tz.localize(local_dt)

        # Переводим в эталонный UTC для базы данных
        utc_dt = localized_dt.astimezone(pytz.UTC).replace(tzinfo=None)

        if utc_dt <= utc_now():
            await message.answer(await I18nService.tr("⚠️ Указанное время уже прошло! Введите будущую дату:", lang))
            return

        await finalize_mailing_creation(message, state, session, ScheduleType.ONCE, run_at=utc_dt, lang=lang)
    except ValueError:
        await message.answer(
            await I18nService.tr("⚠️ Неверный формат даты! Используйте: <code>YYYY-MM-DD HH:MM</code>", lang),
            parse_mode="HTML")


# Финализация: RECURRENT / CRON
@router.callback_query(F.data.startswith("cron:"))
async def process_cron_choice(cb: types.CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    lang = db_user.language_code
    rule = cb.data.split(":", 1)[1]
    if rule == "custom":
        await state.set_state(MailingBuilderStates.waiting_for_cron)
        txt = await I18nService.tr(
            "Введите Cron-маску вручную из 5 частей:\n"
            "<code>минута час день месяц день_недели</code>\n"
            "Пример: <code>0 10 * * 1</code> (каждый понедельник в 10:00)",
            lang
        )
        await cb.message.edit_text(txt, parse_mode="HTML")
        await cb.answer()
        return

    next_run = SchedulerService.calculate_next_cron_run(rule)
    await finalize_mailing_creation(cb.message, state, session, ScheduleType.RECURRENT, run_at=next_run, cron_rule=rule,
                                    lang=lang)
    await cb.answer()


@router.message(MailingBuilderStates.waiting_for_cron)
async def process_custom_cron(message: types.Message, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    lang = db_user.language_code
    rule = message.text.strip()
    try:
        next_run = SchedulerService.calculate_next_cron_run(rule)
        await finalize_mailing_creation(message, state, session, ScheduleType.RECURRENT, run_at=next_run,
                                        cron_rule=rule, lang=lang)
    except Exception as e:
        await message.answer(f"⚠️ Ошибка в Cron-выражении: {e}. Попробуйте еще раз:")


async def finalize_mailing_creation(
        event_obj: types.Message,
        state: FSMContext,
        session: AsyncSession,
        schedule_type: ScheduleType,
        run_at: datetime,
        cron_rule: str | None = None,
        lang: str = "ru"
) -> None:
    """
    Назначение: Финальное сохранение рассылки в БД и отправка отчета на языке админа.
    """
    data = await state.get_data()
    mailing = ScheduledMailing(
        title=data.get("title", "Рассылка"),
        text=data["content_text"],
        media_type=data.get("media_type", MediaType.NONE),
        media_file_id=data.get("media_file_id"),
        target_type=data["target_type"],
        target_id=data.get("target_id"),
        schedule_type=schedule_type,
        cron_rule=cron_rule,
        next_run_at=run_at,
        created_by=event_obj.chat.id
    )
    session.add(mailing)
    await session.commit()
    await state.clear()

    title_ok = await I18nService.tr("✅ <b>Рассылка успешно запланирована!</b>", lang)
    lbl_id = await I18nService.tr("ID рассылки", lang)
    lbl_type = await I18nService.tr("Тип", lang)
    lbl_run = await I18nService.tr("Ближайший запуск", lang)
    lbl_aud = await I18nService.tr("Аудитория", lang)

    text_resp = (
        f"{title_ok}\n\n"
        f"▫️ <b>{lbl_id}:</b> #{mailing.id}\n"
        f"▫️ <b>{lbl_type}:</b> <code>{schedule_type.value}</code>\n"
        f"▫️ <b>{lbl_run}:</b> <code>{run_at.strftime('%Y-%m-%d %H:%M:%S UTC')}</code>\n"
        f"▫️ <b>{lbl_aud}:</b> <code>{data['target_type'].value}</code>"
    )
    if isinstance(event_obj, types.Message):
        await event_obj.answer(text_resp, parse_mode="HTML")


# --- ПРОСМОТР РАССЫЛОК ПОЛЬЗОВАТЕЛЯ ИЗ ЕГО КАРТОЧКИ ---

@router.callback_query(F.data.startswith("user_mailings:"))
async def cb_user_mailings_list(cb: types.CallbackQuery, session: AsyncSession, db_user: User) -> None:
    lang = db_user.language_code
    user_id = int(cb.data.split(":")[1])
    stmt = select(ScheduledMailing).where(
        ScheduledMailing.target_type == TargetType.USER,
        ScheduledMailing.target_id == user_id
    )
    mailings = list((await session.execute(stmt)).scalars().all())

    if not mailings:
        msg_none = await I18nService.tr("У этого пользователя нет персональных запланированных рассылок.", lang)
        await cb.answer(msg_none, show_alert=True)
        return

    buttons = []
    for m in mailings:
        status_icon = "🟢" if m.is_active else "⏸"
        buttons.append([types.InlineKeyboardButton(
            text=f"{status_icon} #{m.id} | {m.title[:20]}",
            callback_data=f"view_mailing:{m.id}"
        )])
    btn_del_all = await I18nService.tr("🗑 Удалить все рассылки юзера", lang)
    buttons.append([types.InlineKeyboardButton(text=btn_del_all, callback_data=f"del_all_user_mailings:{user_id}")])
    back_txt = await I18nService.tr("⬅️ Назад к пользователю", lang)
    buttons.append([types.InlineKeyboardButton(text=back_txt, callback_data=f"back_to_user:{user_id}")])

    head = await I18nService.tr("📬 <b>Персональные рассылки для #{user_id}:</b>", lang, user_id=user_id)
    await cb.message.edit_text(head, reply_markup=types.InlineKeyboardMarkup(inline_keyboard=buttons),
                               parse_mode="HTML")
    await cb.answer()


# --- КАРТОЧКА РАССЫЛКИ, РЕДАКТИРОВАНИЕ И УДАЛЕНИЕ ---

@router.callback_query(F.data.startswith("view_mailing:"))
async def cb_view_single_mailing(cb: types.CallbackQuery, session: AsyncSession, db_user: User) -> None:
    lang = db_user.language_code
    mailing_id = int(cb.data.split(":")[1])
    m = await session.get(ScheduledMailing, mailing_id)
    if not m:
        await cb.answer("Рассылка не найдена.", show_alert=True)
        return

    status = await I18nService.tr("🟢 Активна", lang) if m.is_active else await I18nService.tr("⏸ На паузе", lang)
    sched_info = f"Cron: <code>{m.cron_rule}</code>" if m.schedule_type == ScheduleType.RECURRENT else await I18nService.tr(
        "Разовая", lang)

    head = await I18nService.tr("📬 <b>Рассылка #{id}</b>", lang, id=m.id)
    lbl_st = await I18nService.tr("Статус", lang)
    lbl_tp = await I18nService.tr("Тип", lang)
    lbl_med = await I18nService.tr("Медиа", lang)
    lbl_nxt = await I18nService.tr("Следующий запуск", lang)
    lbl_tx = await I18nService.tr("Текст", lang)

    info = (
        f"{head}\n\n"
        f"▫️ <b>{lbl_st}:</b> {status}\n"
        f"▫️ <b>{lbl_tp}:</b> {sched_info}\n"
        f"▫️ <b>{lbl_med}:</b> <code>{m.media_type.value}</code>\n"
        f"▫️ <b>{lbl_nxt}:</b> <code>{m.next_run_at.strftime('%Y-%m-%d %H:%M:%S UTC')}</code>\n\n"
        f"📝 <b>{lbl_tx}:</b>\n{html.escape(m.text)}"
    )
    kb = await get_mailing_manage_kb(m.id, m.is_active, lang=lang)
    await cb.message.edit_text(info, reply_markup=kb, parse_mode="HTML")
    await cb.answer()


@router.callback_query(F.data.startswith("toggle_mail:"))
async def cb_toggle_mailing_status(cb: types.CallbackQuery, session: AsyncSession, db_user: User) -> None:
    lang = db_user.language_code
    _, m_id, action = cb.data.split(":")
    mailing = await session.get(ScheduledMailing, int(m_id))
    if mailing:
        mailing.is_active = (action == "resume")
        await session.commit()
        await cb.answer(await I18nService.tr("Статус рассылки изменен!", lang))
        await cb_view_single_mailing(cb, session, db_user)


@router.callback_query(F.data.startswith("del_mail:"))
async def cb_delete_mailing(cb: types.CallbackQuery, session: AsyncSession, db_user: User) -> None:
    lang = db_user.language_code
    m_id = int(cb.data.split(":")[1])
    await session.execute(delete(ScheduledMailing).where(ScheduledMailing.id == m_id))
    await session.commit()
    await cb.answer(await I18nService.tr("🗑 Рассылка удалена!", lang), show_alert=True)
    await cb.message.edit_text(await I18nService.tr("✅ Рассылка удалена из базы данных.", lang))


@router.callback_query(F.data.startswith("edit_mail_text:"))
async def cb_start_edit_mailing_text(cb: types.CallbackQuery, state: FSMContext, db_user: User) -> None:
    lang = db_user.language_code
    m_id = int(cb.data.split(":")[1])
    await state.set_state(MailingEditStates.waiting_for_new_text)
    await state.update_data(editing_mailing_id=m_id)
    prompt = await I18nService.tr("Введите <b>новый текст</b> для этой рассылки (поддерживается HTML):", lang)
    await cb.message.answer(prompt, parse_mode="HTML")
    await cb.answer()


@router.message(MailingEditStates.waiting_for_new_text)
async def process_save_new_mailing_text(message: types.Message, state: FSMContext, session: AsyncSession,
                                        db_user: User) -> None:
    lang = db_user.language_code
    data = await state.get_data()
    m_id = data["editing_mailing_id"]
    mailing = await session.get(ScheduledMailing, m_id)
    if mailing and message.text:
        mailing.text = message.text
        await session.commit()
        await state.clear()
        ok_msg = await I18nService.tr("✅ Текст рассылки #{id} успешно обновлен!", lang, id=m_id)
        await message.answer(ok_msg)


# --- 1. СПИСОК РАССЫЛОК: РАЗБИВКА ПО КАТЕГОРИЯМ ---

@router.callback_query(F.data == "admin_mailings_list")
async def cb_mailings_list_categories(cb: types.CallbackQuery, db_user: User) -> None:
    lang = db_user.language_code
    title = await I18nService.tr("📋 <b>Выберите категорию рассылок для просмотра:</b>", lang)
    kb = await get_mailings_categories_kb(lang)
    await cb.message.edit_text(title, reply_markup=kb, parse_mode="HTML")
    await cb.answer()


@router.callback_query(F.data.startswith("mail_cat:"))
async def cb_show_mailings_by_category(cb: types.CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """
    Назначение: Показ списка рассылок выбранной категории (ALL, GROUP, USER).
    """
    lang = db_user.language_code
    cat = cb.data.split(":")[1]
    target_type = TargetType(cat)

    stmt = select(ScheduledMailing).where(ScheduledMailing.target_type == target_type)
    mailings = list((await session.execute(stmt)).scalars().all())

    if not mailings:
        msg = await I18nService.tr("В этой категории пока нет запланированных рассылок.", lang)
        await cb.answer(msg, show_alert=True)
        return

    buttons = []
    for m in mailings:
        icon = "🟢" if m.is_active else "⏸"
        buttons.append([types.InlineKeyboardButton(
            text=f"{icon} #{m.id} | {m.title[:20]}",
            callback_data=f"view_mailing:{m.id}"
        )])

    back_txt = await I18nService.tr("⬅️ Назад к категориям", lang)
    buttons.append([types.InlineKeyboardButton(text=back_txt, callback_data="admin_mailings_list")])

    title = await I18nService.tr("📋 <b>Рассылки в категории [{cat}]:</b>", lang, cat=cat)
    await cb.message.edit_text(title, reply_markup=types.InlineKeyboardMarkup(inline_keyboard=buttons),
                               parse_mode="HTML")
    await cb.answer()


# --- 2. ЦЕНТР УДАЛЕНИЯ РАССЫЛОК ---

@router.callback_query(F.data == "mail_delete_hub")
async def cb_mail_delete_hub(cb: types.CallbackQuery, db_user: User) -> None:
    lang = db_user.language_code
    title = await I18nService.tr("🗑 <b>Центр удаления рассылок</b>\n\nВыберите, какие рассылки необходимо удалить:",
                                 lang)
    kb = await get_mailings_delete_hub_kb(lang)
    await cb.message.edit_text(title, reply_markup=kb, parse_mode="HTML")
    await cb.answer()


@router.callback_query(F.data.startswith("del_batch:"))
async def cb_delete_batch_simple(cb: types.CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """
    Назначение: Удаление всех рассылок типа ALL или USER.
    """
    lang = db_user.language_code
    cat = cb.data.split(":")[1]
    count = await SchedulerService.delete_mailings_by_target(session, TargetType(cat))

    alert = await I18nService.tr("🗑 Удалено рассылок: {count}", lang, count=count)
    await cb.answer(alert, show_alert=True)
    await cb_mail_delete_hub(cb, db_user)


# Удаление рассылок групп: выбор конкретной группы или всех сразу
@router.callback_query(F.data == "del_batch_groups_menu")
async def cb_del_groups_menu(cb: types.CallbackQuery, session: AsyncSession, db_user: User) -> None:
    lang = db_user.language_code
    groups = await GroupService.get_all_groups(session)

    buttons = []
    for g in groups:
        buttons.append([types.InlineKeyboardButton(
            text=f"🗑 Рассылки группы '{g.name}'",
            callback_data=f"del_group_mailings:{g.id}"
        )])

    btn_del_all_groups = await I18nService.tr("💥 Удалить рассылки ВСЕХ групп", lang)
    btn_back = await I18nService.tr("⬅️ Назад", lang)

    buttons.append([types.InlineKeyboardButton(text=btn_del_all_groups, callback_data="del_group_mailings:ALL")])
    buttons.append([types.InlineKeyboardButton(text=btn_back, callback_data="mail_delete_hub")])

    title = await I18nService.tr("👥 Выберите группу, для которой нужно удалить рассылки:", lang)
    await cb.message.edit_text(title, reply_markup=types.InlineKeyboardMarkup(inline_keyboard=buttons),
                               parse_mode="HTML")
    await cb.answer()


@router.callback_query(F.data.startswith("del_group_mailings:"))
async def cb_execute_del_group_mailings(cb: types.CallbackQuery, session: AsyncSession, db_user: User) -> None:
    lang = db_user.language_code
    target_val = cb.data.split(":")[1]

    if target_val == "ALL":
        count = await SchedulerService.delete_mailings_by_target(session, TargetType.GROUP)
    else:
        count = await SchedulerService.delete_mailings_by_target(session, TargetType.GROUP, target_id=int(target_val))

    alert = await I18nService.tr("🗑 Удалено групповых рассылок: {count}", lang, count=count)
    await cb.answer(alert, show_alert=True)
    await cb_mail_delete_hub(cb, db_user)


# --- 3. УЛЬТРА-КНОПКА С ПРЕДУПРЕЖДЕНИЕМ (NUKE ALL) ---

@router.callback_query(F.data == "del_nuke_prompt")
async def cb_nuke_prompt(cb: types.CallbackQuery, db_user: User) -> None:
    lang = db_user.language_code
    warn_text = await I18nService.tr(
        "🚨 <b>ВНИМАНИЕ! КРИТИЧЕСКОЕ ДЕЙСТВИЕ!</b>\n\n"
        "Вы собираетесь БЕЗВОЗВРАТНО удалить <b>абсолютно все рассылки</b> в системе (массовые, групповые и персональные).\n"
        "Все таймеры будут остановлены.\n\n"
        "Вы подтверждаете удаление?",
        lang
    )
    btn_confirm = await I18nService.tr("💥 ДА, УДАЛИТЬ ВСЁ БЕЗВОЗВРАТНО", lang)
    btn_cancel = await I18nService.tr("⬅️ Отмена / Назад", lang)

    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text=btn_confirm, callback_data="del_nuke_execute")],
        [types.InlineKeyboardButton(text=btn_cancel, callback_data="mail_delete_hub")]
    ])
    await cb.message.edit_text(warn_text, reply_markup=kb, parse_mode="HTML")
    await cb.answer()


@router.callback_query(F.data == "del_nuke_execute")
async def cb_nuke_execute(cb: types.CallbackQuery, session: AsyncSession, db_user: User) -> None:
    lang = db_user.language_code
    deleted_count = await SchedulerService.delete_all_mailings(session)

    alert = await I18nService.tr("💣 Все рассылки системы удалены (Всего: {count})!", lang, count=deleted_count)
    await cb.answer(alert, show_alert=True)
    await cb_mail_delete_hub(cb, db_user)


# --- 4. УДАЛЕНИЕ ВСЕХ РАССЫЛОК ПОЛЬЗОВАТЕЛЯ ИЗ ЕГО КАРТОЧКИ ---

@router.callback_query(F.data.startswith("del_all_user_mailings:"))
async def cb_del_all_user_mailings(cb: types.CallbackQuery, session: AsyncSession, db_user: User) -> None:
    lang = db_user.language_code
    user_id = int(cb.data.split(":")[1])

    count = await SchedulerService.delete_mailings_by_target(session, TargetType.USER, target_id=user_id)
    alert = await I18nService.tr("🗑 Удалено персональных рассылок: {count}", lang, count=count)
    await cb.answer(alert, show_alert=True)

    # Возврат в список рассылок юзера (теперь пустой)
    await cb_user_mailings_list(cb, session, db_user)