# Default categories and tags created for every new user on account activation.
# Edit freely — order doesn't matter, duplicates are ignored.

DEFAULT_CATEGORIES = [
    "Housing",
    "Groceries",
    "Snacks",
    "Dining & Bars",
    "Transport",
    "Health & Pharmacy",
    "Fitness & Sports",
    "Shopping & Clothing",
    "Electronics",
    "Entertainment",
    "Travel & Holidays",
    "Education",
    "Subscriptions",
    "Insurance",
    "Personal Care",
    "Gifts & Donations",
    "Miscellaneous",
]

DEFAULT_TAGS = [
    "Essential",
    "Recurring",
    "One-time",
    "Work",
    "Family",
    "Fun",
    "Online",
    "Cash",
    "Reimbursable",
    "Tax-deductible",
]


DEFAULT_DASHBOARD_CARDS = [
    {
        "yaml": (
            "# Shows the sum of all income entries in the selected period.\n"
            "type: cell\n"
            "title: Income\n"
            "query: type=income\n"
            "method: sum\n"
            "color: '#1a3326'\n"
            "positioning:\n"
            "  position: 1\n"
            "  width: 2\n"
            "  height: 1\n"
        ),
    },
    {
        "yaml": (
            "# Shows the sum of all settled (paid) expenses in the selected period.\n"
            "type: cell\n"
            "title: Paid expenses\n"
            "query: type=expense settled=yes\n"
            "method: sum\n"
            "color: '#331a1d'\n"
            "positioning:\n"
            "  position: 2\n"
            "  width: 2\n"
            "  height: 1\n"
        ),
    },
    {
        "yaml": (
            "# Shows the sum of all unsettled (unpaid) expenses in the selected period.\n"
            "type: cell\n"
            "title: Outstanding\n"
            "query: type=expense settled=no\n"
            "method: sum\n"
            "color: '#2b1a1c'\n"
            "positioning:\n"
            "  position: 3\n"
            "  width: 2\n"
            "  height: 1\n"
        ),
    },
    {
        "yaml": (
            "# Shows net savings: deposits minus withdrawals in the selected period.\n"
            "type: cell\n"
            "title: Savings\n"
            "method: custom\n"
            "color: '#0d2a4a'\n"
            "python: |\n"
            "  return query_sum('type=\"savings deposit\"') - query_sum('type=\"savings withdrawal\"')\n"
            "positioning:\n"
            "  position: 4\n"
            "  width: 2\n"
            "  height: 1\n"
        ),
    },
    {
        "yaml": (
            "# Shows disposable budget: income minus expenses and net savings.\n"
            "type: cell\n"
            "title: Left to spend\n"
            "method: custom\n"
            "color: '#1a3326'\n"
            "python: |\n"
            "  return (\n"
            "    query_sum('type=\"income\"')\n"
            "    - query_sum('type=\"expense\"')\n"
            "    - (query_sum('type=\"savings deposit\"') + query_sum('type=\"savings withdrawal\"'))\n"
            "  )\n"
            "positioning:\n"
            "  position: 5\n"
            "  width: 4\n"
            "  height: 1\n"
        ),
    },
    {
        "yaml": (
            "# Pie chart breaking down expenses by category in the selected period.\n"
            "type: pie-chart\n"
            "title: Expenses by category\n"
            "group: categories\n"
            "positioning:\n"
            "  position: 6\n"
            "  width: 6\n"
            "  height: 4\n"
        ),
    },
    {
        "yaml": (
            "# Horizontal bar chart showing the top 10 tags by total expense amount.\n"
            "type: bar-chart\n"
            "title: Expenses by tag\n"
            "group: tags\n"
            "max_groups: 10\n"
            "positioning:\n"
            "  position: 7\n"
            "  width: 6\n"
            "  height: 4\n"
        ),
    },
]


def create_defaults(feuser) -> None:
    from .models import Category, DashboardCard, Tag

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
        DashboardCard.objects.bulk_create([
            DashboardCard(owning_feuser=feuser, yaml_config=entry["yaml"])
            for entry in DEFAULT_DASHBOARD_CARDS
        ])
