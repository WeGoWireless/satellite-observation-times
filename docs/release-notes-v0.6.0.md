# v0.6.0 — which fire concerns me

Text for the GitHub release.

## Release body

The nearest fire is not always the one that matters: it can be a small one
25 km out while a far bigger one at 40 km is the one the wind carries towards
you. This release is about telling those apart — with numbers, not verdicts.

### Every nearby fire gets its own wind, and a smoke-drift angle

The **three nearest fires** (configurable 1–5 under *Configure*) now each
carry the wind at their own coordinates: `wind_bearing`, `wind_direction`,
`wind_speed` — and **`smoke_offset`**, the angle between where that wind
pushes the smoke and the line from that fire to you. `0°` means straight at
you, `180°` straight away.

That is the number the automations were missing. "Fire within 20 km **and**
`smoke_offset` below 60°" alerts on what is drifting your way instead of on
distance alone — [the recipes](docs/templates.md#wind-at-the-fire).

Fires beyond the count simply lack the attributes, so "has a reading" is a
presence check. The count is a budget: every reading is one MET Norway
request per refresh, and all installations share one identity with them.

**This is geometry, not danger.** The angle says where the air at the fire is
moving right now — not where the smoke ends up, and not whether you are safe.
Wind turns, slope and fuel matter as much, and a fire drifting away is not a
fire that is safe.

### Ask any fire: the `get_wind` action

For a fire outside the budget, the first action this integration publishes
returns the same values on demand — one request at most, same cache, same
rate-limit respect:

```yaml
action: nasa_firms.get_wind
data:
  entity_id: geo_location.wildfire_hotspot_43_61_3_93
response_variable: wind
```

When there is no usable reading it raises an error instead of returning empty
values, so nothing templates its way into an automation unnoticed.

### The strongest fire, by name

`sensor.<name>_max_fire_radiative_power` now carries `strongest_entity_id` —
which fire the maximum comes from, same as the nearest-hotspot sensor has
pointed at its fire since v0.2.0.

### Failures say what happened

A FIRMS timeout used to land in `satellite_errors` as "FIRMS request failed:"
with nothing after the colon — Python's timeout carries no text of its own.
It now reads "FIRMS request timed out after 60 s", and the met.no client got
the same fix.

### Docs

New in [`docs/templates.md`](docs/templates.md): a watchdog for the data feed
(`last_reported` moves every cycle even when nothing changed, and costs the
recorder nothing), why a `0` on the hotspots sensor is always a real zero,
what `satellite_errors` does and does not hold, and a filter for "all fires
currently drifting my way".

### Upgrade notes

1. **MET Norway request volume rises** from one fire per cycle to up to
   three. Set *Fires with a wind reading* to 1 in the options to keep the old
   behaviour.
2. Nothing is removed or renamed; existing cards, templates and the blueprint
   keep working. The recommended dashboard card in the docs now reads
   `smoke_offset` instead of computing the angle itself — worth copying anew.
3. One erratum in the docs: earlier versions showed how to apply the nearest
   fire's wind to a different fire. That recipe is gone — per-fire readings
   exist precisely so nobody has to judge how far one reading carries.

Fire data courtesy of NASA FIRMS. Wind data from MET Norway, used under
CC BY 4.0.
