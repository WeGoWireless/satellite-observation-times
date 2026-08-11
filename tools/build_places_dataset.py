"""Rebuild the bundled place-name dataset from GeoNames.

The integration resolves fire coordinates to the nearest populated place
offline, from a trimmed copy of GeoNames' `cities1000` export. This script
produces that copy, so refreshing it is one reproducible command rather than
hand-editing:

    python tools/build_places_dataset.py

It downloads the dump, keeps four columns, sorts by latitude (the runtime
index bisects on that) and writes the gzipped result into the integration.
Nothing here runs inside Home Assistant — this is a maintainer tool.

Licence: GeoNames data is CC BY 4.0. The credit ships in const.ATTRIBUTION_PLACES
and in the README; do not drop either when refreshing the data.
"""
from __future__ import annotations

import csv
import gzip
import io
import sys
import urllib.request
import zipfile
from pathlib import Path

URL = "https://download.geonames.org/export/dump/cities1000.zip"
MEMBER = "cities1000.txt"
TARGET = (
    Path(__file__).resolve().parent.parent
    / "custom_components"
    / "nasa_firms"
    / "places.csv.gz"
)

# Column indices in the GeoNames dump, which is tab-separated and has no header.
COL_NAME = 1
COL_LAT = 4
COL_LON = 5
COL_COUNTRY = 8

# Enough to place a fire, not enough to navigate by: 4 decimals is ~11 m, well
# inside the accuracy of both the place record and the satellite pixel.
COORD_DECIMALS = 4


def fetch(url: str) -> bytes:
    """Download the dump, identifying ourselves as GeoNames asks."""
    print(f"downloading {url} ...", flush=True)
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "ha-nasa-firms dataset builder (github.com/bangboomben/ha-nasa-firms)"},
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        return response.read()


def rows(archive: bytes) -> list[tuple[float, float, str, str]]:
    """(lat, lon, name, country) for every place in the dump."""
    out: list[tuple[float, float, str, str]] = []
    skipped = 0
    with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
        with bundle.open(MEMBER) as handle:
            for line in io.TextIOWrapper(handle, encoding="utf-8"):
                cols = line.rstrip("\n").split("\t")
                try:
                    lat = round(float(cols[COL_LAT]), COORD_DECIMALS)
                    lon = round(float(cols[COL_LON]), COORD_DECIMALS)
                    name = cols[COL_NAME].strip()
                    country = cols[COL_COUNTRY].strip()
                except (IndexError, ValueError):
                    skipped += 1
                    continue
                if not name:
                    skipped += 1
                    continue
                out.append((lat, lon, name, country))
    if skipped:
        print(f"  skipped {skipped} unparseable rows", flush=True)
    return out


def write(places: list[tuple[float, float, str, str]], target: Path) -> None:
    """Write lat,lon,name,country sorted by latitude, gzipped.

    Sorted because the runtime index bisects the latitude column to avoid
    scanning all of it. The loader verifies the order and re-sorts if this
    ever stops being true, so the file stays correct either way — but keeping
    it sorted here is what makes the load cheap.
    """
    places.sort(key=lambda p: p[0])
    buffer = io.StringIO()
    # QUOTE_MINIMAL plus the csv reader on the other side: place names contain
    # commas, quotes and non-Latin scripts, and hand-splitting would corrupt
    # exactly the names that matter to the people living there.
    writer = csv.writer(buffer, lineterminator="\n")
    for lat, lon, name, country in places:
        writer.writerow([f"{lat:g}", f"{lon:g}", name, country])
    raw = buffer.getvalue().encode("utf-8")
    target.parent.mkdir(parents=True, exist_ok=True)
    # mtime=0 so rebuilding identical data produces an identical file and does
    # not show up as a spurious diff.
    with gzip.GzipFile(target, "wb", compresslevel=9, mtime=0) as out:
        out.write(raw)
    print(
        f"wrote {target.relative_to(Path.cwd()) if target.is_relative_to(Path.cwd()) else target}: "
        f"{len(places)} places, {len(raw) / 1e6:.2f} MB raw, "
        f"{target.stat().st_size / 1e6:.2f} MB gzipped",
        flush=True,
    )


def main() -> int:
    places = rows(fetch(URL))
    if not places:
        print("no places parsed — refusing to overwrite the dataset", file=sys.stderr)
        return 1
    countries = {p[3] for p in places}
    print(f"parsed {len(places)} places across {len(countries)} countries", flush=True)
    write(places, TARGET)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
