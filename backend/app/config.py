"""Runtime configuration, loaded from environment variables (and backend/.env if present)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    """Tiny .env loader so the project has no hard dependency on python-dotenv."""
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


_load_dotenv()


def _bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    anthropic_model: str = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5")
    # Only needed for API keys that aren't scoped to a workspace.
    anthropic_workspace_id: str = os.getenv("ANTHROPIC_WORKSPACE_ID", "")
    serpapi_key: str = os.getenv("SERPAPI_KEY", "")
    # Force demo data even when a key is present (useful for rehearsing the demo offline).
    demo_mode: bool = _bool("DEMO_MODE", False)

    database_path: str = os.getenv("DATABASE_PATH", str(BASE_DIR / "decisionos.db"))
    search_cache_ttl_s: int = int(os.getenv("SEARCH_CACHE_TTL_S", "1800"))

    # Region defaults (India-first, overridable).
    country: str = os.getenv("DEFAULT_COUNTRY", "in")
    language: str = os.getenv("DEFAULT_LANGUAGE", "en")
    currency: str = os.getenv("DEFAULT_CURRENCY", "INR")
    timezone: str = os.getenv("DEFAULT_TIMEZONE", "Asia/Kolkata")
    amazon_domain: str = os.getenv("AMAZON_DOMAIN", "amazon.in")

    frontend_origin: str = os.getenv("FRONTEND_ORIGIN", "http://localhost:3000")
    public_backend_url: str = os.getenv("PUBLIC_BACKEND_URL", "http://localhost:8000")

    # Google Calendar OAuth (optional).
    google_client_id: str = os.getenv("GOOGLE_CLIENT_ID", "")
    google_client_secret: str = os.getenv("GOOGLE_CLIENT_SECRET", "")

    # Optional notification channels.
    smtp_host: str = os.getenv("SMTP_HOST", "")
    smtp_port: int = int(os.getenv("SMTP_PORT", "587"))
    smtp_user: str = os.getenv("SMTP_USER", "")
    smtp_password: str = os.getenv("SMTP_PASSWORD", "")
    notify_email_to: str = os.getenv("NOTIFY_EMAIL_TO", "")
    telegram_bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    telegram_chat_id: str = os.getenv("TELEGRAM_CHAT_ID", "")

    proactive_interval_s: int = int(os.getenv("PROACTIVE_INTERVAL_S", "30"))
    # Shared secret the workspace agent sends; empty means local-only, no check.
    agent_token: str = os.getenv("AGENT_TOKEN", "")

    @property
    def use_live_search(self) -> bool:
        return bool(self.serpapi_key) and not self.demo_mode

    @property
    def llm_enabled(self) -> bool:
        return bool(self.anthropic_api_key)


settings = Settings()
