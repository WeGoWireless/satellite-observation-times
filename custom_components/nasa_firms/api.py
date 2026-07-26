"""Client for the NASA FIRMS MapServer WFS GeoJSON endpoints.

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


class FirmsError(Exception):
    """Base error talking to FIRMS."""


class FirmsAuthError(FirmsError):
    """The MAP_KEY was rejected."""


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two points in km."""
    rlat1, rlon1, rlat2, rlon2 = map(math.radians, (lat1, lon1, lat2, lon2))
    h = (
        math.sin((rlat2 - rlat1) / 2) ** 2
        + math.cos(rlat1) * math.cos(rlat2) * math.sin((rlon2 - rlon1) / 2) ** 2
    )
    return EARTH_DIAMETER_KM * math.asin(math.sqrt(h))


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


def _conf_rank(conf: str | None) -> int:
    return CONFIDENCE_RANK.get(conf, -1) if conf else -1


def cluster_hotspots(
    hotspots_with_distance: list[tuple[FirmsHotspot, float]],
    cluster_radius_km: float = 1.0,
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

    clusters = [
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
        )
        for c in raw
    ]
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
            t = str(props.get("acq_time", "0")).zfill(4)
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
