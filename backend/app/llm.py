"""Thin wrapper around the Claude API.

The LLM is used for language understanding (intent, constraints, criteria), judgement on
soft criteria, and writing explanations. Ranking itself is done by the deterministic decision
engine over collected evidence, so recommendations stay traceable.

Every caller has a non-LLM fallback, so the app still runs (in a degraded way) without a key.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from .config import settings

log = logging.getLogger("decisionos.llm")

_client = None
# Last failure reason (None after a successful call) so /api/health can tell "key present" from "key works".
last_error: str | None = None


def _get_client():
    global _client
    if _client is None:
        import anthropic  # imported lazily so the engine can be tested without the SDK
        headers = {"anthropic-workspace-id": settings.anthropic_workspace_id} if settings.anthropic_workspace_id else None
        _client = anthropic.Anthropic(api_key=settings.anthropic_api_key, default_headers=headers)
    return _client


def available() -> bool:
    return settings.llm_enabled


_probed = False


def status() -> tuple[bool, str | None]:
    """(works, error). Sends one tiny request the first time so a rejected key shows up before any decision."""
    global _probed
    if not available():
        return False, "ANTHROPIC_API_KEY is not set"
    if not _probed:
        _probed = True
        complete_text("Reply with OK.", "ping", max_tokens=64)
    return last_error is None, last_error


def complete_text(system: str, user: str, max_tokens: int = 1200) -> str | None:
    global last_error
    if not available():
        return None
    try:
        resp = _get_client().messages.create(
            model=settings.anthropic_model,
            max_tokens=max_tokens,
            # Current models reject custom sampling params; low effort keeps these short
            # extraction/explanation calls fast and leaves room in max_tokens for the answer.
            output_config={"effort": "low"},
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        last_error = None
        return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()
    except Exception as exc:  # network/auth/rate-limit: degrade gracefully
        body = getattr(exc, "body", None)
        api_msg = ((body.get("error") or {}).get("message")) if isinstance(body, dict) else None
        last_error = api_msg or getattr(exc, "message", None) or str(exc)
        log.warning("Claude call failed: %s", exc)
        return None


_JSON_RE = re.compile(r"\{.*\}|\[.*\]", re.S)


def extract_json(text: str | None) -> Any:
    if not text:
        return None
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    candidate = fenced.group(1) if fenced else text
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        m = _JSON_RE.search(candidate)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                return None
    return None


def complete_json(system: str, user: str, max_tokens: int = 1500) -> Any:
    """Ask Claude for JSON only; returns parsed JSON or None."""
    sys = system + "\n\nRespond with a single valid JSON value only. No prose, no markdown fences."
    return extract_json(complete_text(sys, user, max_tokens=max_tokens))
