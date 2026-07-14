# Rooms and Device Placement

The apartment is a compact urban flat in Germany. Each smart-home device lives in exactly one room. Residents can only interact with a device when they are in the corresponding room (or by passing through on the way out).

## Bedroom (Alice & Bob)
The main bedroom used by Alice and Bob. Small, one window facing east, bed and a wardrobe. On winter mornings it is dark well past 07:30.
- `aidot_lamp` — ceiling-mounted bedside bulb. Primary light source when getting up and dressing.

## Charlie's Room
Charlie's bedroom, next to the parents' bedroom. Bed, small desk, toy storage.
- `tapo_lamp` — bedside bulb used to wake Charlie gently and light the room while he gets dressed.

## Living Area
Open-plan living room combined with Alice's work corner (desk, chair, monitor). This is where Alice works from home and where the family spends shared time in the morning.
- `tuya_lamp` — main ceiling light for the living area and Alice's desk. No color-temperature control, so brightness is the only comfort knob here.
- `shelly_relais` — wired to the living-area electric radiator. Switched on to heat the room up in the morning, off once the room is warm or when nobody is home.

## Kitchen
Small galley kitchen opening into the living area. Kettle and coffee machine sit on the counter.
- `tapo_socket` — smart plug powering the kettle / coffee machine combo. Turned on to prepare breakfast drinks, off once breakfast is done.

## Hallway / Entrance
No smart devices. Used for leaving the apartment (Bob + Charlie for the commute and school drop-off at 08:30).
