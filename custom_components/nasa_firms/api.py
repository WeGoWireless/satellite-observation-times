"""Clients for the NASA FIRMS MapServer WFS GeoJSON endpoints and met.no.

Deliberately free of Home Assistant imports: this module is the part that
gets lifted into a standalone PyPI package for an eventual Home Assistant
Core submission (Core requires protocol logic to live in a published
library). Keep it that way.
"""
from __future__ import annotations

import asyncio
import json
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import aiohttp

BASE_URL = "https://firms.modaps.eosdis.nasa.gov/mapserver/wfs/{region}/{map_key}/"

KM_PER_DEG_LAT = 111.0
EARTH_DIAMETER_KM = 12742.0

# FIRMS WFS layer name fragments (fires_<satellite>_<window>) and UI labels.
SATELLITES = {
    "noaa20": "VIIRS · NOAA-20 (JPSS-1)",
    "noaa21": "VIIRS · NOAA-21 (JPSS-2)",
    "snpp": "VIIRS · Suomi NPP",
    "modis": "MODIS · Terra/Aqua",
}

# Known FIRMS MapServer regions. If yours is missing, please open an issue.
REGIONS = [
    "Alaska",
    "Australia_NewZealand",
    "Canada",
    "Central_America",
    "Europe",
    "Northern_and_Central_Africa",
    "Russia_and_Asia",
    "South_America",
    "South_Asia",
    "SouthEast_Asia",
    "Southern_Africa",
    "USA_contiguous_and_Hawaii",
]

WINDOW_24H = "24hrs"
WINDOW_7D = "7days"

CONFIDENCE_RANK = {"low": 0, "nominal": 1, "high": 2}

# Fire radiative power bands, in MW, as (lower bound, label), strongest first.
#
# Absolute thresholds on purpose. A scale relative to whatever is currently on
# screen would make the same colour mean something different from one view to
# the next, so no habit of reading it can ever form — the argument came from
# pyspilf in the community thread, who ran these exact bands against live data
# in his own Node-RED setup before the integration existed. Four bands for the
# same practical reason he settled on four: more and the map turns to mush.
#
# This describes radiated power, nothing else. It is not a hazard rating: a
# small fire next door outranks a large one two valleys away, and FRP knows
# nothing about either distance or terrain.
FRP_BANDS: tuple[tuple[float, str], ...] = (
    (100.0, "extreme"),
    (50.0, "high"),
    (10.0, "moderate"),
    (0.0, "low"),
)


def intensity_for_frp(frp: float | None) -> str | None:
    """Band a fire radiative power reading, or None when there is no reading."""
    if frp is None:
        return None
    for lower, label in FRP_BANDS:
        if frp >= lower:
            return label
    return "low"

# --- met.no Locationforecast 2.0 -----------------------------------------
# Free, no API key, arbitrary coordinates. https://api.met.no/doc/TermsOfService
# is binding; the parts that shape the code below:
#   * identify the application with a contact address in the User-Agent
#   * "don't repeat requests until the time indicated in the Expires header"
#   * send If-Modified-Since so unchanged forecasts cost a 304, not a payload
#   * "truncate all coordinates to max 4 decimals"
#   * data is CC BY 4.0 and must be credited (see const.ATTRIBUTION_WEATHER)
METNO_URL = "https://api.met.no/weatherapi/locationforecast/2.0/compact"

# ~1 km. Well inside met.no's 4-decimal limit, and deliberately coarser: they
# ask callers not to re-request for minimal location changes, and a fire's
# representative pixel shifts a few hundred metres between overpasses. The wind
# 1 km away is the same wind, so this keeps the cache warm across cycles.
WEATHER_COORD_DECIMALS = 2

# How far the chosen forecast step may sit from the moment we ask before we
# call it useless. Steps are hourly, so this only ever bites when a cached
# forecast has gone properly stale.
WEATHER_MAX_STEP_AGE = timedelta(hours=1)

