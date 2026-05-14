"""
Creates a test dataset for the group settlement feature: three users (Anna, Ben, Clara),
a buddy group "Camping Weekend", two offline dummies (Dog, Ranger Rick), and a realistic
collection of camping expenses split various ways.

Credentials:  anna@test.local / 1234
              ben@test.local  / 1234
              clara@test.local / 1234

Run: python manage.py test_create_camping_dataset
Tear down: python manage.py test_delete_camping_dataset
"""

from datetime import date
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from budget.expense_factory import create_expense
from budget.fixtures import create_defaults
from budget.models import Category, TransactionType
from buddies.models import BuddyGroup, BuddyGroupMember, BuddyLink, DummyUser
from feusers.models import FeUser

TEST_EMAILS = ["anna@test.local", "ben@test.local", "clara@test.local"]
GROUP_NAME = "Camping Weekend"

EXPENSE = TransactionType.EXPENSE


def _cat(feuser, name):
    return Category.objects.filter(owning_feuser=feuser, title=name).first()


def _link(a, b):
    lo, hi = sorted([a, b], key=lambda u: u.pk)
    BuddyLink.objects.get_or_create(user_a=lo, user_b=hi)


def _fu(feuser):
    return {"type": "feuser", "id": feuser.pk}


def _du(dummy):
    return {"type": "dummy", "id": dummy.pk}


def _s(participant_dict, pct):
    return {**participant_dict, "share_percent": Decimal(str(pct))}


