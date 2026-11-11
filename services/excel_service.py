import io
from typing import List
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.user import User
from database.models.mailing import ScheduledMailing, TargetType

class ExcelService:
    """
    Назначение: Генерация профессиональных Excel-выгрузок пользователей и их рассылок.
    """

    @classmethod
    async def generate_users_excel(cls, session: AsyncSession, users: List[User]) -> io.BytesIO:
        """
        Назначение: Формирование Excel-файла со списком пользователей и их персональными рассылками.
        Входные параметры:
            session (AsyncSession): Сессия БД.
            users (List[User]): Список объектов пользователей.
        Возвращаемое значение:
            io.BytesIO: Поток байтов готового .xlsx файла.
        """
        wb = Workbook()
        ws = wb.active
        ws.title = "Пользователи"

        # Стили шапки
        header_font = Font(name="Arial", size=11, bold=True, color="FFFFFF")
        header_fill = PatternFill(start_color="2F5597", end_color="2F5597", fill_type="solid")
        alignment_center = Alignment(horizontal="center", vertical="center")
        border_thin = Border(
            left=Side(style='thin', color='D9D9D9'),
            right=Side(style='thin', color='D9D9D9'),
            top=Side(style='thin', color='D9D9D9'),
            bottom=Side(style='thin', color='D9D9D9')
        )

        headers = [
            "Telegram ID", "Юзернейм", "Имя", "Фамилия",
            "Роль", "Статус", "Телефон", "Адрес",
            "Язык", "Часовой пояс", "Дата регистрации", "Персональные рассылки"
        ]
        ws.append(headers)

        # Красим шапку
        for col_num in range(1, len(headers) + 1):
            cell = ws.cell(row=1, column=col_num)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = alignment_center

        # Наполняем строками
        for row_idx, u in enumerate(users, start=2):
            # Достаем персональные рассылки юзера
            stmt_mail = select(ScheduledMailing.title).where(
                ScheduledMailing.target_type == TargetType.USER,
                ScheduledMailing.target_id == u.telegram_id
            )
            mailings = list((await session.execute(stmt_mail)).scalars().all())
            mailings_str = "; ".join(mailings) if mailings else "Нет"

            ban_str = "ЗАБАНЕН" if u.is_banned else "Активен"
            reg_date_str = u.created_at.strftime("%Y-%m-%d %H:%M:%S")

            row_data = [
                u.telegram_id,
                f"@{u.username}" if u.username else "",
                u.first_name,
                u.last_name,
                u.role.value,
                ban_str,
                u.phone or "",
                u.address or "",
                u.language_code.upper(),
                u.timezone,
                reg_date_str,
                mailings_str
            ]
            ws.append(row_data)

            # Форматируем строку
            for col_num in range(1, len(row_data) + 1):
                c = ws.cell(row=row_idx, column=col_num)
                c.border = border_thin
                c.alignment = Alignment(vertical="center")

        # Авто-подбор ширины колонок
        for col in ws.columns:
            max_len = max(len(str(cell.value or '')) for cell in col)
            col_letter = col[0].column_letter
            ws.column_dimensions[col_letter].width = min(max(max_len + 3, 12), 45)

        output = io.BytesIO()
        wb.save(output)
        output.seek(0)
        return output