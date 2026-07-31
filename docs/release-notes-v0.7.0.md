# v0.7.0 — the factory that is not a fire

Text for the GitHub release.

## Release body

FIRMS reports heat, not wildfires. A steel works, a flare stack or a cement
kiln is detected every single day. Ignore zones have handled the ones you know
about by name since v0.4.0 — this release learns the rest.

### Learned heat sources

*Configure* → *Satellites and filters* → **Hide learned persistent heat
sources**. Off by default.

It watches which 1 km spots keep radiating and hides their routine detections.
Two conditions:

- **A spot must appear across 60 calendar days** — spread over two months, not
  many days running. A fire front burning for a week never reaches it.
- **A detection much brighter than that spot's own normal is always shown.**
  The ceiling is a multiple of what the cell usually radiates, not a fixed
  number of megawatts, so a real fire next to a factory still comes through.

Dropped detections are counted as `auto_ignored_detections` on the hotspot
sensor, and a diagnostics download lists every learned source with its span and
baseline.

Calibrated against 39,397 detections over 92 days in seven regions, with known
industrial sites as ground truth: nothing at or above 50 MW was suppressed.

### Sun glint was already covered

Reflections off solar farms, glasshouses and metal roofs are a daytime-only
artefact, and NASA marks those pixels `low` confidence — at night in Europe
nothing is. Setting **minimum confidence** to *Nominal or higher* is therefore
the reflection filter, and it has been there all along. Now stated in the
README, because the dial was not obviously that.

### Upgrade notes

1. **It does nothing for the first 60 days**, and nothing at all unless you
   turn it on. The history builds either way, so enabling it later works
   immediately.
2. Storage grows by a few kilobytes per config entry under `.storage`, removed
   with the entry.
3. Nothing is removed or renamed; existing cards, templates, automations and
   the blueprint keep working.

Fire data courtesy of NASA FIRMS. Wind data from MET Norway, used under
CC BY 4.0.
