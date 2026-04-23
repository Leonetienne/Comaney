from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path("admin/", admin.site.urls),
    path("budget/", include("budget.urls")),
    path("", include("feusers.urls")),
]
