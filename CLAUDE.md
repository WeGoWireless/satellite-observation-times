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
  `nearest_entity_id` on that sensor — the asker's own suggestion and better
  than pre-computing fields, since it unlocks every attribute of that fire
  rather than the ones we guessed. Add `bearing` + cardinal direction alongside
  it (second requester). Removes ~15 lines of Jinja from every user's dashboard.
- **Wind direction: deliberately NOT an integration feature** (maintainer
  decision, 2026-07-28). Technically trivial — `wind_bearing` is free on any
  `weather.*` entity — but it would be the wind at the *user's* location applied
  to a fire tens of km away, in terrain where it can differ completely, and fire
  spread also depends on slope, fuel and humidity. Worst case the integration
  implies "downwind, you're safe", the wind turns, and someone doesn't act.
  This integration reports observations, not risk predictions; cross-entity
  logic belongs in the user's own automations (and would draw fire in a Core
  review). Ship `bearing` as the enabler and document the upwind/downwind
  comparison as a README recipe with its limits stated.
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
