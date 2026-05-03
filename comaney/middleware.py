from django.conf import settings
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.utils import timezone


_LAST_SEEN_THROTTLE_SECONDS = 300


class LastSeenMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        feuser_id = request.session.get("feuser_id")
        if feuser_id:
            now = timezone.now()
            last = request.session.get("_last_seen_ts", 0)
            if (now.timestamp() - last) >= _LAST_SEEN_THROTTLE_SECONDS:
                from feusers.models import FeUser
                FeUser.objects.filter(pk=feuser_id).update(last_seen=now)
                request.session["_last_seen_ts"] = now.timestamp()
        return response


class SystemMisconfiguredMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self.misconfigured = getattr(settings, "SYSTEM_MISCONFIGURED", False)
        self.message = getattr(settings, "SYSTEM_MISCONFIGURED_MSG", "")

    def __call__(self, request):
        if self.misconfigured:
            html = render_to_string("misconfigured.html", {"message": self.message})
            return HttpResponse(html, status=500)
        return self.get_response(request)
