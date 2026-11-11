import aiohttp
import logging
import math
from typing import Optional, Tuple, List, Any, Callable
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

    # =========================================================================
    # Изолированный математический расчет расстояний (Haversine formula)
    # Не требует внешних API, работает мгновенно в памяти, идеален для
    # плагинов недвижимости, магазинов, курьеров и точек выдачи.
    # =========================================================================

    @staticmethod
    def calculate_distance(
        lat1: float,
        lon1: float,
        lat2: float,
        lon2: float,
        unit: str = "km"
    ) -> float:
        """
        Назначение:
            Изолированный высокоточный расчет расстояния между двумя точками на Земле
            по формуле гаверсинусов (Haversine formula, средний радиус WGS-84 = 6371.0088 км).
            Не делает сетевых запросов, не требует сторонних библиотек.

        Пример использования в 2 строчки:
            from services.geo_service import GeoService
            dist = GeoService.calculate_distance(53.9006, 27.5590, 53.9200, 27.6000)

        Параметры:
            lat1, lon1: GPS широта и долгота первой точки (в градусах).
            lat2, lon2: GPS широта и долгота второй точки (в градусах).
            unit: Единица измерения ('km' - км, 'm' - метры, 'mi' - мили).

        Возвращает:
            Расстояние в указанных единицах (округление: км/мили - 3 знака, метры - 1 знак).
        """
        EARTH_RADIUS_KM = 6371.0088

        d_lat = math.radians(lat2 - lat1)
        d_lon = math.radians(lon2 - lon1)
        r_lat1 = math.radians(lat1)
        r_lat2 = math.radians(lat2)

        a = math.sin(d_lat / 2.0) ** 2 + math.cos(r_lat1) * math.cos(r_lat2) * math.sin(d_lon / 2.0) ** 2
        c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
        distance_km = EARTH_RADIUS_KM * c

        unit_clean = unit.strip().lower()
        if unit_clean in ("m", "meter", "meters", "метр", "метры", "м"):
            return round(distance_km * 1000.0, 1)
        elif unit_clean in ("mi", "mile", "miles", "миля", "мили"):
            return round(distance_km * 0.621371, 3)
        return round(distance_km, 3)

    @staticmethod
    def is_within_radius(
        origin_lat: float,
        origin_lon: float,
        target_lat: float,
        target_lon: float,
        radius: float,
        unit: str = "km"
    ) -> bool:
        """
        Назначение:
            Проверка попадания объекта в заданный радиус от точки пользователя
            (например: квартира в радиусе 5 км, зона доставки магазина 15 км).

        Пример использования в 2 строчки:
            from services.geo_service import GeoService
            is_near = GeoService.is_within_radius(user_lat, user_lon, shop_lat, shop_lon, radius=5.0)
        """
        dist = GeoService.calculate_distance(origin_lat, origin_lon, target_lat, target_lon, unit=unit)
        return dist <= radius

    @staticmethod
    def sort_by_distance(
        origin_lat: float,
        origin_lon: float,
        items: List[Any],
        lat_getter: Optional[Callable[[Any], Optional[float]]] = None,
        lon_getter: Optional[Callable[[Any], Optional[float]]] = None,
        unit: str = "km",
        reverse: bool = False
    ) -> List[Tuple[Any, float]]:
        """
        Назначение:
            Сортировка коллекции объектов (квартир, магазинов, объявлений) по удаленности
            от переданной гео-позиции.

        Параметры:
            origin_lat, origin_lon: Координаты точки отсчета (пользователя).
            items: Список объектов (словари, модели SQLAlchemy, Pydantic, DTO).
            lat_getter: Функция извлечения широты (по умолчанию ищет 'latitude' или 'lat').
            lon_getter: Функция извлечения долготы (по умолчанию ищет 'longitude', 'lon' или 'lng').
            unit: 'km' | 'm' | 'mi'.
            reverse: False (ближайшие первыми), True (дальние первыми).

        Возвращает:
            Список кортежей [(item, distance), ...], отсортированный по расстоянию.
        """
        def _default_lat(obj: Any) -> Optional[float]:
            if isinstance(obj, dict):
                val = obj.get("latitude", obj.get("lat"))
            else:
                val = getattr(obj, "latitude", getattr(obj, "lat", None))
            return float(val) if val is not None else None

        def _default_lon(obj: Any) -> Optional[float]:
            if isinstance(obj, dict):
                val = obj.get("longitude", obj.get("lon", obj.get("lng")))
            else:
                val = getattr(obj, "longitude", getattr(obj, "lon", getattr(obj, "lng", None)))
            return float(val) if val is not None else None

        get_lat = lat_getter or _default_lat
        get_lon = lon_getter or _default_lon

        result = []
        for item in items:
            try:
                lat = get_lat(item)
                lon = get_lon(item)
                if lat is None or lon is None:
                    continue
                d = GeoService.calculate_distance(origin_lat, origin_lon, lat, lon, unit=unit)
                result.append((item, d))
            except Exception as e:
                logger.debug(f"Пропуск элемента {item} при сортировке по расстоянию: {e}")
                continue

        result.sort(key=lambda pair: pair[1], reverse=reverse)
        return result
