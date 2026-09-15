#!/usr/bin/env python3
"""
test_approval_panel.py --- covers the panel asking whether a tool call may run

Contains:
    PanelHarness: app mounting a single approval panel
    _answer(): mounts a panel, presses one key, returns the decision
    test_y_allows_the_call(): y approves
    test_n_and_escape_deny_the_call(): n and escape refuse
    test_silence_is_a_refusal(): a timeout never approves
    test_edit_proposal_is_coloured_like_a_diff(): find is red, replace is green
    test_command_is_shown_in_the_card(): a command appears inside the border
    test_answered_panel_shrinks_to_one_line(): the decision is kept, the card is not
"""

import asyncio

from textual.app import App, ComposeResult

from tui.theme import DARK
from tui.widgets.approval_panel import ApprovalPanel, proposal_lines


class PanelHarness(App[None]):
    """Mounts one approval panel so a pilot can press keys at it.

    Attributes:
        panel: The approval panel under test.
    """

    def __init__(self, panel: ApprovalPanel) -> None:
        """Builds the harness around one panel.

        Args:
            panel: The approval panel under test.
        """
        super().__init__()
        self.panel = panel

    def compose(self) -> ComposeResult:
        """Mounts the panel under test."""
        yield self.panel

    def on_mount(self) -> None:
        """Puts the keyboard on the panel, as the app does."""
        self.panel.focus()


def _answer(key: str) -> tuple[bool, bool]:
    """Mounts a panel, presses one key, and reads back the decision.

    Args:
        key: Key to press.

    Returns:
        is_allowed: Whether the call was approved.
        decided: Whether a waiting worker would have been released.
    """
    panel = ApprovalPanel("run_shell", {"command": "pytest -q"}, palette=DARK)

    async def drive() -> tuple[bool, bool]:
        async with PanelHarness(panel).run_test() as pilot:
            await pilot.press(key)
            await pilot.pause()
            return panel.is_allowed, panel.wait_for_decision(0)

    return asyncio.run(drive())


def test_y_allows_the_call() -> None:
    """Asserts pressing y approves the call and releases the waiting run."""
    assert _answer("y") == (True, True)


def test_n_and_escape_deny_the_call() -> None:
    """Asserts n and escape both refuse the call."""
    assert _answer("n") == (False, False)
    assert _answer("escape") == (False, False)


def test_silence_is_a_refusal() -> None:
    """Asserts an unanswered panel never approves when the wait times out."""
    panel = ApprovalPanel("run_shell", {"command": "rm -rf build"}, palette=DARK)

    assert panel.wait_for_decision(0.01) is False


def test_edit_proposal_is_coloured_like_a_diff() -> None:
    """Asserts an edit shows the found line in red and its replacement in green."""
    lines = proposal_lines("edit_file", {"path": "a.py", "find": "x = 1", "replace": "x = 2"}, DARK)

    assert lines == [("-x = 1", DARK.delete), ("+x = 2", DARK.add)]


def test_command_is_shown_in_the_card() -> None:
    """Asserts the command sits inside the bordered card, under the question."""
    drawn = ApprovalPanel("run_shell", {"command": "pytest -q"}, palette=DARK).render().plain

    assert drawn.index("Allow running this command?") < drawn.index("╭")
    assert drawn.index("╭") < drawn.index("pytest -q") < drawn.index("╯")
    assert "[y] allow" in drawn


def test_answered_panel_shrinks_to_one_line() -> None:
    """Asserts an answered panel records the decision on a single line."""
    panel = ApprovalPanel("edit_file", {"path": "a.py", "find": "a", "replace": "b"}, palette=DARK)
    panel.action_deny()

    drawn = panel.render().plain

    assert drawn == "denied  edit_file a.py"
