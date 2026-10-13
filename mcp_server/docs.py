"""The user manual as agent-readable pages: list, search and read. Django-free."""
import re
from dataclasses import dataclass
from pathlib import Path

USER_MANUAL = Path(__file__).resolve().parent.parent / "docs" / "src" / "docs" / "user-manual"
URI_PREFIX = "comaney://docs/user-manual/"
_WORD = re.compile(r"\w{2,}", re.UNICODE)


@dataclass(frozen=True)
class Page:
    path: str  # relative to the user manual, e.g. "contacts/settling-up.md"
    title: str
    text: str

    @property
    def uri(self) -> str:
        return URI_PREFIX + self.path

    def url(self, site_url: str) -> str:
        slug = self.path[:-3]
        slug = slug[:-5] if slug == "index" or slug.endswith("/index") else slug + "/"
        return f"{site_url.rstrip('/')}/docs/user-manual/{slug}"


def _title(text: str, path: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return path


def pages(root: Path = USER_MANUAL) -> list[Page]:
    out = []
    for file in sorted(root.rglob("*.md")):
        rel = file.relative_to(root).as_posix()
        text = file.read_text(encoding="utf-8")
        out.append(Page(rel, _title(text, rel), text))
    return out


def find(path: str, root: Path = USER_MANUAL) -> Page | None:
    path = path.removeprefix(URI_PREFIX).lstrip("/")
    return next((p for p in pages(root) if p.path == path), None)


def _snippet(text: str, terms: list[str], width: int = 220) -> str:
    lower = text.lower()
    hits = [lower.find(t) for t in terms if lower.find(t) >= 0]
    start = max(0, min(hits) - width // 3) if hits else 0
    return " ".join(text[start:start + width].split())


def search(query: str, root: Path = USER_MANUAL, limit: int = 8) -> list[tuple[Page, str]]:
    """Pages ranked by how often the query's words occur, title hits counting most."""
    terms = [t.lower() for t in _WORD.findall(query)]
    if not terms:
        return []
    scored = []
    for page in pages(root):
        title, body = page.title.lower(), page.text.lower()
        score = sum(5 * title.count(t) + body.count(t) for t in terms)
        matched = sum(1 for t in terms if t in body or t in title)
        if score:
            scored.append((matched, score, page))
    scored.sort(key=lambda s: (-s[0], -s[1], s[2].path))
    return [(page, _snippet(page.text, terms)) for _m, _s, page in scored[:limit]]
