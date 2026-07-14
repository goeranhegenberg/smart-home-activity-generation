"""Minimal TTDAS runtime stub -- reconstructed from slide 16 of the assignment
(03-persona-ttdas.pdf), because the lab's real ttdas.py / ttdas_actions/ click
recordings / Appium driver were not part of the course-GitLab clone we received.

It lets the generated TTDAS scripts (see src/ttdas_export.py) import and run for
demonstration: instead of driving a real phone via Appium, the Driver LOGS each
launchApp / replay_recording / stopApp call. ``schedule_at`` registers a job and
``run`` executes the registered jobs in chronological order.

In the real lab harness, ``schedule_at`` blocks until ``run_time`` (slide 16) and
``driver`` is a live Appium session whose ``replay_recording`` replays a recorded
click sequence on the device's app. To run against the real harness, replace this
file with the lab's ttdas.py and drop the recordings into ttdas_actions/.
"""
from __future__ import annotations

_JOBS: list[tuple[str, object]] = []


class Driver:
    """Logging stand-in for the Appium driver used by the TTDAS recordings."""

    def launchApp(self, app: str) -> None:
        print(f'    launchApp({app!r})')

    def replay_recording(self, name: str) -> None:
        print(f'    replay_recording({name!r})')

    def stopApp(self, app: str) -> None:
        print(f'    stopApp({app!r})')


driver = Driver()


def schedule_at(timestr: str, func) -> None:
    """Register ``func`` to run at ``timestr`` (``HH:MM:SS`` today). Mirrors the
    slide-16 signature; this stub does not block -- call ``run`` to execute."""
    _JOBS.append((timestr, func))


def run() -> None:
    """Execute all registered jobs in chronological order (demo: no real waiting).

    ``HH:MM:SS`` strings sort lexicographically in chronological order."""
    for timestr, func in sorted(_JOBS, key=lambda j: j[0]):
        print(f'[{timestr}] {func.__name__}')
        func()
    _JOBS.clear()
