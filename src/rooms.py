"""Parse the prose room map (rooms.md) into a machine-readable accessibility map.

The room map follows a regular structure across all constellations:

    ## <Room name> [(<owner names>)]
    - `device_name` -- description

A room is *private* when its header names owners, either in parentheses
(``## Bedroom (Alice & Bob)``) or as a possessive (``## Nils's Room``); otherwise
it is *shared* (living area, kitchen, hallway) and every resident may operate its
devices. ``build_access`` turns this into ``device -> {residents allowed to operate it}``.

Caregiver rule (avoids false positives in families): if a private room is owned
by a *dependent* resident (a child / someone who "cannot operate devices
autonomously"), the room is treated as accessible to everyone, because caregivers
routinely enter it. Only rooms owned exclusively by independent adults restrict
access to their owners.
"""
from __future__ import annotations

import re

HEADER_RE = re.compile(r'^##\s+(.+?)\s*$')
PARENS_RE = re.compile(r'\(([^)]*)\)')
POSSESSIVE_RE = re.compile(r"\b([A-Z][\w-]*)'s\b")
DEVICE_RE = re.compile(r'^-\s+`([^`]+)`')

_OWNER_SPLIT_RE = re.compile(r'\s*(?:&|,|/|\band\b|\+)\s*')

# Keyword markers in a resident description that mean the person does not operate
# devices independently and thus their room is shared with caregivers.
_DEPENDENT_MARKERS = (
    'cannot operate devices autonomously',
    'primary school',
    'secondary-school',
    'secondary school',
    'schoolchild',
    'toddler',
    'infant',
    'baby',
)
# An explicit age below this counts as a minor / dependent (e.g. "14-year-old").
_MINOR_AGE = 18
_AGE_RE = re.compile(r'(\d{1,2})[\s-]*year', re.IGNORECASE)


def extract_dependents(residents_text: str, resident_names: list[str]) -> set[str]:
    """Residents who are dependents (a child/minor): keyword markers, or an explicit
    age below 18. Used so a dependent's room stays accessible to caregivers."""
    dependents: set[str] = set()
    name_by_lower = {n.lower(): n for n in resident_names}
    for line in residents_text.splitlines():
        line = line.strip().lstrip('-').strip()
        if not line:
            continue
        head, _, rest = line.partition(':')
        name = name_by_lower.get(head.strip().lower())
        if not name:
            continue
        low = rest.lower()
        age_match = _AGE_RE.search(low)
        is_minor = age_match is not None and int(age_match.group(1)) < _MINOR_AGE
        if is_minor or any(marker in low for marker in _DEPENDENT_MARKERS):
            dependents.add(name)
    return dependents


def _match_owners(raw: str, resident_names: list[str]) -> set[str]:
    """Resolve owner tokens against the known resident names (case-insensitive)."""
    name_by_lower = {n.lower(): n for n in resident_names}
    owners: set[str] = set()
    for tok in _OWNER_SPLIT_RE.split(raw.strip()):
        tok = tok.strip()
        if not tok:
            continue
        match = name_by_lower.get(tok.lower())
        if match:
            owners.add(match)
    return owners


def parse_rooms(rooms_text: str, resident_names: list[str]) -> dict[str, dict]:
    """Return ``device -> {'room': name, 'owners': set[str]}`` (owners empty = shared)."""
    devices: dict[str, dict] = {}
    current_room: str | None = None
    current_owners: set[str] = set()

    for line in rooms_text.splitlines():
        header = HEADER_RE.match(line.strip())
        if header:
            title = header.group(1).strip()
            owners: set[str] = set()
            paren = PARENS_RE.search(title)
            if paren:
                owners = _match_owners(paren.group(1), resident_names)
            if not owners:
                poss = POSSESSIVE_RE.search(title)
                if poss:
                    owners = _match_owners(poss.group(1), resident_names)
            current_room = title
            current_owners = owners
            continue
        dev = DEVICE_RE.match(line.strip())
        if dev and current_room is not None:
            devices[dev.group(1)] = {'room': current_room, 'owners': set(current_owners)}
    return devices


def build_access(
    rooms_text: str,
    residents_text: str,
    resident_names: list[str],
) -> dict[str, set[str]]:
    """Map ``device -> set of residents allowed to operate it``.

    Shared devices map to all residents. A private device maps to its owners,
    unless an owner is a dependent (then to all residents, caregiver rule).
    Returns an empty map if no private rooms are found (check then disabled).
    """
    all_residents = set(resident_names)
    dependents = extract_dependents(residents_text, resident_names)
    parsed = parse_rooms(rooms_text, resident_names)

    access: dict[str, set[str]] = {}
    has_restriction = False
    for device, info in parsed.items():
        owners = info['owners']
        if not owners:
            access[device] = set(all_residents)
        elif owners & dependents:
            access[device] = set(all_residents)
        else:
            access[device] = set(owners)
            if owners != all_residents:
                has_restriction = True

    # Single-resident homes or all-shared maps carry no restriction worth checking.
    if not has_restriction or len(all_residents) < 2:
        return {}
    return access
