import calendar
from datetime import date, timedelta


def financial_month_range(year: int, month: int, start_day: int, prev_month: bool) -> tuple[date, date]:
    """Return (start, end) for the financial month labelled (year, month).

    start_day=27, prev_month=True  → April financial month = Mar 27 – Apr 26
    start_day=4,  prev_month=False → April financial month = Apr 4  – May 3
    start_day=1,  prev_month=False → standard calendar month (Apr 1 – Apr 30)
    """
    def clamp(y, m, day):
        return date(y, m, min(day, calendar.monthrange(y, m)[1]))

    if prev_month:
        pm = month - 1 or 12
        py = year - 1 if month == 1 else year
        start = clamp(py, pm, start_day)
        # next financial month's start is in calendar month `month`
        next_start = clamp(year, month, start_day)
    else:
        start = clamp(year, month, start_day)
        # next financial month's start is in calendar month `month + 1`
        nm = month % 12 + 1
        ny = year + 1 if month == 12 else year
        next_start = clamp(ny, nm, start_day)

    return start, next_start - timedelta(days=1)


def financial_year_range(year: int, start_day: int, prev_month: bool) -> tuple[date, date]:
    """Return (start, end) for the financial year labelled `year`.

    Runs from financial January's first day to financial December's last day.
    """
    start, _ = financial_month_range(year, 1, start_day, prev_month)
    _, end = financial_month_range(year, 12, start_day, prev_month)
    return start, end


def current_financial_month(start_day: int, prev_month: bool) -> tuple[int, int]:
    """Return the (year, month) label whose financial window contains today."""
    today = date.today()
    # Check a window of ±2 calendar months to find the one containing today
    for delta in (0, 1, -1, 2, -2):
        m = today.month + delta
        y = today.year
        if m < 1:   m += 12; y -= 1
        elif m > 12: m -= 12; y += 1
        start, end = financial_month_range(y, m, start_day, prev_month)
        if start <= today <= end:
            return y, m
    return today.year, today.month
