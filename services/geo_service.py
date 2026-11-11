import aiohttp
import logging
from typing import Optional, Tuple
from core.config import settings

logger = logging.getLogger(__name__)

# Инициализация TimezoneFinder (если библиотека установлена)
try:
    from timezonefinder import TimezoneFinder
    _tf_instance = TimezoneFinder()
except Exception as _e:
    _tf_instance = None
    logger.info(f"TimezoneFinder работает в режиме математического расчета: {_e}")


class GeoService:
    """
    Назначение:
        Интеллектуальный геосервис ядра:
        - Прямое геокодирование (текст любого города мира -> координаты + часовой пояс).
        - Обратное геокодирование (GPS-координаты -> реальный адрес).
        - Расчет точного часового пояса через TimezoneFinder с математическим фолбэком.
    """

    # Сетка смещений по долготе для определения часовых поясов Земли (фолбэк)
    _utc_offset_map = {
        -8: "America/Los_Angeles",
        -5: "America/New_York",
        -3: "America/Argentina/Buenos_Aires",
        0: "Europe/London",
        1: "Europe/Berlin",
        2: "Europe/Kyiv",
        3: "Europe/Minsk",  # Минск / Москва
        4: "Asia/Dubai",
        5: "Asia/Tashkent",
        6: "Asia/Almaty",
        7: "Asia/Krasnoyarsk",
        8: "Asia/Shanghai",  # Шанхай / Пекин
        9: "Asia/Tokyo",
        10: "Australia/Sydney"
    }

    @classmethod
    def get_timezone_from_coordinates(cls, latitude: float, longitude: float) -> str:
        """
        Назначение: Точный расчет часового пояса по координатам через TimezoneFinder
        с надежным математическим фолбэком при сбоях.
        """
        if _tf_instance is not None:
            try:
                tz = _tf_instance.timezone_at(lat=latitude, lng=longitude)
                if tz:
                    return tz
            except Exception as e:
                logger.debug(f"Ошибка в TimezoneFinder для ({latitude}, {longitude}): {e}")

        # Математический фолбэк
        try:
            # Беларусь и европейская часть СНГ
            if 51.0 <= latitude <= 57.0 and 23.0 <= longitude <= 33.0:
                return "Europe/Minsk"

            offset = round(longitude / 15.0)
            return cls._utc_offset_map.get(offset, settings.DEFAULT_TIMEZONE)
        except Exception:
            return settings.DEFAULT_TIMEZONE

    @classmethod
    def _get_osm_headers(cls) -> dict:
        """Заголовки запроса в соответствии с официальной политикой OpenStreetMap Nominatim."""
        return {
            "User-Agent": "CoreTelegramBot/1.0 (contact: admin@coretgbot.local)",
            "Accept-Language": "ru,en;q=0.8"
        }

    @classmethod
    async def reverse_geocode(cls, latitude: float, longitude: float) -> str:
        """
        Назначение: GPS-координаты -> Человеческий адрес.
        """
        url = f"https://nominatim.openstreetmap.org/reverse?format=json&lat={latitude}&lon={longitude}&zoom=18&addressdetails=1&accept-language=ru,en"
        headers = cls._get_osm_headers()

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=4)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        addr = data.get("address", {})
                        city = addr.get("city") or addr.get("town") or addr.get("village") or ""
                        road = addr.get("road") or ""
                        house = addr.get("house_number") or ""

                        parts = [p for p in [city, road, house] if p]
                        if parts:
                            return ", ".join(parts)

                        display_name = data.get("display_name")
                        if display_name:
                            return ", ".join(display_name.split(", ")[:3])
        except Exception as e:
            logger.warning(f"Ошибка обратного геокодирования OSM: {e}")

        return f"Координаты: {latitude:.5f}, {longitude:.5f}"

    @classmethod
    async def geocode_text_address(cls, text_address: str) -> Tuple[str, str, Optional[float], Optional[float]]:
        """
        Назначение:
            Прямое геокодирование ЛЮБОГО текста города или адреса в мире через OpenStreetMap.
        Входные параметры:
            text_address (str): Введенная пользователем строка (например, 'Шанхай', 'Бобруйск', 'Сидней').
        Возвращаемое значение:
            Tuple[str, str, float, float]: (Канонический адрес, Часовой пояс, Широта, Долгота).
        """
        url = f"https://nominatim.openstreetmap.org/search?q={text_address}&format=json&limit=1&accept-language=ru,en"
        headers = cls._get_osm_headers()

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=4)) as resp:
                    if resp.status == 200:
                        results = await resp.json()
                        if results:
                            item = results[0]
                            lat = float(item["lat"])
                            lon = float(item["lon"])
                            tz = cls.get_timezone_from_coordinates(lat, lon)

                            # Берем красивое официальное название от OSM
                            display_name = ", ".join(item.get("display_name", text_address).split(", ")[:3])
                            return display_name, tz, lat, lon
        except Exception as e:
            logger.warning(f"Ошибка прямого геокодирования города '{text_address}': {e}")

        # Фолбэк, если интернета нет или город совсем марсианский
        return text_address, settings.DEFAULT_TIMEZONE, None, None