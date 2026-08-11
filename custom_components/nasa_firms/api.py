"""Clients for the NASA FIRMS MapServer WFS GeoJSON endpoints and met.no.

Deliberately free of Home Assistant imports: this module is the part that
gets lifted into a standalone PyPI package for an eventual Home Assistant
Core submission (Core requires protocol logic to live in a published
library). Keep it that way.
"""
from __future__ import annotations

import asyncio
import csv
import gzip
import json
import math
import threading
import zlib
from array import array
from bisect import bisect_left, bisect_right
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

import aiohttp

BASE_URL = "https://firms.modaps.eosdis.nasa.gov/mapserver/wfs/{region}/{map_key}/"

# Generous on purpose: the regional MapServers routinely take double-digit
# seconds over a busy box. In the message as well as in the code, so the two
# can never disagree.
FIRMS_TIMEOUT = 60

KM_PER_DEG_LAT = 111.0
EARTH_DIAMETER_KM = 12742.0

# FIRMS WFS layer name fragments (fires_<satellite>_<window>) and UI labels.
SATELLITES = {
    "noaa20": "VIIRS · NOAA-20 (JPSS-1)",
    "noaa21": "VIIRS · NOAA-21 (JPSS-2)",
    "snpp": "VIIRS · Suomi NPP",
    "modis": "MODIS · Terra/Aqua",
}

# FIRMS serves each region from its own MapServer instance, and each one
# declares its own extent in its WFS capabilities document. These are those
# extents, read from the live services on 2026-07-29, as
# (lon_west, lat_south, lon_east, lat_north).
#
# They overlap deliberately, so that a fire near a boundary is served by both
# neighbours — a point can therefore sit in two or three of them at once.
# They also do not cover the whole globe: Greenland falls between Canada and
# Europe, and no region claims it.
#
# Every key is a URL path segment, so a typo in one is an HTTP 400 on every
# request. That is exactly what "Russia_and_Asia" was, from the first release
# until these extents were read off the live services: it is "Russia_Asia".
REGION_BOUNDS: dict[str, tuple[float, float, float, float]] = {
    "Alaska": (-180.0, 50.0, -139.0, 72.0),
    "Australia_NewZealand": (110.0, -55.0, 180.0, -10.0),
    "Canada": (-150.0, 40.0, -49.0, 79.0),
    "Central_America": (-119.5, 7.0, -58.5, 33.5),
    "Europe": (-26.0, 34.0, 35.0, 82.0),
    "Northern_and_Central_Africa": (-27.0, -10.0, 52.0, 37.5),
    "Russia_Asia": (26.0, 9.0, 180.0, 83.5),
    "South_America": (-112.0, -60.0, -26.0, 13.0),
    "South_Asia": (54.0, 5.5, 102.0, 40.0),
    "SouthEast_Asia": (88.0, -12.0, 163.0, 31.0),
    "Southern_Africa": (10.0, -36.0, 58.5, -4.0),
    "USA_contiguous_and_Hawaii": (-160.5, 17.5, -63.8, 50.0),
}

def region_for(latitude: float, longitude: float) -> str | None:
    """The FIRMS region serving a point, or None where none does.

    Containment alone does not decide, because the regions overlap. The
    point's distance to the nearest edge does: the deeper inside a region it
    sits, the less it matters that these extents are declarations rather than
    measurements, and the further it is from whatever the neighbouring service
    does at its own margin.

    None is a real answer rather than a failure to try — FIRMS leaves parts of
    the world uncovered, and saying so beats guessing at the nearest region and
    returning nothing forever.
    """
    best: tuple[float, str] | None = None
    for name, (lon_w, lat_s, lon_e, lat_n) in REGION_BOUNDS.items():
        if not (lon_w <= longitude <= lon_e and lat_s <= latitude <= lat_n):
            continue
        margin = min(
            longitude - lon_w, lon_e - longitude, latitude - lat_s, lat_n - latitude
        )
        if best is None or margin > best[0]:
            best = (margin, name)
    return best[1] if best else None

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

