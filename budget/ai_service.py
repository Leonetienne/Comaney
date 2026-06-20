"""
Single entry point for every AI feature in the app: express expense creation,
dashboard card AI assist, partnership tag/category mapping, and Unclassified
Expenses AI-solve. Nothing outside this file constructs an
anthropic.Anthropic client, calls .messages.create, or hand-parses an AI
JSON response -- it all goes through one AIService instance:

    service  = AIService(feuser)                     # raises AIBudgetExceededError up front if blocked/no key
    items    = service.prompt_express_expense_gen(system_prompt, description, image_b64=..., image_type=...)
    yaml     = service.prompt_dashboard_card_yaml(system_prompt, description)
    mapping  = service.prompt_partnership_mapping(system_prompt, user_message)
    solution = service.prompt_unclassified_solve(system_prompt)

AIService owns HOW to talk to the AI safely: provider dispatch, JSON-response
recovery (one repair retry), envelope parsing, own-key/trial-key resolution,
budget billing, and error classification (auth/billing/rate-limit -> typed
exceptions here, plus the side effects of disabling the shared trial key and
notifying the admin -- see budget.ai_trial). It deliberately knows nothing
about categories, tags, projects, or dashboard cards: each feature module
(budget.express_service, budget.dashboard_card_ai,
buddies.services.partnership_ai, budget.unclassified_ai) owns assembling its
own system prompt text and interpreting the returned payload for saving.
Mixing that business logic in here would just trade "AI plumbing scattered
across files" for "four unrelated features' business rules crammed into one
file" -- the same mess in a different shape.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from decimal import Decimal

from django.conf import settings

_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class AIError(Exception):
    """Base class for every error AIService raises."""


class AIRefusalError(AIError):
    """AI returned {"result": "fail", "msg": "..."}"""
    def __init__(self, msg: str, raw: str = ""):
        super().__init__(msg)
        self.raw = raw


class AIInvalidResponseError(AIError):
    """AI returned unparseable or structurally unexpected output."""
    def __init__(self, raw: str = "", cause: Exception | None = None, usage: dict | None = None):
        super().__init__("Invalid response")
        self.raw = raw
        self.cause = cause
        # Set only when raised after a JSON-repair fallback was attempted --
        # the combined cost of the primary + repair calls, so the caller can
        # still bill it even though the request ultimately failed. None for
        # every other raise site (nothing extra was spent).
        self.usage = usage


class AIBudgetExceededError(AIError):
    """Trial or user budget is exhausted, or no API key is configured at all."""


class AIAuthenticationError(AIError):
    """The configured API key was rejected by Anthropic."""


class AIBillingError(AIError):
    """The shared trial key (or the feuser's own key) is out of credits."""


class AITransientError(AIError):
    """Rate limit, overload, or connectivity issue -- safe to retry later."""
    def __init__(self, message: str, *, overloaded: bool = False, detail: str = ""):
        super().__init__(message)
        self.overloaded = overloaded
        self.detail = detail


# ---------------------------------------------------------------------------
# Agent config / pricing / JSON repair -- implementation details of _call*
# ---------------------------------------------------------------------------

@dataclass
class AgentConfig:
    provider: str = "claude"
    api_key: str = ""
    model: str = "claude-sonnet-4-6"
    max_tokens: int = 8192


_PRICE_INPUT       = 3.00
_PRICE_OUTPUT      = 15.00
_PRICE_CACHE_WRITE = 3.75
_PRICE_CACHE_READ  = 0.30


def _compute_usage_cost(input_tok: int, output_tok: int, cache_write_tok: int, cache_read_tok: int) -> dict:
    """cost_usd/cost_cents for a Claude API call from its token usage.

    cost_cents is kept at the same 4-decimal precision as
    FeUser.ai_trial_budget_spent (a DecimalField(decimal_places=4)): rounding
    to fewer decimals silently truncates cheap, cache-heavy requests to 0.0,
    under-billing trial usage instead of just under-displaying it.
    """
    cost = (
        (input_tok       / 1_000_000) * _PRICE_INPUT +
        (output_tok      / 1_000_000) * _PRICE_OUTPUT +
        (cache_write_tok / 1_000_000) * _PRICE_CACHE_WRITE +
        (cache_read_tok  / 1_000_000) * _PRICE_CACHE_READ
    )
    return {"cost_usd": round(cost, 6), "cost_cents": round(cost * 100, 4)}


def _merge_usage(*usages: dict) -> dict:
    """Combine usage dicts from a primary call + its JSON-repair retry into one."""
    keys = ("input_tokens", "output_tokens", "cache_write_tokens", "cache_read_tokens", "total_tokens")
    merged = {k: sum(u.get(k, 0) for u in usages) for k in keys}
    merged["cost_usd"] = round(sum(u.get("cost_usd", 0) for u in usages), 6)
    merged["cost_cents"] = round(sum(u.get("cost_cents", 0) for u in usages), 4)
    return merged


def _record_ai_usage(feuser, is_trial: bool, usage: dict | None) -> None:
    """Bill a completed AI call's cost against the feuser's trial budget. A
    no-op off-trial (a feuser with their own Anthropic key pays Anthropic
    directly) or when usage is falsy."""
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
    One instance per feuser per request. Resolves the feuser's API key (own
    key wins over the shared trial key) up front and raises
    AIBudgetExceededError immediately if there's nothing usable, so a feature
    method is never called with a prompt it can't actually send.
    """

    def __init__(self, feuser):
        self.feuser = feuser
        self.api_key, self.is_trial, self.trial_limit, self.trial_spent, blocked = self.trial_state_for(feuser)
        if blocked:
            raise AIBudgetExceededError("Trial budget exhausted.")
        if not self.api_key:
            raise AIBudgetExceededError("No AI API key configured.")
        # Usage dict from the most recent call, success or failed-after-repair
        # (see _record_usage) -- feature views read this to show the cost pill
        # without threading a return value through every exception branch.
        self.last_usage: dict | None = None

    @staticmethod
    def trial_state_for(feuser) -> tuple[str, bool, float, float, bool]:
        """
        Return (api_key, is_trial, trial_limit, trial_spent, trial_blocked)
        for display purposes (e.g. the express-creation banner, the
        dashboard's ai_trial_blocked flag) without constructing a full
        AIService, which would raise the moment the trial is blocked.
        """
        if feuser.anthropic_api_key:
            return feuser.anthropic_api_key, False, 0, 0, False
        trial_key = settings.AI_TRIAL_API_KEY
        if feuser.special_ai_trial_budget is not None:
            trial_limit = float(feuser.special_ai_trial_budget)
        else:
            trial_limit = settings.AI_TRIAL_USAGE_LIMIT
        if not trial_key or not trial_limit:
            return "", False, 0, 0, False
        spent = float(feuser.ai_trial_budget_spent or 0)
        blocked = spent >= trial_limit
        return trial_key, True, trial_limit, spent, blocked

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
        content: list[dict] = []
        if image_b64:
            content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": image_type, "data": image_b64},
            })
        content.append({
            "type": "text",
            "text": description or "Please analyse this image and extract all expense items.",
        })
        config = AgentConfig(api_key=self.api_key, max_tokens=8192)
        messages = [{"role": "user", "content": content}]
        parsed, _raw = self._call_for_json(config, system_prompt, messages, feature="express_creation")
        return parsed.get("items", [])

    def prompt_dashboard_card_yaml(self, system_prompt: str | list[dict], description: str) -> str:
        """Dashboard card AI assist: generate/edit one card's YAML config
        from a natural-language description. Returns a non-empty YAML string
        (still needs dashboard_cards.parse_card_config to be schema-valid)."""
        config = AgentConfig(api_key=self.api_key, max_tokens=8192)
        messages = [{"role": "user", "content": description}]
        parsed, raw = self._call_for_json(config, system_prompt, messages, feature="dashboard_card_ai")
        yaml_str = parsed.get("yaml")
        if not isinstance(yaml_str, str) or not yaml_str.strip():
            raise AIInvalidResponseError(raw)
        return yaml_str

    def prompt_partnership_mapping(self, system_prompt: str, user_message: str) -> list[dict]:
        """Partnership onboarding: suggest source->target tag/category
        mappings. There is no meaningful "fail" case for this prompt (an
        unmatched source just maps to null), so unlike the other two features
        it doesn't use the {"result": "good"/"fail"} envelope."""
        config = AgentConfig(api_key=self.api_key, max_tokens=1024)
        messages = [{"role": "user", "content": user_message}]
        parsed, raw = self._call_for_json(config, system_prompt, messages, feature="partnership_ai", envelope=False)
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
        config = AgentConfig(api_key=self.api_key, max_tokens=1024)
        messages = [{"role": "user", "content": "Suggest the missing classification for this expense."}]
        parsed, raw = self._call_for_json(
            config, system_prompt, messages, feature="unclassified_solve", envelope=False,
        )
        tag_idxs = parsed.get("tag_idxs")
        return {
            "category_idx": parsed.get("category_idx"),
            "tag_idxs": tag_idxs if isinstance(tag_idxs, list) else [],
        }

    # -----------------------------------------------------------------
    # Shared core
    # -----------------------------------------------------------------

    def _call_for_json(
        self, config: AgentConfig, system_prompt: str | list[dict], messages: list[dict],
        *, feature: str, envelope: bool = True,
    ) -> tuple[dict, str]:
        """
        Call the AI, recover a JSON object from the response (one repair
        retry on parse failure, see _call_and_repair), and -- for every
        feature except partnership mapping -- enforce the
        {"result": "good"/"fail", ...} envelope every prompt in this app
        asks for. Bills usage before returning or raising either way, so
        callers never touch usage billing themselves.
        Returns (parsed_dict, raw_text).
        """
        try:
            parsed, usage, raw = self._call_and_repair(config, system_prompt, messages, feature=feature)
        except AIInvalidResponseError as exc:
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

    def _call_and_repair(
        self, config: AgentConfig, system_prompt: str | list[dict], messages: list[dict], *, feature: str,
    ) -> tuple[object, dict, str]:
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
        from .ai_trial import notify_admin_json_repair_fallback

        raw, usage = self._call(config, system_prompt, messages)
        _log.debug("%s raw response: %r", feature, raw)

        try:
            return _extract_json_object(raw), usage, raw
        except json.JSONDecodeError as exc:
            _log.warning(
                "%s JSON parse failure, attempting AI repair. raw=%r exc=%s",
                feature, raw, exc,
            )

        repair_config = AgentConfig(
            provider=config.provider, api_key=config.api_key,
            model=config.model, max_tokens=config.max_tokens,
        )
        repair_raw, repair_usage = self._call(
            repair_config, _JSON_REPAIR_SYSTEM, [{"role": "user", "content": raw}],
        )
        combined_usage = _merge_usage(usage, repair_usage)

        try:
            parsed = _extract_json_object(repair_raw)
        except json.JSONDecodeError as repair_exc:
            _log.error(
                "%s JSON repair also failed. raw=%r repair_raw=%r exc=%s",
                feature, raw, repair_raw, repair_exc,
            )
            notify_admin_json_repair_fallback(feature, resolved=False)
            raise AIInvalidResponseError(raw, repair_exc, usage=combined_usage) from repair_exc

        _log.info("%s JSON repair succeeded after primary parse failure.", feature)
        notify_admin_json_repair_fallback(feature, resolved=True)
        return parsed, combined_usage, repair_raw

    def _call(self, config: AgentConfig, system_prompt: str | list[dict], messages: list[dict]) -> tuple[str, dict]:
        """Dispatch to the configured provider, translating any failure into
        one of this module's typed AIError subclasses (see
        _classify_exception) so callers never need to import anthropic."""
        if config.provider != "claude":
            raise ValueError(f"Unsupported AI provider: {config.provider!r}")
        try:
            return self._call_claude(config, system_prompt, messages)
        except AIError:
            raise
        except Exception as exc:
            raise self._classify_exception(exc) from exc

    @staticmethod
    def _call_claude(config: AgentConfig, system_prompt: str | list[dict], messages: list[dict]) -> tuple[str, dict]:
        """Raw Anthropic API call. Returns (response_text, usage_dict). The
        only place in the codebase that constructs an anthropic.Anthropic
        client or calls .messages.create."""
        import anthropic

        if isinstance(system_prompt, str):
            system = [
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ]
        else:
            system = system_prompt

        client = anthropic.Anthropic(api_key=config.api_key)
        response = client.messages.create(
            model=config.model or "claude-sonnet-4-6",
            max_tokens=config.max_tokens,
            system=system,
            messages=messages,
        )

        raw = ""
        for block in response.content:
            if getattr(block, "type", None) == "text":
                raw = block.text.strip()
                break

        if not raw:
            _log.error("_call_claude: empty response. blocks: %r", response.content)
            raise ValueError(
                f"Claude returned an empty response. Content blocks: "
                f"{[getattr(b, 'type', '?') for b in response.content]}"
            )

        u = response.usage
        input_tok       = getattr(u, "input_tokens", 0)
        output_tok      = getattr(u, "output_tokens", 0)
        cache_write_tok = getattr(u, "cache_creation_input_tokens", 0)
        cache_read_tok  = getattr(u, "cache_read_input_tokens", 0)

        usage = {
            "input_tokens":       input_tok,
            "output_tokens":      output_tok,
            "cache_write_tokens": cache_write_tok,
            "cache_read_tokens":  cache_read_tok,
            "total_tokens":       input_tok + output_tok + cache_write_tok + cache_read_tok,
            **_compute_usage_cost(input_tok, output_tok, cache_write_tok, cache_read_tok),
        }
        return raw, usage

    def _classify_exception(self, exc: Exception) -> AIError:
        """
        Turn an anthropic SDK exception into a typed AIError, firing the
        trial-key side effects (disable + admin email) inline so every AI
        feature gets the same protection express creation used to have
        alone: previously only express.py's view disabled the shared trial
        key and notified the admin on a billing/auth failure, so dashboard
        card AI and partnership AI could silently exhaust or break the
        shared key with nobody finding out.
        """
        import anthropic

        if isinstance(exc, anthropic.AuthenticationError):
            if self.is_trial:
                from .ai_trial import notify_admin_invalid_trial_key
                notify_admin_invalid_trial_key()
                return AIAuthenticationError(
                    "The server is misconfigured: the trial API key is invalid. "
                    "Please contact the server administrator."
                )
            return AIAuthenticationError("Invalid API key. Please update it in your profile.")

        if isinstance(exc, anthropic.PermissionDeniedError):
            return AIAuthenticationError(
                "API key does not have permission to use this model. Please check your Anthropic account."
            )

        if isinstance(exc, anthropic.RateLimitError):
            if self._looks_like_billing(exc):
                return self._handle_billing(str(exc))
            return AITransientError("Anthropic rate limit reached. Please wait a moment and try again.")

        if isinstance(exc, anthropic.InternalServerError):
            return AITransientError(
                "Anthropic is temporarily overloaded. Please try again in a moment.",
                overloaded=True, detail=str(exc),
            )

        if isinstance(exc, anthropic.APIConnectionError):
            return AITransientError("Could not reach the Anthropic API. Please check your internet connection.")

        if isinstance(exc, anthropic.APIStatusError):
            if self._looks_like_billing(exc):
                return self._handle_billing(str(exc))
            return AITransientError(f"Anthropic API error {exc.status_code}: {exc.message}")

        return AIError(f"Unexpected error: {exc}")

    @staticmethod
    def _looks_like_billing(exc: Exception) -> bool:
        msg = str(exc).lower()
        return "credit" in msg or "billing" in msg or "balance" in msg

    def _handle_billing(self, reason: str) -> AIBillingError:
        if self.is_trial:
            from .ai_trial import disable_trial, notify_admin_billing
            disable_trial(reason)
            notify_admin_billing(reason)
            return AIBillingError(reason)
        return AIBillingError(
            "Insufficient Anthropic credits. Please top up your account at console.anthropic.com."
        )
