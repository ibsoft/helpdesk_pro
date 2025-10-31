"""Utility MCP tools for working with time."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

from .base import BaseTool, ToolExecutionError


class TimeNowArgs(BaseModel):
    timezone: str = Field(
        default="Europe/Athens",
        description="IANA timezone identifier to use for the reported current time.",
    )


class TimeNowResult(BaseModel):
    timezone: str
    datetime_iso: str
    datetime_utc_iso: str
    epoch_seconds: float
    date: str
    time: str
    human: str


class TimeNowTool(BaseTool[TimeNowArgs, TimeNowResult]):
    name = "time_now"
    description = "Return the current datetime for a given timezone (default Europe/Athens)."
    input_model = TimeNowArgs
    output_model = TimeNowResult

    async def _run(self, arguments: TimeNowArgs) -> Dict[str, Any]:
        try:
            tz = ZoneInfo(arguments.timezone)
        except Exception as exc:  # pragma: no cover - ZoneInfo errors vary
            raise ToolExecutionError(f"Unknown timezone: {arguments.timezone}") from exc

        now = datetime.now(tz)
        now_utc = now.astimezone(timezone.utc)

        return {
            "timezone": arguments.timezone,
            "datetime_iso": now.isoformat(),
            "datetime_utc_iso": now_utc.isoformat(),
            "epoch_seconds": now.timestamp(),
            "date": now.strftime("%Y-%m-%d"),
            "time": now.strftime("%H:%M:%S"),
            "human": now.strftime("%A, %d %B %Y %H:%M:%S %Z"),
        }


__all__ = [
    "TimeNowTool",
]
