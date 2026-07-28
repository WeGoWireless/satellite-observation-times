"""Smoke test for the protocol layer.

`api.py` is the module destined for a standalone PyPI package, so it is the
one part of this integration that can be exercised without Home Assistant.
The test stubs `aiohttp`, loads `api.py` directly, and checks the pure
functions plus the met.no client against a recorded payload — never the
network.

Run it with a plain interpreter, no dependencies, no pytest:

    python tests/smoke_test.py
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

# --- stub aiohttp so api.py imports on a bare interpreter -----------------
_aiohttp = types.ModuleType("aiohttp")


class _ClientError(Exception):
    """Stand-in for aiohttp.ClientError."""


_aiohttp.ClientError = _ClientError
_aiohttp.ClientSession = object
sys.modules.setdefault("aiohttp", _aiohttp)

_ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "firms_api", _ROOT / "custom_components" / "nasa_firms" / "api.py"
)
api = importlib.util.module_from_spec(_spec)
# @dataclass resolves annotations through sys.modules, so register before exec.
sys.modules["firms_api"] = api
_spec.loader.exec_module(api)

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "metno_compact.json").read_text())
# The fixture was recorded at 12:59Z on 2026-07-27; its steps run 12:00-16:00Z.
RECORDED_AT = datetime(2026, 7, 27, 12, 59, tzinfo=timezone.utc)

UTC = timezone.utc
FAILURES: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    """Record one assertion."""
    if ok:
        print(f"  ok   {label}")
        return
    FAILURES.append(label)
    print(f"  FAIL {label} {detail}")


def near(a: float | None, b: float, tol: float = 0.01) -> bool:
    """Float comparison that reads well in a check() call."""
    return a is not None and abs(a - b) <= tol


# --- geometry -------------------------------------------------------------
def test_geometry() -> None:
    """bbox, haversine and bearing."""
    print("geometry")
    lat_s, lon_w, lat_n, lon_e = api.bbox_around(60.0, 10.0, 111.0)
    check("bbox spans 1 degree of latitude", near(lat_n - lat_s, 2.0))
    # cos(60 deg) = 0.5, so the box must be twice as wide in longitude.
    check("bbox widens longitude by 1/cos(lat)", near(lon_e - lon_w, 4.0, 0.02))
    check(
        "bbox does not feed degrees to cos()",
        lon_e > lon_w and lat_n > lat_s,
        f"got {(lat_s, lon_w, lat_n, lon_e)}",
    )

    # Cologne -> Thermi, ~1693 km great circle.
    d = api.haversine_km(50.94, 6.96, 40.54, 23.01)
    check("haversine Cologne->Thermi ~1693 km", near(d, 1693, 5), f"got {d:.1f}")
    check("haversine of a point with itself is 0", near(api.haversine_km(1, 2, 1, 2), 0))

    check("bearing due north is 0", near(api.bearing_deg(40, 23, 41, 23), 0, 0.1))
    check("bearing due east is 90", near(api.bearing_deg(40, 23, 40, 24), 90, 0.5))
    check("bearing due south is 180", near(api.bearing_deg(40, 23, 39, 23), 180, 0.1))
    check("cardinal(0) is N", api.cardinal(0) == "N")
    check("cardinal(348.75) wraps to N", api.cardinal(348.75) == "N")
    check("cardinal(315) is NW", api.cardinal(315) == "NW")
    check("cardinal(-90) is W", api.cardinal(-90) == "W")


# --- FIRMS parsing --------------------------------------------------------
def test_confidence() -> None:
    """VIIRS letters and MODIS percentages collapse onto one scale."""
    print("confidence")
    check("VIIRS 'h' is high", api.normalize_confidence("h") == "high")
    check("VIIRS 'nominal' is nominal", api.normalize_confidence("nominal") == "nominal")
    check("MODIS 95 is high", api.normalize_confidence(95) == "high")
    check("MODIS 50 is nominal", api.normalize_confidence(50) == "nominal")
    check("MODIS 10 is low", api.normalize_confidence(10) == "low")
    check("numeric string is parsed", api.normalize_confidence("85") == "high")
    check("None stays None", api.normalize_confidence(None) is None)
    check("garbage stays None", api.normalize_confidence("banana") is None)


def test_intensity() -> None:
    """FRP falls into four absolute bands, boundaries included."""
    print("intensity")
    band = api.intensity_for_frp
    check("100 MW is extreme", band(100.0) == "extreme")
    check("above 100 stays extreme", band(4321.0) == "extreme")
    check("50 MW is high", band(50.0) == "high")
    check("just under 100 is high", band(99.9) == "high")
    check("10 MW is moderate", band(10.0) == "moderate")
    check("just under 50 is moderate", band(49.9) == "moderate")
    check("under 10 is low", band(9.9) == "low")
    check("zero is low, not missing", band(0.0) == "low")
    check("no reading is None, not a band", band(None) is None)
    # Every band must have a picture, or a fire silently loses its marker.
    labels = {label for _, label in api.FRP_BANDS}
    check("bands and labels line up", labels == {"extreme", "high", "moderate", "low"})


def test_clustering() -> None:
    """Detections of the same fire collapse into one cluster."""
    print("clustering")
    h = api.FirmsHotspot
    # Two detections 300 m apart plus one 5 km away.
    points = [
        (h(latitude=43.600, longitude=3.900, satellite="noaa20", frp=12.0, confidence="nominal"), 5.0),
        (h(latitude=43.602, longitude=3.901, satellite="snpp", frp=30.0, confidence="high"), 5.1),
        (h(latitude=43.650, longitude=3.900, satellite="noaa20", frp=4.0, confidence="low"), 9.0),
    ]
    clusters = api.cluster_hotspots(points, 1.0, (43.5, 3.9))
    check("three detections become two fires", len(clusters) == 2, f"got {len(clusters)}")
    first = clusters[0]
    check("merged cluster counts both detections", first.detections == 2)
    check("merged cluster keeps both satellites", first.satellites == ["noaa20", "snpp"])
    check("merged cluster keeps the strongest FRP", near(first.frp, 30.0))
    check("merged cluster keeps the best confidence", first.confidence == "high")
    check("clusters are sorted by distance", clusters[0].distance_km <= clusters[1].distance_km)
    check("cluster carries a bearing", first.bearing is not None)
    check("cluster carries a compass direction", first.direction in api.CARDINALS)

    # Two fires that round to the same 0.01 degree id must stay distinguishable.
    same_id = [
        (h(latitude=44.0000, longitude=4.0000, satellite="noaa20", frp=9.0), 1.0),
        (h(latitude=44.0010, longitude=4.0010, satellite="noaa20", frp=8.0), 1.2),
    ]
    collided = api.cluster_hotspots(same_id, 0.05, (44.0, 4.0))
    check("colliding ids stay unique", len({c.id for c in collided}) == len(collided))

    check("no detections means no clusters", api.cluster_hotspots([], 1.0, (0, 0)) == [])


# --- met.no parsing -------------------------------------------------------
def test_parse_wind() -> None:
    """Wind is read from the forecast step closest to the moment asked."""
    print("parse_wind")
    wind = api.parse_wind(FIXTURE, RECORDED_AT)
    check("wind is found in the recorded payload", wind is not None)
    # 12:59 is one minute from the 13:00 step and 59 from the 12:00 one.
    check("closest step wins, not timeseries[0]", wind.time == "2026-07-27T13:00:00Z")
    check("wind bearing comes from wind_from_direction", near(wind.bearing, 333.7))
    check("wind speed comes through in m/s", near(wind.speed, 5.0))

    # The sensor renders this bearing as a compass point next to the degrees.
    check("wind bearing maps onto a compass point", api.cardinal(wind.bearing) == "NNW")

    earlier = api.parse_wind(FIXTURE, datetime(2026, 7, 27, 12, 5, tzinfo=UTC))
    check("earlier ask picks the earlier step", earlier.time == "2026-07-27T12:00:00Z")

    stale = api.parse_wind(FIXTURE, RECORDED_AT + timedelta(days=2))
    check("a forecast that no longer covers now returns None", stale is None)

    check("empty payload returns None", api.parse_wind({}, RECORDED_AT) is None)
    check("garbage payload returns None", api.parse_wind({"properties": 7}, RECORDED_AT) is None)
    check(
        "a step without wind returns None",
        api.parse_wind(
            {"properties": {"timeseries": [{"time": "2026-07-27T13:00:00Z", "data": {}}]}},
            RECORDED_AT,
        )
        is None,
    )
    check(
        "an unparsable timestamp is skipped, not fatal",
        api.parse_wind(
            {
                "properties": {
                    "timeseries": [
                        {"time": "not a time", "data": {}},
                        FIXTURE["properties"]["timeseries"][1],
                    ]
                }
            },
            RECORDED_AT,
        )
        is not None,
    )


# --- met.no client --------------------------------------------------------
class FakeResponse:
    """Just enough of an aiohttp response for the client."""

    def __init__(self, status: int, body: str = "", headers: dict | None = None) -> None:
        self.status = status
        self._body = body
        self.headers = headers or {}

    async def text(self) -> str:
        return self._body


class FakeSession:
    """Hands out canned responses and records what was asked for."""

    def __init__(self, *responses) -> None:
        self._responses = list(responses)
        self.calls: list[dict] = []

    async def get(self, url, params=None, headers=None):
        self.calls.append({"url": url, "params": params, "headers": headers})
        if not self._responses:
            raise AssertionError("client made more requests than the test expected")
        nxt = self._responses.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


BODY = json.dumps(FIXTURE)
UA = "ha-nasa-firms/0.3.0 github.com/bangboomben/ha-nasa-firms"


def ok_response(expires: str = "Mon, 27 Jul 2026 13:29:37 GMT") -> FakeResponse:
    """A 200 with the caching headers met.no really sends."""
    return FakeResponse(
        200,
        BODY,
        {"Expires": expires, "Last-Modified": "Mon, 27 Jul 2026 12:59:07 GMT"},
    )


async def test_client_request() -> None:
    """The outgoing request honours the terms of service."""
    print("met.no client: request shape")
    session = FakeSession(ok_response())
    client = api.MetNoClient(session, UA)
    wind = await client.wind_at(43.6012, 3.8987, RECORDED_AT)
    check("wind comes back", wind is not None)
    call = session.calls[0]
    check("hits the compact endpoint", call["url"] == api.METNO_URL)
    check("identifies itself", call["headers"].get("User-Agent") == UA)
    check(
        "no If-Modified-Since on the first request",
        "If-Modified-Since" not in call["headers"],
    )
    check(
        "coordinates are rounded to ~1 km",
        call["params"] == {"lat": "43.6000", "lon": "3.9000"},
        f"got {call['params']}",
    )
    check(
        "coordinates stay within met.no's 4-decimal limit",
        all(len(v.split(".")[1]) <= 4 for v in call["params"].values()),
    )


async def test_client_caching() -> None:
    """Expires is respected, then If-Modified-Since keeps the refresh cheap."""
    print("met.no client: caching")
    session = FakeSession(ok_response(), FakeResponse(304, "", {}))
    client = api.MetNoClient(session, UA)
    await client.wind_at(43.60, 3.90, RECORDED_AT)

    # Same fire, 15 minutes later: still inside the Expires window.
    await client.wind_at(43.60, 3.90, RECORDED_AT + timedelta(minutes=15))
    check("no second request before Expires", len(session.calls) == 1, f"{len(session.calls)} calls")

    # Past Expires: ask again, but conditionally.
    wind = await client.wind_at(43.60, 3.90, RECORDED_AT + timedelta(minutes=45))
    check("refetches once Expires has passed", len(session.calls) == 2)
    check(
        "echoes the stored Last-Modified verbatim",
        session.calls[1]["headers"].get("If-Modified-Since")
        == "Mon, 27 Jul 2026 12:59:07 GMT",
    )
    check("a 304 keeps serving the cached forecast", wind is not None)

    # A different fire invalidates everything we hold.
    session2 = FakeSession(ok_response(), ok_response())
    client2 = api.MetNoClient(session2, UA)
    await client2.wind_at(43.60, 3.90, RECORDED_AT)
    await client2.wind_at(40.54, 23.01, RECORDED_AT)
    check("moving to another fire refetches", len(session2.calls) == 2)
    check(
        "and drops the stale If-Modified-Since",
        "If-Modified-Since" not in session2.calls[1]["headers"],
    )


async def test_client_failures() -> None:
    """Failure paths raise WeatherError and never hammer met.no."""
    print("met.no client: failures")
    session = FakeSession(FakeResponse(429, "slow down", {}))
    client = api.MetNoClient(session, UA)
    try:
        await client.wind_at(43.60, 3.90, RECORDED_AT)
        check("429 raises WeatherError", False, "no exception")
    except api.WeatherError:
        check("429 raises WeatherError", True)
    except Exception as err:  # noqa: BLE001 - the test is the assertion
        check("429 raises WeatherError", False, f"got {type(err).__name__}")

    # Throttled means throttled: nothing goes out for an hour.
    wind = await client.wind_at(43.60, 3.90, RECORDED_AT + timedelta(minutes=15))
    check("backs off after a 429", len(session.calls) == 1, f"{len(session.calls)} calls")
    check("and reports no wind meanwhile", wind is None)

    for label, canned in (
        ("connection error", _ClientError("boom")),
        ("timeout", TimeoutError()),
        ("HTTP 500", FakeResponse(500, "server error", {})),
        ("non-JSON body", FakeResponse(200, "<html>nope</html>", {})),
    ):
        client = api.MetNoClient(FakeSession(canned), UA)
        try:
            await client.wind_at(43.60, 3.90, RECORDED_AT)
            check(f"{label} raises WeatherError", False, "no exception")
        except api.WeatherError:
            check(f"{label} raises WeatherError", True)
        except Exception as err:  # noqa: BLE001 - the test is the assertion
            check(f"{label} raises WeatherError", False, f"got {type(err).__name__}")

    check(
        "WeatherError is not a FirmsError",
        not issubclass(api.WeatherError, api.FirmsError),
    )


def main() -> int:
    """Run everything and report."""
    test_geometry()
    test_confidence()
    test_intensity()
    test_clustering()
    test_parse_wind()
    asyncio.run(test_client_request())
    asyncio.run(test_client_caching())
    asyncio.run(test_client_failures())
    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {', '.join(FAILURES)}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
