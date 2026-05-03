from django.conf import settings
from django.http import HttpResponse
from django.template.loader import render_to_string


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
