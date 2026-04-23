from django.urls import path

from . import views

app_name = "budget"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("categories-tags/", views.categories_tags, name="categories_tags"),
    path("categories/create/", views.category_create, name="category_create"),
    path("categories/<int:uid>/delete/", views.category_delete, name="category_delete"),
    path("categories/<int:uid>/rename/", views.category_rename, name="category_rename"),
    path("tags/create/", views.tag_create, name="tag_create"),
    path("tags/<int:uid>/delete/", views.tag_delete, name="tag_delete"),
    path("tags/<int:uid>/rename/", views.tag_rename, name="tag_rename"),
    path("expenses/", views.expenses_list, name="expenses_list"),
    path("expenses/new/", views.expense_create, name="expense_create"),
    path("expenses/<int:uid>/edit/", views.expense_edit, name="expense_edit"),
    path("expenses/<int:uid>/delete/", views.expense_delete, name="expense_delete"),
    path("scheduled/", views.scheduled_list, name="scheduled_list"),
    path("scheduled/new/", views.scheduled_create, name="scheduled_create"),
    path("scheduled/<int:uid>/edit/", views.scheduled_edit, name="scheduled_edit"),
    path("scheduled/<int:uid>/delete/", views.scheduled_delete, name="scheduled_delete"),
    path("ai/smart-create/", views.smart_create, name="smart_create"),
]
