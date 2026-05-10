import json

from django.shortcuts import render

from ..decorators import feuser_required
from ._period import _get_month, _get_period_mode, _get_year, _month_nav_context, _year_nav_context


@feuser_required
def dashboard(request):
    feuser = request.feuser
    mode = _get_period_mode(request)

    if mode == 'year':
        year = _get_year(request, feuser.month_start_day, feuser.month_start_prev)
        nav_ctx = _year_nav_context(year, feuser.month_start_day, feuser.month_start_prev)
    else:
        year, month = _get_month(request, feuser.month_start_day, feuser.month_start_prev)
        nav_ctx = _month_nav_context(year, month, feuser.month_start_day, feuser.month_start_prev)

    ctx = {'active_nav': 'dashboard'}
    ctx.update(nav_ctx)
    return render(request, 'budget/dashboard.html', ctx)
