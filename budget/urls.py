from django.urls import path

from . import views

app_name = "budget"

urlpatterns = [
    # Dashboard pages
    path("", views.dashboard, name="dashboard"),
    path("dash/<int:uid>/", views.dashboard_detail, name="dashboard_detail"),

    # Dashboard CRUD API
    path("dashboards/", views.dashboards_api, name="dashboards_api"),
    path("dashboards/<int:uid>/", views.dashboard_detail_api, name="dashboard_detail_api"),
    path("dashboards/reorder/", views.dashboards_reorder_api, name="dashboards_reorder"),

    # Dashboard card APIs
    path("dashboard/cards/", views.cards_api, name="dashboard_cards"),
    path("dashboard/cards/reorder/", views.cards_reorder_api, name="dashboard_cards_reorder"),
    path("dashboard/cards/presets/", views.card_presets_api, name="dashboard_card_presets"),
    path("dashboard/cards/reset/", views.cards_reset_api, name="dashboard_cards_reset"),
    path("dashboard/cards/ai/", views.card_ai_api, name="dashboard_card_ai"),
    path("dashboard/cards/<int:uid>/", views.card_detail_api, name="dashboard_card_detail"),
    path("dashboard/cards/<int:uid>/resize/", views.card_resize_api, name="dashboard_card_resize"),

    path("categories-tags/", views.categories_tags, name="categories_tags"),
    path("categories/create/", views.category_create, name="category_create"),
    path("categories/<int:uid>/delete/", views.category_delete, name="category_delete"),
    path("categories/<int:uid>/rename/", views.category_rename, name="category_rename"),
    path("tags/create/", views.tag_create, name="tag_create"),
    path("tags/<int:uid>/delete/", views.tag_delete, name="tag_delete"),
    path("tags/<int:uid>/rename/", views.tag_rename, name="tag_rename"),
    path("expenses/", views.expenses_list, name="expenses_list"),
    path("expenses/bulk-action/", views.expense_bulk_action, name="expense_bulk_action"),
    path("expenses/export/", views.expenses_export, name="expenses_export"),
    path("expenses/new/", views.expense_create, name="expense_create"),
    path("expenses/<int:uid>/edit/", views.expense_edit, name="expense_edit"),
    path("expenses/<int:uid>/edit-overlay/", views.expense_edit_overlay, name="expense_edit_overlay"),
    path("expenses/<int:uid>/clone/", views.expense_clone, name="expense_clone"),
    path("expenses/<int:uid>/delete/", views.expense_delete, name="expense_delete"),
    path("expenses/<int:uid>/settle-via-email/", views.expense_settle_via_email, name="expense_settle_via_email"),
    path("expenses/<int:uid>/mute-notifications/", views.expense_mute_notifications, name="expense_mute_notifications"),
    path("notifications/mute-all/", views.mute_all_notifications, name="mute_all_notifications"),
    path("scheduled/", views.scheduled_list, name="scheduled_list"),
    path("scheduled/new/", views.scheduled_create, name="scheduled_create"),
    path("scheduled/<int:uid>/edit/", views.scheduled_edit, name="scheduled_edit"),
    path("scheduled/<int:uid>/clone/", views.scheduled_clone, name="scheduled_clone"),
    path("scheduled/<int:uid>/delete/", views.scheduled_delete, name="scheduled_delete"),
    path("scheduled/<int:uid>/update-expenses/", views.scheduled_update_expenses_api, name="scheduled_update_expenses"),
    path("ai/express-creation/", views.express_creation, name="express_creation"),
]
