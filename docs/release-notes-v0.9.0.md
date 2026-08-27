# v0.9.0 — the last look

Text for the GitHub release.

## Release body

A quiet map and a quiet sky are not the same thing. This release lets you tell
them apart — and teaches the proximity alert to name the place.

### Satellite observation times ([#4](https://github.com/bangboomben/ha-nasa-firms/issues/4))

- New sensor per config entry, **Next satellite observation**: the next pass
  over your area, for whichever satellites that entry has configured.
- Attributes carry the satellite, the window, how close it comes, the
  sub-satellite point, and the previous pass.
- The point is the gap it makes visible — "0 hotspots" reads very differently
  when the last look was forty minutes ago than when it was seven hours ago.
- **An observation is not a delivery:** FIRMS near-real-time data arrives up to
  three hours after the pass. And a pass without a detection is never an
  all-clear — cloud, scan geometry and fire size all decide what FIRMS reports.
  The integration publishes orbital facts and stops there.
- Elements come from [CelesTrak](https://celestrak.org/): a new outbound
  connection, cached for at least two hours and shared across entries. If it is
  unavailable, fire data updates exactly as before.
- Contributed by @WeGoWireless.

### The alert names the place ([#3](https://github.com/bangboomben/ha-nasa-firms/issues/3))

- The proximity blueprint now reads *"Fire detected 8 km SSE, near
  Saint-Martin-de-Londres"*. Past 25 km it says "in open country" instead of
  naming a town nowhere near the fire.
- **Re-import the blueprint once** to pick this up — Settings → Automations &
  scenes → Blueprints → menu next to "NASA FIRMS — fire within a set distance"
  → Re-import. Your automations keep their settings.
- The README now says outright that `place_name` and `place_distance_km` live
  on the fire entity, not on the sensors — which is where people looked.

Nothing is renamed and nothing needs reconfiguring.

Fire data courtesy of NASA FIRMS. Wind data from MET Norway and place names
from GeoNames, both used under CC BY 4.0.
