"""Dashboard and card reads/writes shared by the web dashboard, the REST API and the MCP server."""
from .dashboard_cards import CardConfigError, compute_card_data, parse_card_config
from .models import Dashboard, DashboardCard, Expense

TITLE_MAX_LENGTH = 128


class DashboardError(Exception):
    """Invalid dashboard request; `status` is the matching HTTP status."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def period_qs(feuser, start, end, sharing, mode="month"):
    """The expense queryset cards compute from, plus the period_info compute_card_data expects."""
    if sharing == "shared":
        from .views._sharing import build_shared_qs
        qs = build_shared_qs(feuser, start, end)
        value_field = "effective_value"
    else:
        qs = Expense.objects.filter(
            owning_feuser=feuser, date_due__gte=start, date_due__lte=end, deactivated=False, is_dummy=False,
        )
        value_field = "value"
    return qs, {"start": start, "end": end, "mode": mode, "sharing": sharing, "value_field": value_field}


def card_json(card: DashboardCard, qs, feuser, period_info: dict = None) -> dict:
    """A card with its data computed for the period; a broken config comes back as `error`."""
    value_field = (period_info or {}).get("value_field", "value")
    try:
        config = parse_card_config(card.yaml_config)
        data = compute_card_data(config, qs, feuser, period_info=period_info, value_field=value_field)
        error = None
    except CardConfigError as exc:
        config, data, error = {}, {}, str(exc)
    pos = config.get("positioning", {}) if config else {}
    mobile = (pos.get("mobile") or {}) if pos else {}
    return {
        "id":              card.pk,
        "dashboard_id":    card.dashboard_id,
        "yaml_config":     card.yaml_config,
        "position":        pos.get("position", 0),
        "width":           pos.get("width", 2),
        "height":          pos.get("height", 2),
        "mobile_position": mobile.get("position"),
        "mobile_width":    mobile.get("width"),
        "mobile_height":   mobile.get("height"),
        "config":          config,
        "data":            data,
        "error":           error,
    }


def cards_json(feuser, dash, qs, period_info) -> list:
    cards = DashboardCard.objects.filter(owning_feuser=feuser, dashboard=dash)
    return sorted((card_json(c, qs, feuser, period_info) for c in cards), key=lambda c: (c["position"], c["id"]))


def first_dashboard(feuser):
    return Dashboard.objects.filter(owning_feuser=feuser).order_by("sorting", "uid").first()


def resolve_dashboard(feuser, dashboard_id) -> Dashboard:
    """The given dashboard, or the first one when dashboard_id is None. Raises DashboardError."""
    if dashboard_id is None:
        dash = first_dashboard(feuser)
        if dash is None:
            raise DashboardError("No dashboard found", 404)
        return dash
    try:
        return Dashboard.objects.get(pk=int(dashboard_id), owning_feuser=feuser)
    except (Dashboard.DoesNotExist, ValueError, TypeError):
        raise DashboardError("Dashboard not found", 404)


def _clean_yaml(yaml_str) -> str:
    yaml_str = (yaml_str or "").strip()
    if not yaml_str:
        raise DashboardError("yaml_config is required")
    try:
        parse_card_config(yaml_str)
    except CardConfigError as exc:
        raise DashboardError(str(exc))
    return yaml_str


def create_card(feuser, dash, yaml_str) -> DashboardCard:
    return DashboardCard.objects.create(owning_feuser=feuser, dashboard=dash, yaml_config=_clean_yaml(yaml_str))


def update_card(feuser, card, *, yaml_str=None, dashboard_id=None) -> DashboardCard:
    """Replace the card's YAML and/or move it to another of feuser's dashboards."""
    if dashboard_id is not None:
        card.dashboard = resolve_dashboard(feuser, dashboard_id)
    if (yaml_str or "").strip():
        card.yaml_config = _clean_yaml(yaml_str)
    elif dashboard_id is None:
        raise DashboardError("yaml_config is required")
    card.save()
    return card


def _clean_title(title, default=None) -> str:
    title = (title or "").strip() or default
    if not title:
        raise DashboardError("title is required")
    if len(title) > TITLE_MAX_LENGTH:
        raise DashboardError(f"Title too long (max {TITLE_MAX_LENGTH} characters)")
    return title


def create_dashboard(feuser, title) -> Dashboard:
    """New dashboard placed after all existing ones; an empty title becomes "Dashboard"."""
    title = _clean_title(title, default="Dashboard")
    last = Dashboard.objects.filter(owning_feuser=feuser).order_by("-sorting", "-uid").first()
    return Dashboard.objects.create(owning_feuser=feuser, title=title, sorting=(last.sorting + 1) if last else 0)


def rename_dashboard(dash, title) -> Dashboard:
    dash.title = _clean_title(title)
    dash.save(update_fields=["title"])
    return dash


def delete_dashboard(feuser, dash) -> None:
    if Dashboard.objects.filter(owning_feuser=feuser).count() <= 1:
        raise DashboardError("Cannot delete the only dashboard", 409)
    dash.delete()
