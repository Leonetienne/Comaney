# Ordered list of (path_prefix, doc_url).
# More specific prefixes must come before broader ones.
HELP_PATH_MAP = [
    ("/budget/ai/express-creation/", "/docs/user-manual/ai-express-creation/"),
    ("/budget/categories-tags/",     "/docs/user-manual/categories-tags/"),
    ("/budget/unclassified/",        "/docs/user-manual/unclassified-expenses/"),
    ("/budget/scheduled/",           "/docs/user-manual/scheduled-expenses/"),
    ("/budget/sankey/",              "/docs/user-manual/sankey-studio/"),
    ("/budget/expenses/",            "/docs/user-manual/expenses/"),
    ("/budget/dash/",                "/docs/user-manual/dashboard/"),
    ("/budget/",                     "/docs/user-manual/dashboard/"),
    ("/projects/",                   "/docs/user-manual/projects/"),
    ("/buddies/",                    "/docs/user-manual/buddies/"),
    ("/notifications/",              "/docs/user-manual/notifications/"),
    ("/totp/",                       "/docs/user-manual/two-factor-auth/"),
    ("/webauthn/",                   "/docs/user-manual/two-factor-auth/"),
    ("/email-2fa/",                  "/docs/user-manual/two-factor-auth/"),
    ("/yubikey/",                    "/docs/user-manual/two-factor-auth/"),
    ("/twofa/",                      "/docs/user-manual/two-factor-auth/"),
    ("/api-key/",                    "/docs/user-manual/api-access/"),
    ("/account/export/",             "/docs/user-manual/data-export/"),
    ("/profile/",                    "/docs/user-manual/account-settings/"),
]


def get_help_fab(path):
    for prefix, url in HELP_PATH_MAP:
        if path.startswith(prefix):
            return url
    return None
