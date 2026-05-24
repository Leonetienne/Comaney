import json

from django.shortcuts import redirect, render, get_object_or_404

from ..decorators import feuser_required
from ..models import Dashboard
from ._period import _get_month, _get_period_mode, _get_year, _month_nav_context, _year_nav_context
from ._sharing import has_buddy_or_multiuser_project


def _first_dashboard(feuser):
    return (
        Dashboard.objects.filter(owning_feuser=feuser)
        .order_by('sorting', 'uid')
        .first()
    )


def _dashboard_list_json(feuser):
    dashes = list(Dashboard.objects.filter(owning_feuser=feuser))
    return [
        {'id': d.pk, 'title': d.title, 'sorting': d.sorting, 'url': f'/budget/dash/{d.pk}/'}
        for d in dashes
    ]


@feuser_required
def dashboard(request):
    """Redirect to the user's first dashboard, preserving query params."""
    feuser = request.feuser
    first = _first_dashboard(feuser)
    if first is None:
        # create_defaults was not yet called; create one now
        from ..fixtures import create_defaults
        create_defaults(feuser)
        first = _first_dashboard(feuser)
    qs = request.GET.urlencode()
    target = f'/budget/dash/{first.pk}/'
    if qs:
        target += '?' + qs
    return redirect(target)


@feuser_required
def dashboard_detail(request, uid: int):
    feuser = request.feuser
    dash = get_object_or_404(Dashboard, pk=uid, owning_feuser=feuser)

    mode = _get_period_mode(request)
    if mode == 'year':
        year = _get_year(request, feuser.month_start_day, feuser.month_start_prev)
        nav_ctx = _year_nav_context(year, feuser.month_start_day, feuser.month_start_prev)
    else:
        year, month = _get_month(request, feuser.month_start_day, feuser.month_start_prev)
        nav_ctx = _month_nav_context(year, month, feuser.month_start_day, feuser.month_start_prev)

    first = _first_dashboard(feuser)
    is_first = (first is not None and first.pk == dash.pk)

    dashboards_json = json.dumps(_dashboard_list_json(feuser))

    ctx = {
        'active_nav': 'dashboard',
        'nav_show_sharing_toggle': has_buddy_or_multiuser_project(feuser),
        'current_dashboard': dash,
        'is_first_dashboard': is_first,
        'dashboards_json': dashboards_json,
    }
    ctx.update(nav_ctx)
    return render(request, 'budget/dashboard.html', ctx)
