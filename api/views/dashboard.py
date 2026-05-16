from decimal import Decimal

from django.views.decorators.csrf import csrf_exempt

from budget.date_utils import financial_month_range
from budget.models import Expense
from ..utils import _err, _ok, _parse_month, _require_auth


@csrf_exempt
@_require_auth
def dashboard(request, feuser):
    if request.method != "GET":
        return _err("Method not allowed.", 405)

    year, month = _parse_month(request, feuser)
    start, end = financial_month_range(year, month, feuser.month_start_day, feuser.month_start_prev)

    qs = Expense.objects.filter(owning_feuser=feuser, date_due__gte=start, date_due__lte=end, deactivated=False)

    def _sum(fqs):
        return sum(e.value for e in fqs) or Decimal("0.00")

    income      = _sum(qs.filter(type="income"))
    paid        = _sum(qs.filter(type="expense", settled=True))
    outstanding = _sum(qs.filter(type="expense", settled=False))
    sav_dep     = _sum(qs.filter(type="savings_dep"))
    sav_wit     = _sum(qs.filter(type="savings_wit"))

    return _ok({
        "year":                 year,
        "month":                month,
        "month_range":          {"start": start.isoformat(), "end": end.isoformat()},
        "currency":             feuser.currency,
        "income":               str(income),
        "expenses_paid":        str(paid),
        "expenses_outstanding": str(outstanding),
        "savings_deposited":    str(sav_dep),
        "savings_withdrawn":    str(sav_wit),
        "balance":              str(income - paid - outstanding - (sav_dep - sav_wit)),
    })
