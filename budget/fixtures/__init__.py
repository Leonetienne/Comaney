# Default starter data created for every new user on account activation.
#
# One module per data model:
#     categories.py        DEFAULT_CATEGORIES
#     tags.py               DEFAULT_TAGS
#     dashboard_cards.py    PREDEFINED_DASHBOARD_CARDS -- full preset catalog
#     dashboards.py         DEFAULT_USER_DASHBOARDS -- which dashboards (and
#                            which subset of the catalog) new users actually get
#
# create_defaults(feuser) wires them together; it's the only entry point
# other modules should import from this package.

from .categories import DEFAULT_CATEGORIES
from .dashboard_cards import PREDEFINED_DASHBOARD_CARDS
from .dashboards import DEFAULT_USER_DASHBOARDS
from .tags import DEFAULT_TAGS

__all__ = [
    "DEFAULT_CATEGORIES",
    "DEFAULT_TAGS",
    "PREDEFINED_DASHBOARD_CARDS",
    "DEFAULT_USER_DASHBOARDS",
    "create_defaults",
]


def create_defaults(feuser) -> None:
    from ..models import Category, Dashboard, DashboardCard, Tag

    existing_cats = set(Category.objects.filter(owning_feuser=feuser).values_list("title", flat=True))
    Category.objects.bulk_create([
        Category(owning_feuser=feuser, title=t)
        for t in DEFAULT_CATEGORIES
        if t not in existing_cats
    ])

    existing_tags = set(Tag.objects.filter(owning_feuser=feuser).values_list("title", flat=True))
    Tag.objects.bulk_create([
        Tag(owning_feuser=feuser, title=t)
        for t in DEFAULT_TAGS
        if t not in existing_tags
    ])

    if not DashboardCard.objects.filter(owning_feuser=feuser).exists():
        for sorting, dash_def in enumerate(DEFAULT_USER_DASHBOARDS.values()):
            dashboard, _ = Dashboard.objects.get_or_create(
                owning_feuser=feuser,
                sorting=sorting,
                defaults={"title": dash_def["title"]},
            )
            DashboardCard.objects.bulk_create([
                DashboardCard(
                    owning_feuser=feuser,
                    dashboard=dashboard,
                    yaml_config=PREDEFINED_DASHBOARD_CARDS[card_key]["yaml"],
                )
                for card_key in dash_def["cards"]
            ])
