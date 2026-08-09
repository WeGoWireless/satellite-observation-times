# Task brief: place names for fires (offline reverse geocoding)

Standalone work package for a separate development session. Everything needed to
start is in this file plus `CLAUDE.md` in the repo root.

## Goal

Give every reported fire a human-readable place name, so a dashboard or
notification can say "near Montpellier" instead of "43.6/3.9".

Requested in the community thread by `RedKing`, post #44:

> "Any way to get a place name from latitude and longitude? There seem to be one
> or two reverse geolocation integrations, but they're mostly concerned with
> tracking devices. It would be nice to put a place name to the nearest hotspot."

He is right about the existing integrations: `places` and friends only follow
`device_tracker`/`person`-style entities and cannot be pointed at `geo_location`
entities or arbitrary coordinates. This has to live in the integration.

## Hard design constraints

These are settled decisions, not open questions. Do not relitigate them without
talking to the maintainer.

1. **Offline, bundled data. No geocoding service is called.** Validated
   2026-08-09 against the providers' own terms; do not redo this research:
   - Nominatim's public API counts the *sum of all users of an application*
     against its 1 req/s limit and strongly discourages periodic requests from
     distributed apps. One block (by User-Agent) would kill the feature for
     every installation at once. That the `places` custom integration uses it
     anyway is not evidence of compliance.
   - BigDataCloud's key-less API is restricted to browsers/mobile apps —
     server-side use is against its terms.
   - GeoNames' web service requires a per-user account, which is a second
     credential in the config flow for data we can simply ship.
   - Photon's public instance offers no guarantees and reserves banning.
   - The `reverse_geocoder` PyPI package needs numpy+scipy and is unmaintained
     since 2016.
   An offline dataset has none of these problems and keeps working when a fire
   takes the internet connection down — exactly the moment this integration
   matters.
2. **City granularity: GeoNames `cities5000`** (places with population ≥ 5 000;
   maintainer decision 2026-08-09). Measured on the real data: 69 058 places
   worldwide, ~0.9 MB gzipped in the release, ~5 MB RAM loaded, ~46 ms for a
   full pure-Python haversine scan on a desktop (a coarse ±1° bounding-box
   prefilter cuts that to ~9 ms). The reference entry 43.60/3.90 resolves to
   "Montpellier, 2.3 km" — verified. No numpy, no scipy, no new dependencies:
   `haversine_km` already lives in `api.py`.
3. **Expose facts, never prose.** Ship the name and the distance as attributes;
   users compose "12 km NE of Montpellier" themselves (bearing recipes already
   exist in the docs). A remote fire whose nearest listed place is 200 km away
   shows exactly that — a true fact, not something to hide or cap.
4. **`api.py` stays free of Home Assistant imports.** The place index (load,
   nearest-lookup, cache) is protocol-layer logic in the same style as
   `FirmsClient`/`MetNoClient` and goes to the PyPI package later. Loading and
   scanning use only the stdlib (`gzip`, `csv`, `math`).
5. **Entity names and IDs do not change.** The place is an attribute on the
   existing `geo_location` fire entities. Renaming entities to
   "Wildfire near Montpellier" would break documented cards, blueprints and the
   cluster-id carry-forward semantics — explicitly out of scope. If naming is
   ever revisited, that is its own task with its own migration story.
6. **No configuration switch.** Attributes stay non-configurable (maintainer
   decision 2026-07-28, recorded in `CLAUDE.md`). The feature is always on;
   5 MB RAM is the cost of doing business.

## Dataset and licensing

- Source: `https://download.geonames.org/export/dump/cities5000.zip`, licence
  **CC BY 4.0** — same licence family as the met.no wind data, so the credit
  mechanism already exists (`const.ATTRIBUTION_WEATHER`, dynamic `attribution`
  property in `sensor.py`).
- Ship a trimmed derivative, not the raw dump: `name,lat,lon,country` per row
  (use the UTF-8 `name` column, not `asciiname` — the people reading these
  names live there). Rounded to 4 decimals; gzip level 9.
- Add a small generator script under `tools/` (e.g.
  `tools/build_places_dataset.py`) that downloads the dump, trims it and writes
  the bundled file, so refreshing the data is one reproducible command.
  Refresh cadence: opportunistically per release; place names barely change.
- Attribution: a `Place names from GeoNames (CC BY 4.0, …)` constant. Note that
  HA carries **one** attribution string per entity — where NASA and GeoNames
  credits meet on the fire entities, combine them into one string. Add GeoNames
  to the README "Credits & disclaimer" section.

## Deliverables

- `PlaceIndex` (or similar) in `api.py`: lazy one-time load of the bundled
  file, `nearest(lat, lon)` returning name/country/distance, in-memory result
  cache keyed by rounded coordinates (~3 decimals). No persistence needed —
  lookups are cheap and deterministic, a restart just recomputes.
- Coordinator wiring: the initial load and the per-cycle lookups run via
  `async_add_executor_job` (the load parses ~69k rows; a burst of new clusters
  can mean dozens of scans). Lookups only for clusters that don't have a cached
  result yet — the id carry-forward means an unchanged fire never rescans.
- Attributes on each fire entity: `place_name`, `place_distance_km` (fire →
  that place). Whether a third `place_bearing`-style attribute earns its keep
  is a maintainer call — default to leaving it out ("add fewer attributes").
- Nothing duplicated onto the nearest-hotspot sensor: the place is reachable
  through `nearest_entity_id`, same reasoning as the v0.2.0 decision not to
  mirror `latitude`/`longitude` there.
- Smoke-test cases in the existing style (`tests/smoke_test.py` loads `api.py`
  directly, no pytest): index load from the real bundled file, known-answer
  lookups for both live entries, cache behaviour, and a far-from-anywhere
  coordinate.
- README: document the attributes and add a "near {place}" notification/card
  recipe; docs/dashboard.md hook-up where it fits. The recipe must include a
  miles variant (`(place_distance_km * 0.621) | round(1)`) and say plainly
  that HA never unit-converts attributes — the unit lives in the attribute
  name on purpose. This follows the line set in thread post #34 (v0.5.1
  episode): geo_location stays km, conversion happens in the user's template.
  Do not convert the attribute per unit system in the entity layer — a value
  whose unit changes per instance while the name stays fixed is exactly the
  confusion of thread posts #20/#32.
- Version bump (this is the headline feature for **v0.8.0** — maintainer
  decision 2026-08-09, and announced as such in the thread), release notes.

## Definition of done

- Smoke test green, including the new place-index cases
- hassfest and HACS actions green with no ignored checks
- Deployed to the maintainer's live instance and verified on the
  southern-France entry (43.60/3.90): fires carry plausible names, the nearest
  fire's name sanity-checked against a map
- Startup timing sanity check on the live instance: the executor load must not
  delay the first coordinator refresh noticeably (log timestamps are enough)
- No errors in the HA log after a restart

## Working notes

- Deploy path: `tar` over SSH to
  `root@192.168.178.81:/homeassistant/custom_components/`, then restart HA. A
  config-entry reload is not enough for code changes.
- The southern-France entry (43.60/3.90) is the only reference for tests and
  examples; the Thermi entry is abandoned.
- Feasibility numbers above were measured 2026-08-09 with a throwaway probe
  (download, trim, time the scans) — re-measuring is unnecessary, but the
  generator script effectively reproduces the trim step.
- The maintainer is not a developer by trade. Pause at checkpoints, explain
  trade-offs in plain language, and give a clear recommendation rather than a
  list of options.
