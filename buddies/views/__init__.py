from .main import buddies_page, my_buddies_page, buddy_summary_page
from .settlement import (
    settle_direct, settle_direct_individual, settle_direct_freeform,
    group_settle_individual, group_settle_all,
)
from .buddies import (
    add_dummy, kick_dummy, rename_dummy, personal_archive_wipe,
    invite_actual, view_invite, accept_invite, decline_invite, revoke_invite, revoke_onboarding_invite,
    kick_actual,
    send_merge_invite, view_merge_invite, accept_merge, decline_merge,
    dummy_picture,
)
from .groups import (
    create_group, group_rename, group_picture,
    group_invite_member, group_revoke_invite, group_remove_member,
    group_add_dummy, group_rename_dummy, group_send_merge, group_archive_wipe,
    group_transfer_admin, group_leave, group_dissolve,
    view_group_invite, accept_group_invite, decline_group_invite,
)
from .expenses import (
    review_expense_as_owner,
    approve_expense, reject_expense,
    approve_settlement_as_creditor, reject_settlement_as_creditor,
    admin_approve_dummy_settlement, admin_reject_dummy_settlement,
    group_expense_delete, group_expense_unlink,
    participant_approve, participant_reject,
)
from .partnership import (
    send_partnership_invite,
    onboarding_wizard,
    onboarding_catalog_state,
    onboarding_ai_suggest_tags,
    onboarding_ai_suggest_cats,
    onboarding_apply,
    onboarding_decline,
    cancel_partnership_invite,
    kick_partner,
    leave_partnership,
)
# Project views (new namespace)
from .projects import (
    projects_list, create_project, project_detail, project_expense_list_partial, project_settings,
    project_rename, project_picture,
    project_invite_member, project_revoke_invite, project_remove_member,
    project_add_dummy, project_rename_dummy, project_send_merge, project_archive_wipe,
    project_transfer_admin, project_leave, project_delete,
    project_archive, project_unarchive, reorder_projects,
    view_project_invite, accept_project_invite, decline_project_invite,
)
