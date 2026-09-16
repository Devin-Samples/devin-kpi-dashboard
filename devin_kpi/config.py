"""Settings loaded from environment / .env file."""

from __future__ import annotations

from functools import cached_property
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DEVIN_API_KEY: str | None = None
    DEVIN_API_BASE_URL: str = "https://api.devin.ai"
    DEVIN_ORG_ID: str | None = None

    ACU_UNIT_PRICE: float | None = None

    GITHUB_TOKEN: str | None = None
    GITLAB_TOKEN: str | None = None
    AZURE_DEVOPS_PAT: str | None = None

    JIRA_BASE_URL: str | None = None
    JIRA_EMAIL: str | None = None
    JIRA_API_TOKEN: str | None = None
    JIRA_STORY_POINTS_FIELD: str = "customfield_10016"
    LINEAR_API_KEY: str | None = None

    ISSUE_KEY_REGEX: str = r"[A-Z][A-Z0-9]+-\d+"

    SEAT_COUNT: int | None = None

    DATABASE_PATH: str = "data/devin_kpi.sqlite"
    DEMO_DATABASE_PATH: str = "data/demo.sqlite"
    CONSUMPTION_DAY_TZ: str = "America/Los_Angeles"

    @property
    def demo_mode(self) -> bool:
        return self.DEVIN_API_KEY is None

    @property
    def acu_price_set(self) -> bool:
        return self.ACU_UNIT_PRICE is not None

    @property
    def effective_acu_unit_price(self) -> float | None:
        """ACU price used for dollar KPIs. In demo mode with no explicit
        price configured, assume $2.00/ACU so dollar KPIs render."""
        if self.ACU_UNIT_PRICE is not None:
            return self.ACU_UNIT_PRICE
        if self.demo_mode:
            return 2.0
        return None

    @cached_property
    def resolved_db_path(self) -> Path:
        raw = self.DEMO_DATABASE_PATH if self.demo_mode else self.DATABASE_PATH
        return Path(raw)
