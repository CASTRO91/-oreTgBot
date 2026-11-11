import asyncio
from aiogram import Router, types, F, Bot
from aiogram.filters import Command
from aiogram.types import BufferedInputFile
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
import html

from services.user_service import UserService
from services.access_service import AccessService
from database.models.user import User, UserRole
from database.models.queue import QueueTask, TaskStatus
from core.queue import QueueManager
from core.worker import task_registry
from utils.keyboards import get_admin_user_manage_kb, get_admin_main_kb
from utils.states import AdminBroadcastStates
from middlewares.acl import SuperAdminFilter, AdminRoleFilter
from database.models.permission import Permission, UserPermission
from utils.keyboards import get_user_permissions_kb
from services.i18n_service import I18nService

from database.models.group import Group, UserGroupMembership
from services.group_service import GroupService
from utils.states import GroupManageStates


from services.excel_service import ExcelService
from services.media_relay_service import MediaRelayService

router = Router(name="admin_router")
router.message.filter(AdminRoleFilter())
router.callback_query.filter(AdminRoleFilter())


async def format_user_card(user: User, viewer_lang: str = "ru") -> str:
    """
    Назначение: Генерация HTML-карточки пользователя на языке просматривающего администратора.
    """
    safe_fn = html.escape(user.first_name)
    safe_ln = html.escape(user.last_name)
    safe_addr = html.escape(user.address)
    safe_uname = html.escape(user.username) if user.username else "нет"
    safe_phone = html.escape(user.phone) if user.phone else "<i>не указан</i>"

    # Переводим статус бана
    ban_badge = await I18nService.tr("🔴 ЗАБАНЕН", viewer_lang) if user.is_banned else await I18nService.tr("🟢 Активен",
                                                                                                           viewer_lang)
    reg_date = user.created_at.strftime("%Y-%m-%d %H:%M:%S")

    # Переводим названия полей карточки
    lbl_user = await I18nService.tr("Пользователь", viewer_lang)
    lbl_fio = await I18nService.tr("ФИО", viewer_lang)
    lbl_role = await I18nService.tr("Роль", viewer_lang)
    lbl_lang = await I18nService.tr("Язык", viewer_lang)
    lbl_tz = await I18nService.tr("Пояс", viewer_lang)
    lbl_phone = await I18nService.tr("Телефон", viewer_lang)
    lbl_addr = await I18nService.tr("Адрес", viewer_lang)
    lbl_reg = await I18nService.tr("Дата регистрации", viewer_lang)

    geo_display = ""
    if user.latitude and user.longitude:
        maps_url = f"https://maps.google.com/?q={user.latitude:.5f},{user.longitude:.5f}"
        lbl_maps = await I18nService.tr("Открыть в Картах", viewer_lang)
        geo_display = f"\n▫️ <b>Локация:</b> <a href='{maps_url}'>📍 {user.latitude:.4f}, {user.longitude:.4f} ({lbl_maps})</a>"

    return (
        f"👤 <b>{lbl_user} #{user.telegram_id}</b> | @{safe_uname}\n"
        f"▫️ <b>{lbl_fio}:</b> {safe_fn} {safe_ln}\n"
        f"▫️ <b>{lbl_role}:</b> <code>{user.role.value}</code> | {ban_badge}\n"
        f"▫️ <b>{lbl_lang}:</b> <code>{user.language_code.upper()}</code> | <b>{lbl_tz}:</b> <code>{user.timezone}</code>\n"
        f"▫️ <b>{lbl_phone}:</b> {safe_phone}\n"
        f"▫️ <b>{lbl_addr}:</b> {safe_addr}{geo_display}\n"
        f"▫️ <b>{lbl_reg}:</b> <code>{reg_date}</code>"
    )


# --- ОБРАБОТЧИК МАССОВОЙ РАССЫЛКИ В ОЧЕРЕДИ ---
@task_registry.register("TASK_BROADCAST_ALL")
async def handle_broadcast_task(task: QueueTask, bot: Bot):
    """Фоновая рассылка сообщений воркером со сглаживанием лимитов TG."""
    message_text = task.payload.get("text", "")
    from database.session import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        # Берем всех незабаненных юзеров
        users = (await session.execute(
            select(User.telegram_id).where(User.is_banned == False)
        )).scalars().all()

    success_count = 0
    for uid in users:
        try:
            await bot.send_message(chat_id=uid, text=message_text, parse_mode="HTML")
            success_count += 1
            await asyncio.sleep(0.05)  # Защита от лимитов Telegram (20 сообщений/сек)
        except Exception:
            pass  # Бот заблокирован юзером и т.д.

    # Оповещаем инициатора об успехе
    await bot.send_message(
        chat_id=task.user_id,
        text=f"📢 Рассылка завершена! Успешно доставлено: <b>{success_count}/{len(users)}</b>",
        parse_mode="HTML"
    )


