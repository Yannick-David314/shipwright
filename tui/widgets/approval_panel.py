#!/usr/bin/env python3
"""
approval_panel.py --- asks the operator whether one tool call may run

Contains:
    ALLOW_KEY / DENY_KEY: the keys that answer the panel
    PREVIEW_LINES: how much of a proposed change the panel shows
    ESCAPE_TOOL: pseudo tool name for a command leaving the working directory
    question_for(): the question the panel asks about one call
    proposal_lines(): what the call would do, coloured like a diff
    ApprovalPanel: bordered card that waits for an explicit yes or no
    ApprovalPanel.render(): draws the question, the proposal and the key hints
    ApprovalPanel.action_allow(): approves the call
    ApprovalPanel.action_deny(): refuses the call
    ApprovalPanel.wait_for_decision(): blocks a worker until the operator answers
    ApprovalPanel.Decided: reports the operator's answer to the app
"""

import threading

from rich.text import Text
from textual.binding import Binding
from textual.message import Message
from textual.widgets import Static

from tui.theme import Palette, palette_for
from tui.widgets.step_row import FALLBACK_CARD_WIDTH, MIN_CARD_WIDTH, CardSection, draw_card

ALLOW_KEY = "y"
DENY_KEY = "n"
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


class ApprovalPanel(Static):
    """Draws one proposed tool call and waits for an explicit yes or no.

    Attributes:
        tool_name: Tool the agent wants to call.
        tool_args: Arguments it would be called with.
        palette: Colours the card is drawn in.
        is_allowed: True once the call has been approved.
        is_answered: True once the operator has answered either way.
    """

    can_focus = True

    DEFAULT_CSS = """
    ApprovalPanel {
        height: auto;
        margin-top: 1;
    }
    """

    class Decided(Message):
        """Reports the operator's answer, so the app can hand the keyboard back.

        Attributes:
            is_allowed: True when the operator approved the call.
        """

        def __init__(self, is_allowed: bool) -> None:
            """Records the answer the operator gave.

            Args:
                is_allowed: True when the operator approved the call.
            """
            super().__init__()
            self.is_allowed = is_allowed

    BINDINGS = [
        Binding(ALLOW_KEY, "allow", "Allow"),
        Binding(DENY_KEY, "deny", "Deny"),
        Binding("escape", "deny", "Deny", show=False),
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
        self.is_allowed = False
        self.is_answered = False
        self._answered = threading.Event()

    def render(self) -> Text:
        """Draws the question, the proposal card and the key hints.

        Once answered the panel shrinks to one line recording the decision,
        so the transcript keeps what was allowed without the whole card.

        Returns:
            rendered: The panel as coloured text.
        """
        block = Text()
        question = question_for(self.tool_name, self.tool_args)
        if self.is_answered:
            verdict = "allowed" if self.is_allowed else "denied"
            colour = self.palette.add if self.is_allowed else self.palette.status_error
            subject = self.tool_args.get("path") or self.tool_args.get("command", "")
            block.append(f"{verdict}  ", style=colour)
            block.append(f"{self.tool_name} {subject}".strip(), style=self.palette.hunk)
            return block
        block.append("? ", style=self.palette.accent)
        block.append(question, style=f"bold {self.palette.foreground}".strip())
        width = self.size.width if self.size.width >= MIN_CARD_WIDTH else FALLBACK_CARD_WIDTH
        label = "EDIT" if self.tool_name in {"edit_file", "write_file", "apply_patch"} else "RUN"
        target = self.tool_args.get("path", "")
        sections: list[CardSection] = []
        if target and self.tool_name != "run_shell":
            sections.append(("FILE", [(target, self.palette.foreground)]))
        sections.append((label, proposal_lines(self.tool_name, self.tool_args, self.palette)))
        draw_card(block, sections, width, self.palette)
        block.append(f"\n[{ALLOW_KEY}] allow   [{DENY_KEY}] deny", style=self.palette.hunk)
        return block

    def action_allow(self) -> None:
        """Approves the call and lets the waiting run proceed."""
        self._decide(True)

    def action_deny(self) -> None:
        """Refuses the call and lets the waiting run carry on without it."""
        self._decide(False)

    def _decide(self, is_allowed: bool) -> None:
        """Records one decision, redraws, and releases anything waiting on it.

        Args:
            is_allowed: True when the operator approved the call.
        """
        if self.is_answered:
            return
        self.is_allowed = is_allowed
        self.is_answered = True
        self._answered.set()
        self.refresh(layout=True)
        self.post_message(self.Decided(is_allowed))

    def wait_for_decision(self, timeout_s: float | None = None) -> bool:
        """Blocks the calling worker until the operator answers.

        A timeout counts as a refusal, so nothing runs that nobody approved.

        Args:
            timeout_s: Seconds to wait before treating silence as a refusal.

        Returns:
            is_allowed: True only when the operator explicitly approved.
        """
        if not self._answered.wait(timeout_s):
            return False
        return self.is_allowed
