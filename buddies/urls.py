from django.urls import path

from . import views

app_name = "buddies"

urlpatterns = [
    path("", views.buddies_page, name="buddies_page"),
    path("my-buddies/", views.my_buddies_page, name="my_buddies"),
    path("summary/", views.buddy_summary_page, name="buddy_summary"),
    path("summary/export/", views.buddy_summary_export, name="buddy_summary_export"),
    path("direct-expenses/partial/", views.direct_expense_list_partial, name="direct_expense_list_partial"),

    # Personal dummy management
    path("add-dummy/", views.add_dummy, name="add_dummy"),
    path("dummy/<int:dummy_id>/kick/", views.kick_dummy, name="kick_dummy"),
    path("dummy/<int:dummy_id>/rename/", views.rename_dummy, name="rename_dummy"),
    path("dummy/<int:dummy_id>/merge/", views.merge_dummy, name="merge_dummy"),
    path("dummy/<int:dummy_id>/archive-wipe/", views.personal_archive_wipe, name="personal_archive_wipe"),
    path("dummy/<int:dummy_id>/picture/", views.dummy_picture, name="dummy_picture"),

    # Actual-user invitations
    path("invite-actual/", views.invite_actual, name="invite_actual"),
    path("buddy/invite/", views.send_buddy_invite, name="buddy_invite"),
    path("invite/<str:token>/", views.view_invite, name="view_invite"),
    path("invite/<str:token>/accept/", views.accept_invite, name="accept_invite"),
    path("invite/<str:token>/decline/", views.decline_invite, name="decline_invite"),
    path("invite/<str:token>/revoke/", views.revoke_invite, name="revoke_invite"),
    path("onboarding-invite/<str:token>/revoke/", views.revoke_onboarding_invite, name="revoke_onboarding_invite"),

    # Actual-buddy kick
    path("link/<int:link_id>/kick/", views.kick_actual, name="kick_actual"),

    # Merge invitations (personal dummy)
    path("merge/<str:token>/", views.view_merge_invite, name="view_merge_invite"),
    path("merge/<str:token>/accept/", views.accept_merge, name="accept_merge"),
    path("merge/<str:token>/decline/", views.decline_merge, name="decline_merge"),
    path("merge/<str:token>/revoke/", views.revoke_merge_invite, name="revoke_merge_invite"),

    # Expense approval
    path("expense/<int:expense_id>/review/", views.review_expense_as_owner, name="review_expense_as_owner"),
    path("expense/<int:expense_id>/approve/", views.approve_expense, name="approve_expense"),
    path("expense/<int:expense_id>/reject/", views.reject_expense, name="reject_expense"),
    path("expense/<int:expense_id>/approve-settlement/", views.approve_settlement_as_creditor, name="approve_settlement_as_creditor"),
    path("expense/<int:expense_id>/reject-settlement/", views.reject_settlement_as_creditor, name="reject_settlement_as_creditor"),
    path("expense/<int:expense_id>/participant-approve/", views.participant_approve, name="participant_approve"),
    path("expense/<int:expense_id>/participant-reject/", views.participant_reject, name="participant_reject"),

    # Catalog Partnership
    path("partnership/invite/", views.send_partnership_invite, name="partnership_invite"),
    path("partnership/accept/<str:token>/", views.onboarding_wizard, name="partnership_onboarding"),
    path("partnership/accept/<str:token>/catalog-state/", views.onboarding_catalog_state, name="partnership_catalog_state"),
    path("partnership/accept/<str:token>/ai-tags/", views.onboarding_ai_suggest_tags, name="partnership_ai_tags"),
    path("partnership/accept/<str:token>/ai-cats/", views.onboarding_ai_suggest_cats, name="partnership_ai_cats"),
    path("partnership/accept/<str:token>/apply/", views.onboarding_apply, name="partnership_apply"),
    path("partnership/accept/<str:token>/decline/", views.onboarding_decline, name="partnership_decline"),
    path("partnership/cancel-invite/<str:token>/", views.cancel_partnership_invite, name="partnership_cancel_invite"),
    path("partnership/kick/<int:feuser_id>/", views.kick_partner, name="partnership_kick"),
    path("partnership/leave/", views.leave_partnership, name="partnership_leave"),

    # Direct settlements
    path("settle/", views.settle_direct, name="settle_direct"),
    path("settle/freeform/", views.settle_direct_freeform, name="settle_direct_freeform"),
    path("settle/<str:buddy_key>/", views.settle_direct_individual, name="settle_direct_individual"),
]
