#!/usr/bin/env python3
"""
test_step_row_render.py --- covers the activity row's drawn output

Contains:
    RowHarness: app mounting a single activity row
    _mounted_text(): mounts a row and returns what it drew
    test_collapsed_row_draws_only_its_summary(): output stays hidden
    test_expanded_row_draws_its_output(): opening reveals the observation
    test_failed_row_is_styled(): a failed row carries the error colour
    test_open_row_draws_a_bordered_card(): input and output sit in one box
    test_card_rows_line_up(): every card line is exactly as wide as the border
    test_card_border_is_not_the_chat_box_blue(): cards are turquoise, the chat box blue
    test_diff_is_drawn_inside_the_card(): the change sits between IN and OUT
    test_added_and_removed_lines_are_green_and_red(): diff lines carry their colours
    test_long_diff_is_previewed(): a huge diff is cut short behind the toggle
    test_row_with_no_output_draws_one_line(): a silent tool draws only a summary
"""

import asyncio

from textual.app import App, ComposeResult

from tui.theme import DARK
from tui.widgets.step_row import (
    DIFF_MARKER,
    DIFF_PREVIEW_LINES,
    INPUT_MARKER,
    OUTPUT_MARKER,
    StepRow,
)


class RowHarness(App[None]):
    """Mounts one activity row so a pilot can render it.

    Attributes:
        row: The activity row under test.
    """

    def __init__(self, row: StepRow) -> None:
        """Builds the harness around one row.

        Args:
            row: The activity row under test.
        """
        super().__init__()
        self.row = row

    def compose(self) -> ComposeResult:
        """Mounts the row under test."""
        yield self.row


async def _mounted_text(row: StepRow, expand: bool) -> str:
    """Mounts a row, optionally opens it, and returns what it drew.

    Args:
        row: The activity row under test.
        expand: Whether to open the row before reading it.

    Returns:
        drawn: Plain text the row rendered.
    """
    app = RowHarness(row)
    async with app.run_test() as pilot:
        if expand:
            row.action_toggle_step()
        await pilot.pause()
        return row.render().plain


def test_collapsed_row_draws_only_its_summary() -> None:
    """Asserts a closed row draws its summary and none of its output."""
    row = StepRow("read_file", {"path": "a.py"}, "secret contents", palette=DARK)
    row.is_expanded = False

    drawn = asyncio.run(_mounted_text(row, expand=False))

    assert "Read" in drawn
    assert "secret contents" not in drawn


def test_expanded_row_draws_its_output() -> None:
    """Asserts opening a row draws the observation beneath the summary."""
    row = StepRow("read_file", {"path": "a.py"}, "line one\nline two", palette=DARK)

    drawn = asyncio.run(_mounted_text(row, expand=False))

    assert "line one" in drawn
    assert "line two" in drawn


def test_failed_row_is_styled() -> None:
    """Asserts a failed row's summary carries the palette's error colour."""
    row = StepRow("run_shell", {"command": "pytest"}, "error: boom", palette=DARK)

    styles = {str(span.style) for span in row.render().spans}

    assert DARK.status_error in styles


def test_open_row_draws_a_bordered_card() -> None:
    """Asserts input and output are drawn inside one box, split by a rule."""
    row = StepRow("run_shell", {"command": "pytest -q"}, "3 passed", palette=DARK)

    drawn = row.render().plain

    assert "╭" in drawn and "╯" in drawn
    assert "├" in drawn
    assert f"{INPUT_MARKER}" in drawn and "pytest -q" in drawn
    assert f"{OUTPUT_MARKER}" in drawn and "3 passed" in drawn
    assert drawn.index("pytest -q") < drawn.index("├") < drawn.index("3 passed")


def test_card_rows_line_up() -> None:
    """Asserts long lines wrap inside the box instead of breaking its right edge."""
    row = StepRow("run_shell", {"command": "x" * 300}, "y" * 250, palette=DARK)

    card = row.render().plain.splitlines()[1:]

    assert len(card) > 4
    assert len({len(line) for line in card}) == 1
    assert all(line[-1] in "╮│┤╯" for line in card)


PATCH = (
    "diff --git a/app/pricing.py b/app/pricing.py\n"
    "--- a/app/pricing.py\n"
    "+++ b/app/pricing.py\n"
    "@@ -1,2 +1,3 @@\n"
    " def apply_discount(price, pct):\n"
    "-    return price * pct\n"
    "+    if pct < 0:\n"
    "+        raise ValueError(pct)\n"
)


def _edit_row(diff: str = PATCH) -> StepRow:
    """Builds an edit step whose card carries a diff.

    Args:
        diff: Unified diff the step produced.

    Returns:
        row: The activity row under test.
    """
    return StepRow("edit_file", {"path": "app/pricing.py"}, "edited", palette=DARK, diff=diff)


def test_diff_is_drawn_inside_the_card() -> None:
    """Asserts the diff is its own card section, between the input and the output."""
    drawn = _edit_row().render().plain

    assert DIFF_MARKER in drawn
    assert "app/pricing.py  +2 -1" in drawn
    assert drawn.index(INPUT_MARKER) < drawn.index(DIFF_MARKER) < drawn.index(OUTPUT_MARKER)
    assert drawn.index("╭") < drawn.index("+    if pct < 0:") < drawn.index("╯")


def test_added_and_removed_lines_are_green_and_red() -> None:
    """Asserts + lines take the add colour and - lines the delete colour."""
    rendered = _edit_row().render()
    colour_of = {
        rendered.plain[span.start : span.end].strip(): str(span.style) for span in rendered.spans
    }

    assert colour_of["+    if pct < 0:"] == DARK.add
    assert colour_of["-    return price * pct"] == DARK.delete


def test_long_diff_is_previewed() -> None:
    """Asserts a huge diff is cut to the preview until the full output is asked for."""
    body = "".join(f"+line {n}\n" for n in range(DIFF_PREVIEW_LINES * 2))
    row = _edit_row(f"diff --git a/big.py b/big.py\n@@ -0,0 +1 @@\n{body}")

    assert "more lines" in row.render().plain
    row.action_show_full_output()
    assert f"+line {DIFF_PREVIEW_LINES * 2 - 1}" in row.render().plain


def test_row_with_no_output_draws_one_line() -> None:
    """Asserts a tool that produced no output draws just its summary line."""
    row = StepRow("git_diff", {}, "", palette=DARK)

    assert "\n" not in row.render().plain


def test_card_border_is_not_the_chat_box_blue() -> None:
    """Asserts the card border is the turquoise highlight, not the chat box blue."""
    row = StepRow("run_shell", {"command": "pytest -q"}, "3 passed", palette=DARK)
    rendered = row.render()
    corner = rendered.plain.index("╭")

    styles = {str(span.style) for span in rendered.spans if span.start <= corner < span.end}

    assert DARK.highlight in styles
    assert DARK.accent not in styles
