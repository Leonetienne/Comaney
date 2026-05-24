"""
AI-assisted dashboard card creation and editing.
Uses the same _call_agent abstraction as express creation and partnership AI.

The system prompt is split into two cached blocks:
  1. Static instructions + the full dashboard user-manual docs, identical for
     every call -- cached so repeated requests (even across users sharing the
     trial key) don't re-pay for ~1.5k lines of schema documentation.
  2. The calling user's catalog, their other cards on this dashboard, and (for
     edits) the card being modified -- dynamic, but still cached per-user so
     repeated generate clicks in the same session are cheap too.
"""
import json
import logging
from functools import lru_cache
from pathlib import Path

_log = logging.getLogger(__name__)

_DOCS_ROOT = Path(__file__).resolve().parent.parent / "docs" / "src" / "docs" / "user-manual" / "dashboard"
_DOCS_BASE_URL = "https://comaney.app/docs/user-manual/dashboard"

# (path under _DOCS_ROOT, URL slug under _DOCS_BASE_URL -- "" for the root page itself)
_DOC_FILES = [
    ("index.md", ""),
    ("cards/index.md", "cards"),
    ("cards/cell.md", "cards/cell"),
    ("cards/bar-chart.md", "cards/bar-chart"),
    ("cards/pie-chart.md", "cards/pie-chart"),
    ("cards/list.md", "cards/list"),
    ("cards/line-chart.md", "cards/line-chart"),
    ("cards/gauge.md", "cards/gauge"),
    ("cards/spacer.md", "cards/spacer"),
    ("query-language.md", "query-language"),
]


@lru_cache(maxsize=1)
def _build_docs_reference() -> str:
    """Concatenate the dashboard user-manual pages so the AI has the full card schema."""
    parts = []
    for rel_path, slug in _DOC_FILES:
        content = (_DOCS_ROOT / rel_path).read_text(encoding="utf-8")
        url = f"{_DOCS_BASE_URL}/{slug}/" if slug else f"{_DOCS_BASE_URL}/"
        parts.append(f"--- {url} ---\n{content}")
    return "\n\n".join(parts)


_SYSTEM_INSTRUCTIONS = """You are a dashboard-card design assistant for a budgeting app called Comaney.
Dashboard cards are configured as a single YAML document, validated against a strict schema.
The full user-facing documentation for that schema (https://comaney.app/docs/user-manual/dashboard/ and every child page) is included below in this message -- read it carefully, it is the only source of truth for which fields exist and what they mean. Do not invent fields that are not documented there.

Your job is to write ONE card's YAML configuration based on the user's request.

Response format -- your entire response must be one of these two JSON objects, no prose, no markdown, no code fences, never produce any output that's not json!:

Success:
{"result": "good", "yaml": "type: cell\\ntitle: ...\\n..."}

Failure (use ONLY when the request has nothing to do with a dashboard card, or is impossible to satisfy with the documented schema. Never ask clarifying questions, make a reasonable choice instead. Make the msg sound cute-ish and friendly, maybe a bit insecure, with cute emoticons such as >.< >_< <_< >_> ^_^ ^.^ ^^ :3 :>, but NEVER actual emojis. Keep it short, it is shown as a small error message.):
{"result": "fail", "msg": "ahh - i don't know how to turn that into a card >.<"}

Rules:
- The "yaml" value must be a single valid YAML document as a JSON string (use \\n for line breaks), parseable on its own -- it will be parsed and strictly validated against the schema documented below. Quote any string value that YAML would otherwise misinterpret (colons, leading numbers/symbols, etc).
- Always include a `positioning` block. Look at the other cards already on this dashboard (listed below) and pick a `position` that comes after all of them, and a `width`/`height` that looks reasonable next to them. Don't overlap or duplicate an existing card.
- Use the `query` field (same syntax as the expense search bar, documented in query-language.md below) together with the user's actual categories, tags and projects (listed below) to scope the card correctly. Never invent a category, tag or project that isn't listed.
- Prefer the simplest card type that satisfies the request.
- Match the visual style (colors, templates) of the user's other cards where it makes sense, but only use fields that are documented below.

Dashboard documentation:
"""


