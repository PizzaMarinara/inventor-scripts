import os
from unittest.mock import patch
import pytest
from config import get_llm_client, Settings, PROVIDER_ENV_VARS


def test_settings_defaults():
    """Settings should default to anthropic provider with no env vars."""
    with patch.dict(os.environ, {}, clear=True):
        s = Settings()
        assert s.provider == "anthropic"
        assert s.api_key is None
        assert s.model is None
        assert s.base_url is None


def test_settings_reads_llm_provider():
    with patch.dict(os.environ, {"LLM_PROVIDER": "openrouter"}, clear=True):
        s = Settings()
        assert s.provider == "openrouter"


def test_settings_reads_api_key():
    """LLM_API_KEY should be read for any provider."""
    with patch.dict(os.environ, {
        "LLM_PROVIDER": "openrouter",
        "LLM_API_KEY": "sk-or-test-key",
    }, clear=True):
        s = Settings()
        assert s.api_key == "sk-or-test-key"


def test_settings_reads_model_override():
    with patch.dict(os.environ, {
        "LLM_PROVIDER": "openrouter",
        "LLM_MODEL": "anthropic/claude-3.5-sonnet",
    }, clear=True):
        s = Settings()
        assert s.model == "anthropic/claude-3.5-sonnet"


def test_settings_reads_custom_base_url():
    with patch.dict(os.environ, {
        "LLM_PROVIDER": "custom",
        "LLM_BASE_URL": "http://localhost:8080/v1",
        "LLM_API_KEY": "test-key",
    }, clear=True):
        s = Settings()
        assert s.base_url == "http://localhost:8080/v1"


def test_get_llm_client_anthropic():
    with patch.dict(os.environ, {
        "LLM_PROVIDER": "anthropic",
        "LLM_API_KEY": "sk-ant-test",
    }, clear=True):
        with patch("config.ClaudeLLMClient") as mock_cls:
            get_llm_client()
            mock_cls.assert_called_once_with(api_key="sk-ant-test", model=None)


def test_get_llm_client_claude_code():
    with patch.dict(os.environ, {"LLM_PROVIDER": "claude_code"}, clear=True):
        with patch("config.ClaudeCodeCLIClient") as mock_cls:
            get_llm_client()
            mock_cls.assert_called_once_with(model=None)


def test_get_llm_client_openrouter():
    with patch.dict(os.environ, {
        "LLM_PROVIDER": "openrouter",
        "LLM_API_KEY": "sk-or-test",
    }, clear=True):
        with patch("config.OpenAICompatibleClient") as mock_cls:
            get_llm_client()
            call_kwargs = mock_cls.call_args.kwargs
            assert call_kwargs["api_key"] == "sk-or-test"
            assert "openrouter.ai" in call_kwargs["base_url"]


def test_get_llm_client_missing_api_key_raises():
    with patch.dict(os.environ, {
        "LLM_PROVIDER": "openrouter",
    }, clear=True):
        with pytest.raises(ValueError, match="LLM_API_KEY"):
            get_llm_client()


def test_get_llm_client_unknown_provider_raises():
    with patch.dict(os.environ, {
        "LLM_PROVIDER": "unknown_provider",
        "LLM_API_KEY": "some-key",
    }, clear=True):
        with pytest.raises(ValueError, match="unknown_provider"):
            get_llm_client()


def test_get_llm_client_custom_provider():
    with patch.dict(os.environ, {
        "LLM_PROVIDER": "custom",
        "LLM_API_KEY": "test-key",
        "LLM_BASE_URL": "http://localhost:9000/v1",
        "LLM_MODEL": "my-model",
    }, clear=True):
        with patch("config.OpenAICompatibleClient") as mock_cls:
            get_llm_client()
            call_kwargs = mock_cls.call_args.kwargs
            assert call_kwargs["base_url"] == "http://localhost:9000/v1"
            assert call_kwargs["model"] == "my-model"
