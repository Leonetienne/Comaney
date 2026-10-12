"""
Single entry point for every AI feature in the app: express expense creation,
dashboard card AI assist, partnership tag/category mapping, and Unclassified
Expenses AI-solve. Nothing outside this file talks to the AI provider or
hand-parses an AI JSON response -- it all goes through one AIService instance:

    service  = AIService(feuser)                     # raises AIBudgetExceededError up front if blocked/no access
    items    = service.prompt_express_expense_gen(system_prompt, description, image_b64=..., image_type=...)
    yaml     = service.prompt_dashboard_card_yaml(system_prompt, description)
    mapping  = service.prompt_partnership_mapping(system_prompt, user_message)
    solution = service.prompt_unclassified_solve(system_prompt)

AIService owns HOW to talk to the AI safely and is provider-neutral: it builds
an ai_providers.AIRequest and hands it to the active provider
(ai_providers.get_provider(), picked by AI_PROVIDER), which owns everything
vendor-specific (SDK, model, prices, mapping vendor errors to the typed
errors in ai_providers.errors). AIService owns JSON-response recovery (one
repair retry), envelope parsing, own-credentials/shared-access resolution,
budget billing, and the side effects of a failing shared access (disabling
the shared trial access and notifying the admin -- see budget.ai_trial). It
deliberately knows nothing about categories, tags, projects, or dashboard
cards: each feature module (budget.express_service, budget.dashboard_card_ai,
buddies.services.partnership_ai, budget.unclassified_ai) owns assembling its
own system prompt text and interpreting the returned payload for saving.
Mixing that business logic in here would just trade "AI plumbing scattered
across files" for "four unrelated features' business rules crammed into one
file" -- the same mess in a different shape.
"""
from __future__ import annotations

import json
import logging
from decimal import Decimal

from django.conf import settings

from ai_providers import get_provider
from ai_providers.base import AIRequest, ImageInput, SystemPart
from feusers.ai_user_config import has_own_access, own_entry

# Errors live in ai_providers/errors.py (providers raise them too); re-exported
# here so `from budget.ai_service import AIError, ...` keeps working.
from ai_providers.errors import (  # noqa: F401
    AIAuthenticationError,
    AIBillingError,
    AIBudgetExceededError,
    AIError,
    AIInvalidResponseError,
    AIRefusalError,
    AITransientError,
    AIVisionUnsupportedError,
)

_log = logging.getLogger(__name__)

_INVALID_SHARED_KEY_MESSAGE = (
    "The server is misconfigured: the trial API key is invalid. "
    "Please contact the server administrator."
)


# ---------------------------------------------------------------------------
# Usage / JSON helpers -- implementation details of _call*
# ---------------------------------------------------------------------------

def _merge_usage(*usages: dict) -> dict:
    """Combine usage dicts from a primary call + its JSON-repair retry into one.
    Provider-neutral: every numeric key any of them reports is summed."""
    keys = sorted({k for u in usages for k, v in u.items() if isinstance(v, (int, float))})
    merged = {k: sum(u.get(k, 0) for u in usages) for k in keys}
    if "cost_usd" in merged:
        merged["cost_usd"] = round(merged["cost_usd"], 6)
    merged["cost_cents"] = round(sum(u.get("cost_cents", 0) for u in usages), 4)
    return merged


def _record_ai_usage(feuser, is_trial: bool, usage: dict | None) -> None:
    """Bill a completed AI call's cost against the feuser's trial budget. A
    no-op off-trial (a feuser with their own credentials pays their AI
    provider directly) or when usage is falsy."""
    if not (is_trial and usage):
        return
    feuser.ai_trial_budget_spent = (feuser.ai_trial_budget_spent or Decimal(0)) + Decimal(str(usage["cost_cents"]))
    feuser.save(update_fields=["ai_trial_budget_spent"])


