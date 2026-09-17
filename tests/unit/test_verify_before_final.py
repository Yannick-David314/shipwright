#!/usr/bin/env python3
"""
test_verify_before_final.py --- covers the run checking its own work first

Contains:
    _config(): builds a config that insists on a check before finishing
    test_finishing_with_unchecked_edits_is_refused(): the model is sent back
    test_running_the_tests_counts_as_checking(): a test run lets it finish
    test_reading_the_file_back_counts_as_checking(): so does re-reading it
    test_editing_again_needs_another_check(): the last edit has to be checked too
    test_a_failed_check_keeps_the_run_going(): what the check said comes back
    test_read_only_runs_finish_as_before(): nothing changed means nothing to check
"""

from pathlib import Path

from agent.circuit_breaker import CircuitBreaker
from agent.llm_client import ScriptedLLM
from agent.loop import UNVERIFIED_FINAL_NOTE, AgentConfig, AgentLoop

WRITE = "Writing.\nAction: write_file\npath=notes.txt\ncontent=hello"
FINISH = "FINAL: wrote notes.txt"


def _config(tmp_path: Path) -> AgentConfig:
    """Builds a config that insists on a check before finishing.

    Args:
        tmp_path: Checkout the loop works in.

    Returns:
        config: Config with the check turned on.
    """
    return AgentConfig(
        repo_path=str(tmp_path),
        task="write notes",
        verify_before_final=True,
        breaker=CircuitBreaker(max_iterations=12, max_cost_usd=1.0),
    )


def test_finishing_with_unchecked_edits_is_refused(tmp_path: Path) -> None:
    """Asserts a run that wrote a file and finished at once is sent back to check."""
    result = AgentLoop(ScriptedLLM([WRITE, FINISH, FINISH, FINISH]), _config(tmp_path)).run()

    assert result.steps[1].observation == UNVERIFIED_FINAL_NOTE


def test_running_the_tests_counts_as_checking(tmp_path: Path) -> None:
    """Asserts running the work through a command lets the run finish."""
    script = [WRITE, "Checking.\nAction: run_shell\ncommand=cat notes.txt", FINISH]

    result = AgentLoop(ScriptedLLM(script), _config(tmp_path)).run()

    assert result.final_answer == "wrote notes.txt"
    assert all(step.observation != UNVERIFIED_FINAL_NOTE for step in result.steps)


def test_reading_the_file_back_counts_as_checking(tmp_path: Path) -> None:
    """Asserts re-reading the changed file counts as looking at the result."""
    script = [WRITE, "Reading it back.\nAction: read_file\npath=notes.txt", FINISH]

    result = AgentLoop(ScriptedLLM(script), _config(tmp_path)).run()

    assert result.final_answer == "wrote notes.txt"


def test_editing_again_needs_another_check(tmp_path: Path) -> None:
    """Asserts a check before the last edit does not cover the edit after it."""
    script = [
        WRITE,
        "Reading it back.\nAction: read_file\npath=notes.txt",
        "Writing.\nAction: write_file\npath=notes.txt\ncontent=hello again",
        FINISH,
        FINISH,
        FINISH,
    ]

    result = AgentLoop(ScriptedLLM(script), _config(tmp_path)).run()

    assert result.steps[3].observation == UNVERIFIED_FINAL_NOTE


def test_a_failed_check_keeps_the_run_going(tmp_path: Path) -> None:
    """Asserts what a failing check printed comes back, so the run can act on it."""
    script = [
        WRITE,
        "Checking.\nAction: run_shell\ncommand=cat missing.txt",
        "Fixing.\nAction: read_file\npath=notes.txt",
        FINISH,
    ]

    result = AgentLoop(ScriptedLLM(script), _config(tmp_path)).run()

    assert "No such file" in result.steps[1].observation
    assert result.final_answer == "wrote notes.txt"


def test_read_only_runs_finish_as_before(tmp_path: Path) -> None:
    """Asserts a run that changed nothing is not asked to check anything."""
    script = ["Looking.\nAction: list_dir\npath=.", "FINAL: nothing to change"]

    result = AgentLoop(ScriptedLLM(script), _config(tmp_path)).run()

    assert result.final_answer == "nothing to change"