# --- ГЛАВНАЯ АДМИН-ПАНЕЛЬ ---
@router.message(Command("admin"))
async def cmd_admin(message: types.Message, db_user: User) -> None:
    lang = db_user.language_code
    if db_user.role not in [UserRole.ADMIN, UserRole.SUPER_ADMIN]:
        msg = await I18nService.tr("⛔️ У вас нет доступа к админ-панели.", lang)
        await message.answer(msg)
        return

    is_super = AccessService.is_super_admin(message.from_user.id)
    role_title = await I18nService.tr("👑 Главный Администратор", lang) if is_super else await I18nService.tr(
        "🛡 Администратор", lang)

    panel_title = await I18nService.tr("🛠 <b>Панель управления ядром</b>", lang)
    status_lbl = await I18nService.tr("Ваш статус", lang)
    action_lbl = await I18nService.tr("Выберите действие:", lang)

    text = f"{panel_title}\n{status_lbl}: <b>{role_title}</b>\n\n{action_lbl}"
    kb = await get_admin_main_kb(is_super, lang=lang)
    await message.answer(text, reply_markup=kb, parse_mode="HTML")


# Статистика очереди задач
@router.callback_query(F.data == "admin_queue_stats")
async def cb_queue_stats(cb: types.CallbackQuery, session: AsyncSession, db_user: User) -> None:
    lang = db_user.language_code
    stmt = select(QueueTask.status, func.count(QueueTask.id)).group_by(QueueTask.status)
    results = dict((await session.execute(stmt)).all())

    pending = results.get(TaskStatus.PENDING, 0)
    processing = results.get(TaskStatus.PROCESSING, 0)
    completed = results.get(TaskStatus.COMPLETED, 0)
    failed = results.get(TaskStatus.FAILED, 0)

    title = await I18nService.tr("📊 <b>Состояние очереди задач:</b>", lang)
    lbl_pending = await I18nService.tr("⏳ Ожидают (PENDING)", lang)
    lbl_proc = await I18nService.tr("⚙️ В работе (PROCESSING)", lang)
    lbl_comp = await I18nService.tr("✅ Успешно (COMPLETED)", lang)
    lbl_fail = await I18nService.tr("🚨 С ошибкой (FAILED)", lang)

    text = (
        f"{title}\n\n"
        f"{lbl_pending}: <code>{pending}</code>\n"
        f"{lbl_proc}: <code>{processing}</code>\n"
        f"{lbl_comp}: <code>{completed}</code>\n"
        f"{lbl_fail}: <code>{failed}</code>\n"
    )
    await cb.message.answer(text, parse_mode="HTML")
    await cb.answer()


# --- СЦЕНАРИЙ: НАПИСАТЬ КОНКРЕТНОМУ ЮЗЕРУ ---
@router.callback_query(F.data == "admin_msg_user")
async def cb_msg_user_start(cb: types.CallbackQuery, state: FSMContext):
    await state.set_state(AdminBroadcastStates.waiting_for_single_user_id)
    await cb.message.answer("Введите <b>Telegram ID</b> пользователя, которому хотите отправить сообщение:",
                            parse_mode="HTML")
    await cb.answer()


