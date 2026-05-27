from django.db import migrations, models

from budget.date_utils import current_financial_month


def backfill_last_run_and_occurrence_date(apps, schema_editor):
    """Deploy-safety backfill for the scheduled-expense materialization rewrite.

    Without this, every existing ScheduledExpense.last_run is NULL, and the
    first post-deploy cron tick would treat every non-deactivated schedule as
    "never run this year" and regenerate + re-notify for all of them at once.
    Backfilling last_run to the current financial year reflects that these
    schedules have already effectively run under the old cron-driven system.

    scheduled_occurrence_date is backfilled from date_due for existing
    generated expenses. This assumes date_due still reflects the original
    occurrence, which is true unless the row was hand-edited before this
    migration ran - a one-time, best-effort backfill for rows that were
    already ambiguously identified before this feature existed.
    """
    ScheduledExpense = apps.get_model('budget', 'ScheduledExpense')
    Expense = apps.get_model('budget', 'Expense')

    for scheduled in ScheduledExpense.objects.filter(deactivated=False).select_related('owning_feuser'):
        feuser = scheduled.owning_feuser
        year, _ = current_financial_month(feuser.month_start_day, feuser.month_start_prev)
        scheduled.last_run = year
        scheduled.save(update_fields=['last_run'])

    Expense.objects.filter(
        source_scheduled__isnull=False,
        scheduled_occurrence_date__isnull=True,
    ).update(scheduled_occurrence_date=models.F('date_due'))


class Migration(migrations.Migration):

    dependencies = [
        ('budget', '0029_expense_scheduled_occurrence_date_and_more'),
    ]

    operations = [
        migrations.RunPython(backfill_last_run_and_occurrence_date, migrations.RunPython.noop),
    ]
