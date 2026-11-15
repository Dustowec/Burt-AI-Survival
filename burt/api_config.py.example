"""API config — пример для копирования.

Скопируйте этот файл в burt/api_config.py и заполните свои значения.
Этот файл НЕ коммитится в git — он в .gitignore.
"""
from __future__ import annotations

import os

# Дефолты — LM Studio
DEFAULT_BASE_URL = "http://localhost:1234/v1"
DEFAULT_MODEL = "local-model"

# Переменные окружения (для CI / контейнеров)
ENV_BASE_URL = "LLM_BASE_URL"
ENV_API_KEY = "LLM_API_KEY"
ENV_MODEL = "LLM_MODEL"


def _read_config() -> dict:
    """Читает API_KEY, BASE_URL, MODEL.

    Приоритет:
    1. Env vars (LLM_API_KEY, LLM_BASE_URL, LLM_MODEL)
    2. Файл api_config.json в корне проекта (для удобства)

    Если API_KEY пустой — возвращаем LM Studio дефолты.
    """
    api_key = os.environ.get(ENV_API_KEY, "")
    base_url = os.environ.get(ENV_BASE_URL, "")
    model = os.environ.get(ENV_MODEL, "")

    # Если ключа нет — LM Studio
    if not api_key:
        return {
            "api_key": "",
            "base_url": DEFAULT_BASE_URL,
            "model": DEFAULT_MODEL,
        }

    # Если URL не задан в env — подставляем API URL
    if not base_url:
        base_url = DEFAULT_BASE_URL

    return {
        "api_key": api_key,
        "base_url": base_url,
        "model": model or DEFAULT_MODEL,
    }


# Глобальная переменная — читается один раз при импорте
_config = _read_config()


def get_api_key() -> str:
    """API ключ. Пустой строка если LM Studio."""
    return _config["api_key"]


def get_base_url() -> str:
    """Base URL. localhost если LM Studio."""
    return _config["base_url"]


def get_model() -> str:
    """Модель. local-model если LM Studio."""
    return _config["model"]


def is_api_configured() -> bool:
    """Есть ли API ключ — используем API или LM Studio."""
    return bool(_config["api_key"])
