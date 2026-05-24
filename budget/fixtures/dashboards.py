# Declares which dashboard(s) -- and which subset of PREDEFINED_DASHBOARD_CARDS
# (dashboard_cards.py) -- a brand-new user receives.
#
# Keyed by a stable dashboard id; the Dashboard.sorting value assigned on
# creation follows dict iteration order. `cards` is a list of keys into
# PREDEFINED_DASHBOARD_CARDS: not every predefined card has to appear here,
# a card can exist purely as a browsable preset without being given to
# new users by default.

DEFAULT_USER_DASHBOARDS = {
    "main": {
        "title": "Dashboard",
        "cards": [
            "income",
            "savings",
            "paid_expenses",
            "outstanding",
            "left_to_spend",
            "expenses_by_category",
            "expenses_by_tag",
            "bills_due_this_week",
            "left_to_spend_line_chart",
            "expenses_per_day",
        ],
    },
}
