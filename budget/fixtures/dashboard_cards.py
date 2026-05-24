# Full catalog of predefined dashboard cards.
#
# This is the complete set offered as presets in the "new card" dialog
# (see budget/dashboard_cards.py:_build_presets). It is a superset of what
# any new user actually gets on signup -- see DEFAULT_USER_DASHBOARDS in
# dashboards.py for which of these keys are auto-assigned to a default
# dashboard. A card can exist here purely as a preset, browsable in the
# dialog, without ever being created for new users automatically.

PREDEFINED_DASHBOARD_CARDS = {
    "income": {
        "yaml": (
            "# Shows the sum of all income entries in the selected period.\n"
            "type: cell\n"
            "title: Income\n"
            "query: type=income\n"
            "method: sum\n"
            "color: '#1a3326e0'\n"
            "color_lightmode: '#bbf7d0e0'\n"
            "link: /budget/expenses/?search=type%3Dincome\n"
            "positioning:\n"
            "  position: 1\n"
            "  width: 2\n"
            "  height: 1\n"
            "  mobile:\n"
            "    position: 1\n"
            "    width: 3\n"
            "    height: 1\n"
        ),
    },
    "savings": {
        "yaml": (
            "# Shows net savings: deposits minus withdrawals in the selected period.\n"
            "type: cell\n"
            "title: Savings\n"
            "method: total\n"
            "query: 'query: type=\"Savings deposit\" || type=\"Savings withdrawal\"'\n"
            "color: '#0d2a4ae0'\n"
            "color_lightmode: '#bfdbfee0'\n"
            "link: /budget/expenses/?search=type%3D%22savings+deposit%22+%7C%7C+type%3D%22savings+withdrawal%22\n"
            "positioning:\n"
            "  position: 2\n"
            "  width: 2\n"
            "  height: 1\n"
            "  mobile:\n"
            "    position: 3\n"
            "    width: 3\n"
            "    height: 1\n"
        ),
    },
    "paid_expenses": {
        "yaml": (
            "# Shows the sum of all settled (paid) expenses in the selected period.\n"
            "type: cell\n"
            "title: Paid expenses\n"
            "query: type=expense settled=yes\n"
            "method: sum\n"
            "color: '#331a1de0'\n"
            "color_lightmode: '#fecacae0'\n"
            "link: /budget/expenses/?search=type%3Dexpense+settled%3Dyes\n"
            "positioning:\n"
            "  position: 3\n"
            "  width: 2\n"
            "  height: 1\n"
            "  mobile:\n"
            "    position: 2\n"
            "    width: 3\n"
            "    height: 1\n"
        ),
    },
    "outstanding": {
        "yaml": (
            "# Shows the sum of all unsettled (unpaid) expenses in the selected period.\n"
            "type: cell\n"
            "title: Outstanding\n"
            "query: type=expense settled=no\n"
            "method: sum\n"
            "color: '#2b1a1c'\n"
            "color_lightmode: '#fed7aa'\n"
            "link: /budget/expenses/?search=type%3Dexpense+settled%3Dno\n"
            "positioning:\n"
            "  position: 4\n"
            "  width: 2\n"
            "  height: 1\n"
            "  mobile:\n"
            "    position: 4\n"
            "    width: 3\n"
            "    height: 1\n"
        ),
    },
    "left_to_spend": {
        "yaml": (
            "# Shows disposable budget: income minus expenses and net savings.\n"
            "type: cell\n"
            "title: Left to spend\n"
            "method: total\n"
            "flip_signs: true\n"
            "color: '#1a3326e0'\n"
            "color_lightmode: '#a7f3d0e0'\n"
            "color_breakpoints:\n"
            "  - less_than: 100\n"
            "    color: '#3b2e00e0'\n"
            "    color_lightmode: '#fef08ae0'\n"
            "  - less_than: 10\n"
            "    color: '#3b0a0ae0'\n"
            "    color_lightmode: '#fecacae0'\n"
            "positioning:\n"
            "  position: 5\n"
            "  width: 4\n"
            "  height: 1\n"
            "  mobile:\n"
            "    position: 5\n"
            "    width: 6\n"
            "    height: 1\n"
        ),
    },
    "expenses_by_category": {
        "yaml": (
            "# Pie chart breaking down expenses by category in the selected period.\n"
            "type: pie-chart\n"
            "title: Expenses by category\n"
            "group: categories\n"
            "method: total\n"
            "query: type=expense\n"
            "link_template: /budget/expenses/?search=type%3Dexpense+cat%3D\"$GROUP_NAME\"\n"
            "positioning:\n"
            "  position: 6\n"
            "  width: 6\n"
            "  height: 4\n"
            "  mobile:\n"
            "    position: 6\n"
        ),
    },
    "expenses_by_tag": {
        "yaml": (
            "# Horizontal bar chart showing the top 10 tags by total expense amount.\n"
            "type: bar-chart\n"
            "title: Expenses by tag\n"
            "query: type=expense\n"
            "method: total\n"
            "group: tags\n"
            "max_groups: 10\n"
            "link_template: /budget/expenses/?search=type%3Dexpense+tag%3D\"$GROUP_NAME\"\n"
            "positioning:\n"
            "  position: 7\n"
            "  width: 6\n"
            "  height: 4\n"
            "  mobile:\n"
            "    position: 7\n"
        ),
    },
    "bills_due_this_week": {
        "yaml": (
            "# Lists unsettled expenses that are due this week\n"
            "title: Bills due this week\n"
            "type: list\n"
            "method: sum\n"
            "query: type=expense settled=no date >= cur_week_start date <= cur_week_end\n"
            "show_sum: true\n"
            "order_by: value\n"
            "order_dir: desc\n"
            "positioning:\n"
            "  height: 3\n"
            "  position: 10\n"
            "  width: 4\n"
            "  mobile:\n"
            "    height: 3\n"
            "    position: 10\n"
            "    width: 6\n"
        ),
    },
    "left_to_spend_line_chart": {
        "yaml": (
            "type: line-chart\n"
            "title: Left to spend\n"
            "method: cum\n"
            "series:\n"
            "- color: '#2887f3'\n"
            "  flip_signs: true\n"
            "  label: Left to spend\n"
            "  link_template: /budget/expenses/?search=date>=$START_DATE+date<=$END_DATE\n"
            "  method: total\n"
            "positioning:\n"
            "  height: 3\n"
            "  mobile:\n"
            "    height: 3\n"
            "    position: 9\n"
            "    width: 6\n"
            "  position: 9\n"
            "  width: 4\n"
        ),
    },
    "expenses_per_day": {
        "yaml": (
            "type: line-chart\n"
            "title: Expenses per day\n"
            "method: base\n"
            "series:\n"
            "- color: '#c45'\n"
            "  label: Money spent\n"
            "  link_template: /budget/expenses/?search=type%3Dexpense+date>=$START_DATE+date<=$END_DATE\n"
            "  method: total\n"
            "  query: type=expense\n"
            "positioning:\n"
            "  height: 3\n"
            "  mobile:\n"
            "    height: 3\n"
            "    position: 9\n"
            "    width: 6\n"
            "  position: 9\n"
            "  width: 4\n"
        ),
    },
    # Catalog-only example: not part of DEFAULT_USER_DASHBOARDS, so it shows up
    # as a preset in the "new card" dialog without being given to new users.
    # Shows how much of all income was spent, with a dynamic (income-based) max
    # and color_breakpoints inverted so the gauge gets redder the more is spent.
    "income_spent_gauge": {
        "yaml": (
            "color_breakpoints:\n"
            "- color: '#ffc800'\n"
            "  color_lightmode: '#ffc800'\n"
            "  less_than: 100\n"
            "- color: '#57a87e'\n"
            "  color_lightmode: '#57a87e'\n"
            "  less_than: 10\n"
            "gauge_color: '#da2525'\n"
            "gauge_color_lightmode: '#da2525'\n"
            "link: /budget/expenses/\n"
            "max_value_method: sum\n"
            "max_value_query: type=income | type=savings\n"
            "method: sum\n"
            "positioning:\n"
            "  height: 2\n"
            "  mobile:\n"
            "    height: 2\n"
            "    position: 11\n"
            "    width: 6\n"
            "  position: 11\n"
            "  width: 3\n"
            "query: type=expense\n"
            "show_percent: true\n"
            "show_raw_values: true\n"
            "title: Income spent\n"
            "type: gauge\n"
        ),
    },
}
