"""NOAA Next Generation Fire System (NGFS) client."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from io import StringIO
from typing import Any

from aiohttp import ClientError, ClientSession

from .const import NGFS_API_ROOT, NGFS_FETCH_COUNT


class NgfsError(Exception):
    """NGFS request or response failed."""


@dataclass(frozen=True)
class NgfsDetection:
    latitude: float
    longitude: float
    acquired: datetime
    satellite: str | None = None
    confidence: str | None = None
    frp: float | None = None
    quality_flag: int | None = None
    feature_tracking_id: str | None = None
    known_incident_name: str | None = None
    daynight: str | None = None


def _float(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int | None:
    try:
        return int(float(value)) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _time(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class NgfsClient:
    """Read recent scene detections from NOAA's public NGFS OGC endpoint."""

    def __init__(self, session: ClientSession) -> None:
        self._session = session

    async def fetch(
        self, collection: str, bbox: tuple[float, float, float, float], lookback: timedelta
    ) -> list[NgfsDetection]:
        lat_s, lon_w, lat_n, lon_e = bbox
        now = datetime.now(timezone.utc)
        start = now - lookback
        url = f"{NGFS_API_ROOT}/collections/{collection}/items"
        params = {
            "bbox": f"{lon_w},{lat_s},{lon_e},{lat_n}",
            "datetime": f"{start.isoformat().replace('+00:00','Z')}/{now.isoformat().replace('+00:00','Z')}",
            "datetime-column": "acq_date_time",
            "limit": str(NGFS_FETCH_COUNT),
            "offset": "0",
            "f": "csv",
            "sortby": "-acq_date_time",
        }
        try:
            async with self._session.get(url, params=params, timeout=30) as response:
                text = await response.text()
                if response.status != 200:
                    raise NgfsError(f"HTTP {response.status}: {text[:200]}")
        except (ClientError, TimeoutError) as err:
            raise NgfsError(str(err)) from err

        rows = csv.DictReader(StringIO(text))
        detections: list[NgfsDetection] = []
        for row in rows:
            lat, lon = _float(row.get("latitude")), _float(row.get("longitude"))
            acquired = _time(row.get("acq_date_time") or row.get("pixel_date_time_utc"))
            if lat is None or lon is None or acquired is None:
                continue
            detections.append(NgfsDetection(
                latitude=lat, longitude=lon, acquired=acquired,
                satellite=row.get("satellite") or None,
                confidence=row.get("confidence") or None, frp=_float(row.get("frp")),
                quality_flag=_int(row.get("quality_flag")),
                feature_tracking_id=row.get("feature_tracking_id") or None,
                known_incident_name=row.get("known_incident_name") or None,
                daynight=row.get("daynight") or None,
            ))
        return detections
