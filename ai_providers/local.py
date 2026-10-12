"""
A self-hosted model behind any OpenAI-compatible server (llama.cpp's
llama-server, Ollama, LM Studio, vLLM, SGLang, MLX-LM, LocalAI, Docker Model
Runner, ...). The API key is optional and sent as a Bearer token when set.
"""
from __future__ import annotations

from ai_providers.base import ConfigField
from ai_providers.openai_compat import OpenAICompatibleProvider

_NUMBER = r"[0-9]+(\.[0-9]+)?"


class LocalProvider(OpenAICompatibleProvider):

    def get_name(self) -> str:
        return "local"

    def get_display_name(self) -> str:
        return "Self-hosted model"

    def sends_data_off_server(self) -> bool:
        return False

    def get_base_url(self) -> str:
        return self.config("base_url")

    def get_config_fields(self) -> list[ConfigField]:
        return [
            ConfigField("base_url", "Base URL", required=True, pattern=r"https?://\S+",
                        help_text="Including the version part, e.g. http://host:11434/v1."),
            ConfigField("model", "Model", required=True),
            ConfigField("api_key", "API key", secret=True,
                        help_text="Sent as a Bearer token if set."),
            ConfigField("max_tokens", "Max tokens", pattern=r"[1-9][0-9]*", default="8192"),
            ConfigField("supports_vision", "Model reads images", choices=("true", "false"), default="false"),
            ConfigField("cents_per_mtok", "Cost in cents per million tokens", pattern=_NUMBER, default="0"),
            # seconds; local models on modest hardware answer slowly
            ConfigField("timeout", "Timeout (seconds)", pattern=r"[1-9][0-9]*", default="600"),
        ]

    def has_shared_access(self) -> bool:
        return True

    def supports_vision(self) -> bool:
        return self.config("supports_vision") == "true"

    def calculate_cost(self, usage: dict) -> float:
        tokens = int(usage.get("prompt_tokens") or 0) + int(usage.get("completion_tokens") or 0)
        return tokens / 1_000_000 * float(self.config("cents_per_mtok"))