# met.no permanently bans clients that keep pushing after being throttled.
WEATHER_RATE_LIMIT_BACKOFF = timedelta(hours=1)


class FirmsError(Exception):
    """Base error talking to FIRMS."""


class FirmsAuthError(FirmsError):
    """The MAP_KEY was rejected."""


class WeatherError(Exception):
    """Base error talking to the weather source.

    Deliberately *not* a FirmsError: fires are the product and wind is a
    nice-to-have, so the two failure modes must never be confused upstream.
    """


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two points in km."""
    rlat1, rlon1, rlat2, rlon2 = map(math.radians, (lat1, lon1, lat2, lon2))
    h = (
        math.sin((rlat2 - rlat1) / 2) ** 2
        + math.cos(rlat1) * math.cos(rlat2) * math.sin((rlon2 - rlon1) / 2) ** 2
    )
    return EARTH_DIAMETER_KM * math.asin(math.sqrt(h))


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial great-circle bearing from point 1 to point 2, in degrees.

    Not the flat approximation — that drifts noticeably away from the equator,
    and "which way is the fire" is exactly where you don't want a rough answer.
    """
    rlat1, rlat2 = math.radians(lat1), math.radians(lat2)
    dlon = math.radians(lon2 - lon1)
    y = math.sin(dlon) * math.cos(rlat2)
    x = math.cos(rlat1) * math.sin(rlat2) - math.sin(rlat1) * math.cos(rlat2) * math.cos(dlon)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


CARDINALS = (
    "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
    "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
)


def cardinal(degrees: float) -> str:
    """Compass point for a bearing, on the 16-point scale."""
    return CARDINALS[int(((degrees % 360) + 11.25) % 360 / 22.5)]


def bbox_around(
    lat: float, lon: float, radius_km: float
) -> tuple[float, float, float, float]:
    """(lat_s, lon_w, lat_n, lon_e) box enclosing a radius around a point.

    Note the radians conversion — feeding degrees to cos() flips the box
    inside out, which is exactly the bug users hit doing this by hand.
    """
    dlat = radius_km / KM_PER_DEG_LAT
    dlon = radius_km / (KM_PER_DEG_LAT * math.cos(math.radians(lat)))
    return (lat - dlat, lon - dlon, lat + dlat, lon + dlon)


def normalize_confidence(value: Any) -> str | None:
    """Map VIIRS letters (l/n/h) and MODIS numbers (0-100) to low/nominal/high."""
    if value is None:
        return None
    if isinstance(value, str):
        v = value.strip().lower()
        if v.startswith("l"):
            return "low"
        if v.startswith("n"):
            return "nominal"
        if v.startswith("h"):
            return "high"
        try:
            value = float(v)
        except ValueError:
            return None
    if isinstance(value, (int, float)):
        if value < 30:
            return "low"
        if value < 80:
            return "nominal"
        return "high"
    return None


@dataclass
class FirmsHotspot:
    """A single satellite fire detection."""

    latitude: float
    longitude: float
    satellite: str
    frp: float | None = None
    confidence: str | None = None
    raw_confidence: Any = None
    brightness: float | None = None
    acq_datetime: str | None = None
    daynight: str | None = None


@dataclass
class FirmsCluster:
    """One or more detections deduplicated into a logical fire."""

    id: str
    latitude: float
    longitude: float
    distance_km: float
    satellites: list[str]
    detections: int
    frp: float | None
    confidence: str | None
    brightness: float | None
    acq_datetime: str | None
    daynight: str | None
    bearing: float | None = None
    direction: str | None = None


def _conf_rank(conf: str | None) -> int:
    return CONFIDENCE_RANK.get(conf, -1) if conf else -1


