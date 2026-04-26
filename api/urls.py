from django.urls import path
from . import views

urlpatterns = [
    path("expenses/",             views.expenses,          name="api_expenses"),
    path("expenses/<str:uid>/",   views.expense_detail,    name="api_expense_detail"),
    path("scheduled/",            views.scheduled,         name="api_scheduled"),
    path("scheduled/<str:uid>/",  views.scheduled_detail,  name="api_scheduled_detail"),
    path("account/",              views.account,           name="api_account"),
    path("dashboard/",            views.dashboard,         name="api_dashboard"),
    path("categories/",           views.categories,        name="api_categories"),
    path("categories/<str:uid>/", views.category_detail,   name="api_category_detail"),
    path("tags/",                 views.tags,              name="api_tags"),
    path("tags/<str:uid>/",       views.tag_detail,        name="api_tag_detail"),
]
