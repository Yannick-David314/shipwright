#!/usr/bin/env python3
"""
test_tool_gate.py --- covers the loop asking before each tool call

Contains:
    _config(): builds a config for a loop pointed at a scratch checkout
    test_no_gate_runs_tools_unattended(): headless runs behave as before
    test_declined_call_does_not_run(): a refused write leaves the file untouched
    test_declined_call_is_reported_to_the_model(): the refusal is observed
    test_approved_call_runs(): a yes lets the tool run normally
"""

from pathlib import Path

from agent.circuit_breaker import CircuitBreaker
from agent.llm_client import ScriptedLLM
from agent.loop import TOOL_ERROR_PREFIX, AgentConfig, AgentLoop

WRITE_THEN_FINISH = ["write it\nAction: write_file\npath=notes.txt\ncontent=hello", "FINAL: done"]


def _config(tmp_path: Path) -> AgentConfig:
    """Builds a config for a loop pointed at a scratch checkout.

    Args:
        tmp_path: Checkout the loop works in.

    Returns:
        config: Config with generous ceilings.
    """
    return AgentConfig(
        repo_path=str(tmp_path),
        task="write notes",
        breaker=CircuitBreaker(max_iterations=10, max_cost_usd=1.0),
    )


def test_no_gate_runs_tools_unattended(tmp_path: Path) -> None:
    """Asserts a run with no gate configured writes exactly as it always has."""
    AgentLoop(ScriptedLLM(list(WRITE_THEN_FINISH)), _config(tmp_path)).run()

    assert (tmp_path / "notes.txt").read_text() == "hello"


def test_declined_call_does_not_run(tmp_path: Path) -> None:
    """Asserts a refused write never touches the checkout."""
    config = _config(tmp_path)
    config.tool_gate = lambda tool, args: False

    AgentLoop(ScriptedLLM(list(WRITE_THEN_FINISH)), config).run()

    assert not (tmp_path / "notes.txt").exists()


def test_declined_call_is_reported_to_the_model(tmp_path: Path) -> None:
    """Asserts the refusal becomes an error observation naming the declined tool."""
    config = _config(tmp_path)
    config.tool_gate = lambda tool, args: False

    result = AgentLoop(ScriptedLLM(list(WRITE_THEN_FINISH)), config).run()

    observation = result.steps[0].observation
    assert observation.startswith(TOOL_ERROR_PREFIX)
    assert "declined this write_file call" in observation
    assert result.steps[0].diff == ""


def test_approved_call_runs(tmp_path: Path) -> None:
    """Asserts a yes lets the tool run and hands the gate the call's arguments."""
    config = _config(tmp_path)
    seen: list[tuple[str, dict[str, str]]] = []
    config.tool_gate = lambda tool, args: seen.append((tool, args)) is None

    AgentLoop(ScriptedLLM(list(WRITE_THEN_FINISH)), config).run()

    assert (tmp_path / "notes.txt").read_text() == "hello"
    assert seen == [("write_file", {"path": "notes.txt", "content": "hello"})]