# Tighter than the FIRMS one: met.no answers in well under a second when it
# answers at all, and the wind is garnish — the fire data must not wait for it.
WEATHER_TIMEOUT = 30

# One cached forecast per rounded coordinate pair. The consumer asks about a
# handful of nearby fires per cycle plus the odd one-off lookup; beyond this
# the least-recently-used entry is dropped. Small on purpose — every entry
# holds a full Locationforecast payload.
WEATHER_CACHE_SIZE = 8


class FirmsError(Exception):
    """Base error talking to FIRMS."""


class FirmsAuthError(FirmsError):
    """The MAP_KEY was rejected."""


class WeatherError(Exception):
    """Base error talking to the weather source.

    Deliberately *not* a FirmsError: fires are the product and wind is a
    nice-to-have, so the two failure modes must never be confused upstream.
    """


class PlaceDataError(Exception):
    """The bundled place dataset could not be read.

    Same reasoning as WeatherError: a missing or corrupt data file costs the
    place names and nothing else. It is not a FirmsError and must never reach
    the coordinator as one.
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


def smoke_offset(wind_bearing: float, fire_bearing: float) -> float:
    """Angle between where the wind pushes the smoke and the fire-to-you line.

    `fire_bearing` is the bearing from the observer to the fire and
    `wind_bearing` is where the wind at the fire blows *from* — the two frames
    every consumer already holds. The smoke travels along `wind_bearing + 180`,
    the line from the fire to the observer along `fire_bearing + 180`, and the
    two 180s cancel, so the offset is the plain angular distance between the
    raw numbers: 0 means the smoke is being pushed straight at the observer,
    180 straight away, always in 0..180.

    One function instead of the same expression in the blueprint, the card and
    the docs, so every surface prints the same number. It is geometry, not
    danger: wind turns, and a fire drifting away is not a fire that is safe.
    """
    return abs((wind_bearing - fire_bearing + 180.0) % 360.0 - 180.0)


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
    bearing: float | None = None
    direction: str | None = None


def _conf_rank(conf: str | None) -> int:
    return CONFIDENCE_RANK.get(conf, -1) if conf else -1


def in_ignored_zone(
    lat: float, lon: float, zones: list[dict[str, Any]] | None
) -> bool:
    """Whether a detection falls inside one of the user's ignore zones.

    FIRMS reports thermal anomalies, not wildfires: a steel works, a flare
    stack or a landfill fire shows up every single day and is indistinguishable
    from the real thing in the data. The only party who can tell them apart is
    the person who lives there, which is why this is a manual list and not a
    heuristic — a genuine fire front burning for a week looks exactly like a
    factory to any "seen here every day" rule.

    Applied to detections rather than to finished clusters: a zone edge could
    otherwise sit inside a cluster, and the fire would be kept or dropped
    depending on where its centroid happened to land.
    """
    if not zones:
        return False
    for zone in zones:
        try:
            centre_lat = float(zone["latitude"])
            centre_lon = float(zone["longitude"])
            radius_km = float(zone["radius"]) / 1000
        except (KeyError, TypeError, ValueError):
            # A malformed zone must never take the whole update down with it.
            continue
        if haversine_km(lat, lon, centre_lat, centre_lon) <= radius_km:
            return True
    return False


def _carry_ids(
    clusters: list[FirmsCluster],
    previous: list[FirmsCluster],
    radius_km: float,
) -> dict[int, str]:
    """Match this cycle's fires onto the last one's and hand the ids down.

    An id is derived from the centroid rounded to 0.01°, so a fire whose
    centroid wanders across one of those invisible grid lines — which it does
    whenever a satellite adds or drops a detection — would otherwise be
    destroyed and recreated as a different entity. History gone, and anything
    pointing at the old entity id silently pointing at nothing.

    Pairs are considered only within the same radius that defines a cluster in
    the first place, and are consumed shortest-first so the nearest candidate
    wins: fires around Bordeaux sit as little as a kilometre apart, and a
    greedy pass in arbitrary order could hand a fire its neighbour's identity.
    Each side is used at most once, so ids can never be duplicated here.
    """
    pairs: list[tuple[float, int, int]] = []
    for i, new in enumerate(clusters):
        for j, old in enumerate(previous):
            gap = haversine_km(
                new.latitude, new.longitude, old.latitude, old.longitude
            )
            if gap <= radius_km:
                pairs.append((gap, i, j))
    # (gap, i, j) sorts deterministically even when two gaps are identical.
    pairs.sort()
    used_new: set[int] = set()
    used_old: set[int] = set()
    carried: dict[int, str] = {}
    for _gap, i, j in pairs:
        if i in used_new or j in used_old:
            continue
        used_new.add(i)
        used_old.add(j)
        carried[i] = previous[j].id
    return carried


def cluster_hotspots(
    hotspots_with_distance: list[tuple[FirmsHotspot, float]],
    cluster_radius_km: float = 1.0,
    origin: tuple[float, float] | None = None,
    previous: list[FirmsCluster] | None = None,
) -> list[FirmsCluster]:
    """Greedy dedupe: detections within cluster_radius_km collapse into one fire.

    Multiple satellites (and successive overpasses) report the same fire at
    slightly different pixel centers; without this, three-satellite setups
    show duplicate markers. Sorting by FRP first makes the strongest
    detection the cluster representative and the greedy pass deterministic.

    `previous` is the last cycle's result. Pass it and a fire keeps its id
    while it drifts; leave it out and every id is derived fresh, which is the
    behaviour this function had before.
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
                bearing=round(brg) if brg is not None else None,
                direction=cardinal(brg) if brg is not None else None,
            )
        )
    clusters.sort(key=lambda c: c.distance_km)

    carried = _carry_ids(clusters, previous, cluster_radius_km) if previous else {}
    for index, cluster_id in carried.items():
        clusters[index].id = cluster_id

    # Two distinct clusters can round to the same 0.01° id — disambiguate.
    # Carried ids are reserved first and never renamed: they are the ones an
    # existing entity is already living under, so a fresh id has to give way,
    # not the other way round.
    seen: set[str] = {clusters[i].id for i in carried}
    for index, cluster in enumerate(clusters):
        if index in carried:
            continue
        base = cluster.id
        suffix = 1
        while cluster.id in seen:
            suffix += 1
            cluster.id = f"{base}#{suffix}"
        seen.add(cluster.id)
    return clusters


