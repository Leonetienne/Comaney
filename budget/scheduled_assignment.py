"""
Helpers for maintaining expense assignment fields on ScheduledExpense when
buddy relationships, dummies, or projects change.
"""
import json
from decimal import Decimal


def clear_scheduled_assignments(queryset) -> None:
    """Reset all assignment fields to 'none' for the given ScheduledExpense queryset."""
    queryset.update(
        assign_buddy_mode='',
        assign_upfront_type='me',
        assign_upfront_feuser_id=None,
        assign_upfront_dummy_id=None,
        assign_project_id=None,
        assign_spendings_json='[]',
    )


def replace_feuser_with_dummy_in_scheduled(owner_feuser, old_feuser, new_dummy) -> None:
    """
    In owner_feuser's scheduled expenses: replace old_feuser with new_dummy.

    - If old_feuser is the upfront payer: switch to dummy upfront type.
    - If old_feuser appears in assign_spendings_json: replace with dummy entry.

    Called when old_feuser's account is deleted and new_dummy is the ghost
    created in owner_feuser's context.
    """
    from .models import ScheduledExpense

    qs = ScheduledExpense.objects.filter(
        owning_feuser=owner_feuser,
        assign_buddy_mode__in=['single', 'group'],
    )

    for sched in qs.filter(assign_upfront_feuser=old_feuser):
        sched.assign_upfront_feuser = None
        sched.assign_upfront_type = 'dummy'
        sched.assign_upfront_dummy = new_dummy
        sched.save(update_fields=['assign_upfront_feuser', 'assign_upfront_type', 'assign_upfront_dummy'])

    for sched in qs.exclude(assign_upfront_feuser=old_feuser):
        spendings = json.loads(sched.assign_spendings_json or '[]')
        new_spendings = []
        changed = False
        for s in spendings:
            if s.get('type') == 'feuser' and s.get('id') == old_feuser.pk:
                new_spendings.append({
                    'type': 'dummy',
                    'id': new_dummy.uid,
                    'share_percent': s['share_percent'],
                })
                changed = True
            else:
                new_spendings.append(s)
        if changed:
            sched.assign_spendings_json = json.dumps(new_spendings)
            sched.save(update_fields=['assign_spendings_json'])


def replace_dummy_in_scheduled(owner_feuser, old_dummy, new_target) -> None:
    """
    In owner_feuser's scheduled expenses: replace old_dummy with new_target,
    which may be another DummyUser or a FeUser.

    - If old_dummy is the upfront payer: the schedule's upfront type/id switches
      to new_target. Any pre-existing participant entry for new_target on that
      same schedule is removed first (the upfront payer is never also a participant).
    - If old_dummy appears in assign_spendings_json: its share is merged into any
      existing entry for new_target on that schedule, or added as a new entry.

    Called when old_dummy is merged into new_target (another dummy, or a real
    user who accepted a merge request).
    """
    from .models import ScheduledExpense
    from buddies.models import DummyUser

    is_feuser = not isinstance(new_target, DummyUser)
    new_type = 'feuser' if is_feuser else 'dummy'
    new_id = new_target.pk if is_feuser else new_target.uid

    qs = ScheduledExpense.objects.filter(
        owning_feuser=owner_feuser,
        assign_buddy_mode__in=['single', 'group'],
    )

    for sched in qs.filter(assign_upfront_dummy=old_dummy):
        sched.assign_upfront_type = new_type
        sched.assign_upfront_feuser = new_target if is_feuser else None
        sched.assign_upfront_dummy = None if is_feuser else new_target
        spendings = json.loads(sched.assign_spendings_json or '[]')
        filtered = [s for s in spendings if not (s.get('type') == new_type and s.get('id') == new_id)]
        sched.assign_spendings_json = json.dumps(filtered)
        sched.save(update_fields=[
            'assign_upfront_feuser', 'assign_upfront_type', 'assign_upfront_dummy', 'assign_spendings_json',
        ])

    for sched in qs.exclude(assign_upfront_dummy=old_dummy):
        spendings = json.loads(sched.assign_spendings_json or '[]')
        if not any(s.get('type') == 'dummy' and s.get('id') == old_dummy.uid for s in spendings):
            continue
        merged: dict = {}
        order = []
        for s in spendings:
            key = (new_type, new_id) if (s.get('type') == 'dummy' and s.get('id') == old_dummy.uid) \
                else (s.get('type'), s.get('id'))
            if key not in merged:
                merged[key] = 0
                order.append(key)
            merged[key] += s.get('share_percent', 0)
        sched.assign_spendings_json = json.dumps(
            [{'type': k[0], 'id': k[1], 'share_percent': merged[k]} for k in order]
        )
        sched.save(update_fields=['assign_spendings_json'])


def reset_project_assignment_to_equal_shares(project) -> None:
    """
    For all scheduled expenses assigned to project: reset the upfront payer to
    'me' and recalculate assign_spendings_json with all current members at equal
    shares. Called whenever the project roster changes.
    """
    from .models import ScheduledExpense

    members = list(project.members.select_related('feuser', 'dummy').all())
    if not members:
        return

    n = len(members)
    per_share = Decimal('100') / n
    spendings = []
    total = Decimal('0')
    for i, m in enumerate(members):
        if i == n - 1:
            s = float(round(Decimal('100') - total, 4))
        else:
            s = float(round(per_share, 4))
            total += Decimal(str(s))
        if m.feuser_id:
            spendings.append({'type': 'feuser', 'id': m.feuser_id, 'share_percent': s})
        else:
            spendings.append({'type': 'dummy', 'id': m.dummy_id, 'share_percent': s})

    ScheduledExpense.objects.filter(assign_project=project).update(
        assign_upfront_type='me',
        assign_upfront_feuser_id=None,
        assign_upfront_dummy_id=None,
        assign_spendings_json=json.dumps(spendings),
    )
