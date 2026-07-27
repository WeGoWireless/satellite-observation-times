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

## Origin & feedback backlog

Grew out of a zero-custom-code `geo_json_events` setup, documented in
https://community.home-assistant.io/t/wildfire-monitoring-with-nasa-firms-live-fire-map-proximity-alerts-zero-custom-components/1016485
Thread feedback drives the roadmap:

- BBOX `cos(radians(lat))` footgun → solved (radius + map picker)
- Confidence/FRP invisible to `geo_json_events` → solved (filters + attributes)
- Persistent heat sources (factories) cause false alarms → **open, v0.2**:
  auto-ignore locations detected across many consecutive days

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
