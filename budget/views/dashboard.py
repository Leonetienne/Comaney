import json
from decimal import Decimal

from django.db.models import Sum
from django.shortcuts import render

from ..date_utils import financial_month_range, financial_year_range
from ..decorators import feuser_required
from ..models import Expense
from ._period import _get_month, _get_period_mode, _get_year, _month_nav_context, _year_nav_context


@feuser_required
def dashboard(request):
    feuser = request.feuser
    mode = _get_period_mode(request)

    if mode == "year":
        year = _get_year(request, feuser.month_start_day, feuser.month_start_prev)
        start, end = financial_year_range(year, feuser.month_start_day, feuser.month_start_prev)
        nav_ctx = _year_nav_context(year, feuser.month_start_day, feuser.month_start_prev)
    else:
        year, month = _get_month(request, feuser.month_start_day, feuser.month_start_prev)
        start, end = financial_month_range(year, month, feuser.month_start_day, feuser.month_start_prev)
        nav_ctx = _month_nav_context(year, month, feuser.month_start_day, feuser.month_start_prev)

    period_qs = Expense.objects.filter(
        owning_feuser=feuser,
        date_due__gte=start,
        date_due__lte=end,
        deactivated=False,
    )

    def _sum(qs):
        return qs.aggregate(t=Sum("value"))["t"] or Decimal("0")

    income      = _sum(period_qs.filter(type="income"))
    carry_over  = _sum(period_qs.filter(type="carry_over"))
    paid        = _sum(period_qs.filter(type="expense", settled=True))
    outstanding = _sum(period_qs.filter(type="expense", settled=False))
    sav_dep     = _sum(period_qs.filter(type="savings_dep"))
    sav_wit     = _sum(period_qs.filter(type="savings_wit"))
    savings     = sav_dep - sav_wit
    left        = income + carry_over - paid - outstanding - savings

    expense_qs = period_qs.filter(type="expense")

    cat_rows = list(
        expense_qs.values("category__title")
        .annotate(total=Sum("value"))
        .order_by("-total")
    )
    for r in cat_rows:
        if r["category__title"] is None:
            r["category__title"] = "Uncategorized"

    tag_rows = list(
        expense_qs.filter(tags__isnull=False)
        .values("tags__title")
        .annotate(total=Sum("value"))
        .order_by("-total")
    )

    ctx = {
        "active_nav": "dashboard",
        "income": income,
        "paid": paid,
        "outstanding": outstanding,
        "savings": savings,
        "left": left,
        "cat_labels": json.dumps([r["category__title"] for r in cat_rows]),
        "cat_values": json.dumps([float(r["total"]) for r in cat_rows]),
        "tag_labels": json.dumps([r["tags__title"] for r in tag_rows]),
        "tag_values": json.dumps([float(r["total"]) for r in tag_rows]),
    }
    ctx.update(nav_ctx)
    return render(request, "budget/dashboard.html", ctx)
