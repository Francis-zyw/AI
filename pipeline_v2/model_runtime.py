from __future__ import annotations

import configparser
import os
from pathlib import Path
from typing import Any, Dict

ENV_STEP_PREFIX = "PIPELINE_"

DEFAULT_MODELS_CONFIG_NAME = "runtime_models.ini"
DEFAULT_OPENAI_MODEL = "gpt-5.4"
DEFAULT_REASONING_EFFORT = "medium"
DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"


def get_default_models_config_path() -> Path:
    return Path(__file__).resolve().parent / DEFAULT_MODELS_CONFIG_NAME


def _read_config(path: Path) -> configparser.ConfigParser:
    parser = configparser.ConfigParser()
    parser.read(path, encoding="utf-8")
    return parser


def normalize_model_name(model: str | None, default: str | None = None) -> str | None:
    text = str(model or "").strip()
    if not text:
        return default
    if "/" in text:
        provider_prefix, candidate = text.split("/", 1)
        if provider_prefix.strip() and candidate.strip():
            return candidate.strip()
    return text


def _step_env_name(step: str, key: str) -> str:
    return f"{ENV_STEP_PREFIX}{str(step).strip().upper()}_{str(key).strip().upper()}"


def _pick_env_or_config(step: str, key: str, config_value: str | None) -> str | None:
    env_value = os.getenv(_step_env_name(step, key))
    if env_value is not None and str(env_value).strip():
        return str(env_value).strip()
    return config_value


def load_step_model_config(step: str, config_path: str | Path | None = None) -> Dict[str, Any]:
    path = Path(config_path).expanduser().resolve() if config_path else get_default_models_config_path()
    if not path.exists():
        return {}
    parser = _read_config(path)
    if not parser.has_section(step):
        return {}
    get = lambda key: str(parser.get(step, key, fallback="")).strip() or None
    return {
        "config_path": str(path),
        "model": _pick_env_or_config(step, "MODEL", get("model")),
        "reasoning_effort": _pick_env_or_config(step, "REASONING_EFFORT", get("reasoning_effort")),
        "provider_mode": _pick_env_or_config(step, "PROVIDER_MODE", get("provider_mode")),
        "api_key_env": _pick_env_or_config(step, "API_KEY_ENV", get("api_key_env")),
        "base_url_env": _pick_env_or_config(step, "BASE_URL_ENV", get("base_url_env")),
        "validation_fallback_model": _pick_env_or_config(step, "VALIDATION_FALLBACK_MODEL", get("validation_fallback_model")),
        "validation_provider_mode": _pick_env_or_config(step, "VALIDATION_PROVIDER_MODE", get("validation_provider_mode")),
        "validation_api_key_env": _pick_env_or_config(step, "VALIDATION_API_KEY_ENV", get("validation_api_key_env")),
        "validation_base_url_env": _pick_env_or_config(step, "VALIDATION_BASE_URL_ENV", get("validation_base_url_env")),
    }


def _resolve_env(api_key_env: str | None, base_url_env: str | None, provider_mode: str | None) -> Dict[str, Any]:
    api_key = os.getenv(api_key_env) if api_key_env else None
    base_url = os.getenv(base_url_env) if base_url_env else None
    return {
        "provider_mode": provider_mode,
        "api_key_env": api_key_env,
        "base_url_env": base_url_env,
        "openai_api_key": api_key,
        "openai_base_url": base_url,
        "use_codex_subscription": str(provider_mode or '').strip().lower() == 'codex',
    }


def resolve_provider_env(step_config: Dict[str, Any]) -> Dict[str, Any]:
    provider_mode = str(step_config.get("provider_mode") or "").strip() or None
    api_key_env = str(step_config.get("api_key_env") or "").strip() or None
    base_url_env = str(step_config.get("base_url_env") or "").strip() or None
    return _resolve_env(api_key_env=api_key_env, base_url_env=base_url_env, provider_mode=provider_mode)


def resolve_validation_provider_env(step_config: Dict[str, Any]) -> Dict[str, Any]:
    provider_mode = str(step_config.get("validation_provider_mode") or "").strip() or None
    api_key_env = str(step_config.get("validation_api_key_env") or "").strip() or None
    base_url_env = str(step_config.get("validation_base_url_env") or "").strip() or None
    if not api_key_env and not base_url_env and not provider_mode:
        return resolve_provider_env(step_config)
    return _resolve_env(api_key_env=api_key_env, base_url_env=base_url_env, provider_mode=provider_mode)
