from django.shortcuts import redirect, render

from ..models import FeUser


def demo_banner_view(request):
    feuser_id = request.session.get("feuser_id")
    if not feuser_id:
        return redirect("login")
    try:
        feuser = FeUser.objects.get(pk=feuser_id, is_active=True)
    except FeUser.DoesNotExist:
        return redirect("login")
    if not feuser.is_demo:
        return redirect("budget:dashboard")

    if request.method == "POST" and request.POST.get("action") == "accept":
        request.session["demo_banner_accepted"] = True
        return redirect("budget:dashboard")

    return render(request, "feusers/demo_banner.html")
