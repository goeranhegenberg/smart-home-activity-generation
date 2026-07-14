# Device descriptions

How each device physically behaves and how its values map to real actions. Use only
these devices and the exact action keys / values from `available-smart-devices.json`.

- `bedroom_lamp` — ceiling/bedside bulb in the parents' bedroom (Lena & Tom). `status` on/off; `brightness` high/low; `light_temp` warm (relaxing) / cool (alert). Used when getting up in the dark and in the evening before sleep.
- `mia_lamp` — bulb in Mia's room. `status` on/off; `brightness` high/low; `light_temp` warm/cool. Used for getting up, homework (cool/high) and winding down (warm/low).
- `living_lamp` — main ceiling light of the living area. `status` on/off; `brightness` high/low (no colour temperature). Used from late afternoon into the evening.
- `kitchen_lamp` — kitchen ceiling light. `status` on/off; `brightness` high/low. Used while preparing meals.
- `bathroom_lamp` — bathroom light. `status` on/off only. Short on/off bursts when someone uses the bathroom.
- `hallway_lamp` — hallway/entrance light. `status` on/off only. Brief use when entering or leaving the house.
- `coffee_socket` — smart plug powering the kitchen coffee machine. `status` on to brew, off once done.
- `tv_socket` — smart plug powering the living-room TV. `status` on while watching, off afterwards.
- `robot_vacuum` — robot vacuum cleaner for the living area / ground floor. `status` on to start a cleaning run, off when finished. Typically run once on a quiet day (often a weekend or day off).
- `heating` — relay wired to the living-area electric heater. `status` on to warm the room on cold mornings/evenings, off once warm, when the room is empty, and overnight.
