#!/usr/bin/env python3
"""
test_permissions.py --- covers which tool calls each permission mode asks about

Contains:
    test_reading_never_asks(): looking at the checkout is always allowed
    test_manual_asks_before_edits_and_commands(): manual asks for both
    test_edit_automatically_asks_only_for_commands(): edits go straight through
    test_plan_edits_without_asking_but_asks_for_commands(): an approved plan edits freely
    test_bypass_never_asks(): bypass runs everything
    test_unknown_tool_is_treated_as_a_command(): new tools fail towards asking
    test_modes_cycle_in_order(): shift+tab walks the modes and wraps
    test_mode_names_and_aliases_parse(): typed names resolve, junk does not
    test_gate_reads_the_mode_on_every_call(): a mode switch applies immediately
"""

import pytest

from agent.permissions import (
    COMMAND_TOOLS,
    EDIT_TOOLS,
    MODE_ORDER,
    READ_ONLY_TOOLS,
    PermissionMode,
    gate_for,
    needs_approval,
    next_mode,
    parse_mode,
)


@pytest.mark.parametrize("mode", list(PermissionMode))
def test_reading_never_asks(mode: PermissionMode) -> None:
    """Asserts no mode asks before reading files, listing, or diffing."""
    assert not any(needs_approval(mode, tool) for tool in READ_ONLY_TOOLS)


def test_manual_asks_before_edits_and_commands() -> None:
    """Asserts manual mode asks before every edit and every command."""
    assert all(needs_approval(PermissionMode.MANUAL, tool) for tool in EDIT_TOOLS | COMMAND_TOOLS)


def test_edit_automatically_asks_only_for_commands() -> None:
    """Asserts edits run unasked while commands still wait for approval."""
    mode = PermissionMode.EDIT_AUTOMATICALLY

    assert not any(needs_approval(mode, tool) for tool in EDIT_TOOLS)
    assert all(needs_approval(mode, tool) for tool in COMMAND_TOOLS)


def test_plan_edits_without_asking_but_asks_for_commands() -> None:
    """Asserts an approved plan edits freely but still asks before commands."""
    mode = PermissionMode.PLAN

    assert not any(needs_approval(mode, tool) for tool in EDIT_TOOLS)
    assert all(needs_approval(mode, tool) for tool in COMMAND_TOOLS)


def test_bypass_never_asks() -> None:
    """Asserts bypass runs every tool without asking."""
    tools = READ_ONLY_TOOLS | EDIT_TOOLS | COMMAND_TOOLS | {"future_tool"}

    assert not any(needs_approval(PermissionMode.BYPASS, tool) for tool in tools)


def test_unknown_tool_is_treated_as_a_command() -> None:
    """Asserts a tool the policy does not know is asked about outside bypass."""
    assert needs_approval(PermissionMode.EDIT_AUTOMATICALLY, "future_tool")


def test_modes_cycle_in_order() -> None:
    """Asserts next_mode walks the cycle and wraps back to the start."""
    mode = MODE_ORDER[0]
    seen = []
    for _ in MODE_ORDER:
        seen.append(mode)
        mode = next_mode(mode)

    assert tuple(seen) == MODE_ORDER
    assert mode is MODE_ORDER[0]


@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        ("manual", PermissionMode.MANUAL),
        ("Edit", PermissionMode.EDIT_AUTOMATICALLY),
        ("edit automatically", PermissionMode.EDIT_AUTOMATICALLY),
        ("plan", PermissionMode.PLAN),
        ("bypass", PermissionMode.BYPASS),
        ("bypass-permissions", PermissionMode.BYPASS),
        ("yolo", None),
    ],
)
def test_mode_names_and_aliases_parse(typed: str, expected: PermissionMode | None) -> None:
    """Asserts names and aliases resolve to their mode and anything else to None."""
    assert parse_mode(typed) is expected


def test_gate_reads_the_mode_on_every_call() -> None:
    """Asserts switching modes changes what the very next call is asked about."""
    current = [PermissionMode.MANUAL]
    asked: list[str] = []
    gate = gate_for(lambda: current[0], lambda tool, args: asked.append(tool) is None and False)

    assert gate("edit_file", {"path": "a.py"}) is False
    current[0] = PermissionMode.EDIT_AUTOMATICALLY
    assert gate("edit_file", {"path": "a.py"}) is True

    assert asked == ["edit_file"]