@router.message(AdminBroadcastStates.waiting_for_single_user_id)
async def cb_msg_user_get_id(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("⚠️ Введите корректный числовой Telegram ID:")
        return
    await state.update_data(target_user_id=int(message.text))
    await state.set_state(AdminBroadcastStates.waiting_for_single_message)
    await message.answer(
        "Теперь отправьте <b>сообщение</b> (текст, фото, видео, аудио, голосовое или файл) для этого пользователя:",
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("manage_perms:"))
async def cb_manage_perms(
        cb: types.CallbackQuery,
        session: AsyncSession,
        db_user: User
) -> None:
    """
    Назначение: Отображение интерактивного списка прав (ACL) целевого пользователя.
    Входные параметры: CallbackQuery, AsyncSession, db_user.
    Возвращаемое значение: None.
    """
    if db_user.role not in [UserRole.ADMIN, UserRole.SUPER_ADMIN]:
        await cb.answer("⛔️ Недостаточно прав.", show_alert=True)
        return

    target_id = int(cb.data.split(":")[1])

    # Получаем все не-системные права
    stmt_all = select(Permission).where(Permission.is_system == False)
    all_perms = list((await session.execute(stmt_all)).scalars().all())

    stmt_user = select(UserPermission.permission_id).where(UserPermission.user_id == target_id)
    user_perm_ids = set((await session.execute(stmt_user)).scalars().all())

    kb = await get_user_permissions_kb(target_id, all_perms, user_perm_ids, lang=db_user.language_code)

    title = await I18nService.tr("⚙️ <b>Управление доступом (ACL) для юзера <code>{target_id}</code></b>",
                                 db_user.language_code, target_id=target_id)
    hint = await I18nService.tr("Нажимайте на кнопки, чтобы выдать [✅] или забрать [❌] право:", db_user.language_code)

    await cb.message.edit_text(f"{title}\n\n{hint}", reply_markup=kb, parse_mode="HTML")
    await cb.answer()


@router.callback_query(F.data.startswith("toggle_perm:"))
async def cb_toggle_permission(
        cb: types.CallbackQuery,
        session: AsyncSession,
        db_user: User
) -> None:
    """
    Назначение: Выдача или отзыв индивидуального права в один клик.
    Входные параметры: CallbackQuery, AsyncSession, db_user.
    Возвращаемое значение: None.
    """
    lang = db_user.language_code
    if db_user.role not in [UserRole.ADMIN, UserRole.SUPER_ADMIN]:
        await cb.answer(await I18nService.tr("⛔️ Недостаточно прав.", lang), show_alert=True)
        return

    _, target_id_str, perm_code, action = cb.data.split(":")
    target_id = int(target_id_str)

    try:
        if action == "grant":
            await AccessService.grant_permission(session, cb.from_user.id, target_id, perm_code)
            msg = await I18nService.tr("✅ Право выдано!", lang)
            await cb.answer(msg)
        else:
            await AccessService.revoke_permission(session, cb.from_user.id, target_id, perm_code)
            msg = await I18nService.tr("❌ Право отозвано!", lang)
            await cb.answer(msg)

        # Достаем свежие данные
        stmt_all = select(Permission).where(Permission.is_system == False)
        all_perms = list((await session.execute(stmt_all)).scalars().all())

        stmt_user = select(UserPermission.permission_id).where(UserPermission.user_id == target_id)
        user_perm_ids = set((await session.execute(stmt_user)).scalars().all())

        # ОБЯЗАТЕЛЬНО СТАВИМ AWAIT:
        kb = await get_user_permissions_kb(target_id, all_perms, user_perm_ids, lang=lang)

        await cb.message.edit_reply_markup(reply_markup=kb)

    except PermissionError as e:
        await cb.answer(str(e), show_alert=True)
    except Exception as e:
        # Короткий ответ без краша MESSAGE_TOO_LONG
        await cb.answer("Ошибка переключения права.", show_alert=True)


@router.callback_query(F.data.startswith("back_to_user:"))
async def cb_back_to_user(
        cb: types.CallbackQuery,
        session: AsyncSession
) -> None:
    """
    Назначение: Возврат из меню прав назад в главную карточку пользователя через единый шаблон.
    Входные параметры: CallbackQuery, AsyncSession.
    Возвращаемое значение: None.
    """
    target_id = int(cb.data.split(":")[1])
    u = await UserService.get_by_id(session, target_id)
    if not u:
        await cb.answer("Пользователь не найден.")
        return

    is_admin = u.role in [UserRole.ADMIN, UserRole.SUPER_ADMIN]
    await cb.message.edit_text(
        text=await format_user_card(u),
        reply_markup=await get_admin_user_manage_kb(u.telegram_id, is_admin, u.is_banned),
        parse_mode="HTML"
    )
    await cb.answer()


@router.message(AdminBroadcastStates.waiting_for_single_message)
async def cb_msg_user_send(message: types.Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    target_id = data["target_user_id"]
    await state.clear()

    success = await MediaRelayService.relay_message(
        bot=bot,
        message=message,
        target_chat_id=target_id,
        header_text="✉️ <b>Сообщение от администрации:</b>"
    )
    if success:
        await message.answer(
            f"✅ Сообщение успешно доставлено пользователю <code>{target_id}</code>!",
            parse_mode="HTML"
        )
    else:
        await message.answer(
            f"❌ Не удалось отправить сообщение пользователю <code>{target_id}</code>. "
            f"Возможно, бот заблокирован пользователем.",
            parse_mode="HTML"
        )


# --- СЦЕНАРИЙ: РАССЫЛКА ВСЕМ ЧЕРЕЗ ОЧЕРЕДЬ ---
@router.callback_query(F.data == "admin_msg_all")
async def cb_msg_all_start(cb: types.CallbackQuery, state: FSMContext):
    await state.set_state(AdminBroadcastStates.waiting_for_all_message)
    await cb.message.answer("Введите текст для <b>массовой рассылки всем</b> пользователям:", parse_mode="HTML")
    await cb.answer()


@router.message(AdminBroadcastStates.waiting_for_all_message)
async def cb_msg_all_send(message: types.Message, state: FSMContext, session: AsyncSession):
    await state.clear()

    # Ставим задачу в очередь ядра!
    task = await QueueManager.enqueue(
        session=session,
        task_code="TASK_BROADCAST_ALL",
        user_id=message.from_user.id,
        payload={"text": f"📢 <b>Объявление:</b>\n\n{message.text}"}
    )
    await message.answer(
        f"🚀 Рассылка поставлена в фоновую очередь задач ядра (Задача #{task.id}). "
        f"Воркеры уже начали отправку!",
        parse_mode="HTML"
    )


@router.message(Command("last_users"))
async def cmd_last_users(
        message: types.Message,
        session: AsyncSession,
        db_user: User
) -> None:
    """
    Назначение: Вывод списка последних зарегистрированных пользователей с кнопками управления.
    Входные параметры:
        message (types.Message): Сообщение от администратора (например: '/last_users' или '/last_users 5').
        session (AsyncSession): Асинхронная сессия БД.
        db_user (User): Объект пользователя, вызвавшего команду.
    Возвращаемое значение: None.
    """
    if db_user.role not in [UserRole.ADMIN, UserRole.SUPER_ADMIN]:
        await message.answer("⛔️ Команда доступна только администрации.")
        return

    # Парсим количество (по умолчанию 1)
    args = message.text.split()
    limit = 1
    if len(args) > 1:
        if args[1].isdigit():
            limit = min(int(args[1]), 25)  # Ограничиваем потолок в 25, чтобы не спамить в чат
        else:
            await message.answer("⚠️ Неверный формат. Используйте: <code>/last_users [число]</code>", parse_mode="HTML")
            return

    users = await UserService.get_latest_users(session=session, limit=limit)

    if not users:
        await message.answer("База пользователей пока пуста.")
        return

    await message.answer(f"📋 <b>Последние пользователи (показано: {len(users)}):</b>", parse_mode="HTML")

    for u in users:
        is_admin = u.role in [UserRole.ADMIN, UserRole.SUPER_ADMIN]

        # Передаем db_user.language_code (язык админа)
        card_text = await format_user_card(u, viewer_lang=db_user.language_code)
        kb = await get_admin_user_manage_kb(u.telegram_id, is_admin, u.is_banned, lang=db_user.language_code)

        await message.answer(text=card_text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data == "admin_last_users")
async def cb_last_users_quick(
        cb: types.CallbackQuery,
        session: AsyncSession,
        db_user: User
) -> None:
    if db_user.role not in [UserRole.ADMIN, UserRole.SUPER_ADMIN]:
        await cb.answer("⛔️ Недостаточно прав.", show_alert=True)
        return

    users = await UserService.get_latest_users(session=session, limit=5)
    await cb.answer()

    if not users:
        await cb.message.answer("База пользователей пуста.")
        return

    admin_lang = db_user.language_code  # ВОТ ОН - ТВОЙ ЯЗЫК 'it'!

    title = await I18nService.tr("📋 Последние 5 зарегистрированных пользователей:", admin_lang)
    await cb.message.answer(title, parse_mode="HTML")

    for u in users:
        is_admin = u.role in [UserRole.ADMIN, UserRole.SUPER_ADMIN]

        # ПЕРЕДАЕМ admin_lang В ОБЕ ФУНКЦИИ:
        card_text = await format_user_card(u, viewer_lang=admin_lang)
        kb = await get_admin_user_manage_kb(
            target_id=u.telegram_id,
            is_admin=is_admin,
            is_banned=u.is_banned,
            lang=admin_lang
        )

        await cb.message.answer(
            text=card_text,
            reply_markup=kb,
            parse_mode="HTML"
        )


@router.callback_query(F.data == "admin_export_users_excel")
async def cb_export_all_users_excel(cb: types.CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """
    Назначение: Полная выгрузка всей базы пользователей со всеми данными в файл Excel.
    """
    lang = db_user.language_code
    if db_user.role not in [UserRole.ADMIN, UserRole.SUPER_ADMIN]:
        await cb.answer(await I18nService.tr("⛔️ Недостаточно прав.", lang), show_alert=True)
        return

    await cb.answer(await I18nService.tr("⏳ Формируем Excel файл...", lang))

    # Достаем абсолютно всех пользователей
    stmt = select(User).order_by(User.created_at.desc())
    all_users = list((await session.execute(stmt)).scalars().all())

    excel_stream = await ExcelService.generate_users_excel(session, all_users)
    doc = BufferedInputFile(excel_stream.read(), filename="all_users_export.xlsx")

    caption = await I18nService.tr("📊 Полная выгрузка базы пользователей (Всего: {total}):", lang, total=len(all_users))
    await cb.message.answer_document(doc, caption=caption, parse_mode="HTML")

@router.message(Command("find_user"))
async def cmd_find_user(message: types.Message, session: AsyncSession, db_user: User) -> None:
    lang = db_user.language_code
    if db_user.role not in [UserRole.ADMIN, UserRole.SUPER_ADMIN]:
        await message.answer(await I18nService.tr("⛔️ Команда доступна только администрации.", lang))
        return

    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer(await I18nService.tr("⚠️ Использование: <code>/find_user [id/ник/имя]</code>", lang), parse_mode="HTML")
        return

    raw_query = args[1].strip()
    # Ищем до 500 пользователей для поиска
    users = await UserService.search_users(session, raw_query, limit=500)

    if not users:
        not_found_msg = await I18nService.tr("🔍 По запросу <code>{query}</code> никто не найден.", lang, query=html.escape(raw_query))
        await message.answer(not_found_msg, parse_mode="HTML")
        return

    # ЕСЛИ НАЙДЕНО ДО 10 ЧЕЛОВЕК — ВЫВОДИМ КАРТОЧКАМИ В ЧАТ
    if len(users) <= 10:
        for u in users:
            is_admin = u.role in [UserRole.ADMIN, UserRole.SUPER_ADMIN]
            card_text = await format_user_card(u, viewer_lang=lang)
            kb = await get_admin_user_manage_kb(u.telegram_id, is_admin, u.is_banned, lang=lang)
            await message.answer(text=card_text, reply_markup=kb, parse_mode="HTML")
    else:
        # ЕСЛИ НАЙДЕНО БОЛЬШЕ 10 ЧЕЛОВЕК — ГЕНЕРИРУЕМ И ШЛЕМ EXCEL ФАЙЛ!
        notice = await I18nService.tr(
            "🔍 Найдено пользователей: <b>{count}</b>. Чтобы не спамить в чат, сформирован Excel-отчет:",
            lang,
            count=len(users)
        )
        await message.answer(notice, parse_mode="HTML")

        excel_stream = await ExcelService.generate_users_excel(session, users)
        doc = BufferedInputFile(excel_stream.read(), filename=f"search_results_{raw_query}.xlsx")
        await message.answer_document(doc)

@router.callback_query(F.data.startswith("admin_direct_msg:"))
async def cb_admin_direct_msg(
        cb: types.CallbackQuery,
        state: FSMContext,
        db_user: User
) -> None:
    """
    Назначение: Переход к вводу сообщения для конкретного пользователя по кнопке из его карточки.
    Входные параметры: CallbackQuery, FSMContext, db_user.
    Возвращаемое значение: None.
    """
    if db_user.role not in [UserRole.ADMIN, UserRole.SUPER_ADMIN]:
        await cb.answer("⛔️ Недостаточно прав.", show_alert=True)
        return

    target_id = int(cb.data.split(":")[1])
    await state.update_data(target_user_id=target_id)
    await state.set_state(AdminBroadcastStates.waiting_for_single_message)

    await cb.message.answer(
        f"✍️ Отправьте сообщение для пользователя <code>{target_id}</code>\n"
        f"<i>(Поддерживаются текст, фото, видео, аудио, голосовые и файлы)</i>:",
        parse_mode="HTML"
    )
    await cb.answer()


@router.callback_query(F.data.startswith("promote_admin:"), SuperAdminFilter())
async def cb_promote_admin(
        cb: types.CallbackQuery,
        session: AsyncSession
) -> None:
    """
    Назначение: Повышение до ADMIN с обновлением роли в тексте карточки.
    Входные параметры: CallbackQuery, AsyncSession.
    Возвращаемое значение: None.
    """
    target_id = int(cb.data.split(":")[1])
    try:
        await AccessService.promote_to_admin(session, cb.from_user.id, target_id)
        updated_user = await UserService.get_by_id(session, target_id)

        await cb.message.edit_text(
            text=await format_user_card(updated_user),
            reply_markup=await get_admin_user_manage_kb(target_id, is_admin=True, is_banned=updated_user.is_banned),
            parse_mode="HTML"
        )
        await cb.answer("✅ Пользователь повышен до ADMIN!", show_alert=True)
    except PermissionError as e:
        await cb.answer(str(e), show_alert=True)


@router.callback_query(F.data == "admin_find_user")
async def cb_find_user_hint(cb: types.CallbackQuery):
    await cb.message.answer(
        "🔎 Чтобы найти пользователя, напишите команду:\n"
        "<code>/find_user [id или ник без @ или имя]</code>\n\n"
        "Например:\n"
        "<code>/find_user 123456789</code>\n"
        "<code>/find_user durov</code>\n"
        "<code>/find_user Иван</code>",
        parse_mode="HTML"
    )
    await cb.answer()


@router.callback_query(F.data.startswith("demote_admin:"), SuperAdminFilter())
async def cb_demote_admin(
        cb: types.CallbackQuery,
        session: AsyncSession
) -> None:
    """
    Назначение: Разжалование админа до USER с обновлением текста карточки.
    Входные параметры: CallbackQuery, AsyncSession.
    Возвращаемое значение: None.
    """
    target_id = int(cb.data.split(":")[1])
    try:
        await AccessService.demote_admin(session, cb.from_user.id, target_id)
        updated_user = await UserService.get_by_id(session, target_id)

        await cb.message.edit_text(
            text=await format_user_card(updated_user),
            reply_markup=await get_admin_user_manage_kb(target_id, is_admin=False, is_banned=updated_user.is_banned),
            parse_mode="HTML"
        )
        await cb.answer("🔻 Пользователь разжалован до USER.", show_alert=True)
    except Exception as e:
        await cb.answer(str(e), show_alert=True)


# Защита от попыток обычных админов кликать кнопки роли
@router.callback_query(F.data.startswith(("promote_admin:", "demote_admin:")))
async def cb_role_denied(cb: types.CallbackQuery):
    await cb.answer("⛔️ ТОЛЬКО Главный Администратор (SUPER_ADMIN) имеет право менять роли!", show_alert=True)


@router.callback_query(F.data.startswith("ban:"))
async def cb_ban_user(
        cb: types.CallbackQuery,
        session: AsyncSession,
        db_user: User
) -> None:
    """
    Назначение: Блокировка пользователя с моментальным обновлением текста карточки и клавиатуры.
    Входные параметры: CallbackQuery, AsyncSession, db_user.
    Возвращаемое значение: None.
    """
    lang = db_user.language_code
    if db_user.role not in [UserRole.ADMIN, UserRole.SUPER_ADMIN]:
        await cb.answer(await I18nService.tr("⛔️ Недостаточно прав.", lang), show_alert=True)
        return

    target_id = int(cb.data.split(":")[1])
    if AccessService.is_super_admin(target_id):
        await cb.answer(await I18nService.tr("⛔️ Нельзя заблокировать Главного Админа!", lang), show_alert=True)
        return

    await UserService.set_ban_status(session, cb.from_user.id, target_id, is_banned=True)

    updated_user = await UserService.get_by_id(session, target_id)
    if not updated_user:
        await cb.answer("Пользователь не найден.")
        return

    is_admin = updated_user.role in [UserRole.ADMIN, UserRole.SUPER_ADMIN]
    card_text = await format_user_card(updated_user, viewer_lang=lang)
    kb = await get_admin_user_manage_kb(target_id, is_admin=is_admin, is_banned=True, lang=lang)

    try:
        await cb.message.edit_text(text=card_text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise e

    await cb.answer(await I18nService.tr("🔴 Пользователь заблокирован.", lang))


@router.callback_query(F.data.startswith("unban:"))
async def cb_unban_user(
        cb: types.CallbackQuery,
        session: AsyncSession,
        db_user: User
) -> None:
    """
    Назначение: Разблокировка пользователя с моментальным обновлением текста карточки и клавиатуры.
    Входные параметры: CallbackQuery, AsyncSession, db_user.
    Возвращаемое значение: None.
    """
    lang = db_user.language_code
    if db_user.role not in [UserRole.ADMIN, UserRole.SUPER_ADMIN]:
        await cb.answer(await I18nService.tr("⛔️ Недостаточно прав.", lang), show_alert=True)
        return

    target_id = int(cb.data.split(":")[1])
    await UserService.set_ban_status(session, cb.from_user.id, target_id, is_banned=False)

    updated_user = await UserService.get_by_id(session, target_id)
    if not updated_user:
        await cb.answer("Пользователь не найден.")
        return

    is_admin = updated_user.role in [UserRole.ADMIN, UserRole.SUPER_ADMIN]
    card_text = await format_user_card(updated_user, viewer_lang=lang)
    kb = await get_admin_user_manage_kb(target_id, is_admin=is_admin, is_banned=False, lang=lang)

    try:
        await cb.message.edit_text(text=card_text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise e

    await cb.answer(await I18nService.tr("🟢 Пользователь разблокирован.", lang))


@router.callback_query(F.data == "admin_groups_menu")
async def cb_admin_groups_menu(cb: types.CallbackQuery, session: AsyncSession, db_user: User) -> None:
    lang = db_user.language_code
    if db_user.role not in [UserRole.ADMIN, UserRole.SUPER_ADMIN]:
        await cb.answer(await I18nService.tr("⛔️ Недостаточно прав.", lang), show_alert=True)
        return

    groups = await GroupService.get_all_groups(session)
    buttons = []

    for g in groups:
        buttons.append([types.InlineKeyboardButton(text=f"👥 {g.name}", callback_data=f"view_group:{g.id}")])

    btn_create = await I18nService.tr("➕ Создать новую группу", lang)
    btn_back = await I18nService.tr("⬅️ Назад в админку", lang)

    buttons.append([types.InlineKeyboardButton(text=btn_create, callback_data="create_group_start")])
    buttons.append([types.InlineKeyboardButton(text=btn_back, callback_data="admin_back_main")])

    title = await I18nService.tr(
        "🏷 <b>Управление группами пользователей (Сегменты)</b>\n\nВыберите группу или создайте новую:", lang)
    await cb.message.edit_text(title, reply_markup=types.InlineKeyboardMarkup(inline_keyboard=buttons),
                               parse_mode="HTML")
    await cb.answer()


@router.callback_query(F.data == "create_group_start")
async def cb_create_group_start(cb: types.CallbackQuery, state: FSMContext, db_user: User) -> None:
    lang = db_user.language_code
    await state.set_state(GroupManageStates.waiting_for_group_name)
    msg = await I18nService.tr("Введите <b>название</b> новой группы (например: VIP-клиенты):", lang)
    await cb.message.edit_text(msg, parse_mode="HTML")
    await cb.answer()


@router.message(GroupManageStates.waiting_for_group_name)
async def process_create_group_name(message: types.Message, state: FSMContext) -> None:
    name = message.text.strip()
    if len(name) < 2 or len(name) > 60:
        await message.answer("⚠️ Название должно быть от 2 до 60 символов. Введите еще раз:")
        return

    await state.update_data(group_name=name)
    await state.set_state(GroupManageStates.waiting_for_group_desc)
    await message.answer("Теперь введите краткое <b>описание</b> группы (или отправьте '-', чтобы пропустить):",
                         parse_mode="HTML")


@router.message(GroupManageStates.waiting_for_group_desc)
async def process_create_group_desc(message: types.Message, state: FSMContext, session: AsyncSession) -> None:
    desc = None if message.text.strip() == "-" else message.text.strip()
    data = await state.get_data()
    group_name = data["group_name"]

    try:
        group = await GroupService.create_group(session, name=group_name, created_by=message.from_user.id,
                                                description=desc)
        await state.clear()
        await message.answer(f"✅ Группа <b>{group.name}</b> успешно создана!", parse_mode="HTML")
    except Exception as e:
        await state.clear()
        await message.answer(f"⚠️ Не удалось создать группу (возможно, такое имя уже есть): {e}")


# --- 2. ПРИВЯЗКА ЮЗЕРА К ГРУППАМ ИЗ КАРТОЧКИ ПОЛЬЗОВАТЕЛЯ ---

@router.callback_query(F.data.startswith("user_groups:"))
async def cb_manage_user_groups(cb: types.CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """
    Назначение: Показ списка групп с чекбоксами для конкретного пользователя.
    """
    lang = db_user.language_code
    if db_user.role not in [UserRole.ADMIN, UserRole.SUPER_ADMIN]:
        await cb.answer(await I18nService.tr("⛔️ Недостаточно прав.", lang), show_alert=True)
        return

    target_id = int(cb.data.split(":")[1])
    groups = await GroupService.get_all_groups(session)

    if not groups:
        await cb.answer("В системе пока нет созданных групп. Сначала создайте группу в меню админки.", show_alert=True)
        return

    # Достаем ID групп, в которых состоит юзер
    user_groups = await GroupService.get_user_groups(session, target_id)
    user_group_ids = {g.id for g in user_groups}

    buttons = []
    for g in groups:
        is_member = g.id in user_group_ids
        icon = "✅" if is_member else "❌"
        action = "remove" if is_member else "add"
        buttons.append([types.InlineKeyboardButton(
            text=f"{icon} {g.name}",
            callback_data=f"toggle_group:{target_id}:{g.id}:{action}"
        )])

    btn_back = await I18nService.tr("⬅️ Назад к пользователю", lang)
    buttons.append([types.InlineKeyboardButton(text=btn_back, callback_data=f"back_to_user:{target_id}")])

    title = await I18nService.tr(
        "👥 <b>Управление группами для юзера #{target_id}</b>\n\nНажимайте, чтобы добавить [✅] или исключить [❌]:",
        lang,
        target_id=target_id
    )
    await cb.message.edit_text(title, reply_markup=types.InlineKeyboardMarkup(inline_keyboard=buttons),
                               parse_mode="HTML")
    await cb.answer()


@router.callback_query(F.data.startswith("toggle_group:"))
async def cb_toggle_user_group(cb: types.CallbackQuery, session: AsyncSession, db_user: User) -> None:
    lang = db_user.language_code
    _, target_id_str, group_id_str, action = cb.data.split(":")
    target_id = int(target_id_str)
    group_id = int(group_id_str)

    if action == "add":
        await GroupService.add_user_to_group(session, target_id, group_id, added_by=cb.from_user.id)
        await cb.answer(await I18nService.tr("✅ Добавлен в группу!", lang))
    else:
        await GroupService.remove_user_from_group(session, target_id, group_id)
        await cb.answer(await I18nService.tr("❌ Исключен из группы!", lang))

    # Перерисовываем меню групп пользователя
    await cb_manage_user_groups(cb, session, db_user)

@router.callback_query(F.data == "admin_back_main")
async def cb_admin_back_main(cb: types.CallbackQuery, db_user: User) -> None:
    await cmd_admin(cb.message, db_user)
    await cb.answer()


@router.callback_query(F.data.startswith("view_group:"))
async def cb_view_single_group(cb: types.CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """
    Назначение: Отображение карточки группы с количеством участников и кнопкой удаления.
    """
    lang = db_user.language_code
    if db_user.role not in [UserRole.ADMIN, UserRole.SUPER_ADMIN]:
        await cb.answer(await I18nService.tr("⛔️ Недостаточно прав.", lang), show_alert=True)
        return

    group_id = int(cb.data.split(":")[1])
    group = await GroupService.get_group_by_id(session, group_id)
    if not group:
        await cb.answer("Группа не найдена.", show_alert=True)
        return

    members_count = await GroupService.count_group_members(session, group_id)
    desc_str = group.description or await I18nService.tr("нет описания", lang)

    title = await I18nService.tr("🏷 <b>Карточка группы:</b> {name}", lang, name=group.name)
    lbl_desc = await I18nService.tr("Описание", lang)
    lbl_count = await I18nService.tr("Участников", lang)

    text = (
        f"{title}\n\n"
        f"▫️ <b>{lbl_desc}:</b> {desc_str}\n"
        f"▫️ <b>{lbl_count}:</b> <code>{members_count}</code>"
    )

    btn_del = await I18nService.tr("🗑 Удалить группу", lang)
    btn_back = await I18nService.tr("⬅️ Назад к группам", lang)

    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text=btn_del, callback_data=f"del_group_req:{group.id}")],
        [types.InlineKeyboardButton(text=btn_back, callback_data="admin_groups_menu")]
    ])

    await cb.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await cb.answer()


@router.callback_query(F.data.startswith("del_group_req:"))
async def cb_request_delete_group(cb: types.CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """
    Назначение: Проверка участников: если 0 — удаляем сразу, если >0 — экран подтверждения.
    """
    lang = db_user.language_code
    group_id = int(cb.data.split(":")[1])
    group = await GroupService.get_group_by_id(session, group_id)
    if not group:
        await cb.answer("Группа не найдена.", show_alert=True)
        return

    members_count = await GroupService.count_group_members(session, group_id)

    # 1. ЕСЛИ В ГРУППЕ НИКОГО НЕТ — УДАЛЯЕМ МГНОВЕННО БЕЗ ПРЕДУПРЕЖДЕНИЙ!
    if members_count == 0:
        await GroupService.delete_group(session, group_id)
        alert_msg = await I18nService.tr("🗑 Группа '{name}' удалена!", lang, name=group.name)
        await cb.answer(alert_msg, show_alert=True)
        # Возвращаемся в список групп
        await cb_admin_groups_menu(cb, session, db_user)
        return

    # 2. ЕСЛИ В ГРУППЕ ЕСТЬ ЛЮДИ — ЭКРАН ПОДТВЕРЖДЕНИЯ!
    warn_text = await I18nService.tr(
        "⚠️ <b>Внимание!</b>\n\n"
        "В группе <b>{name}</b> состоит <code>{count}</code> пользователей.\n"
        "При удалении группы все пользователи будут автоматически отвязаны от неё.\n\n"
        "Вы действительно хотите удалить эту группу?",
        lang,
        name=group.name,
        count=members_count
    )

    btn_confirm = await I18nService.tr("💥 Да, удалить группу", lang)
    btn_cancel = await I18nService.tr("⬅️ Отмена / Назад", lang)

    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text=btn_confirm, callback_data=f"del_group_confirm:{group.id}")],
        [types.InlineKeyboardButton(text=btn_cancel, callback_data=f"view_group:{group.id}")]
    ])

    await cb.message.edit_text(warn_text, reply_markup=kb, parse_mode="HTML")
    await cb.answer()


@router.callback_query(F.data.startswith("del_group_confirm:"))
async def cb_confirm_delete_group(cb: types.CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """
    Назначение: Окончательное удаление группы после согласия администратора.
    """
    lang = db_user.language_code
    group_id = int(cb.data.split(":")[1])
    group = await GroupService.get_group_by_id(session, group_id)
    group_name = group.name if group else ""

    await GroupService.delete_group(session, group_id)

    alert_msg = await I18nService.tr("🗑 Группа '{name}' и связи участников удалены!", lang, name=group_name)
    await cb.answer(alert_msg, show_alert=True)

    # Возвращаемся в обновленный список групп
    await cb_admin_groups_menu(cb, session, db_user)