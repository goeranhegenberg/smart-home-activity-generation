# Smart-Home Device Descriptions

Short descriptions of each device and how its allowed values map to real-world behavior. Use these descriptions to pick realistic devices and values in the narrative.

## aidot_lamp
A dimmable tunable-white smart bulb (Aidot brand).
- `status`: turns the bulb on or off.
- `brightness`: `high` is full output (good for getting dressed, reading, or focused tasks in a dark winter morning); `low` is a dim ambient level (good for winding down or not disturbing a sleeping partner).
- `light_temp`: `warm` is a cozy orange-tinted light (good for mornings, evenings, relaxing); `cool` is a blue-tinted daylight (good for focused work or waking up alert).

## tapo_lamp
A dimmable tunable-white smart bulb (TP-Link Tapo brand). Functionally equivalent to the aidot_lamp — same three parameters (`status`, `brightness`, `light_temp`), same value options.

## tuya_lamp
A dimmable smart bulb (generic Tuya brand), but without color-temperature control.
- `status`: on/off.
- `brightness`: `high` for strong illumination, `low` for ambient light.
- No `light_temp` — its color temperature is fixed.

## tapo_socket
A smart plug (TP-Link Tapo brand). Switches power to whatever is plugged into it — typically a small kitchen appliance such as a kettle, coffee machine, or toaster.
- `status`: `on` powers the attached appliance; `off` cuts power. The socket itself has no dimming or mode — the attached appliance behaves however it normally does when powered.

## shelly_relais
A smart relay (Shelly brand) wired into a fixed installation — typically controlling a heater, a radiator valve, or hard-wired lighting.
- `status`: `on` energizes the attached load (e.g. starts heating), `off` de-energizes it. No other parameters.
