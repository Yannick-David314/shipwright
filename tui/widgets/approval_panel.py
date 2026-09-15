#!/usr/bin/env python3
"""
approval_panel.py --- asks the operator whether one tool call may run

Contains:
    ALLOW_KEY / DENY_KEY / OTHER_KEY: the keys that answer the panel
    PREVIEW_LINES: how much of a proposed change the panel shows
    ESCAPE_TOOL: pseudo tool name for a command leaving the working directory
    question_for(): the question the panel asks about one call
    proposal_lines(): what the call would do, coloured like a diff
    ApprovalCard: draws the panel's question and card at its own width
    ApprovalPanel: bordered card that waits for approve, deny, or other
    ApprovalPanel.verdict_line(): the one line an answered panel shrinks to
    ApprovalPanel.card_text(): draws the question, the proposal and the key hints
    ApprovalPanel.action_allow(): approves the call
    ApprovalPanel.action_deny(): refuses the call
    ApprovalPanel.action_other(): opens the field for the operator's own suggestion
    ApprovalPanel.on_input_submitted(): declines the call with that suggestion
    ApprovalPanel.wait_for_decision(): blocks a worker until the operator answers
    ApprovalPanel.Decided: reports the operator's answer to the app
"""

import threading

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.events import Key
from textual.message import Message
from textual.widgets import Input, Static

from tui.theme import Palette, palette_for
from tui.widgets.step_row import FALLBACK_CARD_WIDTH, MIN_CARD_WIDTH, CardSection, draw_card

ALLOW_KEY = "y"
DENY_KEY = "n"
OTHER_KEY = "o"
OTHER_PLACEHOLDER = "What should the agent do instead?"
PREVIEW_LINES = 20
ESCAPE_TOOL = "leave_workspace"
QUESTIONS = {
    "edit_file": "Allow this edit to {path}?",
    "write_file": "Allow writing {path}?",
    "apply_patch": "Allow applying this patch?",
    "run_shell": "Allow running this command?",
    "run_tests": "Allow running the tests?",
    ESCAPE_TOOL: "This command reaches outside the working directory. Allow it?",
}


def question_for(tool_name: str, tool_args: dict[str, str]) -> str:
    """Returns the question the panel asks about one call.

    Args:
        tool_name: Tool the agent wants to call.
        tool_args: Arguments it would be called with.

    Returns:
        question: One line naming what is being approved.
    """
    template = QUESTIONS.get(tool_name, f"Allow {tool_name}?")
    return template.format(path=tool_args.get("path", "this file"))


def _preview(lines: list[tuple[str, str]], palette: Palette) -> list[tuple[str, str]]:
    """Cuts a long proposal down to the preview, saying how much was held back.

    Args:
        lines: Proposal lines with their styles.
        palette: Colours for the hint.

    Returns:
        lines: At most PREVIEW_LINES lines, plus a hint when any were dropped.
    """
    if len(lines) <= PREVIEW_LINES:
        return lines
    hidden = len(lines) - PREVIEW_LINES
    return [*lines[:PREVIEW_LINES], (f"… {hidden} more lines", palette.hunk)]


def proposal_lines(
    tool_name: str, tool_args: dict[str, str], palette: Palette
) -> list[tuple[str, str]]:
    """Renders what the call would do, coloured the way its diff will be.

    Args:
        tool_name: Tool the agent wants to call.
        tool_args: Arguments it would be called with.
        palette: Colours for added and removed lines.

    Returns:
        lines: (text, style) pairs describing the proposed change or command.
    """
    plain = palette.foreground
    if tool_name == "edit_file":
        removed = [(f"-{line}", palette.delete) for line in tool_args.get("find", "").splitlines()]
        added = [(f"+{line}", palette.add) for line in tool_args.get("replace", "").splitlines()]
        return _preview(removed + added, palette)
    if tool_name == "write_file":
        content = tool_args.get("content", "")
        return _preview([(f"+{line}", palette.add) for line in content.splitlines()], palette)
    if tool_name == "apply_patch":
        styled = []
        for line in tool_args.get("patch", "").splitlines():
            if line.startswith("+") and not line.startswith("+++"):
                styled.append((line, palette.add))
            elif line.startswith("-") and not line.startswith("---"):
                styled.append((line, palette.delete))
            else:
                styled.append((line, plain))
        return _preview(styled, palette)
    command = tool_args.get("command") or " ".join(tool_args.values())
    return [(line, plain) for line in command.splitlines()] or [("(no arguments)", palette.hunk)]


class ApprovalCard(Static):
    """Draws the panel's question and card at whatever width it is given."""

    def render(self) -> Text:
        """Draws the owning panel's text at this widget's width.

        Returns:
            rendered: The question, card and key hints, or the one-line verdict.
        """
        panel = self.parent
        assert isinstance(panel, ApprovalPanel)
        return panel.card_text(self.size.width)