def _extract_json_object(raw: str):
    """
    Best-effort recovery of a single JSON value from a raw AI text response.

    Every AI feature's system prompt asks for a reply that is nothing but a
    JSON object, but models sometimes still wrap it in a ``` code fence,
    prefix it with a line of prose, or tack on a trailing sign-off sentence
    despite being told not to. This tolerates all three by locating the first
    "{" and parsing only the JSON value that starts there (via
    json.JSONDecoder.raw_decode), rather than requiring -- like json.loads --
    that the entire remaining string be valid JSON; anything trailing the
    parsed value (a closing fence, a stray comment) is simply ignored instead
    of causing an "Extra data" failure. strict=False additionally tolerates a
    raw, unescaped line break inside a string value instead of raising.

    Raises json.JSONDecodeError if no valid JSON value can be found at all.
    """
    cleaned = raw
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1]
        cleaned = cleaned.rsplit("```", 1)[0].strip()

    idx = cleaned.find("{")
    if idx != -1:
        cleaned = cleaned[idx:]

    parsed, _end = json.JSONDecoder(strict=False).raw_decode(cleaned)
    return parsed


_JSON_REPAIR_SYSTEM = """You are a strict JSON repair tool.
You will be given a piece of text that was supposed to be a single JSON object but failed to parse as one -- for example because it was wrapped in a markdown code fence, had a leading or trailing sentence around it, or contained a stray unescaped character.
Your ONLY job is to recover the JSON object that was intended and output it, unchanged in meaning, and nothing else. Do not change, add, remove, or "improve" any keys or values -- only fix formatting/syntax so the result is valid JSON.
Your entire reply must be exactly the corrected JSON object: no prose, no markdown, no code fences, no leading or trailing text of any kind. The first character of your reply MUST be "{" and the last character MUST be "}".
If you cannot find a coherent JSON object to recover at all, reply with exactly: {"result": "fail", "msg": "could not recover"}"""


# ---------------------------------------------------------------------------
# AIService
# ---------------------------------------------------------------------------

