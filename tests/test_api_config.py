"""Tests for burt/api_config.py — отдельный файл API ключа.

Если ключ есть — API, если нет — LM Studio.
Ключ только в одном месте — не размазан по конфигами.
"""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from burt import api_config, llm_client


# ─── Helpers ───────────────────────────────────────────────────


def _patch_aiohttp(response_json=None, captured: dict | None = None):
    """Патч aiohttp.ClientSession для тестов."""
    if response_json is None:
        response_json = {"choices": [{"message": {"content": "ok"}}]}

    mock_response = MagicMock()
    mock_response.status = 200

    async def rj():
        return response_json

    async def rtext():
        return '{"error":"test"}'

    mock_response.json = rj
    mock_response.text = rtext

    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_response)
    mock_cm.__aexit__ = AsyncMock(return_value=None)

    mock_session = MagicMock()

    def post_side_effect(url_arg, *args, **kwargs):
        if captured is not None:
            captured["post_url"] = url_arg
            captured["post_kwargs"] = kwargs
        return mock_cm

    mock_session.post.side_effect = post_side_effect
    session_cm = MagicMock()
    session_cm.__aenter__ = AsyncMock(return_value=mock_session)
    session_cm.__aexit__ = AsyncMock(return_value=None)

    patcher = patch("aiohttp.ClientSession")
    mock_sess_cls = patcher.start()
    mock_sess_cls.return_value = session_cm
    return patcher


# ─── api_config defaults ──────────────────────────────────────


class TestApiConfigDefaults:
    """По умолчанию — LM Studio."""

    def test_default_base_url(self):
        assert api_config.DEFAULT_BASE_URL == "http://localhost:1234/v1"

    def test_default_model(self):
        assert api_config.DEFAULT_MODEL == "local-model"

    def test_no_api_key_by_default(self):
        """По умолчанию ключ пустой — LM Studio."""
        # При пустом API_KEY — возвращаем LM Studio
        result = api_config._read_config()
        assert result["api_key"] == ""
        assert result["base_url"] == "http://localhost:1234/v1"
        assert result["model"] == "local-model"


# ─── api_config with env vars ─────────────────────────────────


class TestApiConfigEnvVars:
    """Чтение из env vars."""

    def test_api_key_from_env(self, monkeypatch):
        monkeypatch.setenv("LLM_API_KEY", "sk-test-123")
        monkeypatch.setenv("LLM_BASE_URL", "https://api.example.com/v1")
        monkeypatch.setenv("LLM_MODEL", "gpt-4o-mini")

        import importlib
        import burt.api_config as ac
        try:
            importlib.reload(ac)
            assert ac.get_api_key() == "sk-test-123"
            assert ac.get_base_url() == "https://api.example.com/v1"
            assert ac.get_model() == "gpt-4o-mini"
            assert ac.is_api_configured() is True
        finally:
            monkeypatch.delenv("LLM_API_KEY", raising=False)
            monkeypatch.delenv("LLM_BASE_URL", raising=False)
            monkeypatch.delenv("LLM_MODEL", raising=False)
            importlib.reload(ac)

    def test_no_key_means_lm_studio(self, monkeypatch):
        """Пустой ключ — LM Studio."""
        monkeypatch.setenv("LLM_API_KEY", "")
        import importlib
        import burt.api_config as ac
        try:
            importlib.reload(ac)
            assert ac.get_api_key() == ""
            assert ac.get_base_url() == "http://localhost:1234/v1"
            assert ac.is_api_configured() is False
        finally:
            monkeypatch.delenv("LLM_API_KEY", raising=False)
            importlib.reload(ac)


# ─── Auth header ──────────────────────────────────────────────


class TestAuthHeader:
    """Отправка Authorization заголовка при наличии API_KEY."""

    @pytest.mark.asyncio
    async def test_auth_header_sent_when_key_set(self):
        """При API_KEY — заголовок Bearer отправляется."""
        captured: dict = {}
        patcher = _patch_aiohttp(captured=captured)
        try:
            with patch.object(llm_client, "_API_KEY", "sk-test-key-123"):
                await llm_client.create_chat_completion([{"role": "user", "content": "hi"}])
        finally:
            patcher.stop()

        headers = captured["post_kwargs"]["headers"]
        assert headers is not None
        assert "Authorization" in headers
        assert headers["Authorization"] == "Bearer sk-test-key-123"

    @pytest.mark.asyncio
    async def test_no_auth_header_when_key_empty(self):
        """При пустом API_KEY заголовок не отправляется."""
        captured: dict = {}
        patcher = _patch_aiohttp(captured=captured)
        try:
            with patch.object(llm_client, "_API_KEY", ""):
                await llm_client.create_chat_completion([{"role": "user", "content": "hi"}])
        finally:
            patcher.stop()

        headers = captured["post_kwargs"].get("headers")
        assert headers is None or "Authorization" not in headers


# ─── URL ──────────────────────────────────────────────────────


class TestUrl:
    """URL формируется из BASE_URL."""

    @pytest.mark.asyncio
    async def test_url_with_trailing_slash(self):
        """BASE_URL с trailing slash → корректный URL."""
        captured: dict = {}
        patcher = _patch_aiohttp(captured=captured)
        try:
            with patch.object(llm_client, "_BASE_URL", "https://api.example.com/v1/"):
                await llm_client.create_chat_completion([{"role": "user", "content": "hi"}])
        finally:
            patcher.stop()

        url = captured["post_url"]
        assert url == "https://api.example.com/v1/chat/completions"

    @pytest.mark.asyncio
    async def test_url_without_trailing_slash(self):
        """BASE_URL без trailing slash — корректный URL."""
        captured: dict = {}
        patcher = _patch_aiohttp(captured=captured)
        try:
            with patch.object(llm_client, "_BASE_URL", "https://api.example.com/v1"):
                await llm_client.create_chat_completion([{"role": "user", "content": "hi"}])
        finally:
            patcher.stop()

        url = captured["post_url"]
        assert url == "https://api.example.com/v1/chat/completions"
