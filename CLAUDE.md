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
- The nearest-hotspot sensor carries only the distance, with no pointer back to
  the fire it came from (post #12) → **open, v0.2 candidate, cheap**: expose
  exactly three attributes — `nearest_entity_id` (the asker's own suggestion,
  better than pre-computing fields since it unlocks the whole entity),
  `bearing` and a cardinal direction (two requesters; the great-circle formula
  is easy to get wrong by hand — see the `cos(radians)` confusion in this very
  thread). Deliberately **not** `latitude`/`longitude` on the sensor: reachable
  through the entity id, so they would be redundant.
- **Attributes stay non-configurable** (maintainer decision, 2026-07-28). A
  multi-select "which attributes do you want" in the config flow was considered
  and rejected: attributes are invisible until looked for and cost nothing,
  optional ones force an "if you enabled this" caveat onto every documented
  template, and HA convention reserves configuration for things that change
  behaviour or cost (poll interval, filters, satellite count = API calls) —
  Core review would flag it. Recorder growth is the one real concern and users
  can already exclude attributes via `recorder:`. The answer to "is this getting
  bloated?" is to add fewer attributes, not to make them switchable.
- **Wind direction — community answered YES, now a v0.2 item** (post #14,
  2026-07-27). pyspilf: *"Having the wind direction at the spot would be
  fantastic, in fact I was already planning to correlate hotspot bearing to wind
  direction from my own weather station to help qualify the risk a bit better."*
  He had the same idea independently and was building it by hand; wind **at the
  fire** beats his own station-based plan. Same post also confirms the three
  attributes are wanted ("I prefer everything to be self contained as opposed to
  bits and pieces everywhere") and that he will retire his own bearing code.
  **Design line to hold:** expose the *facts* (`wind_bearing`, `wind_speed` at
  the fire) and let users judge — never ship a safety verdict like
  "downwind, you are fine". Since `bearing` ships alongside, comparing the two
  is a one-liner for the user. Fetch for the **nearest fire only**, not every
  hotspot: one extra call per 15-min cycle instead of up to 1000. Source: met.no
  Locationforecast (free, no key, arbitrary lat/lon) — mind its User-Agent and
  If-Modified-Since requirements.
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

**Sequencing (maintainer decision, 2026-07-27):** none of the open items get
built yet. v0.1.2 has been public for a day; wait for real installation
feedback before committing to a v0.2 scope, so the roadmap follows actual
usage instead of two forum posts.

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
- Pure logic changes need a run of the smoke test (stubs `aiohttp`, exercises
  bbox/haversine/parsing/clustering — see git history or ask the maintainer).
- Runtime verification happens on the maintainer's live HA instance before
  any release; this repo has no HA test harness yet (planned with the Core
  prep: pytest-homeassistant-custom-component).

## Release checklist

1. Bump `version` in `manifest.json`
2. Smoke test green, hassfest + HACS actions green
3. Tag `vX.Y.Z` + GitHub release (HACS installs from releases)
4. Update the forum thread for user-visible changes
