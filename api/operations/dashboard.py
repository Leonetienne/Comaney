from decimal import Decimal

from budget import dashboard_service
from budget.dashboard_service import DashboardError
from budget.models import Dashboard, DashboardCard, Expense

from .common import ID, PERIOD_PARAMS, SHARING, resolve_period
from ..registry import READ, WRITE, NotFound, OpError, operation

_YAML = {"type": "string", "description": "Card YAML; read cards_reference for the schema."}


def _service(fn):
    try:
        return fn()
    except DashboardError as exc:
        raise OpError(str(exc), exc.status)


def _dashboard_json(dash):
    return {"id": dash.pk, "title": dash.title, "sorting": dash.sorting}


def _get_dashboard(feuser, uid):
    dash = Dashboard.objects.filter(pk=uid, owning_feuser=feuser).first()
    if dash is None:
        raise NotFound("Dashboard not found.")
    return dash


def _get_card(feuser, uid):
    card = DashboardCard.objects.filter(pk=uid, owning_feuser=feuser).first()
    if card is None:
        raise NotFound("Card not found.")
    return card


def _period(feuser, args):
    start, end = resolve_period(feuser, args)
    mode = "year" if args.get("view") == "year" else "month"
    return dashboard_service.period_qs(feuser, start, end, args.get("sharing", ""), mode)


@operation(
    "dashboard_summary", concern="dashboard", access=READ, method="GET", path="dashboard/",
    description=(
        "Income, paid and outstanding expenses, savings and resulting balance of one financial month "
        "(default current), own expenses only."
    ),
    params={"year": PERIOD_PARAMS["year"], "month": PERIOD_PARAMS["month"]},
)
def dashboard_summary(ctx, args):
    feuser = ctx.feuser
    start, end = resolve_period(feuser, {k: v for k, v in args.items() if k in ("year", "month")})
    qs = Expense.objects.filter(owning_feuser=feuser, date_due__gte=start, date_due__lte=end, deactivated=False)

    def total(**filters):
        return sum((e.value for e in qs.filter(**filters)), Decimal("0.00"))

    income = total(type="income")
    paid = total(type="expense", settled=True)
    outstanding = total(type="expense", settled=False)
    sav_dep = total(type="savings_dep")
    sav_wit = total(type="savings_wit")
    return {
        "month_range":          {"start": start.isoformat(), "end": end.isoformat()},
        "currency":             feuser.currency,
        "income":               str(income),
        "expenses_paid":        str(paid),
        "expenses_outstanding": str(outstanding),
        "savings_deposited":    str(sav_dep),
        "savings_withdrawn":    str(sav_wit),
        "balance":              str(income - paid - outstanding - (sav_dep - sav_wit)),
    }


@operation(
    "dashboards_list", concern="dashboard", access=READ, method="GET", path="dashboards/",
    description="The feuser's dashboards in display order.",
)
def dashboards_list(ctx, args):
    return {"dashboards": [_dashboard_json(d) for d in Dashboard.objects.filter(owning_feuser=ctx.feuser).order_by("sorting", "uid")]}


@operation(
    "dashboards_create", concern="dashboard", access=WRITE, method="POST", path="dashboards/",
    description="Add an empty dashboard after the existing ones.",
    params={"title": {"type": "string"}}, status=201,
)
def dashboards_create(ctx, args):
    return _dashboard_json(_service(lambda: dashboard_service.create_dashboard(ctx.feuser, args.get("title", ""))))


@operation(
    "dashboards_update", concern="dashboard", access=WRITE, method="PATCH", path="dashboards/<int:id>/",
    description="Rename a dashboard.", params={"id": ID, "title": {"type": "string"}}, required=["id", "title"],
)
def dashboards_update(ctx, args):
    dash = _get_dashboard(ctx.feuser, args["id"])
    return _dashboard_json(_service(lambda: dashboard_service.rename_dashboard(dash, args["title"])))


@operation(
    "dashboards_delete", concern="dashboard", access=WRITE, method="DELETE", path="dashboards/<int:id>/",
    description="Delete a dashboard with its cards. The last dashboard cannot be deleted.",
    params={"id": ID}, required=["id"], destructive=True, status=204,
)
def dashboards_delete(ctx, args):
    dash = _get_dashboard(ctx.feuser, args["id"])
    _service(lambda: dashboard_service.delete_dashboard(ctx.feuser, dash))
    return None


@operation(
    "cards_list", concern="dashboard", access=READ, method="GET", path="cards/",
    description="A dashboard's cards (default: first dashboard) with their data computed for a period.",
    params={"dashboard_id": ID, **PERIOD_PARAMS, "sharing": SHARING},
)
def cards_list(ctx, args):
    dash = _service(lambda: dashboard_service.resolve_dashboard(ctx.feuser, args.get("dashboard_id")))
    qs, info = _period(ctx.feuser, args)
    return {"dashboard_id": dash.pk, "cards": dashboard_service.cards_json(ctx.feuser, dash, qs, info)}


@operation(
    "cards_reference", concern="dashboard", access=READ, method="GET", path="cards/reference/",
    description="The documentation of the card YAML schema and the query language. Read it before writing a card.",
)
def cards_reference(ctx, args):
    from budget.dashboard_card_ai import build_docs_reference
    return {"reference": build_docs_reference()}


@operation(
    "cards_create", concern="dashboard", access=WRITE, method="POST", path="cards/",
    description="Add a card to a dashboard (default: first dashboard). Placement comes from the YAML positioning block.",
    params={"dashboard_id": ID, "yaml_config": _YAML}, required=["yaml_config"], status=201,
)
def cards_create(ctx, args):
    feuser = ctx.feuser
    dash = _service(lambda: dashboard_service.resolve_dashboard(feuser, args.get("dashboard_id")))
    card = _service(lambda: dashboard_service.create_card(feuser, dash, args["yaml_config"]))
    qs, info = _period(feuser, {})
    return dashboard_service.card_json(card, qs, feuser, info)


@operation(
    "cards_update", concern="dashboard", access=WRITE, method="PATCH", path="cards/<int:id>/",
    description="Replace a card's YAML and/or move it to another dashboard.",
    params={"id": ID, "yaml_config": _YAML, "dashboard_id": ID}, required=["id"],
)
def cards_update(ctx, args):
    feuser = ctx.feuser
    card = _get_card(feuser, args["id"])
    _service(lambda: dashboard_service.update_card(
        feuser, card, yaml_str=args.get("yaml_config"), dashboard_id=args.get("dashboard_id"),
    ))
    qs, info = _period(feuser, {})
    return dashboard_service.card_json(card, qs, feuser, info)


@operation(
    "cards_delete", concern="dashboard", access=WRITE, method="DELETE", path="cards/<int:id>/",
    description="Delete a card.", params={"id": ID}, required=["id"], destructive=True, status=204,
)
def cards_delete(ctx, args):
    _get_card(ctx.feuser, args["id"]).delete()
    return None
