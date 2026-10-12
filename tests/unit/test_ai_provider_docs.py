"""
Every built-in AI provider is documented in admin-manual/ai-providers.md:
a "## ... (`<name>`)" section naming each of its AI_PROVIDER_<NAME>_* options,
the label of each per-user field, and an Authentication subsection.
Run with: venv/bin/pytest tests/unit/test_ai_provider_docs.py -v
"""
import re
from pathlib import Path

import pytest

import ai_providers
from ai_providers import _provider_class
from ai_providers.base import env_var_name

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "docs" / "src" / "docs" / "admin-manual" / "ai-providers.md"
# modules in ai_providers/ that are framework, not providers
NOT_PROVIDERS = {"__init__", "base", "errors", "openai_compat"}

PROVIDERS = sorted(
    p.stem for p in Path(ai_providers.__file__).parent.glob("*.py") if p.stem not in NOT_PROVIDERS
)


def _section(name: str) -> str:
    text = DOC.read_text(encoding="utf-8")
    match = re.search(rf"^## [^\n]*\(`{re.escape(name)}`\)\n(.*?)(?=^## |\Z)", text, re.S | re.M)
    assert match, f"admin-manual/ai-providers.md has no '## ... (`{name}`)' section"
    return match.group(1)


def test_built_in_providers_found():
    assert {"claude", "deepseek", "local"} <= set(PROVIDERS)


@pytest.mark.parametrize("name", PROVIDERS)
def test_section_documents_every_option(name):
    provider = _provider_class(name)({})
    section = _section(name)
    missing = [env_var_name(name, f.key) for f in provider.get_config_fields()
               if env_var_name(name, f.key) not in section]
    assert not missing, f"undocumented options for {name}: {missing}"


@pytest.mark.parametrize("name", PROVIDERS)
def test_section_documents_authentication_and_user_fields(name):
    provider = _provider_class(name)({})
    section = _section(name)
    assert "### Authentication" in section
    missing = [f.label for f in provider.get_user_fields() if f.label not in section]
    assert not missing, f"user fields of {name} not named in its section: {missing}"