class ApprovalPanel(Vertical):
    """Draws one proposed tool call and waits for approve, deny, or other.

    Other opens a field for the operator's own suggestion; submitting it
    declines the call and hands the text to the agent instead.

    Attributes:
        tool_name: Tool the agent wants to call.
        tool_args: Arguments it would be called with.
        palette: Colours the card is drawn in.
        decision: True, False, or the operator's suggestion once answered.
        is_answered: True once the operator has answered.
    """

    can_focus = True

    DEFAULT_CSS = """
    ApprovalPanel {
        height: auto;
        margin-top: 1;
    }
    ApprovalPanel ApprovalCard {
        height: auto;
    }
    ApprovalPanel Input {
        display: none;
        border: round $accent;
    }
    ApprovalPanel.other Input {
        display: block;
    }
    """

    class Decided(Message):
        """Reports the operator's answer, so the app can hand the keyboard back.

        Attributes:
            decision: True, False, or the operator's suggestion.
        """

        def __init__(self, decision: bool | str) -> None:
            """Records the answer the operator gave.

            Args:
                decision: True, False, or the operator's suggestion.
            """
            super().__init__()
            self.decision = decision

    BINDINGS = [
        Binding(ALLOW_KEY, "allow", "Approve"),
        Binding(DENY_KEY, "deny", "Deny"),
        Binding(OTHER_KEY, "other", "Other"),
        Binding("escape", "escape", "Deny", show=False),
    ]

    def __init__(
        self, tool_name: str, tool_args: dict[str, str], palette: Palette | None = None
    ) -> None:
        """Builds the panel for one proposed call.

        Args:
            tool_name: Tool the agent wants to call.
            tool_args: Arguments it would be called with.
            palette: Colours to draw from; detected from the terminal when None.
        """
        super().__init__()
        self.tool_name = tool_name
        self.tool_args = tool_args
        self.palette: Palette = palette_for() if palette is None else palette
        self.decision: bool | str = False
        self.is_answered = False
        self._answered = threading.Event()

    def compose(self) -> ComposeResult:
        """Lays out the card and the hidden field for another suggestion."""
        yield ApprovalCard()
        yield Input(placeholder=OTHER_PLACEHOLDER)

    @property
    def is_allowed(self) -> bool:
        """Reports whether the call was approved.

        Returns:
            is_allowed: True only for an explicit approval.
        """
        return self.decision is True

    def verdict_line(self) -> Text:
        """Renders the one line an answered panel shrinks to.

        Returns:
            line: The decision, the call it applied to, and any suggestion.
        """
        subject = self.tool_args.get("path") or self.tool_args.get("command", "")
        call = f"{self.tool_name} {subject}".strip()
        line = Text()
        if isinstance(self.decision, str):
            line.append("other  ", style=self.palette.accent)
            line.append(f"{call}: ", style=self.palette.hunk)
            line.append(self.decision)
            return line
        verdict = "approved" if self.decision else "denied"
        colour = self.palette.add if self.decision else self.palette.status_error
        line.append(f"{verdict}  ", style=colour)
        line.append(call, style=self.palette.hunk)
        return line

    def card_text(self, width: int) -> Text:
        """Draws the question, the proposal card and the key hints.

        Once answered the panel shrinks to one line recording the decision,
        so the transcript keeps what was decided without the whole card.

        Args:
            width: Width available to the card.

        Returns:
            rendered: The panel as coloured text.
        """
        if self.is_answered:
            return self.verdict_line()
        block = Text()
        block.append("? ", style=self.palette.accent)
        block.append(question_for(self.tool_name, self.tool_args), style="bold")
        width = width if width >= MIN_CARD_WIDTH else FALLBACK_CARD_WIDTH
        label = "EDIT" if self.tool_name in {"edit_file", "write_file", "apply_patch"} else "RUN"
        target = self.tool_args.get("path", "")
        sections: list[CardSection] = []
        if target and self.tool_name != "run_shell":
            sections.append(("FILE", [(target, self.palette.foreground)]))
        sections.append((label, proposal_lines(self.tool_name, self.tool_args, self.palette)))
        draw_card(block, sections, width, self.palette)
        block.append(
            f"\n[{ALLOW_KEY}] approve   [{DENY_KEY}] deny   [{OTHER_KEY}] other",
            style=self.palette.hunk,
        )
        return block

    def action_allow(self) -> None:
        """Approves the call and lets the waiting run proceed."""
        self._decide(True)

    def action_deny(self) -> None:
        """Refuses the call and lets the waiting run carry on without it."""
        self._decide(False)

    def action_other(self) -> None:
        """Opens the field for the operator's own suggestion."""
        if self.is_answered:
            return
        self.add_class("other")
        self.query_one(Input).focus()

    def action_escape(self) -> None:
        """Closes the suggestion field if it is open, otherwise denies the call."""
        if self.has_class("other"):
            self.remove_class("other")
            self.focus()
            return
        self._decide(False)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Declines the call with the typed suggestion; an empty one just denies.

        Args:
            event: Message carrying the suggestion text.
        """
        event.stop()
        suggestion = event.value.strip()
        self._decide(suggestion or False)

    def on_key(self, event: Key) -> None:
        """Closes the suggestion field on escape while it has the keyboard.

        Args:
            event: Key pressed inside the panel.
        """
        if event.key == "escape" and self.has_class("other"):
            event.stop()
            self.action_escape()

    def _decide(self, decision: bool | str) -> None:
        """Records one decision, redraws, and releases anything waiting on it.

        Args:
            decision: True, False, or the operator's suggestion.
        """
        if self.is_answered:
            return
        self.decision = decision
        self.is_answered = True
        self._answered.set()
        self.remove_class("other")
        if self.is_mounted:
            self.query_one(ApprovalCard).refresh(layout=True)
        self.post_message(self.Decided(decision))

    def wait_for_decision(self, timeout_s: float | None = None) -> bool | str:
        """Blocks the calling worker until the operator answers.

        A timeout counts as a refusal, so nothing runs that nobody approved.

        Args:
            timeout_s: Seconds to wait before treating silence as a refusal.

        Returns:
            decision: True when approved, the suggestion for other, else False.
        """
        if not self._answered.wait(timeout_s):
            return False
        return self.decision
