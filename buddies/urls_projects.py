from django.urls import path

from . import views

app_name = "projects"

urlpatterns = [
    # List + create
    path("", views.projects_list, name="projects_list"),
    path("reorder/", views.reorder_projects, name="reorder_projects"),

    # Project detail
    path("<int:project_id>/", views.project_detail, name="project_detail"),
    path("<int:project_id>/expenses/partial/", views.project_expense_list_partial, name="project_expense_list_partial"),
    path("<int:project_id>/settings/", views.project_settings, name="project_settings"),
    path("<int:project_id>/rename/", views.project_rename, name="project_rename"),
    path("<int:project_id>/picture/", views.project_picture, name="project_picture"),
    path("<int:project_id>/archive/", views.project_archive, name="project_archive"),
    path("<int:project_id>/unarchive/", views.project_unarchive, name="project_unarchive"),
    path("<int:project_id>/delete/", views.project_delete, name="project_delete"),
    path("<int:project_id>/leave/", views.project_leave, name="project_leave"),
    path("<int:project_id>/transfer-admin/", views.project_transfer_admin, name="project_transfer_admin"),

    # Member management
    path("<int:project_id>/invite/", views.project_invite_member, name="project_invite_member"),
    path("<int:project_id>/invite/<str:token>/revoke/", views.project_revoke_invite, name="project_revoke_invite"),
    path("<int:project_id>/member/<int:member_id>/remove/", views.project_remove_member, name="project_remove_member"),
    path("<int:project_id>/add-dummy/", views.project_add_dummy, name="project_add_dummy"),
    path("<int:project_id>/dummy/<int:dummy_id>/rename/", views.project_rename_dummy, name="project_rename_dummy"),
    path("<int:project_id>/dummy/<int:dummy_id>/send-merge/", views.project_send_merge, name="project_send_merge"),
    path("<int:project_id>/dummy/<int:dummy_id>/archive-wipe/", views.project_archive_wipe, name="project_archive_wipe"),

    # Project invite accept/decline
    path("project-invite/<str:token>/", views.view_project_invite, name="view_project_invite"),
    path("project-invite/<str:token>/accept/", views.accept_project_invite, name="accept_project_invite"),
    path("project-invite/<str:token>/decline/", views.decline_project_invite, name="decline_project_invite"),

    # Expense actions (group_settle_individual, group_settle_all still in buddies namespace)
    path("<int:group_id>/settle-individual/", views.group_settle_individual, name="group_settle_individual"),
    path("<int:group_id>/settle-all/", views.group_settle_all, name="group_settle_all"),
    path("<int:group_id>/expense/<int:expense_id>/approve-dummy/", views.admin_approve_dummy_settlement, name="admin_approve_dummy_settlement"),
    path("<int:group_id>/expense/<int:expense_id>/reject-dummy/", views.admin_reject_dummy_settlement, name="admin_reject_dummy_settlement"),
    path("<int:group_id>/expense/<int:expense_id>/delete/", views.group_expense_delete, name="group_expense_delete"),
    path("<int:group_id>/expense/<int:expense_id>/unlink/", views.group_expense_unlink, name="group_expense_unlink"),
]
