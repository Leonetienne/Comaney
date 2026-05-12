from django.urls import path

from . import views

app_name = "buddies"

urlpatterns = [
    path("", views.buddies_page, name="buddies_page"),

    # Dummy management
    path("add-dummy/", views.add_dummy, name="add_dummy"),
    path("dummy/<int:dummy_id>/kick/", views.kick_dummy, name="kick_dummy"),
    path("dummy/<int:dummy_id>/send-merge/", views.send_merge_invite, name="send_merge_invite"),

    # Actual-user invitations
    path("invite-actual/", views.invite_actual, name="invite_actual"),
    path("invite/<str:token>/", views.view_invite, name="view_invite"),
    path("invite/<str:token>/accept/", views.accept_invite, name="accept_invite"),
    path("invite/<str:token>/decline/", views.decline_invite, name="decline_invite"),
    path("invite/<str:token>/revoke/", views.revoke_invite, name="revoke_invite"),

    # Actual-buddy kick
    path("link/<int:link_id>/kick/", views.kick_actual, name="kick_actual"),

    # Merge invitations
    path("merge/<str:token>/", views.view_merge_invite, name="view_merge_invite"),
    path("merge/<str:token>/accept/", views.accept_merge, name="accept_merge"),
    path("merge/<str:token>/decline/", views.decline_merge, name="decline_merge"),

    # Expense approval
    path("expense/<int:expense_id>/approve/", views.approve_expense, name="approve_expense"),
    path("expense/<int:expense_id>/reject/", views.reject_expense, name="reject_expense"),
]
