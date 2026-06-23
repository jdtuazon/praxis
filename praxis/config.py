"""Typed configuration loaded from environment / .env."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Load .env once at import so the CLI and server both pick it up.
load_dotenv()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", extra="ignore", env_file=".env")

    # ── LLM ──────────────────────────────────────────────────────────────────
    llm_provider: Literal["anthropic", "openai", "scripted"] = Field(
        default="anthropic", alias="PRAXIS_LLM_PROVIDER"
    )
    # Reasoning model drives planning + synthesis (quality matters most here).
    llm_model: str = Field(default="claude-sonnet-4-6", alias="PRAXIS_LLM_MODEL")
    anthropic_api_key: str | None = Field(default=None, alias="ANTHROPIC_API_KEY")
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")

    # ── Platform: Linear ───────────────────────────────────────────────────────
    linear_api_key: str | None = Field(default=None, alias="LINEAR_API_KEY")
    linear_api_url: str = Field(default="https://api.linear.app/graphql", alias="LINEAR_API_URL")

    # ── Memory ─────────────────────────────────────────────────────────────────
    memory_path: str = Field(default=".praxis/memory.sqlite", alias="PRAXIS_MEMORY_PATH")

    # ── Synthesis ───────────────────────────────────────────────────────────────
    synthesis_max_attempts: int = Field(default=3, alias="PRAXIS_SYNTHESIS_MAX_ATTEMPTS")
    # A synthesized capability is promoted candidate→trusted after this many
    # successful real executions.
    capability_promote_after: int = Field(default=2, alias="PRAXIS_CAPABILITY_PROMOTE_AFTER")

    # ── Safety ──────────────────────────────────────────────────────────────────
    # If true, side-effecting capabilities may be validated with a real
    # create-canary-then-inverse-op probe (in a sandbox team, with [PRAXIS-PROBE]
    # markers). If false, the synthesizer stops at non-destructive test tiers.
    require_rollback_journal: bool = Field(default=True, alias="PRAXIS_REQUIRE_ROLLBACK_JOURNAL")
    # Team used for destructive synthesis canaries (keeps probes out of real teams).
    sandbox_team_key: str | None = Field(default=None, alias="PRAXIS_SANDBOX_TEAM_KEY")

    def memory_file(self) -> Path:
        p = Path(self.memory_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def llm_ready(self) -> bool:
        if self.llm_provider == "anthropic":
            return bool(self.anthropic_api_key)
        if self.llm_provider == "openai":
            return bool(self.openai_api_key)
        return True  # scripted

    def platform_ready(self) -> bool:
        return bool(self.linear_api_key)


def load_settings() -> Settings:
    return Settings()
