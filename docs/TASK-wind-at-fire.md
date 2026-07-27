# Task brief: wind direction at the fire location

Standalone work package for a separate development session. Everything needed to
start is in this file plus `CLAUDE.md` in the repo root.

## Goal

Expose the wind at each reported fire's own coordinates, so users can tell whether
a fire is being blown towards them or away — the single most requested addition
after v0.2.0.

Requested in the community thread by `pyspilf`, post #14:

> "Having the wind direction at the spot would be fantastic, in fact I was already
> planning to correlate hotspot bearing to wind direction from my own weather
> station to help qualify the risk a bit better."

He was building this by hand against his local weather station. Wind **at the
fire** is strictly better than wind at the user's house, which is why this is
worth doing inside the integration rather than leaving it to templates.

## Hard design constraints

These are settled decisions, not open questions. Do not relitigate them without
talking to the maintainer.

1. **Expose facts, never a verdict.** Ship `wind_bearing` and `wind_speed` as
   measured at the fire. Do **not** ship anything resembling "you are safe",
   "downwind", a risk score or a threat level. Wind shifts, and slope, fuel and
   humidity matter as much — the integration reports observations, users draw
   conclusions. `bearing` already ships (v0.2.0), so comparing the two is a
   one-liner in the user's own template.
2. **Nearest fire only.** Do not fetch weather for every hotspot: a busy box can
   hold hundreds. One request per update cycle (15 min), for the fire the
   `nearest_hotspot` sensor already points at.
3. **`api.py` stays free of Home Assistant imports.** It is the protocol layer
   destined for a PyPI package and a Core submission. A weather client belongs
   there too, in the same style as `FirmsClient`.
4. **Graceful degradation.** A weather lookup failing must never break the fire
   data. Fires are the product; wind is a nice-to-have. Missing wind = attributes
   are `None`, no `UpdateFailed`, no repeated error spam in the log.

## Suggested source

met.no Locationforecast 2.0 — free, no API key, accepts arbitrary lat/lon, and is
already the default weather source in Home Assistant so the licence terms are
well understood in this ecosystem.

Their terms of service are binding and easy to get wrong. Before writing code,
read them and honour at least:

- an identifying `User-Agent` including a contact address (they hard-block
  generic agents)
- `If-Modified-Since` / caching — do not refetch unchanged data
- respect `Expires` headers rather than polling blindly

If the ToS turn out to conflict with redistributing this in an integration,
say so and stop — an alternative source (or making the feature opt-in with a
user-provided key) is then the maintainer's decision, not yours to assume.

## Deliverables

- Weather client in `api.py`, no HA imports, with its own error type
- Coordinator wiring: one lookup per cycle for the nearest cluster only
- `wind_bearing` and `wind_speed` attributes on the nearest-hotspot sensor,
  alongside the existing `nearest_entity_id` / `bearing` / `direction`
- Unit-level checks in the same style as the existing smoke test (stub `aiohttp`,
  exercise the pure functions; feed a recorded met.no payload rather than hitting
  the network in tests)
- README: document the new attributes and add an upwind/downwind template recipe
  **with its limitations stated plainly**
- Version bump, release notes

## Definition of done

- Smoke test green, including new cases for the weather parsing
- hassfest and HACS actions green with no ignored checks
- Deployed to the maintainer's live instance and verified against both config
  entries (Thermi and the southern-France test entry), with the returned wind
  sanity-checked against an independent source for the same coordinates
- A deliberate failure test: make the weather endpoint unreachable and confirm
  the fire entities and sensors keep working, with wind attributes `None` and no
  log spam
- No errors in the HA log after a restart

## Working notes

- Deploy path: `tar` over SSH to `root@192.168.178.81:/homeassistant/custom_components/`,
  then restart HA. A config-entry reload is not enough for code changes.
- Two config entries exist on that instance for testing: Thermi (40.54/23.01) and
  a southern-France stress-test entry (43.60/3.90, usually the busier one).
- The maintainer is not a developer by trade. Pause at checkpoints, explain
  trade-offs in plain language, and give a clear recommendation rather than a
  list of options.
