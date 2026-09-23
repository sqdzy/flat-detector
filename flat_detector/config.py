"""Explicit environment config. No credentials are ever passed to model-visible tools."""
from dataclasses import dataclass
import os

@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv("FD_DATABASE_URL", "sqlite:///./dev.db")
    telegram_token: str = os.getenv("FD_TELEGRAM_TOKEN", "")
    telegram_token_file: str = os.getenv("FD_TELEGRAM_TOKEN_FILE", "")
    admin_token: str = os.getenv("FD_ADMIN_TOKEN", "")
    demo_mode: bool = os.getenv("FD_DEMO_MODE", "false").lower() == "true"
    demo_delivery: bool = os.getenv("FD_DEMO_DELIVERY", "false").lower() == "true"
    # NEVER set admin token using a URL or expose the MCP port on 0.0.0.0 without auth.
    mcp_host: str = os.getenv("FD_MCP_HOST", "127.0.0.1")


def get_settings() -> Settings:
    # The class dataclass defaults are evaluated at import; deployment sets env before process start.
    return Settings()
