from feusers import settings_service
from feusers.forms import NotificationPreferencesForm

from ..registry import READ, WRITE, OpError, operation

_NOTIFY = {f: {"type": "boolean"} for f in NotificationPreferencesForm._meta.fields}

SETTINGS_PARAMS = {
    "first_name":               {"type": "string"},
    "last_name":                {"type": "string"},
    "currency":                 {"type": "string", "description": "Shown next to amounts, up to 10 characters."},
    "month_start_day":          {"type": "integer", "description": "Financial month start day 1-31."},
    "month_start_prev":         {"type": "boolean", "description": "Start day lies in the previous calendar month."},
    "unspent_allowance_action": {"type": "string", "enum": ["do_nothing", "deposit_savings"]},
    **_NOTIFY,
    "enable_early_access":      {"type": "boolean"},
    "warn_unclassified_on_save": {"type": "boolean"},
}


@operation(
    "account_get", concern="settings", access=READ, method="GET", path="account/",
    description="The feuser's profile and settings, never any secret.",
)
def account_get(ctx, args):
    return settings_service.read_settings(ctx.feuser)


@operation(
    "account_update", concern="settings", access=WRITE, method="PATCH", path="account/",
    description=(
        "Change profile and settings; only given fields change. email_notifications=false turns every "
        "email off. Email, password, second factors and API keys are not changeable here."
    ),
    params=SETTINGS_PARAMS,
)
def account_update(ctx, args):
    errors = settings_service.update_settings(ctx.feuser, args)
    if errors:
        field, message = next(iter(errors.items()))
        raise OpError(f"'{field}': {message}")
    return settings_service.read_settings(ctx.feuser)