def cluster_hotspots(
    hotspots_with_distance: list[tuple[FirmsHotspot, float]],
    cluster_radius_km: float = 1.0,
    origin: tuple[float, float] | None = None,
) -> list[FirmsCluster]:
    """Greedy dedupe: detections within cluster_radius_km collapse into one fire.

    Multiple satellites (and successive overpasses) report the same fire at
    slightly different pixel centers; without this, three-satellite setups
    show duplicate markers. Sorting by FRP first makes the strongest
    detection the cluster representative and the greedy pass deterministic.
    """
    ordered = sorted(hotspots_with_distance, key=lambda hd: -(hd[0].frp or 0.0))
    raw: list[dict[str, Any]] = []
    for hotspot, dist in ordered:
        target = None
        for c in raw:
            if (
                haversine_km(hotspot.latitude, hotspot.longitude, c["lat"], c["lon"])
                <= cluster_radius_km
            ):
                target = c
                break
        if target is None:
            raw.append(
                {
                    "lat": hotspot.latitude,
                    "lon": hotspot.longitude,
                    "dist": dist,
                    "sats": {hotspot.satellite},
                    "count": 1,
                    "frp": hotspot.frp,
                    "conf": hotspot.confidence,
                    "bright": hotspot.brightness,
                    "acq": hotspot.acq_datetime,
                    "daynight": hotspot.daynight,
                }
            )
            continue
        target["sats"].add(hotspot.satellite)
        target["count"] += 1
        if hotspot.frp is not None:
            target["frp"] = max(target["frp"] or 0.0, hotspot.frp)
        if _conf_rank(hotspot.confidence) > _conf_rank(target["conf"]):
            target["conf"] = hotspot.confidence
        if hotspot.acq_datetime and (
            target["acq"] is None or hotspot.acq_datetime > target["acq"]
        ):
            target["acq"] = hotspot.acq_datetime

    clusters = []
    for c in raw:
        brg = (
            bearing_deg(origin[0], origin[1], c["lat"], c["lon"])
            if origin is not None
            else None
        )
        clusters.append(
            FirmsCluster(
                id=f"{c['lat']:.2f}/{c['lon']:.2f}",
                latitude=c["lat"],
                longitude=c["lon"],
                distance_km=round(c["dist"], 1),
                satellites=sorted(c["sats"]),
                detections=c["count"],
                frp=c["frp"],
                confidence=c["conf"],
                brightness=c["bright"],
                acq_datetime=c["acq"],
                daynight=c["daynight"],
                bearing=round(brg) if brg is not None else None,
                direction=cardinal(brg) if brg is not None else None,
            )
        )
    clusters.sort(key=lambda c: c.distance_km)
    # Two distinct clusters can round to the same 0.01° id — disambiguate.
    seen: dict[str, int] = {}
    for cluster in clusters:
        n = seen.get(cluster.id, 0)
        seen[cluster.id] = n + 1
        if n:
            cluster.id = f"{cluster.id}#{n + 1}"
    return clusters