def _build_catalog_block(feuser) -> str:
    from buddies.models import Project

    from .models import Category, Tag

    categories = list(
        Category.objects.filter(owning_feuser=feuser).values_list("title", flat=True).order_by("title")
    )
    tags = list(
        Tag.objects.filter(owning_feuser=feuser).values_list("title", flat=True).order_by("title")
    )
    projects = list(
        Project.objects.filter(members__feuser=feuser, archived=False)
        .distinct().values_list("name", flat=True).order_by("name")
    )
    parts = [
        f"User's categories: {json.dumps(categories, ensure_ascii=False)}",
        f"User's tags: {json.dumps(tags, ensure_ascii=False)}",
    ]
    if projects:
        parts.append(f"User's projects: {json.dumps(projects, ensure_ascii=False)}")
    return "\n".join(parts)


def _build_other_cards_block(feuser, dashboard, exclude_card_id=None) -> str:
    from .models import DashboardCard

    qs = DashboardCard.objects.filter(owning_feuser=feuser, dashboard=dashboard)
    if exclude_card_id is not None:
        qs = qs.exclude(pk=exclude_card_id)
    cards = list(qs.order_by("pk"))
    if not cards:
        return "This dashboard has no other cards yet."
    blocks = [f"--- card {i + 1} ---\n{c.yaml_config}" for i, c in enumerate(cards)]
    return "Other cards already on this dashboard:\n" + "\n".join(blocks)


def _parse_response(raw: str):
    """Parse the {"result": "good"/"fail", ...} envelope. Returns the yaml string on success."""
    from .express_service import AIInvalidResponseError, AIRefusalError

    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

    if not raw.startswith('{"result":'):
        idx = raw.find('{"result":')
        if idx == -1:
            idx = raw.find('{ "result":')
        if idx != -1:
            raw = raw[idx:]

    if not raw:
        raise AIInvalidResponseError(raw)

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AIInvalidResponseError(raw, exc) from exc

    if not isinstance(parsed, dict):
        raise AIInvalidResponseError(raw)

    if parsed.get("result") == "fail":
        raise AIRefusalError(parsed.get("msg", ""), raw)
    if parsed.get("result") != "good":
        raise AIInvalidResponseError(raw)

    yaml_str = parsed.get("yaml")
    if not isinstance(yaml_str, str) or not yaml_str.strip():
        raise AIInvalidResponseError(raw)

    return yaml_str


def generate_card_yaml(
    feuser,
    dashboard,
    description: str,
    current_yaml: str | None = None,
    exclude_card_id: int | None = None,
) -> str:
    """
    Generate (or, if current_yaml is given, modify) a single dashboard card's YAML
    from a natural-language description. Returns a schema-validated YAML string.

    Raises budget.express_service.AIBudgetExceededError/AIRefusalError/AIInvalidResponseError,
    or budget.dashboard_cards.CardConfigError if the AI's output doesn't pass validation.
    """
    from .dashboard_cards import parse_card_config
    from .express_service import AIBudgetExceededError, _call_agent, _default_agent_config, _trial_state

    api_key, is_trial, trial_limit, trial_spent, trial_blocked = _trial_state(feuser)
    if trial_blocked:
        raise AIBudgetExceededError("Trial budget exhausted.")

    config = _default_agent_config(feuser)
    if not config.api_key:
        raise AIBudgetExceededError("No AI API key configured.")

    context_parts = [
        _build_catalog_block(feuser),
        _build_other_cards_block(feuser, dashboard, exclude_card_id=exclude_card_id),
    ]
    if current_yaml:
        context_parts.append(f"The card to modify (its current YAML):\n{current_yaml}")
    custom = (feuser.ai_custom_instructions or "").strip()
    if custom:
        context_parts.append(f"User's custom instructions: {custom}")

    system_blocks = [
        {
            "type": "text",
            "text": _SYSTEM_INSTRUCTIONS + "\n" + _build_docs_reference(),
            "cache_control": {"type": "ephemeral"},
        },
        {
            "type": "text",
            "text": "\n\n".join(context_parts),
            "cache_control": {"type": "ephemeral"},
        },
    ]
    messages = [{"role": "user", "content": description}]

    raw, usage = _call_agent(config, system_blocks, messages)
    _log.debug("dashboard_card_ai raw response: %r", raw)

    yaml_str = _parse_response(raw)
    parse_card_config(yaml_str)  # raises CardConfigError if invalid; propagated to the caller

    if is_trial and usage:
        from decimal import Decimal

        feuser.ai_trial_budget_spent = (feuser.ai_trial_budget_spent or Decimal(0)) + Decimal(str(usage["cost_cents"]))
        feuser.save(update_fields=["ai_trial_budget_spent"])

    return yaml_str
