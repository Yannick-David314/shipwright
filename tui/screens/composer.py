#!/usr/bin/env python3
"""
composer.py --- live instruction input that queues while a run is in flight

Contains:
    QUEUED_NOTICE / SENT_NOTICE: what the composer reports back on submit
    IDLE_PROMPT / BUSY_PROMPT: placeholder text per run state
    STOP_ID / STOP_GLYPH / STOP_TOOLTIP: the stop control shown while a run is in flight
    Composer.StopRequested: reports that the run in flight should stop
    Composer.on_click(): asks for the run to stop when the control is clicked
    Composer: input that sends when idle and queues while a run is running
    Composer.prompt_text(): the placeholder matching the current run state
    Composer.compose(): builds the input line
    Composer.submit(): sends or queues one typed instruction
    Composer.take_next(): pops the next queued instruction
    Composer.on_input_submitted(): sends what was typed when Enter is pressed
    Composer.focus_input(): puts the cursor in the instruction field
    Composer.mark_busy(): records that a run has started
    Composer.mark_idle(): records that the run finished
    Composer._refresh_outlines(): rescans the checkout at most once per run state
    Composer.Submitted: carries an instruction that is ready to run
"""

from textual import events
from textual.app import ComposeResult
from textual.message import Message
from textual.widgets import Input, Static

from agent.repo_map import RepoMap

INPUT_ID = "composer-input"
STOP_ID = "composer-stop"
STOP_GLYPH = "■"
STOP_TOOLTIP = "Stop this run (esc)"
QUEUED_NOTICE = "queued"
SENT_NOTICE = "sent"
IDLE_PROMPT = "Queue a message"
BUSY_PROMPT = "Queue a message for when this run finishes"


class Composer(Static):
    """Accepts instructions, sending them when idle and queueing them when not.

    Attributes:
        repo_map: Outline cache consulted before an instruction is handed on.
        is_busy: True while a run is in flight.
        pending: Instructions typed while the run was busy, oldest first.
    """

    class Submitted(Message):
        """Carries one instruction that is ready to be run.

        Attributes:
            instruction: Text the operator submitted.
        """

        def __init__(self, instruction: str) -> None:
            """Records the instruction being sent.

            Args:
                instruction: Text the operator submitted.
            """
            super().__init__()
            self.instruction = instruction

    class Queued(Message):
        """Reports an instruction held back because a run is in flight.

        Attributes:
            instruction: Text the operator submitted.
        """

        def __init__(self, instruction: str) -> None:
            """Records the instruction being queued.

            Args:
                instruction: Text the operator submitted.
            """
            super().__init__()
            self.instruction = instruction

    def __init__(self, repo_map: RepoMap | None = None) -> None:
        """Builds the composer, optionally sharing an outline cache.

        Args:
            repo_map: Outline cache to refresh before handing on an instruction.
        """
        super().__init__()
        self.repo_map: RepoMap | None = repo_map
        self.is_busy = False
        self.pending: list[str] = []
        self._outlines_are_stale: bool = True

    def prompt_text(self) -> str:
        """Returns the placeholder matching the current run state.

        Returns:
            prompt: Placeholder telling the operator whether input will queue.
        """
        return BUSY_PROMPT if self.is_busy else IDLE_PROMPT

    DEFAULT_CSS = """
    Composer {
        layout: horizontal;
    }
    Composer #composer-input {
        width: 1fr;
    }
    /* Only there while a run is: nothing to stop otherwise. */
    Composer #composer-stop {
        display: none;
        width: 5;
        height: 3;
        content-align: center middle;
        color: $error;
    }
    Composer.busy #composer-stop {
        display: block;
    }
    Composer #composer-stop:hover {
        background: $error;
        color: $text;
    }
    """

    class StopRequested(Message):
        """Reports that the operator asked the run in flight to stop."""

    def compose(self) -> ComposeResult:
        """Builds the instruction input beside the stop control."""
        yield Input(placeholder=self.prompt_text(), id=INPUT_ID)
        stop = Static(STOP_GLYPH, id=STOP_ID)
        stop.tooltip = STOP_TOOLTIP
        yield stop

    def on_click(self, event: events.Click) -> None:
        """Asks for the run to stop when the stop control is clicked.

        Args:
            event: The click, which may be anywhere in the composer.
        """
        widget = event.widget
        if widget is not None and widget.id == STOP_ID:
            event.stop()
            self.post_message(self.StopRequested())

    def mark_busy(self) -> None:
        """Records that a run has started, so later input is queued."""
        self.is_busy = True
        self.add_class("busy")
        self._outlines_are_stale = True

    def mark_idle(self) -> None:
        """Records that the run finished, so the next instruction sends directly."""
        self.is_busy = False
        self.remove_class("busy")
        self._outlines_are_stale = True

    def submit(self, text: str) -> str:
        """Sends the instruction, or queues it when a run is already in flight.

        Args:
            text: Raw text the operator typed.

        Returns:
            notice: Whether the instruction was sent or queued; empty when blank.
        """
        instruction = text.strip()
        if not instruction:
            return ""

        self._refresh_outlines()
        if self.is_busy:
            self.pending.append(instruction)
            self.post_message(self.Queued(instruction))
            return QUEUED_NOTICE

        self.post_message(self.Submitted(instruction))
        return SENT_NOTICE

    def focus_input(self) -> None:
        """Puts the cursor in the instruction field.

        The timeline is focusable so it can be scrolled, and it composes first,
        so without this the caret starts there and typing goes nowhere.
        """
        self.query_one(f"#{INPUT_ID}", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Sends or queues the typed instruction when Enter is pressed.

        Args:
            event: Submission carrying the text the operator typed.
        """
        if event.input.id != INPUT_ID:
            return
        if self.submit(event.value):
            event.input.value = ""

    def take_next(self) -> str | None:
        """Pops the next queued instruction, oldest first.

        Returns:
            instruction: Next queued instruction, or None when the queue is empty.
        """
        if not self.pending:
            return None
        return self.pending.pop(0)

    def _refresh_outlines(self) -> None:
        """Drops outline cache entries for files that changed on disk.

        Queueing several follow-ups behind one run used to rescan the checkout
        per instruction, which is pure waste: nothing can change on disk between
        two keystrokes while the agent holds the run. The scan is therefore done
        once and reused until the run state changes.
        """
        if self.repo_map is None or not self._outlines_are_stale:
            return
        self.repo_map.refresh(self.repo_map.detect_changes())
        self._outlines_are_stale = False
