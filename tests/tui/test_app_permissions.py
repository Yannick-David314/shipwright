#!/usr/bin/env python3
"""
test_app_permissions.py --- covers the app asking before tool calls, per mode

Contains:
    configured: keeps onboarding out of the way of the composer
    GatedApp: app whose loop is scripted but gated exactly like a real run
    _run(): submits an instruction, answers any approval, and reports the outcome
    test_manual_asks_and_approve_runs_the_edit(): y lets the write happen
    test_manual_deny_leaves_the_file_alone(): n stops the write
    test_edit_automatically_writes_without_asking(): no panel for an edit
    test_edit_automatically_still_asks_before_a_command(): commands still wait
    test_bypass_never_asks(): nothing is asked in bypass
"""

import asyncio
from pathlib import Path

import pytest

from agent.llm_client import ScriptedLLM
from agent.loop import AgentConfig, AgentLoop
from agent.permissions import PermissionMode
from tui.app import ShipwrightApp
from tui.screens.timeline import Timeline
from tui.widgets.approval_panel import ApprovalPanel

WRITE = ["Writing.\nAction: write_file\npath=notes.txt\ncontent=hello", "FINAL: wrote it"]
COMMAND = ["Checking.\nAction: run_shell\ncommand=touch ran.txt", "FINAL: ran it"]


@pytest.fixture(autouse=True)
def configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """Gives every test a provider key so onboarding does not take focus.

    Args:
        monkeypatch: Fixture used to set the credential.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-configured")


class GatedApp(ShipwrightApp):
    """Replays a script through a loop gated the way the real app gates it.

    Attributes:
        script: Model replies the loop replays.
    """

    script: list[str] = []

    def build_loop(self, instruction: str) -> AgentLoop:
        """Builds a scripted loop carrying the app's own tool gate.

        Args:
            instruction: What the operator asked the agent to do.

        Returns:
            loop: Loop that replays the script instead of calling a provider.
        """
        config = AgentConfig(repo_path=str(self.repo_path), task=instruction)
        config.breaker = self.breaker
        config.tool_gate = self.tool_gate()
        return AgentLoop(ScriptedLLM(list(self.script)), config)


def _run(
    tmp_path: Path, script: list[str], mode: PermissionMode, answer: str | None
) -> tuple[int, bool]:
    """Submits one instruction, answers any approval panel, and waits for the turn.

    Args:
        tmp_path: Checkout the app works in.
        script: Model replies for the run.
        mode: Permission mode the app starts in.
        answer: Key to press at an approval panel, or None to press nothing.

    Returns:
        panels: How many approval panels were shown.
        finished: Whether the turn completed.
    """
    app = GatedApp(tmp_path, provider="anthropic", permission_mode=mode)
    app.script = script

    async def drive() -> tuple[int, bool]:
        async with app.run_test() as pilot:
            await pilot.pause()
            app.start_turn_for("do the thing")
            answered = False
            for _ in range(80):
                await pilot.pause()
                await asyncio.sleep(0.02)
                waiting = [p for p in app.query(ApprovalPanel) if not p.is_answered]
                if waiting and answer is not None and not answered:
                    await pilot.press(answer)
                    answered = True
                turns = app.query_one(Timeline).turns
                if turns and turns[-1].is_finished:
                    break
            panels = len(app.query(ApprovalPanel))
            for panel in app.query(ApprovalPanel):
                panel.action_deny()
            return panels, app.query_one(Timeline).turns[-1].is_finished

    return asyncio.run(drive())


def test_manual_asks_and_approve_runs_the_edit(tmp_path: Path) -> None:
    """Asserts manual mode shows a panel and y lets the write happen."""
    assert _run(tmp_path, WRITE, PermissionMode.MANUAL, "y") == (1, True)
    assert (tmp_path / "notes.txt").read_text() == "hello"


def test_manual_deny_leaves_the_file_alone(tmp_path: Path) -> None:
    """Asserts denying the panel stops the write and the run still finishes."""
    assert _run(tmp_path, WRITE, PermissionMode.MANUAL, "n") == (1, True)
    assert not (tmp_path / "notes.txt").exists()


def test_edit_automatically_writes_without_asking(tmp_path: Path) -> None:
    """Asserts an edit runs with no panel in edit-automatically mode."""
    assert _run(tmp_path, WRITE, PermissionMode.EDIT_AUTOMATICALLY, None) == (0, True)
    assert (tmp_path / "notes.txt").read_text() == "hello"


def test_edit_automatically_still_asks_before_a_command(tmp_path: Path) -> None:
    """Asserts a shell command still waits for approval in edit-automatically mode."""
    assert _run(tmp_path, COMMAND, PermissionMode.EDIT_AUTOMATICALLY, "n") == (1, True)
    assert not (tmp_path / "ran.txt").exists()


def test_bypass_never_asks(tmp_path: Path) -> None:
    """Asserts bypass runs the write and the command without a single panel."""
    assert _run(tmp_path, WRITE, PermissionMode.BYPASS, None) == (0, True)
    assert _run(tmp_path, COMMAND, PermissionMode.BYPASS, None) == (0, True)
    assert (tmp_path / "ran.txt").exists()
