from aiogram.fsm.state import State, StatesGroup


class RegistrationStates(StatesGroup):
    waiting_for_first_name = State()
    waiting_for_last_name = State()
    waiting_for_address = State()
    waiting_for_phone = State()  # Опционально


class ProfileEditStates(StatesGroup):
    waiting_for_new_first_name = State()
    waiting_for_new_last_name = State()
    waiting_for_new_address = State()
    waiting_for_new_phone = State()


class AdminBroadcastStates(StatesGroup):
    waiting_for_single_user_id = State()
    waiting_for_single_message = State()
    waiting_for_all_message = State()

class MailingBuilderStates(StatesGroup):
    """
    Назначение: Машина состояний для пошагового создания отложенных и циклических рассылок.
    """
    waiting_for_target = State()       # Кому (Всем / Себе / Группе / Юзеру)
    waiting_for_user_id = State()      # Если конкретному юзеру
    waiting_for_group_id = State()     # Если группе
    waiting_for_content = State()      # Текст или медиа (фото/видео/документ с подписью)
    waiting_for_schedule_type = State()# Тип: Через время / В точную дату / Циклично
    waiting_for_exact_datetime = State()# Ввод точной даты 'YYYY-MM-DD HH:MM'
    waiting_for_delay = State()        # Ввод задержки в минутах/часах
    waiting_for_cron = State()         # Ввод или выбор cron-маски

class GroupManageStates(StatesGroup):
    """
    Назначение: Состояния для создания новой пользовательской группы.
    """
    waiting_for_group_name = State()
    waiting_for_group_desc = State()

class MailingEditStates(StatesGroup):
    """
    Назначение: Состояние для редактирования текста существующей рассылки.
    """
    waiting_for_new_text = State()

class SupportStates(StatesGroup):
    waiting_for_message = State()