class Command(BaseCommand):
    help = "Create test dataset: three users, a buddy group, dummies, and camping expenses."

    def handle(self, *args, **options):
        for email in TEST_EMAILS:
            if FeUser.objects.filter(email=email).exists():
                raise CommandError(
                    f"User '{email}' already exists. "
                    "Run test_delete_camping_dataset first."
                )

        with transaction.atomic():
            self._run()

        self.stdout.write(self.style.SUCCESS(
            "Camping dataset created.\n"
            "  anna@test.local / 1234\n"
            "  ben@test.local  / 1234\n"
            "  clara@test.local / 1234\n"
            f"  Group: {GROUP_NAME}"
        ))

    def _run(self):
        # --- users ---
        anna = self._make_user("anna@test.local", "Anna", "Zeller")
        ben = self._make_user("ben@test.local", "Ben", "Hartmann")
        clara = self._make_user("clara@test.local", "Clara", "Meier")

        # buddy links so they can see each other's shared expenses outside the group
        _link(anna, ben)
        _link(anna, clara)
        _link(ben, clara)

        # --- group ---
        group = BuddyGroup.objects.create(name=GROUP_NAME, admin_feuser=anna)
        BuddyGroupMember.objects.create(group=group, feuser=anna)
        BuddyGroupMember.objects.create(group=group, feuser=ben)
        BuddyGroupMember.objects.create(group=group, feuser=clara)

        # --- offline dummies ---
        dog = DummyUser.objects.create(owning_group=group, display_name="Dog")
        BuddyGroupMember.objects.create(group=group, dummy=dog)

        ranger = DummyUser.objects.create(owning_group=group, display_name="Ranger Rick")
        BuddyGroupMember.objects.create(group=group, dummy=ranger)

        day1 = date(2025, 8, 1)
        day2 = date(2025, 8, 2)
        day3 = date(2025, 8, 3)

        # Anna paid campsite fee: split equally among all 5
        create_expense(
            owning_feuser=anna,
            title="Campsite fee",
            type=EXPENSE,
            value=Decimal("125.00"),
            payee="Waldcamping Sonnental",
            category=_cat(anna, "Travel & Holidays"),
            date_due=day1,
            buddy_approved=True,
            buddy_group=group,
            buddy_spendings=[
                _s(_fu(ben),   20),
                _s(_fu(clara), 20),
                _s(_du(dog),   20),
                _s(_du(ranger),20),
            ],
        )

        # Ben paid firewood: split between Anna, Ben, Clara (Ben owns, Anna+Clara participate)
        create_expense(
            owning_feuser=ben,
            title="Firewood (2 bundles)",
            type=EXPENSE,
            value=Decimal("18.00"),
            payee="Campsite shop",
            category=_cat(ben, "Miscellaneous"),
            date_due=day1,
            buddy_approved=True,
            buddy_group=group,
            buddy_spendings=[
                _s(_fu(anna),  "33.333"),
                _s(_fu(clara), "33.334"),
            ],
        )

        # Clara paid groceries: split among the three real users
        create_expense(
            owning_feuser=clara,
            title="Groceries — day 1",
            type=EXPENSE,
            value=Decimal("67.40"),
            payee="Edeka",
            category=_cat(clara, "Groceries"),
            date_due=day1,
            buddy_approved=True,
            buddy_group=group,
            buddy_spendings=[
                _s(_fu(anna), "33.333"),
                _s(_fu(ben),  "33.334"),
            ],
        )

        # Ranger Rick paid for ice bags (dummy upfront payer): split among all 5
        create_expense(
            owning_feuser=anna,
            title="Ice bags",
            type=EXPENSE,
            value=Decimal("9.50"),
            payee="Petrol station",
            category=_cat(anna, "Groceries"),
            date_due=day1,
            is_dummy=True,
            upfront_payee_dummy=ranger,
            buddy_approved=True,
            buddy_group=group,
            buddy_spendings=[
                _s(_fu(anna),  20),
                _s(_fu(ben),   20),
                _s(_fu(clara), 20),
                _s(_du(dog),   20),
            ],
        )

        # Anna paid breakfast supplies: split among all 5
        create_expense(
            owning_feuser=anna,
            title="Breakfast supplies",
            type=EXPENSE,
            value=Decimal("34.80"),
            payee="Farmer's market",
            category=_cat(anna, "Groceries"),
            date_due=day2,
            buddy_approved=True,
            buddy_group=group,
            buddy_spendings=[
                _s(_fu(ben),   20),
                _s(_fu(clara), 20),
                _s(_du(dog),   20),
                _s(_du(ranger),20),
            ],
        )

        # Ben paid kayak rental: split between Anna, Ben, Clara
        create_expense(
            owning_feuser=ben,
            title="Kayak rental (3 h)",
            type=EXPENSE,
            value=Decimal("54.00"),
            payee="Seecamp Verleih",
            category=_cat(ben, "Entertainment"),
            date_due=day2,
            buddy_approved=True,
            buddy_group=group,
            buddy_spendings=[
                _s(_fu(anna),  "33.333"),
                _s(_fu(clara), "33.334"),
            ],
        )

        # Dog bought sausages (dummy upfront payer): split between Ben and Clara
        create_expense(
            owning_feuser=anna,
            title="Sausages & buns",
            type=EXPENSE,
            value=Decimal("21.60"),
            payee="Metzgerei Huber",
            category=_cat(anna, "Groceries"),
            date_due=day2,
            is_dummy=True,
            upfront_payee_dummy=dog,
            buddy_approved=True,
            buddy_group=group,
            buddy_spendings=[
                _s(_fu(ben),   50),
                _s(_fu(clara), 50),
            ],
        )

        # Clara paid bar tab evening 2: split among the three real users
        create_expense(
            owning_feuser=clara,
            title="Bar tab — evening 2",
            type=EXPENSE,
            value=Decimal("43.00"),
            payee="Waldhütte",
            category=_cat(clara, "Dining & Bars"),
            date_due=day2,
            buddy_approved=True,
            buddy_group=group,
            buddy_spendings=[
                _s(_fu(anna), "33.333"),
                _s(_fu(ben),  "33.334"),
            ],
        )

        # Anna paid petrol home: split among the three real users
        create_expense(
            owning_feuser=anna,
            title="Petrol home",
            type=EXPENSE,
            value=Decimal("48.60"),
            payee="Shell Autobahn",
            category=_cat(anna, "Transport"),
            date_due=day3,
            buddy_approved=True,
            buddy_group=group,
            buddy_spendings=[
                _s(_fu(ben),   "33.333"),
                _s(_fu(clara), "33.334"),
            ],
        )

        # One pending settlement: Ben paying Anna back (awaiting Anna's approval)
        create_expense(
            owning_feuser=ben,
            title="Settlement: Ben -> Anna",
            type=EXPENSE,
            value=Decimal("30.00"),
            date_due=day3,
            buddy_approved=False,
            buddy_group=group,
            buddy_spendings=[
                _s(_fu(anna), 100),
            ],
        )

    @staticmethod
    def _make_user(email, first, last):
        user = FeUser(
            email=email,
            first_name=first,
            last_name=last,
            is_active=True,
            is_confirmed=True,
        )
        user.set_password("1234")
        user.generate_api_key()
        user.save()
        create_defaults(user)
        return user
