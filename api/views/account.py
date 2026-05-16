from django.views.decorators.csrf import csrf_exempt

from ..utils import _err, _ok, _parse_body, _require_auth


@csrf_exempt
@_require_auth
def account(request, feuser):
    if request.method == "GET":
        return _ok({
            "email":                      feuser.email,
            "first_name":                 feuser.first_name,
            "last_name":                  feuser.last_name,
            "currency":                   feuser.currency,
            "month_start_day":            feuser.month_start_day,
            "month_start_prev":           feuser.month_start_prev,
            "unspent_allowance_action":   feuser.unspent_allowance_action,
            "allowance_transition_month": feuser.allowance_transition_month,
            "email_notifications":        feuser.email_notifications,
        })

    if request.method == "PATCH":
        data = _parse_body(request)
        if data is None:
            return _err("Invalid JSON body.")
        update_fields = []
        if "first_name" in data:
            v = str(data["first_name"])
            if len(v) > 128:
                return _err("'first_name' must be 128 characters or fewer.")
            feuser.first_name = v
            update_fields.append("first_name")
        if "last_name" in data:
            v = str(data["last_name"])
            if len(v) > 128:
                return _err("'last_name' must be 128 characters or fewer.")
            feuser.last_name = v
            update_fields.append("last_name")
        if "currency" in data:
            v = str(data["currency"])
            if len(v) > 10:
                return _err("'currency' must be 10 characters or fewer.")
            feuser.currency = v
            update_fields.append("currency")
        if "month_start_day" in data:
            try:
                day = int(data["month_start_day"])
                if not 1 <= day <= 31:
                    return _err("'month_start_day' must be 1-31.")
                feuser.month_start_day = day
                update_fields.append("month_start_day")
            except (ValueError, TypeError):
                return _err("'month_start_day' must be an integer.")
        if "month_start_prev" in data:
            feuser.month_start_prev = bool(data["month_start_prev"])
            update_fields.append("month_start_prev")
        if "unspent_allowance_action" in data:
            valid = {"do_nothing", "deposit_savings", "carry_over"}
            val = str(data["unspent_allowance_action"])
            if val not in valid:
                return _err(f"'unspent_allowance_action' must be one of: {', '.join(sorted(valid))}.")
            feuser.unspent_allowance_action = val
            update_fields.append("unspent_allowance_action")
        if "allowance_transition_month" in data:
            feuser.allowance_transition_month = str(data["allowance_transition_month"])[:10]
            update_fields.append("allowance_transition_month")
        if "email_notifications" in data:
            feuser.email_notifications = bool(data["email_notifications"])
            update_fields.append("email_notifications")
        if update_fields:
            feuser.save(update_fields=update_fields)
        return _ok({
            "email":                      feuser.email,
            "first_name":                 feuser.first_name,
            "last_name":                  feuser.last_name,
            "currency":                   feuser.currency,
            "month_start_day":            feuser.month_start_day,
            "month_start_prev":           feuser.month_start_prev,
            "unspent_allowance_action":   feuser.unspent_allowance_action,
            "allowance_transition_month": feuser.allowance_transition_month,
            "email_notifications":        feuser.email_notifications,
        })

    return _err("Method not allowed.", 405)
