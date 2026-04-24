# Default categories and tags created for every new user on account activation.
# Edit freely — order doesn't matter, duplicates are ignored.

DEFAULT_CATEGORIES = [
    "Housing",
    "Groceries",
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
    "Ax-deductible",
]


def create_defaults(feuser) -> None:
    from .models import Category, Tag

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
