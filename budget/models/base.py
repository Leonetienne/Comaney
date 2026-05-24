from django.db import models


class TransactionType(models.TextChoices):
    INCOME = "income", "Income"
    EXPENSE = "expense", "Expense"
    SAVINGS_DEPOSIT = "savings_dep", "Savings Deposit"
    SAVINGS_WITHDRAWAL = "savings_wit", "Savings Withdrawal"
    CARRY_OVER = "carry_over", "Carry-Over"


class RepeatUnit(models.TextChoices):
    DAYS = "days", "Days"
    WEEKS = "weeks", "Weeks"
    MONTHS = "months", "Months"
    YEARS = "years", "Years"


class OwnedModel(models.Model):
    uid = models.BigAutoField(primary_key=True)
    owning_feuser = models.ForeignKey("feusers.FeUser", on_delete=models.CASCADE, related_name="+")

    class Meta:
        abstract = True
