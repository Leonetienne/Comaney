from functools import wraps

from django.conf import settings
from django.shortcuts import redirect

from feusers.models import FeUser


def feuser_required(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        feuser_id = request.session.get("feuser_id")
        if not feuser_id:
            return redirect("login")
        try:
            request.feuser = FeUser.objects.get(pk=feuser_id, is_active=True)
        except FeUser.DoesNotExist:
            return redirect("login")
        if request.feuser.is_demo and not settings.ENABLE_DEMO_USERS:
            request.session.flush()
            return redirect("login")
        if request.feuser.is_demo and not request.session.get("demo_banner_accepted"):
            return redirect("demo_banner")
        return view_func(request, *args, **kwargs)
    return wrapper