# --- Persistent thermal sources -------------------------------------------
#
# Factories, flare stacks and kilns radiate around the clock and land in the
# feed as fires. NASA maintains exactly this mask ("Static Thermal Anomalies",
# 400 m grid, >=5 detections per calendar year) but publishes it as
# "not available for distribution", and the WFS carries no such layer — so we
# build it from what we can see ourselves.
#
# WHY THESE NUMBERS. Calibrated 2026-07-31 against 39,397 real detections over
# 92 days in seven regions (southern France, UK moors, Permian Basin,
# Andalusia, Greece, Bordeaux, Etna), with ArcelorMittal Fos, Immingham,
# Scunthorpe, Grangemouth and Hope Cement as industrial ground truth. Result:
# zero detections at or above 50 MW wrongly suppressed. Three earlier rule
# shapes died on that data and are recorded so they are not retried:
#
#   * "count detections over a short window" — a two-day wildfire produces
#     ~22 detections while NASA's industrial threshold is 5 PER YEAR, so
#     counting flags every real fire.
#   * "density = active days / span" — Fos runs on 87 of 92 days, giving it a
#     density of 0.95, which reads as a fire; meanwhile a 645 MW wildfire that
#     reflared over 14 days reads as industry. Wrong in both directions.
#   * "span >= 30 d AND frp_max < 50 MW" — the megawatt constant does not
#     travel. UK industry reaches 50 MW while UK fires sit at a median of
#     15.6; in the Permian Basin the flares are brighter than the fires. And a
#     Saddleworth Moor peat fire spanning 31 days was silenced at 309 MW.
#
# What survived: a long calendar span to recognise a source, and a purely
# relative brightness test to judge each detection. No megawatt constant
# appears below, which is why it holds across all seven regions.

