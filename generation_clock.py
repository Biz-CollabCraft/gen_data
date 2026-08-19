"""Clock policies for accelerated replay and physical wall-clock live mode."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Callable


UTC = timezone.utc
ACCELERATED_MODE = "accelerated"
WALL_CLOCK_MODE = "wall_clock"
SUPPORTED_CLOCK_MODES = {ACCELERATED_MODE, WALL_CLOCK_MODE}


def normalize_clock_mode(value: object) -> str:
    mode = str(value or ACCELERATED_MODE).strip().lower()
    aliases = {
        "simulation": ACCELERATED_MODE,
        "replay": ACCELERATED_MODE,
        "wall": WALL_CLOCK_MODE,
        "live": WALL_CLOCK_MODE,
    }
    mode = aliases.get(mode, mode)
    if mode not in SUPPORTED_CLOCK_MODES:
        raise ValueError(
            f"GEN_DATA_CLOCK_MODE must be one of {sorted(SUPPORTED_CLOCK_MODES)}; got {value!r}"
        )
    return mode


def _require_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("clock timestamps must include timezone information")
    return value.astimezone(UTC)


def ceil_wall_clock_boundary(now: datetime, interval_minutes: int) -> datetime:
    """Return the first UTC cadence boundary at-or-after ``now``.

    Boundaries are anchored to the Unix epoch, so a ten-minute cadence remains
    ``:00, :10, :20, ...`` across process restarts and cannot accumulate sleep
    drift.
    """

    current = _require_aware(now)
    cadence_seconds = int(interval_minutes) * 60
    if cadence_seconds <= 0:
        raise ValueError("interval_minutes must be positive")
    epoch_seconds = int(current.timestamp())
    floor_seconds = epoch_seconds - (epoch_seconds % cadence_seconds)
    floor = datetime.fromtimestamp(floor_seconds, tz=UTC)
    return floor if current == floor else floor + timedelta(seconds=cadence_seconds)


def next_wall_clock_boundary(
    now: datetime,
    *,
    interval_minutes: int,
    last_emitted_at: datetime | None = None,
) -> datetime:
    """Plan the next physical-sensor emission without backfilling downtime.

    A restart aligns to the current/future wall-clock boundary.  A persisted
    watermark is only a lower bound, which prevents duplicate timestamps and
    protects against temporary OS/NTP clock rollback.
    """

    candidate = ceil_wall_clock_boundary(now, interval_minutes)
    if last_emitted_at is None:
        return candidate
    last = _require_aware(last_emitted_at)
    tick = timedelta(minutes=int(interval_minutes))
    if candidate <= last:
        return last + tick
    return candidate


def accelerated_start_time(
    now: datetime,
    *,
    interval_minutes: int,
    backfill_hours: int,
    last_emitted_at: datetime | None = None,
) -> datetime:
    """Preserve the historical accelerated/replay daemon start policy."""

    current = _require_aware(now)
    if last_emitted_at is not None:
        return _require_aware(last_emitted_at) + timedelta(minutes=int(interval_minutes))
    return current - timedelta(hours=int(backfill_hours))


class SystemClock:
    """Injectable system clock used by the production daemon."""

    def now(self) -> datetime:
        return datetime.now(tz=UTC)

    def sleep(self, seconds: float) -> None:
        time.sleep(max(0.0, float(seconds)))

    def sleep_until(
        self,
        deadline: datetime,
        *,
        cancelled: Callable[[], bool] | None = None,
    ) -> None:
        target = _require_aware(deadline)
        while True:
            if cancelled is not None and cancelled():
                return
            delay = (target - self.now()).total_seconds()
            if delay <= 0:
                return
            # Keep shutdown latency bounded even for a ten-minute live cadence.
            self.sleep(min(delay, 1.0))
