from django.db import migrations
from django.db.models import Q


def clear_invalid_buddy_assignment(apps, schema_editor):
    """Buddy/project assignment only makes sense for type=expense (income/savings
    would invert who owes whom in the debt graph). Drop the assignment - rather
    than the record itself - from any existing row that violates this."""
    Expense = apps.get_model('budget', 'Expense')
    ScheduledExpense = apps.get_model('budget', 'ScheduledExpense')
    BuddySpending = apps.get_model('buddies', 'BuddySpending')

    bad_expense_ids = list(
        Expense.objects.exclude(type='expense')
        .filter(Q(project__isnull=False) | Q(is_dummy=True) | Q(buddy_spendings__isnull=False))
        .values_list('uid', flat=True)
        .distinct()
    )
    BuddySpending.objects.filter(expense_id__in=bad_expense_ids).delete()
    Expense.objects.filter(uid__in=bad_expense_ids).update(
        project=None, is_dummy=False, upfront_payee_dummy=None, buddy_approved=True,
    )

    ScheduledExpense.objects.exclude(type='expense').exclude(assign_buddy_mode='').update(
        assign_buddy_mode='',
        assign_upfront_type='me',
        assign_upfront_feuser=None,
        assign_upfront_dummy=None,
        assign_project=None,
        assign_spendings_json='[]',
    )


class Migration(migrations.Migration):

    dependencies = [
        ('budget', '0027_alter_expense_type_alter_scheduledexpense_type'),
        ('buddies', '0015_remove_buddyonboardinginvite_dummy'),
    ]

    operations = [
        migrations.RunPython(clear_invalid_buddy_assignment, migrations.RunPython.noop),
    ]
