from datetime import date

from ..date_utils import current_financial_month, financial_month_range, financial_year_range


def _get_period_mode(request) -> str:
    return "year" if request.GET.get("view") == "year" else "month"


def _get_year(request, start_day: int = 1, prev_month: bool = False) -> int:
    try:
        year = int(request.GET["year"])
        if year < 1:
            raise ValueError
    except (KeyError, ValueError, TypeError):
        return current_financial_month(start_day, prev_month)[0]
    return year


def _year_nav_context(year: int, start_day: int = 1, prev_month: bool = False) -> dict:
    cur_year, cur_month = current_financial_month(start_day, prev_month)
    is_current = (year == cur_year)
    start, end = financial_year_range(year, start_day, prev_month)
    is_default = (start_day == 1 and not prev_month)
    range_str = f"{start.strftime('%-d %b %Y')} – {end.strftime('%-d %b %Y')}" if not is_default else ""
    return {
        "nav_mode": "year",
        "nav_year": year,
        "nav_month": cur_month,
        "nav_label": str(year),
        "nav_range": range_str,
        "nav_prev_year": year - 1,
        "nav_next_year": year + 1,
        "nav_is_current": is_current,
    }


def _get_month(request, start_day: int = 1, prev_month: bool = False) -> tuple[int, int]:
    try:
        year = int(request.GET["year"])
        month = int(request.GET["month"])
        if not (1 <= month <= 12):
            raise ValueError
    except (KeyError, ValueError, TypeError):
        return current_financial_month(start_day, prev_month)
    return year, month


def _month_nav_context(year: int, month: int, start_day: int = 1, prev_month: bool = False) -> dict:
    nav_prev_month = month - 1 or 12
    nav_prev_year  = year - 1 if month == 1 else year
    nav_next_month = month % 12 + 1
    nav_next_year  = year + 1 if month == 12 else year
    cur_year, cur_month = current_financial_month(start_day, prev_month)
    is_current = year > cur_year or (year == cur_year and month == 12)
    start, end = financial_month_range(year, month, start_day, prev_month)
    is_default = (start_day == 1 and not prev_month)
    range_str = f"{start.strftime('%-d %b')} – {end.strftime('%-d %b')}" if not is_default else ""
    return {
        "nav_mode": "month",
        "nav_year": year,
        "nav_month": month,
        "nav_label": date(year, month, 1).strftime("%B %Y"),
        "nav_range": range_str,
        "nav_prev_year": nav_prev_year,
        "nav_prev_month": nav_prev_month,
        "nav_next_year": nav_next_year,
        "nav_next_month": nav_next_month,
        "nav_is_current": is_current,
    }
