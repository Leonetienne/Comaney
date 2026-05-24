import json

from django.shortcuts import redirect, render, get_object_or_404

from ..decorators import feuser_required
from ..models import Dashboard
from ._period import _date_range_presets_context
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

    first = _first_dashboard(feuser)
    is_first = (first is not None and first.pk == dash.pk)

    dashboards_json = json.dumps(_dashboard_list_json(feuser))

    ctx = {
        'active_nav': 'dashboard',
        'nav_show_sharing_toggle': has_buddy_or_multiuser_project(feuser),
        'current_dashboard': dash,
        'is_first_dashboard': is_first,
        'dashboards_json': dashboards_json,
        'initial_date_from': request.GET.get('date_from', ''),
        'initial_date_to':   request.GET.get('date_to', ''),
    }
    ctx.update(_date_range_presets_context(feuser))
    return render(request, 'budget/dashboard.html', ctx)