class AIService:
    """
    One instance per feuser per request. Resolves the feuser's access (own
    credentials win over the shared trial access) up front and raises
    AIBudgetExceededError immediately if there's nothing usable, so a feature
    method is never called with a prompt it can't actually send.
    """

    def __init__(self, feuser):
        self.feuser = feuser
        self.provider = get_provider()
        if self.provider is None:
            raise AIBudgetExceededError("AI is not configured on this server.")
        has_access, self.is_trial, self.trial_limit, self.trial_spent, blocked = self.trial_state_for(feuser)
        if blocked:
            raise AIBudgetExceededError("Trial budget exhausted.")
        if not has_access:
            raise AIBudgetExceededError("No AI access configured.")
        # the feuser's own settings for the provider; {} = shared access
        self.user_config: dict = {} if self.is_trial else own_entry(feuser.ai_user_config, self.provider)
        # Usage dict from the most recent call, success or failed-after-repair
        # (see _record_usage) -- feature views read this to show the cost pill
        # without threading a return value through every exception branch.
        self.last_usage: dict | None = None

    @staticmethod
    def trial_state_for(feuser) -> tuple[bool, bool, float, float, bool]:
        """
        Return (has_access, is_trial, trial_limit, trial_spent, trial_blocked)
        for display purposes (e.g. the express-creation banner, the
        dashboard's ai_trial_blocked flag) without constructing a full
        AIService, which would raise the moment the trial is blocked.
        Own settings complete for the active provider win; otherwise the
        provider's shared access, if it has one and a trial limit applies.
        """
        provider = get_provider()
        if provider is None:
            return False, False, 0, 0, False
        if has_own_access(feuser.ai_user_config, provider):
            return True, False, 0, 0, False
        if feuser.special_ai_trial_budget is not None:
            trial_limit = float(feuser.special_ai_trial_budget)
        else:
            trial_limit = settings.AI_TRIAL_USAGE_LIMIT
        if not provider.has_shared_access() or not trial_limit:
            return False, False, 0, 0, False
        spent = float(feuser.ai_trial_budget_spent or 0)
        blocked = spent >= trial_limit
        return True, True, trial_limit, spent, blocked

    # -----------------------------------------------------------------
    # Feature entry points -- preprompt to validated JSON response
    # -----------------------------------------------------------------

    def prompt_express_expense_gen(
        self, system_prompt: str, description: str,
        image_b64: str = "", image_type: str = "image/jpeg",
    ) -> list[dict]:
        """Express expense creation: extract expense/income items from a
        description and/or receipt image. Returns the raw "items" list
        (still needs express_service._validate_items before it's trusted)."""
        request = AIRequest(
            feature="express_creation",
            system=_system_parts(system_prompt),
            user_text=description or "Please analyse this image and extract all expense items.",
            images=[ImageInput(data_b64=image_b64, media_type=image_type)] if image_b64 else [],
            max_tokens=8192,
        )
        parsed, _raw = self._call_for_json(request)
        return parsed.get("items", [])

    def prompt_dashboard_card_yaml(self, system_prompt: str | list[SystemPart], description: str) -> str:
        """Dashboard card AI assist: generate/edit one card's YAML config
        from a natural-language description. Returns a non-empty YAML string
        (still needs dashboard_cards.parse_card_config to be schema-valid)."""
        request = AIRequest(
            feature="dashboard_card_ai", system=_system_parts(system_prompt),
            user_text=description, max_tokens=8192,
        )
        parsed, raw = self._call_for_json(request)
        yaml_str = parsed.get("yaml")
        if not isinstance(yaml_str, str) or not yaml_str.strip():
            raise AIInvalidResponseError(raw)
        return yaml_str

    def prompt_partnership_mapping(self, system_prompt: str, user_message: str) -> list[dict]:
        """Partnership onboarding: suggest source->target tag/category
        mappings. There is no meaningful "fail" case for this prompt (an
        unmatched source just maps to null), so unlike the other two features
        it doesn't use the {"result": "good"/"fail"} envelope."""
        request = AIRequest(
            feature="partnership_ai", system=_system_parts(system_prompt),
            user_text=user_message, max_tokens=4096,
        )
        parsed, raw = self._call_for_json(request, envelope=False)
        mappings = parsed.get("mappings")
        if not isinstance(mappings, list):
            raise AIInvalidResponseError(raw)
        return mappings

    def prompt_unclassified_solve(self, system_prompt: str) -> dict:
        """Unclassified Expenses: suggest a category and/or tags (whichever
        the caller's system prompt says is missing) for a single expense,
        picking only from the feuser's own closed catalog. The AI is shown
        that catalog as 0-based "idx" positions, never real uids (same
        reasoning as express creation's project/buddy idx -- see
        budget/unclassified_ai.py), so budget.unclassified_ai.solve_unclassified
        is the one that translates an idx back to a real uid, bounds-checked
        against the exact catalog list the prompt was built from. Like
        partnership mapping, there's no meaningful "fail" case -- a field the
        AI can't confidently match just comes back null -- so this skips the
        {"result": "good"/"fail"} envelope too. Returns
        {"category_idx": int|None, "tag_idxs": list[int]}."""
        request = AIRequest(
            feature="unclassified_solve", system=_system_parts(system_prompt),
            user_text="Suggest the missing classification for this expense.", max_tokens=4096,
        )
        parsed, raw = self._call_for_json(request, envelope=False)
        tag_idxs = parsed.get("tag_idxs")
        return {
            "category_idx": parsed.get("category_idx"),
            "tag_idxs": tag_idxs if isinstance(tag_idxs, list) else [],
        }

    # -----------------------------------------------------------------
    # Shared core
    # -----------------------------------------------------------------

    def _call_for_json(self, request: AIRequest, *, envelope: bool = True) -> tuple[dict, str]:
        """
        Call the AI, recover a JSON object from the response (one repair
        retry on parse failure, see _call_and_repair), and -- for every
        feature except partnership mapping and unclassified solve -- enforce
        the {"result": "good"/"fail", ...} envelope every prompt in this app
        asks for. Bills usage before returning or raising either way, so
        callers never touch usage billing themselves.
        Returns (parsed_dict, raw_text).
        """
        try:
            parsed, usage, raw = self._call_and_repair(request)
        except (AIInvalidResponseError, AIRefusalError) as exc:
            self._record_usage(exc.usage)
            raise
        self._record_usage(usage)

        if not isinstance(parsed, dict):
            raise AIInvalidResponseError(raw)
        if envelope:
            if parsed.get("result") == "fail":
                raise AIRefusalError(parsed.get("msg", ""), raw)
            if parsed.get("result") != "good":
                raise AIInvalidResponseError(raw)
        return parsed, raw

    def _record_usage(self, usage: dict | None) -> None:
        if not usage:
            return
        _record_ai_usage(self.feuser, self.is_trial, usage)
        self.last_usage = usage
        if self.is_trial:
            self.trial_spent = float(self.feuser.ai_trial_budget_spent)

    def _call_and_repair(self, request: AIRequest) -> tuple[object, dict, str]:
        """
        The one retry every AI feature wants: if the model's raw response
        doesn't parse as JSON at all (see _extract_json_object) -- most often
        because it wrapped the JSON in extra code-fencing or prose despite
        being told not to -- the raw text is forwarded to one small repair AI
        call before giving up. The instance admin is emailed about it
        (feature name and outcome only, never the response content -- see
        budget.ai_trial.notify_admin_json_repair_fallback) so repeated
        fencing problems on a given feature's prompt get noticed.

        Returns (parsed_json_value, usage, raw_text): usage is the combined
        cost of every AI call made for this one logical request. raw_text is
        the exact response text that was actually parsed (the primary
        response, or the repaired one if a repair was needed).

        Raises AIInvalidResponseError (with .usage set to the combined cost
        spent so far) if the response still can't be parsed after repair.
        """
        from . import ai_trial

        raw, usage = self._call(request)
        _log.debug("%s raw response: %r", request.feature, raw)

        try:
            return _extract_json_object(raw), usage, raw
        except json.JSONDecodeError as exc:
            _log.warning(
                "%s JSON parse failure, attempting AI repair. raw=%r exc=%s",
                request.feature, raw, exc,
            )

        repair_request = AIRequest(
            feature="json_repair", system=[SystemPart(_JSON_REPAIR_SYSTEM)],
            user_text=raw, max_tokens=request.max_tokens,
        )
        try:
            repair_raw, repair_usage = self._call(repair_request)
        except AIRefusalError as exc:
            exc.usage = _merge_usage(usage, exc.usage or {})
            raise
        combined_usage = _merge_usage(usage, repair_usage)

        try:
            parsed = _extract_json_object(repair_raw)
        except json.JSONDecodeError as repair_exc:
            _log.error(
                "%s JSON repair also failed. raw=%r repair_raw=%r exc=%s",
                request.feature, raw, repair_raw, repair_exc,
            )
            ai_trial.notify_admin_json_repair_fallback(request.feature, resolved=False)
            raise AIInvalidResponseError(raw, repair_exc, usage=combined_usage) from repair_exc

        _log.info("%s JSON repair succeeded after primary parse failure.", request.feature)
        ai_trial.notify_admin_json_repair_fallback(request.feature, resolved=True)
        return parsed, combined_usage, repair_raw

    def _call(self, request: AIRequest) -> tuple[str, dict]:
        """One provider call -> (text, usage incl. cost_cents). Providers raise
        only typed AIErrors; a failing shared access additionally disables the
        trial and notifies the admin here, for every AI feature alike."""
        from . import ai_trial

        try:
            response = self.provider.send(request, self.user_config)
        except AIAuthenticationError as exc:
            if not self.is_trial:
                raise
            ai_trial.notify_admin_invalid_trial_key()
            raise AIAuthenticationError(_INVALID_SHARED_KEY_MESSAGE) from exc
        except AIBillingError as exc:
            if not self.is_trial:
                raise
            ai_trial.disable_trial(exc.detail)
            ai_trial.notify_admin_billing(exc.detail)
            raise AIBillingError(exc.detail) from exc
        except AIError:
            raise
        except Exception as exc:  # a provider must raise typed errors only; never leak a raw one
            _log.exception("AI provider %s raised an untyped error", self.provider.get_name())
            raise AIError(f"Unexpected error: {exc}") from exc
        return response.text, {**response.usage, "cost_cents": response.cost_cents}


def _system_parts(system_prompt: str | list[SystemPart]) -> list[SystemPart]:
    if isinstance(system_prompt, str):
        return [SystemPart(system_prompt)]
    return list(system_prompt)
