#!/usr/bin/env python3
"""
test_stopping.py --- covers stopping a run between steps

Contains:
    _config(): builds a config whose stop flag a test controls
    test_run_stops_before_the_first_step(): stopping at once does nothing at all
    test_run_stops_after_the_step_in_flight(): the tool that started is not repeated
    test_stopped_run_keeps_what_it_did(): the steps taken so far come back
    test_run_without_a_stop_flag_finishes(): an unattended run is unaffected
"""

from pathlib import Path

from agent.circuit_breaker import CircuitBreaker
from agent.llm_client import ScriptedLLM
from agent.loop import AgentConfig, AgentLoop

WRITE_THEN_FINISH = [
    "Writing.\nAction: write_file\npath=notes.txt\ncontent=hello",
    "FINAL: wrote it",
]


def _config(tmp_path: Path, stop: list[bool]) -> AgentConfig:
    """Builds a config whose stop flag the test flips.

    Args:
        tmp_path: Checkout the loop works in.
        stop: One-item list standing in for the stop flag.

    Returns:
        config: Config wired to that flag.
    """
    config = AgentConfig(
        repo_path=str(tmp_path),
        task="write notes",
        breaker=CircuitBreaker(max_iterations=10, max_cost_usd=1.0),
    )
    config.stop_requested = lambda: stop[0]
    return config


def test_run_stops_before_the_first_step(tmp_path: Path) -> None:
    """Asserts a run stopped before it starts calls no tool and answers nothing."""
    result = AgentLoop(ScriptedLLM(list(WRITE_THEN_FINISH)), _config(tmp_path, [True])).run()

    assert result.final_answer is None
    assert result.steps == []
    assert not (tmp_path / "notes.txt").exists()


def test_run_stops_after_the_step_in_flight(tmp_path: Path) -> None:
    """Asserts a stop between steps ends the run without dispatching the next tool."""
    stop = [False]
    config = _config(tmp_path, stop)
    client = ScriptedLLM(list(WRITE_THEN_FINISH))

    class StoppingLLM(ScriptedLLM):
        def complete(self, messages, system, max_tokens=0):  # type: ignore[no-untyped-def]
            stop[0] = True
            return client.complete(messages, system, max_tokens or 1)

    result = AgentLoop(StoppingLLM([]), config).run()

    assert result.final_answer is None
    assert not (tmp_path / "notes.txt").exists()


def test_stopped_run_keeps_what_it_did(tmp_path: Path) -> None:
    """Asserts the steps already taken are returned with the stopped run."""
    stop = [False]
    config = _config(tmp_path, stop)

    def stop_after_first(step) -> None:  # type: ignore[no-untyped-def]
        stop[0] = True

    result = AgentLoop(ScriptedLLM(list(WRITE_THEN_FINISH)), config).run(on_step=stop_after_first)

    assert result.final_answer is None
    assert [step.tool_name for step in result.steps] == ["write_file"]
    assert (tmp_path / "notes.txt").read_text() == "hello"


def test_run_without_a_stop_flag_finishes(tmp_path: Path) -> None:
    """Asserts a run with no stop flag behaves exactly as before."""
    config = AgentConfig(
        repo_path=str(tmp_path),
        task="write notes",
        breaker=CircuitBreaker(max_iterations=10, max_cost_usd=1.0),
    )

    result = AgentLoop(ScriptedLLM(list(WRITE_THEN_FINISH)), config).run()

    assert result.final_answer == "wrote it"
