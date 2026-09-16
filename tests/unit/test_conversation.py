#!/usr/bin/env python3
"""
test_conversation.py --- covers answering conversation without calling tools

Contains:
    _config(): builds a guarded config, conversational or not
    test_reply_ends_a_conversational_run_without_tools(): "hi" gets a reply, no tools
    test_final_without_tools_is_still_refused(): claiming work still needs a tool
    test_reply_is_not_accepted_outside_conversation(): headless runs keep the old rules
    test_conversational_prompt_explains_reply(): the model is told when to reply
"""

from agent.circuit_breaker import CircuitBreaker
from agent.llm_client import ScriptedLLM
from agent.loop import (
    CONVERSATION_INSTRUCTIONS,
    MAX_UNGROUNDED_FINALS,
    UNGROUNDED_FINAL_NOTE,
    AgentConfig,
    AgentLoop,
)


def _config(conversational: bool, task: str = "hi") -> AgentConfig:
    """Builds a config that refuses ungrounded finals, as the interface does.

    Args:
        conversational: Whether REPLY: is accepted.
        task: What the operator typed.

    Returns:
        config: Guarded config pointed at the current directory.
    """
    return AgentConfig(
        repo_path=".",
        task=task,
        require_tool_before_final=True,
        conversational=conversational,
        breaker=CircuitBreaker(max_iterations=10, max_cost_usd=1.0),
    )


def test_reply_ends_a_conversational_run_without_tools() -> None:
    """Asserts a greeting is answered in one step, with no tool call."""
    result = AgentLoop(ScriptedLLM(["REPLY: Hi! What are we building?"]), _config(True)).run()

    assert result.final_answer == "Hi! What are we building?"
    assert len(result.steps) == 1
    assert all(not step.tool_name for step in result.steps)


def test_final_without_tools_is_still_refused() -> None:
    """Asserts FINAL: with no tool call is still refused in a conversational run."""
    replies = ["FINAL: fixed the bug"] * (MAX_UNGROUNDED_FINALS + 1)

    result = AgentLoop(ScriptedLLM(replies), _config(True, task="fix the bug")).run()

    assert result.steps[0].observation == UNGROUNDED_FINAL_NOTE


def test_reply_is_not_accepted_outside_conversation() -> None:
    """Asserts a headless run does not treat REPLY: as a way to skip the tools."""
    # Without FINAL: each reply also earns a format retry, so every step reads two.
    replies = ["REPLY: done"] * ((MAX_UNGROUNDED_FINALS + 1) * 2)

    result = AgentLoop(ScriptedLLM(replies), _config(False)).run()

    assert len(result.steps) > 1


def test_conversational_prompt_explains_reply() -> None:
    """Asserts only a conversational run is told how to reply without tools."""
    chatty = AgentLoop(ScriptedLLM([]), _config(True))._build_system_prompt()
    headless = AgentLoop(ScriptedLLM([]), _config(False))._build_system_prompt()

    assert CONVERSATION_INSTRUCTIONS in chatty
    assert CONVERSATION_INSTRUCTIONS not in headless
