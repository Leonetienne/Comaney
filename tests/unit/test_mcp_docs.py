"""
mcp_server/docs.py: the user manual as agent-readable pages.
Run with: venv/bin/pytest tests/unit/test_mcp_docs.py -v
"""
from mcp_server import docs


def test_every_manual_page_is_listed_with_a_title():
    pages = docs.pages()
    assert len(pages) == len(list(docs.USER_MANUAL.rglob("*.md")))
    assert all(p.title and not p.title.endswith(".md") for p in pages)


def test_urls_follow_the_docs_site():
    assert docs.find("index.md").url("https://x.test/") == "https://x.test/docs/user-manual/"
    assert docs.find("contacts/index.md").url("https://x.test") == "https://x.test/docs/user-manual/contacts/"
    assert docs.find("expenses.md").url("https://x.test") == "https://x.test/docs/user-manual/expenses/"


def test_find_accepts_resource_uris():
    assert docs.find(docs.URI_PREFIX + "expenses.md").path == "expenses.md"
    assert docs.find("../AGENTS.md") is None


def test_search_ranks_matching_pages_with_snippets():
    hits = docs.search("settle up contact")
    assert "contacts/settling-up.md" in [p.path for p, _ in hits[:3]]
    assert all(snippet for _, snippet in hits)


def test_search_without_words_finds_nothing():
    assert docs.search("  ?! ") == []
