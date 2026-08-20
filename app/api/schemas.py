from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class StartRunRequest(BaseModel):
    run_id: str | None = None
    seed: int = 42
    start_at: datetime | None = None
    duration_hours: int = Field(default=24, ge=1)
    interval_minutes: int = Field(default=10, ge=1)
    product_cycle_minutes: int = Field(default=20, ge=1)
    rate_profile: str = "balanced_demo"
    speed: float = Field(default=60.0, gt=0)
    continuous: bool = True
    publish_opcua: bool = True
