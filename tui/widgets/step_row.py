#!/usr/bin/env python3
"""
step_row.py --- one Read/Edited/Ran activity row, collapsed or expanded

Contains:
    COLLAPSED_MARKER / EXPANDED_MARKER: the disclosure glyphs
    WARNING_PREFIX: marker put in front of a failed step's summary
    PREVIEW_LINES: how much of a long observation is shown before the toggle
    MORE_OUTPUT_TEMPLATE: the hint offering the rest of a long observation
    TARGET_ARGS: tool arguments that name what a step acted on
    step_target(): picks the argument naming what a step acted on
    shorten_target(): trims a target through the CLI's own truncation helper
    CardSection: one labelled section of a bordered card
    draw_card(): appends a bordered card of labelled sections to some text
    StepRow: one activity row that opens to reveal its output
    StepRow.has_failed(): whether the step reported an error
    StepRow.summary_line(): renders the collapsed one-line summary
    StepRow.card_width(): how wide the bordered card is drawn
    StepRow.diff_lines(): the step's diff as red and green card lines
    StepRow.card_sections(): the IN, DIFF and OUT sections the open card shows
    StepRow.highlight_color(): the colour a failed row is drawn in
    StepRow.detail_lines(): renders the output revealed when expanded
    StepRow.observation_lines(): the observation split into lines
    StepRow.is_truncated(): whether the observation is longer than the preview
    StepRow.action_show_full_output(): reveals the rest of a long observation
    NODE_MARKER: the node that starts each entry in the reasoning chain
    INPUT_MARKER / OUTPUT_MARKER / DIFF_MARKER: labels of the card's sections
    DIFF_PREVIEW_LINES: how much of a diff is shown before the toggle
    StepRow.render(): draws the summary and a bordered card beneath it
    StepRow.action_toggle_step(): opens or closes the row
    StepRow.watch_is_expanded(): redraws only this row when it opens
"""

from rich.cells import cell_len, chop_cells
from rich.text import Text
from textual.binding import Binding
from textual.reactive import reactive
from textual.widgets import Static

from agent.cli import _shorten
from agent.loop import TOOL_ERROR_PREFIX
from tui.labels import label_for
from tui.theme import Palette, palette_for
from tui.widgets.diff_panel import LineKind, diff_stats, parse_diff

PREVIEW_LINES = 12
MORE_OUTPUT_TEMPLATE = "… show full output ({remaining} more lines)"
WARNING_PREFIX = "!"
INPUT_MARKER = "IN"
OUTPUT_MARKER = "OUT"
DIFF_MARKER = "DIFF"
# A rewrite of a large file should not bury the rest of the timeline.
DIFF_PREVIEW_LINES = 40
# The label column inside the card, wide enough for the longest label plus a gap.
LABEL_WIDTH = 5
MIN_CARD_WIDTH = 20
FALLBACK_CARD_WIDTH = 80
# The reasoning chain: a node starts each entry.
NODE_MARKER = "●"
COLLAPSED_MARKER = "▸"
EXPANDED_MARKER = "▾"
# The arguments that name a step's subject, in the order they are preferred.
TARGET_ARGS = ("path", "command", "selector")


def step_target(tool_args: dict[str, str]) -> str:
    """Picks the argument that names what a step acted on.

    Args:
        tool_args: Arguments the step was dispatched with.

    Returns:
        target: First recognized target argument, or an empty string.
    """
    for name in TARGET_ARGS:
        value = tool_args.get(name, "")
        if value:
            return value
    return ""


def shorten_target(target: str) -> str:
    """Trims a target for display using the CLI's own truncation helper.

    The terminal and the headless CLI therefore elide long arguments
    identically, instead of each having its own idea of "too long".

    Args:
        target: Argument value naming what the step acted on.

    Returns:
        text: The value, truncated the same way the CLI truncates it.
    """
    return _shorten(target)


type CardSection = tuple[str, list[tuple[str, str]]]


