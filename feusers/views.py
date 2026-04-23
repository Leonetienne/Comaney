from django.shortcuts import render

from .models import FeUser


def hello_world(request):
    feusers = FeUser.objects.all()
    return render(request, "feusers/hello_world.html", {"feusers": feusers})