# 1 km, matching CLUSTER_RADIUS_KM. Not NASA's 400 m: at that size the Fos
# steelworks smears across 34 cells instead of 9, because a VIIRS pixel grows
# from 375 m at nadir to ~800 m at the swath edge. NASA can afford 400 m only
# because their mask is smoothed once a year, offline.
SOURCE_CELL_SIZE_M = 1000.0
# A cell becomes a known source once it has been seen across this many
# calendar days. 60 clears the longest fire in the sample — a 31-day peat
# fire — with 29 days of margin, and still catches every major plant, whose
# spans ran 75-92 days.
SOURCE_MIN_SPAN_DAYS = 60
# Noise floor. Mildly latitude-sensitive, because overpass density runs 0.85x
# (Permian) to 1.25x (UK) of the 43.6 N reference, so 5 here means roughly
# 4-6 elsewhere. Too small a spread to be worth scaling below ~60 N.
SOURCE_MIN_ACTIVE_DAYS = 5
# A detection is suppressed only while it stays within this multiple of its
# cell's own normal brightness. A ratio, not a threshold in MW — that is what
# makes it portable. 3.0 and 5.0 landed within 2 % of each other, so the rule
# does not balance on this number.
SOURCE_FRP_FACTOR = 3.0
# Slightly more than the span we need, so a source stays recognised through a
# quiet fortnight.
SOURCE_RETENTION_DAYS = 100


def source_cell_key(latitude: float, longitude: float) -> tuple[int, int]:
    """Index of the ~1 km cell holding this point.

    Longitude degrees shrink with latitude, so the cell is sized at its own
    row. Deliberately not a great-circle calculation: the key only has to be
    stable and roughly square, and this runs for every detection of every
    cycle.
    """
    lat_step = SOURCE_CELL_SIZE_M / 111_000.0
    cos_lat = max(math.cos(math.radians(latitude)), 0.01)
    lon_step = SOURCE_CELL_SIZE_M / (111_000.0 * cos_lat)
    return (math.floor(latitude / lat_step), math.floor(longitude / lon_step))


