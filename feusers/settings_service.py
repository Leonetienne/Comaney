"""Account settings writes shared by the REST API and the MCP server, validated by the profile forms."""
from django.forms.models import model_to_dict
from django.utils import timezone

from .forms import EarlyAccessSettingsForm, ExpenseEntrySettingsForm, NotificationPreferencesForm, ProfileForm

SETTINGS_FORMS = (ProfileForm, NotificationPreferencesForm, EarlyAccessSettingsForm, ExpenseEntrySettingsForm)

# what the profile page lets a demo user change
DEMO_FIELDS = {"currency", "month_start_day", "month_start_prev", "unspent_allowance_action"}

READ_ONLY_FIELDS = ("email", "allowance_transition_month")


def settings_fields() -> list[str]:
    return [f for form in SETTINGS_FORMS for f in form._meta.fields]


def read_settings(feuser) -> dict:
    data = {f: getattr(feuser, f) for f in READ_ONLY_FIELDS}
    data.update({f: getattr(feuser, f) for f in settings_fields()})
    return data


def update_settings(feuser, changes: dict) -> dict:
    """
    Apply the given settings through the same forms the profile page uses.
    Returns {field: message} for every rejected field; nothing is saved then.
    """
    known = set(settings_fields())
    errors = {f: "Unknown or read-only setting." for f in changes if f not in known}
    if feuser.is_demo:
        errors.update({f: "Demo accounts cannot change this setting." for f in changes if f in known - DEMO_FIELDS})
    if errors:
        return errors

    forms = []
    for form_class in SETTINGS_FORMS:
        fields = form_class._meta.fields
        if not any(f in changes for f in fields):
            continue
        data = model_to_dict(feuser, fields=fields)
        data.update({f: changes[f] for f in fields if f in changes})
        # an unchecked checkbox posts nothing, so False must be absent
        data = {k: v for k, v in data.items() if v is not False and v is not None}
        form = form_class(data, instance=feuser)
        if not form.is_valid():
            errors.update({f: " ".join(msgs) for f, msgs in form.errors.items()})
        forms.append(form)
    if errors:
        return errors
    for form in forms:
        form.save()
    feuser.last_mod = timezone.now()
    feuser.save(update_fields=["last_mod"])
    return {}
