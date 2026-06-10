"""
AI-assisted tag and category mapping for partnership onboarding.
Uses the same call_ai_for_json abstraction as express creation and dashboard card AI.
"""
import json

_TAG_MAPPING_SYSTEM = """You are a tag migration assistant for a personal finance app.
The user is joining a Catalog Partnership and needs to map their existing tags to their partner's tags.

Given a list of source tags (the user's) and a list of target tags (the partner's), suggest the best mapping.
Rules:
- Map each source tag to exactly one target tag (N-to-1 is fine: multiple source tags can map to the same target).
- If a source tag has no reasonable semantic match in the target list, map it to null (the user will drop it).
- Prefer exact or near-exact matches first, then semantic equivalents.
- The tags may be in any language; treat them semantically.

Your ENTIRE reply, from the very first character to the very last, must be exactly this JSON object and nothing else: no prose, no markdown, no code fences, no leading text, no trailing note or summary after the closing brace. The first character of your reply MUST be "{" and the last character MUST be "}".
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

Your ENTIRE reply, from the very first character to the very last, must be exactly this JSON object and nothing else: no prose, no markdown, no code fences, no leading text, no trailing note or summary after the closing brace. The first character of your reply MUST be "{" and the last character MUST be "}".
{"mappings": [{"source": "...", "target": "..." | null}, ...]}
"""


def suggest_tag_mappings(feuser, master_feuser, source_tags: list[str], target_tags: list[str]) -> list[dict]:
    """
    Return [{source: str, target: str|None}, ...] for unmatched source tags.
    Raises budget.express_service.AIBudgetExceededError if budget is exceeded.
    Raises budget.express_service.AIInvalidResponseError on unexpected AI response.
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
        AIBudgetExceededError, AIInvalidResponseError, _default_agent_config,
        _trial_state, call_ai_for_json, record_ai_usage,
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

    try:
        parsed, usage, raw = call_ai_for_json(config, system_prompt, messages, feature="partnership_ai")
        mappings = parsed["mappings"]
    except AIInvalidResponseError as exc:
        # A repair fallback may have been attempted (see call_ai_for_json) and
        # still ultimately failed -- bill whatever it cost before propagating
        # (a no-op when .usage is unset, i.e. every other raise site here).
        record_ai_usage(feuser, is_trial, exc.usage)
        raise
    except (KeyError, TypeError) as exc:
        raise AIInvalidResponseError(raw) from exc

    record_ai_usage(feuser, is_trial, usage)
    return mappings
