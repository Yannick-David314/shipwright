#!/usr/bin/env python3
"""
test_queueing.py --- covers messages sent while the agent is still working

Contains:
    configured: keeps onboarding out of the way of the composer
    SlowApp: app whose runs take a moment and record the order they ran in
    _wait_until_idle(): waits for every run and queued message to finish
    test_message_sent_while_working_waits_its_turn(): runs never overlap
    test_queued_message_is_shown_until_its_turn(): a queued box sits above the composer
    test_escape_stops_the_run_in_flight(): the keyboard interrupts a run
    test_stop_control_shows_only_while_working(): the square appears with the run
    test_stopping_drops_whatever_was_queued(): stopping takes back control
"""

import asyncio
import threading
import time
from pathlib import Path

import pytest
from textual.pilot import Pilot

from agent.llm_client import Completion, Message, ScriptedLLM
from agent.loop import AgentConfig, AgentLoop
from tui.app import STOPPED_NOTICE, ShipwrightApp
from tui.screens.composer import STOP_ID, Composer
from tui.screens.timeline import Timeline

RUN_SECONDS = 0.05
GATE_TIMEOUT_S = 5.0


@pytest.fixture(autouse=True)
def configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """Gives every test a provider key so onboarding does not take focus.

    Args:
        monkeypatch: Fixture used to set the credential.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-configured")


class SlowLLM(ScriptedLLM):
    """Scripted model that answers slowly, and only once its gate is open.

    Attributes:
        gate: Held closed by a test that needs the model still thinking.
    """

    def __init__(self, replies: list[str], gate: threading.Event) -> None:
        """Builds the model behind one gate.

        Args:
            replies: Scripted replies, in order.
            gate: Event a test opens to let the answer through.
        """
        super().__init__(replies)
        self.gate = gate

    def complete(self, messages: list[Message], system: str, max_tokens: int = 0) -> Completion:
        """Waits for the gate, then returns the next scripted completion.

        Args:
            messages: Passed through.
            system: Passed through.
            max_tokens: Passed through.

        Returns:
            completion: The next scripted completion.
        """
        self.gate.wait(GATE_TIMEOUT_S)
        time.sleep(RUN_SECONDS)
        return super().complete(messages, system, max_tokens or 1)


class SlowApp(ShipwrightApp):
    """Runs each message through a slow scripted model and records overlaps.

    Attributes:
        started: Messages in the order their runs began.
        overlapped: True if two runs were ever in flight at once.
    """

    def __init__(self, repo_path: Path) -> None:
        """Builds the app with an empty record.

        Args:
            repo_path: Checkout the app is pointed at.
        """
        super().__init__(repo_path, provider="anthropic")
        self.started: list[str] = []
        self.gate = threading.Event()
        self.gate.set()
        self.overlapped = False
        self._in_flight = 0
        self._lock = threading.Lock()

    def build_loop(self, instruction: str) -> AgentLoop:
        """Builds a loop that answers slowly and notes when it runs.

        Args:
            instruction: What the operator asked the agent to do.

        Returns:
            loop: Loop replying to the message after a short wait.
        """
        app = self

        class Tracked(AgentLoop):
            def run(self, on_step=None):  # type: ignore[no-untyped-def]
                with app._lock:
                    app._in_flight += 1
                    app.overlapped = app.overlapped or app._in_flight > 1
                    app.started.append(instruction)
                try:
                    return super().run(on_step=on_step)
                finally:
                    with app._lock:
                        app._in_flight -= 1

        config = AgentConfig(repo_path=str(self.repo_path), task=instruction, conversational=True)
        config.breaker = self.breaker
        config.stop_requested = self.stop_flag.is_set
        return Tracked(SlowLLM([f"REPLY: done with {instruction}"], self.gate), config)


async def _wait_until_idle(app: ShipwrightApp, pilot: Pilot[None]) -> None:
    """Waits until no run is in flight and nothing is left in the queue.

    Args:
        app: Application under test.
        pilot: Pilot driving the app.
    """
    composer = app.query_one(Composer)
    for _ in range(200):
        await pilot.pause()
        await asyncio.sleep(0.02)
        if not composer.is_busy and not composer.pending:
            return


def test_message_sent_while_working_waits_its_turn(tmp_path: Path) -> None:
    """Asserts a message sent mid-run is queued and runs after, never alongside."""
    app = SlowApp(tmp_path)

    async def _run() -> tuple[list[str], list[str]]:
        async with app.run_test() as pilot:
            await pilot.pause()
            composer = app.query_one(Composer)
            # Back to back, before the first run's worker has even started.
            composer.submit("one")
            composer.submit("two")
            await _wait_until_idle(app, pilot)
            return app.started, [turn.answer for turn in app.query_one(Timeline).turns]

    started, answers = asyncio.run(_run())

    assert started == ["one", "two"]
    assert answers == ["done with one", "done with two"]
    assert app.overlapped is False


def test_queued_message_is_shown_until_its_turn(tmp_path: Path) -> None:
    """Asserts a message typed mid-run shows as queued, then leaves when it starts."""
    app = SlowApp(tmp_path)

    async def _run() -> tuple[list[tuple[str, str]], int]:
        async with app.run_test() as pilot:
            await pilot.pause()
            composer = app.query_one(Composer)
            app.gate.clear()
            composer.submit("one")
            await pilot.pause()
            composer.submit("two")
            await pilot.pause()
            shown = [
                (str(box.render()), str(box.border_title))
                for box in app.query("#region-queue .queued")
            ]
            app.gate.set()
            await _wait_until_idle(app, pilot)
            return shown, len(app.query("#region-queue .queued"))

    shown, left = asyncio.run(_run())

    assert shown == [("two", "queued")]
    assert left == 0


def test_escape_stops_the_run_in_flight(tmp_path: Path) -> None:
    """Asserts escape ends the run and reports it as stopped."""
    app = SlowApp(tmp_path)

    async def _run() -> tuple[str, bool]:
        async with app.run_test() as pilot:
            await pilot.pause()
            app.gate.clear()
            app.query_one(Composer).submit("one")
            await pilot.pause()
            await pilot.press("escape")
            # The model is still thinking; let its answer through afterwards.
            app.gate.set()
            await _wait_until_idle(app, pilot)
            turns = app.query_one(Timeline).turns
            return turns[-1].answer, app.query_one(Composer).is_busy

    answer, still_busy = asyncio.run(_run())

    assert answer == STOPPED_NOTICE
    assert still_busy is False


def test_stop_control_shows_only_while_working(tmp_path: Path) -> None:
    """Asserts the stop square is hidden when idle and shown while a run is in flight."""
    app = SlowApp(tmp_path)

    async def _run() -> tuple[bool, bool, bool]:
        async with app.run_test() as pilot:
            await pilot.pause()
            stop = app.query_one(f"#{STOP_ID}")
            idle = stop.display and stop.region.width > 0
            app.gate.clear()
            app.query_one(Composer).submit("one")
            await pilot.pause()
            busy = stop.region.width > 0
            app.gate.set()
            await _wait_until_idle(app, pilot)
            return idle, busy, stop.region.width > 0

    idle, busy, after = asyncio.run(_run())

    assert (idle, busy, after) == (False, True, False)


def test_stopping_drops_whatever_was_queued(tmp_path: Path) -> None:
    """Asserts stopping clears the queue instead of starting the next message."""
    app = SlowApp(tmp_path)

    async def _run() -> tuple[list[str], int]:
        async with app.run_test() as pilot:
            await pilot.pause()
            composer = app.query_one(Composer)
            app.gate.clear()
            composer.submit("one")
            await pilot.pause()
            composer.submit("two")
            await pilot.pause()
            app.request_stop()
            app.gate.set()
            await _wait_until_idle(app, pilot)
            return app.started, len(app.query("#region-queue .queued"))

    started, queued_left = asyncio.run(_run())

    assert started == ["one"]
    assert queued_left == 0