def draw_card(block: Text, sections: list[CardSection], width: int, palette: Palette) -> Text:
    """Appends a bordered card of labelled sections to a block of text.

    Sections are split by a rule, lines wrap inside the border instead of
    breaking its right edge, and the border is drawn in the accent colour.

    Args:
        block: Text the card is appended to, on a new line.
        sections: (label, [(text, style)]) pairs, drawn top to bottom.
        width: Total width of the card, borders included.
        palette: Colours for the border and the labels.

    Returns:
        block: The same text, with the card appended.
    """
    border = palette.accent
    inner = width - 2
    text_width = max(inner - LABEL_WIDTH - 2, 1)
    block.append("\n╭" + "─" * inner + "╮", style=border)
    for index, (label, lines) in enumerate(sections):
        if index:
            block.append("\n├" + "─" * inner + "┤", style=border)
        first = True
        for line, style in lines:
            for chunk in chop_cells(line, text_width) or [""]:
                block.append("\n│ ", style=border)
                shown_label = label if first else ""
                block.append(f"{shown_label:<{LABEL_WIDTH}}", style=palette.hunk)
                block.append(chunk + " " * (text_width - cell_len(chunk)), style=style)
                block.append(" │", style=border)
                first = False
    block.append("\n╰" + "─" * inner + "╯", style=border)
    return block


