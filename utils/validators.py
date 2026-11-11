import re


class InputValidator:
    """
    Назначение: Валидация вводимых пользователем данных (Имя, Фамилия, Адрес).
    """

    @staticmethod
    def validate_name(name: str) -> tuple[bool, str]:
        """
        Назначение: Проверка корректности имени или фамилии.
        Входные параметры:
            name (str): Введенная строка.
        Возвращаемое значение:
            tuple[bool, str]: (Успех/Неудача, Текст ошибки при неудаче).
        """
        cleaned = name.strip()

        # 1. Запрет на слэш (мимикрия под команды)
        if cleaned.startswith("/"):
            return False, "⚠️ Имя не должно начинаться со знака слэша '/'"

        # 2. Длина от 2 до 50 символов
        if len(cleaned) < 2 or len(cleaned) > 50:
            return False, "⚠️ Длина должна быть от 2 до 50 символов."

        # 3. Разрешены только буквы, пробел и дефис
        if not re.match(r"^[A-Za-zА-Яа-яЁёІіЇїЎў\s\-']+$", cleaned):
            return False, "⚠️ Имя может содержать только буквы, дефис и пробелы."

        return True, ""

    @staticmethod
    def validate_address(address: str) -> tuple[bool, str]:
        """
        Назначение: Проверка корректности адреса.
        """
        cleaned = address.strip()
        if cleaned.startswith("/"):
            return False, "⚠️ Адрес не должен начинаться со знака слэша '/'"

        if len(cleaned) < 3 or len(cleaned) > 150:
            return False, "⚠️ Адрес должен содержать от 3 до 150 символов."

        return True, ""