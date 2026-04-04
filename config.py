"""
Centralized LLM provider configuration.

Usage:
    from config import get_llm_client
    llm = get_llm_client()
"""
from __future__ import annotations
import logging
import os
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

from agent.llm import (
    LLMClient,
    ClaudeLLMClient,
    ClaudeCodeCLIClient,
    OpenAICompatibleClient,
    PROVIDER_PRESETS,
)


# Map of provider names to the env var that holds their API key.
# All providers use LLM_API_KEY, but this dict documents the mapping
# for error messages (telling the user which env var to set).
PROVIDER_ENV_VARS: dict[str, str] = {
    "anthropic": "LLM_API_KEY",
    "openrouter": "LLM_API_KEY",
    "openai": "LLM_API_KEY",
    "groq": "LLM_API_KEY",
    "together": "LLM_API_KEY",
    "ollama": "LLM_API_KEY",
    "custom": "LLM_API_KEY",
}


@dataclass
class Settings:
    provider: str | None = None
    api_key: str | None = None
    model: str | None = None
    base_url: str | None = None

    def __post_init__(self) -> None:
        # Read from environment variables if not explicitly set
        self.provider = self.provider or os.environ.get("LLM_PROVIDER", "anthropic")
        self.api_key = self.api_key or os.environ.get("LLM_API_KEY")
        self.model = self.model or os.environ.get("LLM_MODEL")
        self.base_url = self.base_url or os.environ.get("LLM_BASE_URL")


def get_llm_client(
    provider: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
) -> LLMClient:
    """
    Create and return an LLM client based on current settings.

    Args:
        provider: Override the provider from env (used by CLI --provider flag
                  and web UI per-session selection).
        model: Override the model from env (used by CLI --model flag).
        api_key: Override the API key from env (used by web UI per-session entry).
    """
    settings = Settings(api_key=api_key)

    # CLI/Web overrides take priority over env var
    selected_provider = provider or settings.provider
    selected_model = model or settings.model

    logger.info("get_llm_client: provider=%r selected_provider=%r", provider, selected_provider)

    # Claude Code CLI — no API key needed
    if selected_provider == "claude_code":
        return ClaudeCodeCLIClient(model=selected_model)

    # Anthropic API
    if selected_provider == "anthropic":
        resolved_key = settings.api_key
        if not resolved_key:
            env_var = PROVIDER_ENV_VARS.get(selected_provider, "LLM_API_KEY")
            raise ValueError(
                f"No API key configured. Set {env_var} in your .env file.\n"
                "  Get one at: https://console.anthropic.com/\n"
                "  Tip: select 'Claude Code CLI' as the provider to use your local Claude login instead."
            )
        return ClaudeLLMClient(api_key=resolved_key, model=selected_model)

    # OpenAI-compatible providers (OpenRouter, OpenAI, Groq, Together, Ollama, custom)
    if selected_provider in PROVIDER_PRESETS or selected_provider == "custom":
        resolved_key = settings.api_key
        if not resolved_key:
            env_var = PROVIDER_ENV_VARS.get(selected_provider, "LLM_API_KEY")
            raise ValueError(
                f"No API key configured for '{selected_provider}'. "
                f"Set {env_var} in your .env file."
            )

        if selected_provider == "custom":
            if not settings.base_url:
                raise ValueError(
                    "Custom provider requires LLM_BASE_URL. "
                    "Set it in your .env file."
                )
            base_url = settings.base_url
            default_model = selected_model or "unknown"
        else:
            base_url, default_model = PROVIDER_PRESETS[selected_provider]
            if selected_model:
                default_model = selected_model

        return OpenAICompatibleClient(
            api_key=resolved_key,
            base_url=base_url,
            model=default_model,
        )

    # Unknown provider
    available = ", ".join(sorted(
        list(PROVIDER_PRESETS.keys()) + ["anthropic", "claude_code", "custom"]
    ))
    raise ValueError(
        f"Unknown LLM provider: '{selected_provider}'.\n"
        f"Available providers: {available}"
    )
