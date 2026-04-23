from .models import FeUser


def current_feuser(request):
    feuser_id = request.session.get("feuser_id")
    if not feuser_id:
        return {"current_feuser": None}
    try:
        return {"current_feuser": FeUser.objects.get(pk=feuser_id, is_active=True)}
    except FeUser.DoesNotExist:
        return {"current_feuser": None}
