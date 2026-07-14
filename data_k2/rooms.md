# Rooms and Device Placement

A compact two-room urban apartment in Germany, occupied by a single resident (Mara). Each smart-home device lives in exactly one room. The resident can only interact with a device when she is in the corresponding room (or by passing through on the way out).

## Bedroom (Mara)
The single bedroom. Bed, wardrobe, one east-facing window. Dark on winter mornings.
- `aidot_lamp` — ceiling/bedside bulb. Primary light for getting up and dressing.

## Living / Work Area
Open-plan living room with a small desk and a reading corner.
- `tuya_lamp` — main ceiling light for the living area (brightness only, no color temperature).
- `tapo_lamp` — a reading/floor lamp in the living corner used before leaving.
- `shelly_relais` — wired to the living-area electric radiator. Switched on to warm the room, off when warm or when nobody is home.

## Kitchen
Small galley kitchen opening into the living area.
- `tapo_socket` — smart plug powering the kettle / coffee machine. On to prepare the breakfast drink, off once done.

## Hallway / Entrance
No smart devices. Used for leaving the apartment for the commute by 08:00.
