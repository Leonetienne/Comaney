import json
from datetime import date

from django.utils.safestring import mark_safe

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


def _date_range_presets_context(feuser) -> dict:
    """Return context dict with preset date ranges for the date range picker."""
    today = date.today()
    cur_year = today.year
    sd = feuser.month_start_day
    pm = feuser.month_start_prev

    cur_fin_year, cur_fin_month_num = current_financial_month(sd, pm)

    def _prev_fin_month(y, m):
        m -= 1
        if m < 1:
            m = 12
            y -= 1
        return y, m

    def _next_fin_month(y, m):
        m += 1
        if m > 12:
            m = 1
            y += 1
        return y, m

    prev_y, prev_m = _prev_fin_month(cur_fin_year, cur_fin_month_num)
    next_y, next_m = _next_fin_month(cur_fin_year, cur_fin_month_num)

    cur_fin_start, cur_fin_end = financial_month_range(cur_fin_year, cur_fin_month_num, sd, pm)
    prev_fin_start, prev_fin_end = financial_month_range(prev_y, prev_m, sd, pm)
    next_fin_start, next_fin_end = financial_month_range(next_y, next_m, sd, pm)

    def _month_label(y, m):
        return date(y, m, 1).strftime("%b")

    presets = {
        "prev_fin_month": {"label": "Fin." + _month_label(prev_y, prev_m),
                           "from": prev_fin_start.isoformat(), "to": prev_fin_end.isoformat()},
        "cur_fin_month":  {"label": "Fin." + _month_label(cur_fin_year, cur_fin_month_num),
                           "from": cur_fin_start.isoformat(), "to": cur_fin_end.isoformat()},
        "next_fin_month": {"label": "Fin." + _month_label(next_y, next_m),
                           "from": next_fin_start.isoformat(), "to": next_fin_end.isoformat()},
        "prev_year": {"label": str(cur_year - 1),
                      "from": f"{cur_year - 1}-01-01", "to": f"{cur_year - 1}-12-31"},
        "cur_year":  {"label": str(cur_year),
                      "from": f"{cur_year}-01-01", "to": f"{cur_year}-12-31"},
        "next_year": {"label": str(cur_year + 1),
                      "from": f"{cur_year + 1}-01-01", "to": f"{cur_year + 1}-12-31"},
        "q1": {"label": "Q1", "from": f"{cur_year}-01-01", "to": f"{cur_year}-03-31"},
        "q2": {"label": "Q2", "from": f"{cur_year}-04-01", "to": f"{cur_year}-06-30"},
        "q3": {"label": "Q3", "from": f"{cur_year}-07-01", "to": f"{cur_year}-09-30"},
        "q4": {"label": "Q4", "from": f"{cur_year}-10-01", "to": f"{cur_year}-12-31"},
    }

    return {
        "date_range_presets_json": mark_safe(json.dumps(presets)),
        "date_range_default_from": cur_fin_start.isoformat(),
        "date_range_default_to":   cur_fin_end.isoformat(),
    }


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
