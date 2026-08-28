# Wildfire Monitor wm.1 test build

This is the first private-fork build based on upstream NASA FIRMS v0.9.0.

## Seasonal monitoring

A new **Seasonal monitoring** options page controls the FIRMS polling cadence:

- **Automatic seasonal** (default): full rate during the configured fire season, reduced rate outside it.
- **Full monitoring**: FIRMS every 15 minutes.
- **Reduced monitoring**: FIRMS every 2 hours.
- **Disabled**: no scheduled wildfire-data requests. The hotspot-count sensor becomes unavailable rather than reporting a misleading zero.

The default fire season is May 1 through October 31. Start and end month/day are configurable, including seasons that wrap across New Year.

The NGFS cadence constants are reserved for the next provider step: 5 minutes at full rate and 1 hour at reduced rate.

## Compatibility

The integration domain remains `nasa_firms`, so existing config entries and entity IDs continue to work. The UI name is now **Wildfire Monitor**.
