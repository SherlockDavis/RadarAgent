from __future__ import annotations

from typing import Any, Literal

from apscheduler.triggers.cron import CronTrigger
from pydantic import BaseModel, Field, field_validator


class SubscriptionFilter(BaseModel):
    keywords_boost: list[str] = Field(default_factory=list)
    keywords_ignore: list[str] = Field(default_factory=list)
    min_score: float = 6.0
    source_whitelist: list[str] = Field(default_factory=list)

    @field_validator("min_score")
    @classmethod
    def _score_range(cls, v: float) -> float:
        if not 0.0 <= v <= 10.0:
            raise ValueError("min_score must be in [0, 10]")
        return v


class Channel(BaseModel):
    type: Literal["email"]
    config: dict[str, Any]


class SubscriptionCreate(BaseModel):
    user_id: int
    name: str
    interest_profile: str
    filter: SubscriptionFilter = Field(default_factory=SubscriptionFilter)
    schedule: str = "0 8 * * *"
    channels: list[Channel]
    format: Literal["digest", "alert", "summary"] = "digest"
    enabled: bool = True

    @field_validator("schedule")
    @classmethod
    def _valid_cron(cls, v: str) -> str:
        try:
            CronTrigger.from_crontab(v)
        except (ValueError, KeyError) as exc:
            raise ValueError(f"invalid cron expression: {v!r}") from exc
        return v


class Subscription(SubscriptionCreate):
    id: int
    created_at: str
