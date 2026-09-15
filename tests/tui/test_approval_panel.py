#!/usr/bin/env python3
"""
test_approval_panel.py --- covers the panel asking whether a tool call may run

Contains:
    PanelHarness: app mounting a single approval panel
    _answer(): mounts a panel, presses keys, returns the decision
    test_y_allows_the_call(): y approves
    test_n_and_escape_deny_the_call(): n and escape refuse
    test_other_passes_a_typed_suggestion(): o, text, enter hands the text back
    test_escape_closes_other_without_answering(): escape backs out of the field
    test_empty_suggestion_is_a_denial(): enter on an empty field just denies
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


def _answer(*keys: str) -> tuple[bool, bool | str]:
    """Mounts a panel, presses keys in order, and reads back the decision.

    Args:
        keys: Keys to press.

    Returns:
        is_answered: Whether the operator has answered.
        decision: What a waiting worker would receive right now.
    """
    panel = ApprovalPanel("run_shell", {"command": "pytest -q"}, palette=DARK)

    async def drive() -> tuple[bool, bool | str]:
        async with PanelHarness(panel).run_test() as pilot:
            await pilot.press(*keys)
            await pilot.pause()
            return panel.is_answered, panel.wait_for_decision(0)

    return asyncio.run(drive())


def test_y_allows_the_call() -> None:
    """Asserts pressing y approves the call and releases the waiting run."""
    assert _answer("y") == (True, True)


def test_n_and_escape_deny_the_call() -> None:
    """Asserts n and escape both refuse the call."""
    assert _answer("n") == (True, False)
    assert _answer("escape") == (True, False)


def test_other_passes_a_typed_suggestion() -> None:
    """Asserts o opens a field whose submitted text becomes the answer."""
    typed = list("use tox")
    typed[3] = "space"

    assert _answer("o", *typed, "enter") == (True, "use tox")


def test_escape_closes_other_without_answering() -> None:
    """Asserts escape inside the field backs out rather than denying outright."""
    assert _answer("o", "escape") == (False, False)


def test_empty_suggestion_is_a_denial() -> None:
    """Asserts submitting an empty suggestion counts as a plain denial."""
    assert _answer("o", "enter") == (True, False)


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
    drawn = ApprovalPanel("run_shell", {"command": "pytest -q"}, palette=DARK).card_text(80).plain

    assert drawn.index("Allow running this command?") < drawn.index("╭")
    assert drawn.index("╭") < drawn.index("pytest -q") < drawn.index("╯")
    assert "[y] approve   [n] deny   [o] other" in drawn


def test_answered_panel_shrinks_to_one_line() -> None:
    """Asserts an answered panel records the decision on a single line."""
    panel = ApprovalPanel("edit_file", {"path": "a.py", "find": "a", "replace": "b"}, palette=DARK)
    panel.action_deny()

    drawn = panel.card_text(80).plain

    assert drawn == "denied  edit_file a.py"
