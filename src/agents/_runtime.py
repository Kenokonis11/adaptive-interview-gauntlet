"""Shared runtime helpers for pydantic-ai agents."""

from __future__ import annotations

import json
import os
from typing import Any

from pydantic import BaseModel

try:
    from pydantic_ai import Agent
except ImportError:  # pragma: no cover
    Agent = None

# No fallback chain — lock to gemini-2.5-flash only.
# Older models (2.0-flash, 1.5-flash) return 404 for new API keys.
# Transient 503s are handled by the Try Again button in the UI.
_FALLBACK_MODELS: list[str] = []


def get_default_model() -> str:
    """Return the pydantic-ai model string, ensuring the google-gla: provider prefix is present."""
    model = os.getenv("GAUNTLET_MODEL", "google-gla:gemini-2.5-flash")
    # Normalise bare Gemini model names that lack a provider prefix
    if model.startswith("gemini-") and ":" not in model:
        model = f"google-gla:{model}"
    return model


def _is_capacity_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(k in msg for k in (
        "503", "overloaded", "unavailable", "resource_exhausted", "quota_exceeded",
        "404", "not_found", "no longer available",  # deprecated / removed models
    ))


def _build_agent(model: str, system_prompt: str, result_type: type[BaseModel] | None = None) -> Any:
    """Build a pydantic-ai Agent for a specific model string."""
    if Agent is None:  # pragma: no cover
        raise ImportError("pydantic_ai is not available in the current environment.")
    if result_type is None:
        return Agent(model=model, system_prompt=system_prompt)
    try:
        return Agent(model=model, system_prompt=system_prompt, output_type=result_type)
    except TypeError:
        return Agent(model=model, system_prompt=system_prompt, result_type=result_type)


def create_agent(system_prompt: str, result_type: type[BaseModel] | None = None) -> Any:
    """Create a pydantic-ai agent using the configured model. Kept for compatibility."""
    return _build_agent(get_default_model(), system_prompt, result_type)


def run_text(system_prompt: str, prompt: str) -> str:
    """Create an agent and run it, with automatic model fallback on 503/overload errors.

    Tries the primary model first, then falls back through _FALLBACK_MODELS.
    Only falls back on capacity errors — auth errors (400/401) are re-raised immediately.
    """
    primary = get_default_model()
    models = [primary] + [m for m in _FALLBACK_MODELS if m != primary]

    last_exc: Exception | None = None
    for model in models:
        try:
            agent = _build_agent(model, system_prompt, None)
            result = agent.run_sync(prompt)
            payload = _extract_payload(result)
            if isinstance(payload, str):
                return payload
            if isinstance(payload, BaseModel):
                return payload.model_dump_json(indent=2)
            if isinstance(payload, dict):
                return json.dumps(payload, indent=2)
            return str(payload)
        except Exception as exc:
            if _is_capacity_error(exc):
                last_exc = exc
                continue
            raise

    raise last_exc or RuntimeError("All models in fallback chain exhausted.")


def run_structured(system_prompt: str, prompt: str, result_type: type[BaseModel]) -> BaseModel:
    """Create an agent and run it for structured output, with automatic model fallback on 503/overload errors."""
    primary = get_default_model()
    models = [primary] + [m for m in _FALLBACK_MODELS if m != primary]

    last_exc: Exception | None = None
    for model in models:
        try:
            agent = _build_agent(model, system_prompt, result_type)
            result = agent.run_sync(prompt)
            payload = _extract_payload(result)
            if isinstance(payload, result_type):
                return payload
            return result_type.model_validate(payload)
        except Exception as exc:
            if _is_capacity_error(exc):
                last_exc = exc
                continue
            raise

    raise last_exc or RuntimeError("All models in fallback chain exhausted.")


def _extract_payload(result: Any) -> Any:
    for attr in ("output", "data", "result"):
        if hasattr(result, attr):
            return getattr(result, attr)
    return result


def state_value(state_dict: dict[str, Any], *keys: str, default: Any = None) -> Any:
    """Return the first matching state value across multiple schema variants."""
    for key in keys:
        if key in state_dict and state_dict[key] is not None:
            return state_dict[key]
    return default


def dump_for_prompt(value: Any) -> str:
    """Serialize state values for prompt interpolation."""
    normalized = _normalize(value)
    if isinstance(normalized, str):
        return normalized
    return json.dumps(normalized, indent=2, sort_keys=True)


def normalize_question(question: Any) -> dict[str, Any]:
    """Convert question objects into a prompt-friendly dict."""
    data = _normalize(question)
    if not isinstance(data, dict):
        return {"text": "", "expected_concepts": []}
    return {
        "text": data.get("text") or data.get("prompt") or "",
        "skill": data.get("skill") or "",
        "difficulty": data.get("difficulty") or "",
        "expected_concepts": data.get("expected_concepts") or data.get("expected_artifacts") or [],
    }


def mastery_for_skill(state_dict: dict[str, Any], skill: str) -> float:
    """Read mastery using either the doc schema or the current scaffold schema."""
    mastery = state_value(state_dict, "mastery", "mastery_snapshot", default={}) or {}
    if isinstance(mastery, dict):
        value = mastery.get(skill, 0.0)
        return float(value or 0.0)
    return 0.0


def current_proxy(state_dict: dict[str, Any]) -> dict[str, Any]:
    """Find the proxy config for the current skill."""
    skill = state_value(state_dict, "current_skill", default="") or ""
    proxies = state_value(state_dict, "skill_proxies", default=[]) or []
    normalized = _normalize(proxies)

    if isinstance(normalized, dict):
        proxy = normalized.get(skill, {})
        if isinstance(proxy, dict):
            return {
                "original_skill": proxy.get("original_skill", skill),
                "proxy_type": proxy.get("proxy_type", "python_general"),
                "proxy_context": proxy.get("proxy_context") or proxy.get("signals", []),
                "test_dataset": proxy.get("test_dataset", ""),
            }

    if isinstance(normalized, list):
        for proxy in normalized:
            if not isinstance(proxy, dict):
                continue
            if proxy.get("original_skill") == skill or proxy.get("name") == skill:
                return {
                    "original_skill": proxy.get("original_skill") or proxy.get("name") or skill,
                    "proxy_type": proxy.get("proxy_type", "python_general"),
                    "proxy_context": proxy.get("proxy_context") or proxy.get("signals", []),
                    "test_dataset": proxy.get("test_dataset", ""),
                }

    return {"original_skill": skill, "proxy_type": "python_general", "proxy_context": "", "test_dataset": ""}


def normalize_proxies(proxies: Any) -> list[dict[str, Any]]:
    """Convert the skill proxy collection into a list of dicts."""
    normalized = _normalize(proxies)
    if isinstance(normalized, list):
        return [proxy for proxy in normalized if isinstance(proxy, dict)]
    if isinstance(normalized, dict):
        results = []
        for name, proxy in normalized.items():
            if isinstance(proxy, dict):
                results.append({"original_skill": name, **proxy})
            else:
                results.append({"original_skill": name})
        return results
    return []


def _normalize(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    if isinstance(value, dict):
        return {key: _normalize(item) for key, item in value.items()}
    return value