class FirmsClient:
    """Minimal async client for the FIRMS WFS GeoJSON endpoints."""

    def __init__(
        self, session: aiohttp.ClientSession, map_key: str, region: str
    ) -> None:
        self._session = session
        self._map_key = map_key
        self._region = region

    async def fetch(
        self,
        satellite: str,
        window: str,
        bbox: tuple[float, float, float, float],
        count: int = 1000,
    ) -> list[FirmsHotspot]:
        """Fetch hotspots for one satellite layer within a bounding box."""
        lat_s, lon_w, lat_n, lon_e = bbox
        url = BASE_URL.format(region=self._region, map_key=self._map_key)
        params = {
            "SERVICE": "WFS",
            "REQUEST": "GetFeature",
            "VERSION": "2.0.0",
            "TYPENAME": f"ms:fires_{satellite}_{window}",
            "STARTINDEX": "0",
            "COUNT": str(count),
            "SRSNAME": "urn:ogc:def:crs:EPSG::4326",
            "BBOX": f"{lat_s:.4f},{lon_w:.4f},{lat_n:.4f},{lon_e:.4f},urn:ogc:def:crs:EPSG::4326",
            "outputformat": "geojson",
        }
        try:
            async with asyncio.timeout(60):
                resp = await self._session.get(url, params=params)
                body = await resp.text()
        except (TimeoutError, aiohttp.ClientError) as err:
            raise FirmsError(f"FIRMS request failed: {err}") from err
        if resp.status in (401, 403):
            raise FirmsAuthError(f"MAP_KEY rejected (HTTP {resp.status})")
        if resp.status != 200:
            raise FirmsError(f"FIRMS returned HTTP {resp.status}: {body[:200]}")
        try:
            data = json.loads(body)
        except ValueError as err:
            # Invalid keys come back as an HTML/XML error page, not GeoJSON.
            if "map_key" in body.lower():
                raise FirmsAuthError(f"MAP_KEY rejected: {body[:200]}") from err
            raise FirmsError(f"Unexpected non-GeoJSON response: {body[:200]}") from err
        features = data.get("features") or []
        return [
            h
            for h in (self._parse_feature(f, satellite) for f in features)
            if h is not None
        ]

    @staticmethod
    def _parse_feature(feature: dict, satellite: str) -> FirmsHotspot | None:
        """Tolerantly extract one hotspot from a GeoJSON feature."""
        props = feature.get("properties") or {}

        def _num(key: str) -> float | None:
            try:
                v = props.get(key)
                return float(v) if v is not None else None
            except (TypeError, ValueError):
                return None

        lat, lon = _num("latitude"), _num("longitude")
        if lat is None or lon is None:
            # Fall back to the geometry (GeoJSON axis order: lon, lat).
            coords = (feature.get("geometry") or {}).get("coordinates") or []
            if len(coords) < 2:
                return None
            try:
                lon, lat = float(coords[0]), float(coords[1])
            except (TypeError, ValueError):
                return None

        acq = None
        if props.get("acq_date"):
            # acq_time arrives as HHMM, sometimes float-formatted ("1134.0").
            try:
                t = f"{int(float(props.get('acq_time') or 0)):04d}"
            except (TypeError, ValueError):
                t = "0000"
            acq = f"{props['acq_date']} {t[:2]}:{t[2:]} UTC"

        return FirmsHotspot(
            latitude=lat,
            longitude=lon,
            satellite=satellite,
            frp=_num("frp"),
            confidence=normalize_confidence(props.get("confidence")),
            raw_confidence=props.get("confidence"),
            brightness=_num("bright_ti4") or _num("brightness"),
            acq_datetime=acq,
            daynight=props.get("daynight"),
        )


@dataclass
class WindObservation:
    """Wind at one point, from the forecast step closest to the moment asked.

    `bearing` is the direction the wind blows *from*, in the same 0-360 frame
    as FirmsCluster.bearing, which is what makes the two comparable.
    """

    bearing: float  # degrees, 0 = from the north
    speed: float  # m/s, 10 m above ground, 10-minute average
    time: str  # ISO 8601 timestamp of the forecast step


def _sub(node: Any, key: str) -> Any:
    """Dict lookup that tolerates anything at all on the way down."""
    return node.get(key) if isinstance(node, dict) else None


