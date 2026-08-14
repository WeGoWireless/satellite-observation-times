# v0.8.1 — the second front door

Text for the GitHub release.

## Release body

Two fixes, both from user reports that arrived within a day of each other —
thank you.

### Setup no longer rejects valid MAP_KEYs ([#2](https://github.com/bangboomben/ha-nasa-firms/issues/2))

NASA serves FIRMS from two hostnames, and they do not accept the same
MAP_KEYs: a key can fetch data on one and answer HTTP 403 on the other.
The integration only ever asked the first host, so a key living on the
second failed setup with "FIRMS rejected the MAP_KEY" — with a key that was
perfectly valid.

The integration now asks the second host before it believes a rejection,
then remembers the one that accepts your key. Existing installations keep
working unchanged. If you patched `api.py` yourself as a workaround, just
update — the release replaces the patch and does the right thing on its own.

Error messages now also quote NASA's actual answer instead of a bare
"rejected", so the next puzzle of this kind explains itself.

### The alert no longer reads out 14 decimal places

On an instance that displays the nearest-hotspot distance in miles, the raw
state behind `{{ states(sensor) }}` is the converted value at full float
precision — the blueprint notification read "35.41474612803779 mi". Every
published template now asks for the displayed value instead
(`states(sensor, rounded=True)`), so a notification matches the dashboard.
Metric instances never showed the problem, which is how it survived this
long.

**If you use the blueprint:** re-import it once to pick the fix up —
Settings → Automations & scenes → Blueprints → menu next to "NASA FIRMS —
fire within a set distance" → Re-import. Your existing automations keep
their settings.

Nothing is renamed and nothing needs reconfiguring.

Fire data courtesy of NASA FIRMS. Wind data from MET Norway and place names
from GeoNames, both used under CC BY 4.0.
