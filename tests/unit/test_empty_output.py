#!/usr/bin/env python3
"""
test_empty_output.py --- covers tools that succeed while printing nothing

A command that matches nothing is an answer, not a call that never happened.
Dropping its empty observation left the model with no record of having run it,
so it ran the same command again and again.

Contains:
    _config(): builds a config pointed at a scratch checkout
    test_empty_output_is_reported_as_such(): the step carries (no output)
    test_empty_observation_reaches_the_model(): the transcript replays it
    test_repeating_a_successful_call_is_called_out(): the second one says so
    test_output_is_left_alone_when_there_is_some(): ordinary output is untouched
"""

from pathlib import Path

from agent.circuit_breaker import CircuitBreaker
from agent.llm_client import ScriptedLLM
from agent.loop import (
    EMPTY_OUTPUT_NOTE,
    REPEATED_SUCCESS_NOTE,
    AgentConfig,
    AgentLoop,
)

NOTHING_TWICE = [
    "Looking.\nAction: run_shell\ncommand=find . -name '*nothing*'",
    "Again.\nAction: run_shell\ncommand=find . -name '*nothing*'",
    "FINAL: nothing matched",
]


def _config(tmp_path: Path) -> AgentConfig:
    """Builds a config pointed at a scratch checkout.

    Args:
        tmp_path: Checkout the loop works in.

    Returns:
        config: Config with generous ceilings.
    """
    return AgentConfig(
        repo_path=str(tmp_path),
        task="find the exercises",
        breaker=CircuitBreaker(max_iterations=10, max_cost_usd=1.0),
    )


def test_empty_output_is_reported_as_such(tmp_path: Path) -> None:
    """Asserts a command that printed nothing observes (no output), not emptiness."""
    result = AgentLoop(ScriptedLLM(list(NOTHING_TWICE)), _config(tmp_path)).run()

    assert result.steps[0].observation.startswith(EMPTY_OUTPUT_NOTE)


def test_empty_observation_reaches_the_model(tmp_path: Path) -> None:
    """Asserts the empty result is replayed, so the model knows the call was made."""
    loop = AgentLoop(ScriptedLLM(list(NOTHING_TWICE)), _config(tmp_path))
    loop.run()

    replayed = [message.content for message in loop._build_messages()]

    assert any(content.startswith(f"Observation: {EMPTY_OUTPUT_NOTE}") for content in replayed)


def test_repeating_a_successful_call_is_called_out(tmp_path: Path) -> None:
    """Asserts running the very same command again is answered with a warning."""
    result = AgentLoop(ScriptedLLM(list(NOTHING_TWICE)), _config(tmp_path)).run()

    assert REPEATED_SUCCESS_NOTE not in result.steps[0].observation
    assert REPEATED_SUCCESS_NOTE in result.steps[1].observation


def test_output_is_left_alone_when_there_is_some(tmp_path: Path) -> None:
    """Asserts a command with real output observes exactly that."""
    (tmp_path / "widget.py").write_text("print('hi')\n")
    script = ["Looking.\nAction: run_shell\ncommand=ls", "FINAL: listed it"]

    result = AgentLoop(ScriptedLLM(script), _config(tmp_path)).run()

    assert "widget.py" in result.steps[0].observation
    assert EMPTY_OUTPUT_NOTE not in result.steps[0].observation
