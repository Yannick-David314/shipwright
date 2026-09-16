#!/usr/bin/env python3
"""
test_smoke.py --- boots the terminal widgets under a headless Textual pilot

Contains:
    SmokeApp: minimal app mounting the widgets CI should prove still boot
    _boot(): runs the app under a pilot and reports what mounted
    test_widgets_mount_headless(): the interface boots with no display attached
    test_boot_is_repeatable(): a second boot in the same process still works
"""

import asyncio

from textual.app import App, ComposeResult

from agent.planner import Plan, PlanStep
from tui.widgets.plan_panel import PlanPanel


class SmokeApp(App[None]):
    """Mounts the widgets CI should prove still boot without a terminal.

    Kept deliberately small: this guards against import-time and mount-time
    breakage, not against how any single widget renders.
    """

    def compose(self) -> ComposeResult:
        """Mounts the plan panel."""
        plan = Plan(task="smoke", steps=[PlanStep(index=0, description="do nothing")])
        yield PlanPanel(plan)


async def _boot() -> list[str]:
    """Runs the app under a pilot and reports what mounted.

    Returns:
        mounted: Class names of the widgets that mounted.
    """
    app = SmokeApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        return [type(n).__name__ for n in app.query("PlanPanel")]


def test_widgets_mount_headless() -> None:
    """Asserts the interface boots with no display attached, as CI runs it."""
    assert "PlanPanel" in asyncio.run(_boot())


def test_boot_is_repeatable() -> None:
    """Asserts booting twice in one process works, as the suite does in CI."""
    assert asyncio.run(_boot()) == asyncio.run(_boot())
