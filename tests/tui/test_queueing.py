#!/usr/bin/env python3
"""
test_queueing.py --- covers messages sent while the agent is still working

Contains:
    configured: keeps onboarding out of the way of the composer
    SlowApp: app whose runs take a moment and record the order they ran in
    _type_and_send(): types a line into the composer and presses Enter
    _wait_until_idle(): waits for every run and queued message to finish
    test_message_sent_while_working_waits_its_turn(): runs never overlap
"""

import asyncio
import threading
import time
from pathlib import Path

import pytest
from textual.pilot import Pilot

from agent.llm_client import Completion, Message, ScriptedLLM
from agent.loop import AgentConfig, AgentLoop
from tui.app import ShipwrightApp
from tui.screens.composer import Composer
from tui.screens.timeline import Timeline

RUN_SECONDS = 0.3


@pytest.fixture(autouse=True)
def configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """Gives every test a provider key so onboarding does not take focus.

    Args:
        monkeypatch: Fixture used to set the credential.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-configured")


class SlowLLM(ScriptedLLM):
    """Scripted model that takes a moment to answer, like a real one."""

    def complete(self, messages: list[Message], system: str, max_tokens: int = 0) -> Completion:
        """Waits, then returns the next scripted completion.

        Args:
            messages: Passed through.
            system: Passed through.
            max_tokens: Passed through.

        Returns:
            completion: The next scripted completion.
        """
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
        return Tracked(SlowLLM([f"REPLY: done with {instruction}"]), config)


async def _type_and_send(pilot: Pilot[None], line: str) -> None:
    """Types a line into the composer and presses Enter.

    Args:
        pilot: Pilot driving the app.
        line: Text to send.
    """
    for character in line:
        await pilot.press("space" if character == " " else character)
    await pilot.press("enter")


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
