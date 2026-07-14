# Rooms and Device Placement

An older shared apartment (Wohngemeinschaft) in Germany, occupied by two flatmates (Nils and Jana), each with a private room plus shared living area and kitchen. Each smart-home device lives in exactly one room. A resident can only interact with a device when in the corresponding room (or passing through).

## Nils's Room
Private room with bed, desk and bookshelves.
- `aidot_lamp` — ceiling/desk bulb used to get up and to light the desk for studying.

## Jana's Room
Private room with bed and a small workspace.
- `tapo_lamp` — bedside/desk bulb used to wake up and light the room.

## Shared Living Area
Common room the flatmates share in the morning.
- `tuya_lamp` — main ceiling light for the shared area (brightness only, no color temperature).
- `shelly_relais` — wired to the living-area electric radiator. Switched on to take the chill off in the morning, off once comfortable or when the room is empty.

## Kitchen
Shared kitchen opening into the living area.
- `tapo_socket` — smart plug powering the kettle / coffee machine, shared by both. On to make coffee, off once done.

## Hallway / Entrance
No smart devices.