def parse_wind(
    payload: dict[str, Any], now: datetime | None = None
) -> WindObservation | None:
    """Read the wind for `now` out of a Locationforecast 2.0 payload.

    Picks the step closest in time rather than timeseries[0]: steps sit on the
    full hour, so at :55 the *next* one is 55 minutes closer to reality.

    Returns None instead of raising on anything unexpected — a shape change at
    met.no must degrade the wind attributes, never the fire data.
    """
    now = now or datetime.now(timezone.utc)
    series = _sub(_sub(payload, "properties"), "timeseries")
    if not isinstance(series, list):
        return None
    best: tuple[timedelta, dict[str, Any]] | None = None
    for step in series:
        if not isinstance(step, dict):
            continue
        try:
            when = datetime.fromisoformat(str(step.get("time")).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        gap = abs(when - now)
        if best is None or gap < best[0]:
            best = (gap, step)
    if best is None or best[0] > WEATHER_MAX_STEP_AGE:
        return None
    details = _sub(_sub(_sub(best[1], "data"), "instant"), "details")
    bearing, speed = _sub(details, "wind_from_direction"), _sub(details, "wind_speed")
    if bearing is None or speed is None:
        return None
    try:
        return WindObservation(
            bearing=float(bearing) % 360,
            speed=float(speed),
            time=str(best[1].get("time")),
        )
    except (TypeError, ValueError):
        return None


def _cache_until(headers: Any, now: datetime) -> datetime | None:
    """Turn met.no's Expires header into a "do not ask again before" moment.

    None means "no guidance given" — ask again next cycle, which is still
    cheap because If-Modified-Since turns it into a 304.
    """
    raw = headers.get("Expires") if headers else None
    if not raw:
        return None
    try:
        expires = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if expires is None:
        return None
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    return expires if expires > now else None


class MetNoClient:
    """Minimal async client for met.no Locationforecast 2.0.

    Holds exactly one cached forecast, because the integration only ever asks
    about the nearest fire. Moving to a different fire drops the cache; staying
    on the same one costs at most one request per Expires window, and a 304
    when the forecast has not been rerun.
    """

    def __init__(self, session: aiohttp.ClientSession, user_agent: str) -> None:
        self._session = session
        self._user_agent = user_agent
        self._key: tuple[float, float] | None = None
        self._payload: dict[str, Any] | None = None
        self._last_modified: str | None = None
        self._valid_until: datetime | None = None

    async def wind_at(
        self, latitude: float, longitude: float, now: datetime | None = None
    ) -> WindObservation | None:
        """Current wind at a point, or None when the forecast has nothing to say."""
        now = now or datetime.now(timezone.utc)
        payload = await self._forecast(latitude, longitude, now)
        return parse_wind(payload, now) if payload else None

    async def _forecast(
        self, latitude: float, longitude: float, now: datetime
    ) -> dict[str, Any] | None:
        key = (
            round(latitude, WEATHER_COORD_DECIMALS),
            round(longitude, WEATHER_COORD_DECIMALS),
        )
        if key != self._key:
            # A different fire — nothing we hold applies to it.
            self._key = key
            self._payload = None
            self._last_modified = None
            self._valid_until = None
        if self._valid_until is not None and now < self._valid_until:
            return self._payload

        headers = {"User-Agent": self._user_agent}
        if self._last_modified:
            # Must match the stored Last-Modified verbatim, per their ToS.
            headers["If-Modified-Since"] = self._last_modified
        try:
            async with asyncio.timeout(30):
                resp = await self._session.get(
                    METNO_URL,
                    params={"lat": f"{key[0]:.4f}", "lon": f"{key[1]:.4f}"},
                    headers=headers,
                )
                body = await resp.text()
        except (TimeoutError, aiohttp.ClientError) as err:
            raise WeatherError(f"met.no request failed: {err}") from err

        if resp.status in (403, 429):
            # Being throttled and carrying on regardless earns a permanent ban.
            self._valid_until = now + WEATHER_RATE_LIMIT_BACKOFF
            raise WeatherError(f"met.no refused the request (HTTP {resp.status})")
        if resp.status == 304:
            self._valid_until = _cache_until(resp.headers, now)
            return self._payload
        if resp.status != 200:
            raise WeatherError(f"met.no returned HTTP {resp.status}: {body[:200]}")
        try:
            payload = json.loads(body)
        except ValueError as err:
            raise WeatherError(f"met.no sent no usable JSON: {body[:200]}") from err
        self._payload = payload
        self._last_modified = resp.headers.get("Last-Modified")
        self._valid_until = _cache_until(resp.headers, now)
        return self._payload
