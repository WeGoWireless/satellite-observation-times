# v0.3.0 — wind at the fire

Text for the GitHub release. Delete this file once the release is published,
or keep it as the running draft for the next one.

## Release body

### Wind at the fire, not at your house

The nearest-hotspot sensor now also reports the wind **at the fire's own
coordinates**:

- `wind_bearing` — the direction the wind is blowing *from*, in degrees, in the
  same frame as the existing `bearing`
- `wind_direction` — the same as a 16-point compass abbreviation (`SW`, `NNE`),
  for dashboards that would rather not show a number
- `wind_speed` — in m/s at 10 m above ground

Requested by @pyspilf in the community thread, who was building the same thing
by hand against his own weather station. The wind at the fire is the number that
actually matters, and it is now one attribute away.

Because `bearing` (you → fire) and `wind_bearing` (where the wind comes from at
the fire) share the same reference, comparing them is a single line of Jinja —
the README has the recipe, along with a plain statement of what that number can
and cannot tell you. **The integration reports observations and does not judge
them:** there is deliberately no risk score, no threat level and no "you are
safe", because wind turns and slope, fuel and humidity matter as much as
direction.

Source is [met.no Locationforecast](https://api.met.no/), free and key-free,
queried **once per 15-minute cycle for the nearest fire only** — not per hotspot
— and cached according to their own `Expires` header with `If-Modified-Since`,
as their terms of service require. If the lookup fails, the two attributes go
`None` and nothing else changes: fire data never depends on the weather source.

### Fires now look like fires on the map

Every hotspot is drawn as a flame marker instead of the three-letter name stub
the map card falls back to (`Wildfire hotspot 43.6/3.9` used to render as
"Wh4"). The card cannot read an entity's icon for markers fed in through
`geo_location_sources`, so the flame ships as the entity picture — nothing to
configure, no custom card, and it reads the same in light and dark themes.

### Also in this release

- **Fixed a thread-safety error that filled the log on every restart.** The
  2-second nudge that publishes `nearest_entity_id` ran off the event loop, so
  Home Assistant rejected the state writes behind it with
  `calls async_write_ha_state from a thread other than the event loop`. Present
  since v0.2.0 and harmless to the data, but noisy — worth updating for on its
  own.
- `tests/smoke_test.py` is now part of the repository — no dependencies, run it
  with `python tests/smoke_test.py`
- Fixed: a malformed weather payload could raise instead of degrading quietly
  (found by the new tests)

**Upgrade note:** nothing to reconfigure. New attributes appear on the existing
`sensor.<name>_nearest_hotspot` after a restart.

Wind data from MET Norway, used under CC BY 4.0.

