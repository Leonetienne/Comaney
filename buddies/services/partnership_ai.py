"""
AI-assisted tag and category mapping for partnership onboarding.
Uses the same _call_agent abstraction as express creation.
"""
import json
import logging

_log = logging.getLogger(__name__)

_TAG_MAPPING_SYSTEM = """You are a tag migration assistant for a personal finance app.
The user is joining a Catalog Partnership and needs to map their existing tags to their partner's tags.

Given a list of source tags (the user's) and a list of target tags (the partner's), suggest the best mapping.
Rules:
- Map each source tag to exactly one target tag (N-to-1 is fine: multiple source tags can map to the same target).
- If a source tag has no reasonable semantic match in the target list, map it to null (the user will drop it).
- Prefer exact or near-exact matches first, then semantic equivalents.
- The tags may be in any language; treat them semantically.

Respond with ONLY a JSON object, no prose, no markdown:
{"mappings": [{"source": "...", "target": "..." | null}, ...]}
"""

_CATEGORY_MAPPING_SYSTEM = """You are a category migration assistant for a personal finance app.
The user is joining a Catalog Partnership and needs to map their existing expense categories to their partner's categories.

Given a list of source categories (the user's) and a list of target categories (the partner's), suggest the best mapping.
Rules:
- Map each source category to exactly one target category (N-to-1 is allowed).
- If a source category has no reasonable match, map it to null (it will be dropped).
- Prefer exact or near-exact matches, then semantic equivalents.
- Categories may be in any language; treat them semantically.

Respond with ONLY a JSON object, no prose, no markdown:
{"mappings": [{"source": "...", "target": "..." | null}, ...]}
"""


def suggest_tag_mappings(feuser, master_feuser, source_tags: list[str], target_tags: list[str]) -> list[dict]:
    """
    Return [{source: str, target: str|None}, ...] for unmatched source tags.
    Raises budget.express_service.AIBudgetExceededError if budget is exceeded.
    Raises ValueError on unexpected AI response.
    """
    return _suggest_mappings(feuser, master_feuser, source_tags, target_tags, _TAG_MAPPING_SYSTEM)


def suggest_category_mappings(feuser, master_feuser, source_cats: list[str], target_cats: list[str]) -> list[dict]:
    """Same as suggest_tag_mappings but for categories."""
    return _suggest_mappings(feuser, master_feuser, source_cats, target_cats, _CATEGORY_MAPPING_SYSTEM)


def _build_context_block(feuser, master_feuser) -> str:
    """Build context with both users' custom AI instructions and full catalogs."""
    from budget.models import Tag, Category

    lines = []

    invitee_instructions = (feuser.ai_custom_instructions or "").strip()
    master_instructions = (master_feuser.ai_custom_instructions or "").strip()

    if invitee_instructions or master_instructions:
        lines.append("User context:")
        if invitee_instructions:
            lines.append(f"  Invitee notes: {invitee_instructions}")
        if master_instructions:
            lines.append(f"  Partner notes: {master_instructions}")
        lines.append("")

    invitee_tags = list(Tag.objects.filter(owning_feuser=feuser).values_list("title", flat=True).order_by("title"))
    master_tags = list(Tag.objects.filter(owning_feuser=master_feuser).values_list("title", flat=True).order_by("title"))
    invitee_cats = list(Category.objects.filter(owning_feuser=feuser).values_list("title", flat=True).order_by("title"))
    master_cats = list(Category.objects.filter(owning_feuser=master_feuser).values_list("title", flat=True).order_by("title"))

    lines.append(f"Invitee full tag catalog: {json.dumps(invitee_tags, ensure_ascii=False)}")
    lines.append(f"Partner full tag catalog: {json.dumps(master_tags, ensure_ascii=False)}")
    lines.append(f"Invitee full category catalog: {json.dumps(invitee_cats, ensure_ascii=False)}")
    lines.append(f"Partner full category catalog: {json.dumps(master_cats, ensure_ascii=False)}")

    return "\n".join(lines)


def _suggest_mappings(feuser, master_feuser, sources: list[str], targets: list[str], system_prompt: str) -> list[dict]:
    from budget.express_service import (
        _call_agent, _default_agent_config, _trial_state, AIBudgetExceededError
    )

    _, is_trial, trial_limit, trial_spent, trial_blocked = _trial_state(feuser)
    if trial_blocked:
        raise AIBudgetExceededError("Trial budget exhausted.")

    config = _default_agent_config(feuser)
    if not config.api_key:
        raise AIBudgetExceededError("No AI API key configured.")

    config.max_tokens = 1024

    context_block = _build_context_block(feuser, master_feuser)
    user_message = (
        f"{context_block}\n\n"
        f"Source tags: {json.dumps(sources, ensure_ascii=False)}\n"
        f"Target tags: {json.dumps(targets, ensure_ascii=False)}"
    )
    messages = [{"role": "user", "content": user_message}]

    raw, usage = _call_agent(config, system_prompt, messages)
    _log.debug("partnership_ai raw response: %r", raw)

    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

    try:
        parsed = json.loads(raw)
        mappings = parsed["mappings"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ValueError(f"Unexpected AI response: {raw!r}") from exc

    if is_trial and usage:
        from decimal import Decimal
        feuser.ai_trial_budget_spent = (feuser.ai_trial_budget_spent or Decimal(0)) + Decimal(str(usage["cost_cents"]))
        feuser.save(update_fields=["ai_trial_budget_spent"])

    return mappings