@dataclass
class CellHistory:
    """What one cell has shown, one entry per calendar day.

    Only the day's peak FRP is kept, and that is what makes the baseline
    robust: a fire burning on a handful of days cannot drag the median up,
    because every day contributes exactly one number no matter whether it
    carried one detection or three hundred.
    """

    daily_peak_frp: dict[str, float] = field(default_factory=dict)

    def observe(self, acq_date: str, frp: float | None) -> None:
        """Fold one detection into the day's peak."""
        value = frp or 0.0
        current = self.daily_peak_frp.get(acq_date)
        if current is None or value > current:
            self.daily_peak_frp[acq_date] = value

    def prune(self, today: date) -> None:
        """Drop days that have fallen out of the retention window."""
        cutoff = (today - timedelta(days=SOURCE_RETENTION_DAYS)).isoformat()
        for day in [d for d in self.daily_peak_frp if d < cutoff]:
            del self.daily_peak_frp[day]

    @property
    def active_days(self) -> int:
        """Distinct days on which this cell produced anything."""
        return len(self.daily_peak_frp)

    @property
    def span_days(self) -> int:
        """Calendar days from the first record to the last, inclusive."""
        if not self.daily_peak_frp:
            return 0
        days = sorted(self.daily_peak_frp)
        try:
            first, last = date.fromisoformat(days[0]), date.fromisoformat(days[-1])
        except ValueError:
            return 0
        return (last - first).days + 1

    @property
    def is_known_source(self) -> bool:
        """Whether this cell has been around long enough to be a fixed source."""
        return (
            self.active_days >= SOURCE_MIN_ACTIVE_DAYS
            and self.span_days >= SOURCE_MIN_SPAN_DAYS
        )

    @property
    def baseline_frp(self) -> float:
        """Median of the daily peaks — what this cell normally looks like."""
        values = sorted(self.daily_peak_frp.values())
        if not values:
            return 0.0
        return values[len(values) // 2]

    def suppresses(self, frp: float | None) -> bool:
        """Whether this detection is just the source doing its usual thing.

        Anything markedly brighter than the cell's own normal passes through.
        That is the wildfire-next-door case and it is not hypothetical: near
        Bordeaux a weak daytime source ran at 5-16 MW for three months, and a
        real fire broke out in the very same cell at 292 MW.
        """
        if not self.is_known_source:
            return False
        # The floor keeps a near-zero baseline from collapsing the ceiling to
        # zero, which would suppress nothing at all.
        return (frp or 0.0) <= SOURCE_FRP_FACTOR * max(self.baseline_frp, 1.0)


class PersistentSources:
    """Rolling per-cell history, and the suppression decision built on it."""

    def __init__(self, cells: dict[tuple[int, int], CellHistory] | None = None):
        self._cells: dict[tuple[int, int], CellHistory] = cells or {}

    def record(self, detections: list[tuple[float, float, float | None, str]],
               today: date) -> None:
        """Fold one cycle into the history, then drop what has aged out.

        Takes `(latitude, longitude, frp, acq_date)` tuples rather than
        hotspots so this stays independent of the feed's own shape.

        Feed it the detections *before* the user's confidence and FRP filters.
        Filtered first, the baseline would be computed from a truncated sample
        and would sit too high — which suppresses more, in the one direction
        this feature cannot afford to get wrong.
        """
        for latitude, longitude, frp, acq_date in detections:
            if not acq_date:
                continue
            key = source_cell_key(latitude, longitude)
            self._cells.setdefault(key, CellHistory()).observe(acq_date, frp)
        for key in list(self._cells):
            cell = self._cells[key]
            cell.prune(today)
            if not cell.daily_peak_frp:
                del self._cells[key]

    def is_suppressed(
        self, latitude: float, longitude: float, frp: float | None
    ) -> bool:
        """Whether this detection sits on a known source and looks routine."""
        cell = self._cells.get(source_cell_key(latitude, longitude))
        return bool(cell and cell.suppresses(frp))

    @property
    def known_sources(self) -> list[CellHistory]:
        """Cells currently treated as persistent sources. For diagnostics."""
        return [c for c in self._cells.values() if c.is_known_source]

    @property
    def tracked_cells(self) -> int:
        """How many cells carry any history at all."""
        return len(self._cells)

    def as_dict(self) -> dict[str, Any]:
        """Serialise for the config entry's store."""
        # Tuple keys are not JSON-serialisable; "row:col" round-trips cleanly.
        return {
            f"{key[0]}:{key[1]}": cell.daily_peak_frp
            for key, cell in self._cells.items()
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> PersistentSources:
        """Restore from the store, skipping anything that does not parse.

        A malformed store is not worth failing a restart over — the worst case
        is that the history restarts, which costs time and nothing else.
        """
        cells: dict[tuple[int, int], CellHistory] = {}
        for key, value in (raw or {}).items():
            try:
                row, col = str(key).split(":")
                cell_key = (int(row), int(col))
                daily = {str(k): float(v) for k, v in (value or {}).items()}
            except (ValueError, AttributeError, TypeError):
                continue
            cells[cell_key] = CellHistory(daily_peak_frp=daily)
        return cls(cells)


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
            async with asyncio.timeout(FIRMS_TIMEOUT):
                resp = await self._session.get(url, params=params)
                body = await resp.text()
        except TimeoutError as err:
            # str() of a TimeoutError is empty, so folding it into the generic
            # message put "FIRMS request failed: " with nothing after the
            # colon into satellite_errors — every real timeout on the live
            # instance read exactly like that. Say what actually happened.
            raise FirmsError(f"FIRMS request timed out after {FIRMS_TIMEOUT} s") from err
        except aiohttp.ClientError as err:
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

        # No `daynight`, on purpose. The layer schema declares the field —
        # DescribeFeatureType lists it as a string — but the GeoJSON never
        # carries it. Checked on 2026-07-29 across VIIRS SNPP, NOAA-20 and
        # MODIS, both windows, in Europe, the USA and Australia: the properties
        # are acq_date, acq_datetime, acq_time, brightness, brightness_2,
        # confidence, frp, latitude, longitude, scan, track, and nothing else.
        # It shipped as an attribute that was `None` in every release up to
        # v0.4.0. Do not read it back in because the schema says it exists.
        return FirmsHotspot(
            latitude=lat,
            longitude=lon,
            satellite=satellite,
            frp=_num("frp"),
            confidence=normalize_confidence(props.get("confidence")),
            raw_confidence=props.get("confidence"),
            brightness=_num("bright_ti4") or _num("brightness"),
            acq_datetime=acq,
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


@dataclass
class _CachedForecast:
    """One point's forecast plus the header state that keeps refreshes cheap."""

    payload: dict[str, Any] | None = None
    last_modified: str | None = None
    valid_until: datetime | None = None


class MetNoClient:
    """Minimal async client for met.no Locationforecast 2.0.

    Holds one cached forecast per rounded coordinate pair, least-recently-used
    out beyond WEATHER_CACHE_SIZE: the consumer revisits the same handful of
    fires every cycle, so each point costs at most one request per Expires
    window, and a 304 when the forecast has not been rerun.

    A 403/429 blocks the whole client, not one entry. met.no throttles the
    consumer, not the coordinate — carrying on against the next fire is
    exactly the behaviour that turns a temporary refusal into a permanent ban.
    """

    def __init__(self, session: aiohttp.ClientSession, user_agent: str) -> None:
        self._session = session
        self._user_agent = user_agent
        # Insertion order doubles as recency order, via move_to_end().
        self._cache: OrderedDict[tuple[float, float], _CachedForecast] = OrderedDict()
        self._blocked_until: datetime | None = None

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
        entry = self._cache.get(key)
        if self._blocked_until is not None and now < self._blocked_until:
            # Throttled means throttled: nothing goes out for any coordinate,
            # and an unknown one is not even worth a cache slot. A stale
            # payload served here is kept honest by parse_wind's step-age cap.
            return entry.payload if entry else None
        if entry is None:
            entry = _CachedForecast()
            self._cache[key] = entry
            while len(self._cache) > WEATHER_CACHE_SIZE:
                self._cache.popitem(last=False)
        else:
            self._cache.move_to_end(key)
            if entry.valid_until is not None and now < entry.valid_until:
                return entry.payload

        headers = {"User-Agent": self._user_agent}
        if entry.last_modified:
            # Must match the stored Last-Modified verbatim, per their ToS.
            headers["If-Modified-Since"] = entry.last_modified
        try:
            async with asyncio.timeout(WEATHER_TIMEOUT):
                resp = await self._session.get(
                    METNO_URL,
                    params={"lat": f"{key[0]:.4f}", "lon": f"{key[1]:.4f}"},
                    headers=headers,
                )
                body = await resp.text()
        except TimeoutError as err:
            # Same blank-message trap as in FirmsClient.fetch: str() of a
            # TimeoutError is empty.
            raise WeatherError(
                f"met.no request timed out after {WEATHER_TIMEOUT} s"
            ) from err
        except aiohttp.ClientError as err:
            raise WeatherError(f"met.no request failed: {err}") from err

        if resp.status in (403, 429):
            self._blocked_until = now + WEATHER_RATE_LIMIT_BACKOFF
            raise WeatherError(f"met.no refused the request (HTTP {resp.status})")
        if resp.status == 304:
            entry.valid_until = _cache_until(resp.headers, now)
            return entry.payload
        if resp.status != 200:
            raise WeatherError(f"met.no returned HTTP {resp.status}: {body[:200]}")
        try:
            payload = json.loads(body)
        except ValueError as err:
            raise WeatherError(f"met.no sent no usable JSON: {body[:200]}") from err
        entry.payload = payload
        entry.last_modified = resp.headers.get("Last-Modified")
        entry.valid_until = _cache_until(resp.headers, now)
        return payload


# --- Place names -----------------------------------------------------------
#
# A fire arrives as a pair of coordinates, and "43.60/3.90" tells a person
# nothing. The nearest populated place does.
#
# WHY THIS IS OFFLINE. Every hosted geocoder was read against its own terms
# before this was written (2026-08-09), and each one rules itself out for
# software that many people install:
#
#   * Nominatim counts the sum of ALL users of an application against one
#     rate limit and discourages periodic requests outright. A single block,
#     matched on the User-Agent every installation shares, would take the
#     feature away from all of them at once.
#   * BigDataCloud's key-less endpoint is licensed for browsers and mobile
#     apps, explicitly not for servers.
#   * GeoNames' own web service wants an account per user — a second
#     credential in the config flow, for data we can simply carry.
#   * Photon's public instance promises no availability and reserves banning.
#
# A bundled dataset has none of those failure modes, needs no key, and still
# answers when a fire has taken the internet connection down — which is the
# moment this integration exists for. The cost is granularity: the nearest
# listed town, never a street address.
#
# The file is the GeoNames cities1000 export trimmed to four columns and
# sorted by latitude, built by tools/build_places_dataset.py. It is CC BY 4.0,
# so the credit in const.ATTRIBUTION_PLACES travels with it wherever it shows.

PLACES_FILE = Path(__file__).with_name("places.csv.gz")

# Cache key granularity, ~110 m. A cluster centroid jitters by a few hundred
# metres between overpasses while the answer stays identical, so rounding the
# key turns nearly every repeat lookup into a dict hit. The cache holds far
# more fires than an entry ever shows at once.
PLACE_COORD_DECIMALS = 3
PLACE_CACHE_SIZE = 512

# Search bands in km, smallest first. The index is sorted by latitude, so each
# band bisects out a horizontal strip and measures only what lies inside it.
#
# Stopping at the first band that yields a hit closer than the band itself is
# correct, not merely fast: a place outside the strip differs by more than the
# band in latitude alone, and a degree of latitude is worth at least
# KM_PER_DEG_LAT km (111.0 is the conservative end of 111.19-111.69), so its
# distance necessarily exceeds the band. The last band spans the globe, so an
# empty stretch of ocean returns what a full scan would.
PLACE_SEARCH_BANDS_KM = (25.0, 100.0, 400.0, 1600.0, 20100.0)

# None is a legitimate cached answer ("nothing within reach"), so absence from
# the cache needs a marker of its own.
_MISSING = object()


@dataclass
class PlaceMatch:
    """The populated place nearest to a point, and how far off it is."""

    name: str
    country: str  # ISO 3166-1 alpha-2
    distance_km: float


class PlaceIndex:
    """Nearest-populated-place lookup over the bundled GeoNames extract.

    Loads once, lazily, and keeps the table for the lifetime of the process:
    one index serves every config entry, because two entries watching two
    corners of the world still want the same table, and it is the largest
    thing this integration holds in memory.

    Both `load()` and `nearest()` block — the load parses ~170k rows and a
    cold lookup measures a strip of them. Call them from an executor, never
    from the event loop.
    """

    def __init__(self, path: Path | str | None = None) -> None:
        self._path = Path(path) if path is not None else PLACES_FILE
        self._lats = array("d")
        self._lons = array("d")
        self._names: list[str] = []
        self._countries: list[str] = []
        self._loaded = False
        # Latched so an unreadable file is reported once, not every cycle.
        self._failed = False
        self._cache: OrderedDict[tuple[float, float], PlaceMatch | None] = OrderedDict()
        # One index serves every config entry, and entries set up
        # concurrently — so two executor threads can arrive here at the same
        # moment, on the very first cycle, before anything is loaded. The lock
        # covers both the load and the cache bookkeeping.
        self._lock = threading.Lock()

    def __len__(self) -> int:
        return len(self._lats)

    @property
    def loaded(self) -> bool:
        """Whether the dataset is in memory. For diagnostics."""
        return self._loaded

    def load(self) -> None:
        """Read the dataset into memory. Idempotent, blocking.

        Raises PlaceDataError once if the file is unreadable, then stays
        silent: a broken install should cost the place names, not a warning
        every fifteen minutes for as long as Home Assistant runs.

        Serialised, because config entries set up concurrently and each one
        reaches this from its own executor thread. Without the lock the second
        thread finds the index mid-load — neither loaded nor failed — and the
        entry that got there second spends the rest of the session with no
        place names at all.
        """
        if self._loaded or self._failed:
            return
        with self._lock:
            self._load_locked()

    def _load_locked(self) -> None:
        # Another thread may have finished the whole job — or failed at it —
        # while this one waited for the lock.
        if self._loaded or self._failed:
            return
        try:
            with gzip.open(self._path, "rt", encoding="utf-8", newline="") as handle:
                lats, lons = array("d"), array("d")
                names: list[str] = []
                countries: list[str] = []
                # ~250 distinct country codes over ~170k rows, and csv hands
                # back a fresh string for every one of them. Pooling is worth
                # several megabytes for two lines.
                pool: dict[str, str] = {}
                for row in csv.reader(handle):
                    if len(row) < 4 or not row[2]:
                        continue
                    try:
                        latitude, longitude = float(row[0]), float(row[1])
                    except ValueError:
                        continue
                    lats.append(latitude)
                    lons.append(longitude)
                    names.append(row[2])
                    countries.append(pool.setdefault(row[3], row[3]))
        # Every way this file can be broken has to land here. An interrupted
        # download leaves a truncated gzip stream (zlib.error, EOFError) or
        # bytes that are not UTF-8 — and an exception escaping this method
        # would fail the whole update cycle and take the fire entities down
        # with it, which is the one outcome a missing place name must not have.
        except (OSError, EOFError, csv.Error, UnicodeDecodeError, zlib.error) as err:
            self._failed = True
            raise PlaceDataError(
                f"place dataset unreadable ({self._path}): {err}"
            ) from err

        # The generator writes latitude order and the search bisects on it.
        # Verified rather than trusted: an unsorted file would not fail, it
        # would confidently return the wrong neighbour.
        if any(lats[index] > lats[index + 1] for index in range(len(lats) - 1)):
            order = sorted(range(len(lats)), key=lats.__getitem__)
            lats = array("d", (lats[i] for i in order))
            lons = array("d", (lons[i] for i in order))
            names = [names[i] for i in order]
            countries = [countries[i] for i in order]

        self._lats, self._lons = lats, lons
        self._names, self._countries = names, countries
        self._loaded = True

    def nearest(self, latitude: float, longitude: float) -> PlaceMatch | None:
        """The nearest populated place, or None if the dataset holds none.

        The lock is taken around the cache bookkeeping but deliberately not
        held across the search: two entries looking up at once may then do the
        same work twice, which costs a few milliseconds, whereas holding it
        would make every entry queue behind every other one.
        """
        key = (
            round(latitude, PLACE_COORD_DECIMALS),
            round(longitude, PLACE_COORD_DECIMALS),
        )
        with self._lock:
            cached = self._cache.get(key, _MISSING)
            if cached is not _MISSING:
                self._cache.move_to_end(key)
                return cached  # type: ignore[return-value]
        match = self._search(latitude, longitude)
        with self._lock:
            self._cache[key] = match
            self._cache.move_to_end(key)
            while len(self._cache) > PLACE_CACHE_SIZE:
                self._cache.popitem(last=False)
        return match

    def _search(self, latitude: float, longitude: float) -> PlaceMatch | None:
        self.load()
        lats, lons = self._lats, self._lons
        if not lats:
            return None
        best_index, best_km = -1, None
        for band in PLACE_SEARCH_BANDS_KM:
            dlat = band / KM_PER_DEG_LAT
            start = bisect_left(lats, latitude - dlat)
            stop = bisect_right(lats, latitude + dlat)
            for index in range(start, stop):
                km = haversine_km(latitude, longitude, lats[index], lons[index])
                if best_km is None or km < best_km:
                    best_index, best_km = index, km
            if best_km is not None and best_km <= band:
                break
        if best_index < 0 or best_km is None:
            return None
        return PlaceMatch(
            name=self._names[best_index],
            country=self._countries[best_index],
            distance_km=round(best_km, 1),
        )
