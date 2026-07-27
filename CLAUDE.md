# CLAUDE.md — ha-nasa-firms

Home Assistant custom integration `nasa_firms`: NASA FIRMS satellite wildfire
detections as native HA entities. Public repo — everything committed here is
published.

## Goal

Public release via HACS (custom repo → default store), long-term a Home
Assistant Core submission. Donation-funded ("coffee tip jar"), never paid.

## Architecture rules

- **`custom_components/nasa_firms/api.py` must stay free of Home Assistant
  imports.** It is the protocol layer (WFS client, parsing, haversine, bbox,
  clustering) that gets extracted to a PyPI package for the Core submission —
  Core requires protocol logic in a published library. Everything else is
  thin HA glue (coordinator, config flow, two platforms).
- Model after the existing Core geo-feed family (`nsw_rural_fire_service_feed`,
  `qld_bushfire_feed`, `geo_json_events`) — same patterns, feed-specific value.
- The MAP_KEY lives in config entry data only. Never put it in entry titles,
  logs, code, docs, or screenshots.
- Brand icon ships in `custom_components/nasa_firms/brand/` (icon.png 256,
  icon@2x.png 512) — the HA 2026.3+ mechanism. The home-assistant/brands repo
  no longer accepts custom-integration icons (our PR #10856 was auto-closed);
  do not resubmit there.

## Origin & feedback backlog

Grew out of a zero-custom-code `geo_json_events` setup, documented in
https://community.home-assistant.io/t/wildfire-monitoring-with-nasa-firms-live-fire-map-proximity-alerts-zero-custom-components/1016485
Thread feedback drives the roadmap:

- BBOX `cos(radians(lat))` footgun → solved (radius + map picker)
- Confidence/FRP invisible to `geo_json_events` → solved (filters + attributes)
- 5-min polling vs. NASA's 15-min refresh → solved (`UPDATE_INTERVAL`)
- Persistent heat sources (factories) cause false alarms → **open, v0.2 lead
  candidate**: auto-ignore locations detected across many consecutive days,
  plus manual ignore zones (coordinate + radius) in the options flow. Raised
  independently by two users (posts #4/#5, #7) — the strongest differentiator
  left over the plain YAML setup.
- Map markers carry no intensity signal → **open, v0.2 candidate**: colour by
  FRP. A user solved it with Node-RED + nathan.gs map-card + auto-entities +
  z-index layering (post #7); we should manage it natively. Idea: per-cluster
  `entity_picture` as a colour-graded SVG data URI, which the core map card
  renders in the marker — needs verifying that it actually applies to
  `geo_location` entities. Fallback/companion: a plain `severity` attribute
  (low/moderate/high/extreme) so card-mod and auto-entities users can style
  without parsing raw FRP.
- ~~The nearest-hotspot sensor carries only the distance~~ → **DONE in v0.2.0**
  (post #12). Ships `nearest_entity_id`, `bearing` and `direction`; `latitude`
  /`longitude` deliberately not duplicated, they are reachable through the
  entity id. Note the startup race fixed along the way: entity ids only exist
  after HA adds the entities, so the geo_location platform nudges the
  coordinator listeners ~2 s after adding — without that the sensor renders
  before any id exists and the attribute stays `None` for a full refresh cycle.
  That nudge shipped with a bug fixed in v0.3.0: the `async_call_later` target
  needs `@callback`, otherwise HA runs it in an executor thread and every state
  write behind it raises `async_write_ha_state from a thread other than the
  event loop`. Any future `async_call_later`/`async_track_*` target here needs
  the same decorator.
- **Attributes stay non-configurable** (maintainer decision, 2026-07-28). A
  multi-select "which attributes do you want" in the config flow was considered
  and rejected: attributes are invisible until looked for and cost nothing,
  optional ones force an "if you enabled this" caveat onto every documented
  template, and HA convention reserves configuration for things that change
  behaviour or cost (poll interval, filters, satellite count = API calls) —
  Core review would flag it. Recorder growth is the one real concern and users
  can already exclude attributes via `recorder:`. The answer to "is this getting
  bloated?" is to add fewer attributes, not to make them switchable.
- ~~Wind direction at the fire~~ → **DONE in v0.3.0** (post #14). Ships
  `wind_bearing`, `wind_direction` and `wind_speed` on the nearest sensor, from
  met.no Locationforecast, one request per 15-min cycle for the nearest cluster
  only. Degrees *and* compass point on purpose, mirroring `bearing`/`direction`:
  the degrees are what the upwind/downwind template needs, the compass point is
  what goes on a dashboard — dropping the degrees would break the feature's
  actual purpose.
  **Design line held and not up for revision:** facts only, no risk score, no
  "downwind, you are fine" — wind turns and slope/fuel matter as much. The
  upwind/downwind maths lives in the README as a user template, with its limits
  spelled out. met.no's ToS shapes `MetNoClient`: identifying User-Agent with
  the repo as contact, `Expires` respected before any refetch,
  `If-Modified-Since` for cheap 304s, coordinates rounded to 2 decimals (~1 km,
  well inside their 4-decimal cap, and it keeps the cache warm as the
  representative pixel jitters). 403/429 back off for an hour. Attribution is
  CC BY 4.0 and only shown while wind data is actually present.
- Superseded history of the wind decision (kept so it is not re-litigated):
  First ruled out because the obvious implementation uses `wind_bearing` from
  the user's own `weather.*` entity, i.e. the wind at *their* house applied to a
  fire tens of km away — meaningless in mountains. Maintainer then raised the
  better framing: query the wind **at the fire's coordinates** (met.no
  Locationforecast takes arbitrary lat/lon, no API key), which removes that
  objection entirely. Remaining concerns: one API call per fire (fine at 5
  hotspots, ugly at 100, plus met.no rate limits and User-Agent rules), and the
  bigger one — a dashboard saying "downwind, you're fine" is a safety claim
  satellite data cannot back, since wind shifts and slope/fuel matter as much.
  Asked pyspilf directly in the thread for his read before deciding. Either way
  `bearing` ships first as the enabler.
- Cluster IDs are `lat/lon` rounded to 2 decimals (`api.py`), so a centroid
  drifting across a 0.01° boundary destroys the entity and creates a new one
  (history lost) → **open, hygiene**: carry the ID forward by matching new
  clusters against the previous cycle within the cluster radius.

**Evaluated and rejected:** Gridware/GridScope pole sensors as an extra alert
source (posts #8/#10). B2B hardware sold to utilities, no public developer
API, deployments concentrated in the US; the Spanish user's own utility
confirmed no API access. Not a data channel we can consume — do not revisit
without new evidence.

**Sequencing (maintainer decision, 2026-07-27):** the three nearest-hotspot
attributes shipped as v0.2.0 because a user was waiting on them to retire his
own workaround. Everything else still waits for real installation feedback
rather than forum enthusiasm.

**Wind shipped as v0.3.0** — brief kept in `docs/TASK-wind-at-fire.md` as the
record of why it looks the way it does. It introduced the **first external data
source** into the integration, so it sets the precedent for the next one: the
client lives in `api.py` with its own error type, the coordinator swallows its
failures, and the fire data never depends on it. Any future second source
follows that shape.

## Conventions

- Code, comments, commit messages, README: English. Conversation with the
  maintainer: German.
- No AI co-author trailers in commit messages (maintainer decision,
  2026-07-27). AI assistance is disclosed once, in the README's
  "Credits & disclaimer" section.
- **Editorial rule (all channels — README, forum, Ko-fi, release notes):**
  never use active disasters as urgency marketing. The personal
  vacation-home-in-Greece story is the anchor; ongoing fires may be mentioned
  factually (e.g. as test validation), never as a sales hook, never with
  dramatic disaster imagery. Wherever the tip jar appears, keep the
  wildfire-relief pointer (IFRC / local Red Cross) next to it.
- Pure logic changes need a run of the smoke test: `python tests/smoke_test.py`.
  No dependencies and no pytest — it stubs `aiohttp`, loads `api.py` directly
  and exercises bbox/haversine/clustering plus the met.no client against a
  recorded payload in `tests/fixtures/`. It lives in the repo since v0.3.0;
  earlier versions kept it out of tree, which is why older notes say to ask.
- Runtime verification happens on the maintainer's live HA instance before
  any release; this repo has no HA test harness yet (planned with the Core
  prep: pytest-homeassistant-custom-component).

## Release checklist

1. Bump `version` in `manifest.json`
2. Smoke test green, hassfest + HACS actions green
3. Tag `vX.Y.Z` + GitHub release (HACS installs from releases)
4. Update the forum thread for user-visible changes