class StepRow(Static):
    """Renders one activity row that opens to reveal that step's output.

    Attributes:
        tool_name: Tool the agent dispatched for this step.
        tool_args: Arguments the step was dispatched with.
        observation: Output the tool returned.
        diff: Unified diff of what the step changed.
        is_expanded: True while the row is showing its output.
    """

    BINDINGS = [
        Binding("enter", "toggle_step", "Expand step"),
        Binding("o", "show_full_output", "Full output"),
    ]

    is_expanded: reactive[bool] = reactive(True)
    shows_full_output: reactive[bool] = reactive(False)

    def __init__(
        self,
        tool_name: str,
        tool_args: dict[str, str],
        observation: str,
        palette: Palette | None = None,
        diff: str = "",
    ) -> None:
        """Builds one activity row from a completed step.

        Args:
            tool_name: Tool the agent dispatched for this step.
            tool_args: Arguments the step was dispatched with.
            observation: Output the tool returned.
            palette: Colours to draw from; detected from the terminal when None.
            diff: Unified diff of what this step changed, empty when it changed nothing.
        """
        super().__init__()
        self.palette: Palette = palette_for() if palette is None else palette
        self.tool_name: str = tool_name
        self.tool_args: dict[str, str] = tool_args
        self.observation: str = observation
        self.diff: str = diff

    def has_failed(self) -> bool:
        """Reports whether this step's tool returned an error.

        The same prefix the agent loop writes is used, so a step reads as failed
        in the terminal exactly when the loop treated it as failed.

        Returns:
            has_failed: True when the observation is an error.
        """
        return self.observation.startswith(TOOL_ERROR_PREFIX)

    def summary_line(self) -> str:
        """Renders the collapsed one-line summary of the step.

        A failed step is prefixed so it stands out even where colour is
        unavailable, rather than relying on red alone to carry the meaning.

        Returns:
            line: Disclosure marker, activity label, and what it acted on.
        """
        marker = EXPANDED_MARKER if self.is_expanded else COLLAPSED_MARKER
        target = shorten_target(step_target(self.tool_args))
        label = label_for(self.tool_name)
        prefix = f"{WARNING_PREFIX} " if self.has_failed() else ""
        return f"{marker} {prefix}{label} {target}".rstrip()

    def highlight_color(self) -> str:
        """Returns the colour this row is drawn in.

        Returns:
            color: The error colour for a failed step, otherwise the default text colour.
        """
        if self.has_failed():
            return self.palette.status_error
        return self.palette.foreground

    def observation_lines(self) -> list[str]:
        """Splits the observation into lines.

        Returns:
            lines: Observation lines, empty when there was no output.
        """
        return self.observation.splitlines()

    def is_truncated(self) -> bool:
        """Reports whether the observation is longer than the preview shows.

        Returns:
            is_truncated: True when output is being held back behind the toggle.
        """
        return len(self.observation_lines()) > PREVIEW_LINES

    def detail_lines(self) -> list[str]:
        """Renders the output revealed when the row is expanded.

        A long observation is previewed rather than dumped, so one noisy test
        run cannot push the rest of the timeline off screen.

        Returns:
            lines: Observation lines, plus a hint when output is held back.
        """
        if not self.is_expanded or not self.observation:
            return []
        lines = self.observation_lines()
        if self.shows_full_output or not self.is_truncated():
            return lines
        remaining: int = len(lines) - PREVIEW_LINES
        hint = MORE_OUTPUT_TEMPLATE.format(remaining=remaining)
        return [*lines[:PREVIEW_LINES], hint]

    def action_show_full_output(self) -> None:
        """Reveals the rest of a long observation."""
        self.shows_full_output = True

    def card_width(self) -> int:
        """Returns how wide the bordered card is drawn.

        Returns:
            width: The row's laid-out width, or a fallback before layout.
        """
        return self.size.width if self.size.width >= MIN_CARD_WIDTH else FALLBACK_CARD_WIDTH

    def diff_lines(self) -> list[tuple[str, str]]:
        """Renders the step's diff as coloured lines for the card.

        Added lines are drawn in the palette's add colour and removed lines in
        its delete colour, so a change reads at a glance; the +/- markers stay,
        so it still reads on a terminal without colour.

        Returns:
            lines: (text, style) pairs, empty when the step changed nothing.
        """
        files = parse_diff(self.diff)
        styles = {
            LineKind.ADD: self.palette.add,
            LineKind.DELETE: self.palette.delete,
            LineKind.HUNK: self.palette.hunk,
            LineKind.CONTEXT: self.palette.foreground,
        }
        lines: list[tuple[str, str]] = []
        for changed in files:
            added, removed = diff_stats([changed])
            lines.append((f"{changed.path}  +{added} -{removed}", self.palette.hunk))
            lines.extend((line.text, styles[line.kind]) for line in changed.lines if line.text)
        if len(lines) > DIFF_PREVIEW_LINES and not self.shows_full_output:
            remaining = len(lines) - DIFF_PREVIEW_LINES
            hint = MORE_OUTPUT_TEMPLATE.format(remaining=remaining)
            lines = [*lines[:DIFF_PREVIEW_LINES], (hint, self.palette.hunk)]
        return lines

    def card_sections(self) -> list[CardSection]:
        """Groups what the open card shows into its labelled sections.

        Returns:
            sections: (label, [(text, style)]) pairs; empty when there is nothing to show.
        """
        if not self.is_expanded:
            return []
        plain = self.palette.foreground
        sections: list[CardSection] = []
        target = step_target(self.tool_args)
        if target:
            sections.append(
                (INPUT_MARKER, [(line, plain) for line in target.splitlines() or [target]])
            )
        changes = self.diff_lines()
        if changes:
            sections.append((DIFF_MARKER, changes))
        output = self.detail_lines()
        if output:
            sections.append((OUTPUT_MARKER, [(line, plain) for line in output]))
        return sections

    def render(self) -> Text:
        """Draws the summary line and, when open, a bordered card beneath it.

        The card holds what the step was given, the diff of what it changed,
        and what it returned, each in its own section.

        Returns:
            rendered: The row as coloured text ready for the timeline.
        """
        border = self.palette.accent
        block: Text = Text()
        block.append(f"{NODE_MARKER} ", style=border)
        block.append(self.summary_line(), style=self.highlight_color())
        sections = self.card_sections()
        if not sections:
            return block
        return draw_card(block, sections, self.card_width(), self.palette)

        inner = self.card_width() - 2
        text_width = max(inner - LABEL_WIDTH - 2, 1)
        block.append("\n╭" + "─" * inner + "╮", style=border)
        for index, (label, lines) in enumerate(sections):
            if index:
                block.append("\n├" + "─" * inner + "┤", style=border)
            first = True
            for line in lines:
                for chunk in chop_cells(line, text_width) or [""]:
                    block.append("\n│ ", style=border)
                    block.append(
                        f"{label if first else '':<{LABEL_WIDTH}}", style=self.palette.hunk
                    )
                    block.append(chunk + " " * (text_width - cell_len(chunk)))
                    block.append(" │", style=border)
                    first = False
        block.append("\n╰" + "─" * inner + "╯", style=border)
        return block

    def action_toggle_step(self) -> None:
        """Opens the row when it is closed, and closes it when it is open."""
        self.is_expanded = not self.is_expanded

    def watch_is_expanded(self, is_expanded: bool) -> None:
        """Redraws only this row when it opens or closes.

        Args:
            is_expanded: Whether the row is now showing its output.
        """
        del is_expanded
        if self.is_mounted:
            self.refresh()
