# v0.9.0 — the last look

Text for the GitHub release.

## Release body

A quiet map and a quiet sky are not the same thing, and until now there was no
way to tell them apart.

### When a satellite last looked, and when the next one is due ([#4](https://github.com/bangboomben/ha-nasa-firms/issues/4))

Every config entry gains one sensor, **Next satellite observation**. Its state
is the next time one of your configured satellites passes over your area. Its
attributes carry the previous pass, and the detail of the next one: which
satellite, the window, and how close it comes to you.

What it buys you is the gap it makes visible. "0 hotspots" reads very
differently when the last look was forty minutes ago than when it was seven
hours ago, and nothing here used to say which.

**An observation is not a delivery.** FIRMS near-real-time data arrives up to
three hours after the pass, so the hours right after one are exactly when a
quiet map says least. And a pass without a detection is never an all-clear —
cloud, scan geometry and fire size all decide what FIRMS reports. The
integration publishes orbital facts and stops there.

Orbital elements come from CelesTrak. That is a new outbound connection, cached
for at least two hours and shared by all your entries; if it is unavailable,
fire updates carry on exactly as before.

Contributed by @WeGoWireless.

### The alert names the place ([#3](https://github.com/bangboomben/ha-nasa-firms/issues/3))

The proximity blueprint now reads *"Fire detected 8 km SSE, near
Saint-Martin-de-Londres"* instead of stopping at the direction — which is what
the place names in v0.8.0 were built for in the first place. Past 25 km it says
"in open country" rather than name a town that is nowhere near the fire.

**If you use the blueprint:** re-import it once to pick this up — Settings →
Automations & scenes → Blueprints → menu next to "NASA FIRMS — fire within a
set distance" → Re-import. Your automations keep their settings.

The README now also says outright that `place_name` and `place_distance_km`
live on the fire entity rather than on the sensors, which is where people went
looking for them.

Nothing is renamed and nothing needs reconfiguring.

Fire data courtesy of NASA FIRMS. Wind data from MET Norway and place names
from GeoNames, both used under CC BY 4.0.
