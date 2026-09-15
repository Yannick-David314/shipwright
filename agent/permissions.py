#!/usr/bin/env python3
"""
permissions.py --- decides which tool calls need the operator's approval first

Contains:
    PermissionMode: how much the agent may do without asking
    MODE_ORDER: the order shift+tab cycles through the modes
    MODE_DESCRIPTIONS: one line explaining each mode
    READ_ONLY_TOOLS / EDIT_TOOLS / COMMAND_TOOLS: tools grouped by what they touch
    parse_mode(): reads a mode name, accepting short aliases
    next_mode(): the mode after this one in the cycle
    needs_approval(): whether one tool call must be approved in a mode
    ToolGate: callable asked before a tool runs
    gate_for(): builds the gate a run checks every tool call against
"""

from collections.abc import Callable
from enum import StrEnum


class PermissionMode(StrEnum):
    """Says how much the agent may do before it has to ask."""

    MANUAL = "manual"
    EDIT_AUTOMATICALLY = "edit automatically"
    PLAN = "plan"
    BYPASS = "bypass permissions"


MODE_ORDER = (
    PermissionMode.MANUAL,
    PermissionMode.EDIT_AUTOMATICALLY,
    PermissionMode.PLAN,
    PermissionMode.BYPASS,
)
MODE_DESCRIPTIONS: dict[PermissionMode, str] = {
    PermissionMode.MANUAL: "asks before every edit and every command",
    PermissionMode.EDIT_AUTOMATICALLY: "edits files without asking; still asks before commands",
    PermissionMode.PLAN: "proposes a plan to approve, then edits without asking",
    PermissionMode.BYPASS: "edits and runs commands without asking",
}
MODE_ALIASES: dict[str, PermissionMode] = {
    "manual": PermissionMode.MANUAL,
    "default": PermissionMode.MANUAL,
    "edit": PermissionMode.EDIT_AUTOMATICALLY,
    "edits": PermissionMode.EDIT_AUTOMATICALLY,
    "auto-edit": PermissionMode.EDIT_AUTOMATICALLY,
    "edit-automatically": PermissionMode.EDIT_AUTOMATICALLY,
    "plan": PermissionMode.PLAN,
    "bypass": PermissionMode.BYPASS,
    "bypass-permissions": PermissionMode.BYPASS,
}

# Looking never needs permission; changing files and running things can.
READ_ONLY_TOOLS = frozenset({"read_file", "list_dir", "git_diff"})
EDIT_TOOLS = frozenset({"edit_file", "write_file", "apply_patch"})
COMMAND_TOOLS = frozenset({"run_shell", "run_tests"})


def parse_mode(name: str) -> PermissionMode | None:
    """Reads a mode name as the operator typed it.

    Args:
        name: Mode name or alias, in any case, with - or spaces.

    Returns:
        mode: The matching mode, or None when the name is not one.
    """
    key = name.strip().lower()
    if key in MODE_ALIASES:
        return MODE_ALIASES[key]
    return MODE_ALIASES.get(key.replace(" ", "-"))


def next_mode(mode: PermissionMode) -> PermissionMode:
    """Returns the mode after this one, wrapping at the end of the cycle.

    Args:
        mode: Mode currently in force.

    Returns:
        mode: The next mode shift+tab switches to.
    """
    return MODE_ORDER[(MODE_ORDER.index(mode) + 1) % len(MODE_ORDER)]


def needs_approval(mode: PermissionMode, tool_name: str) -> bool:
    """Reports whether one tool call must be approved before it runs.

    A tool this module does not know is treated as a command: failing towards
    asking is the safe direction when a new tool is added.

    Args:
        mode: Mode currently in force.
        tool_name: Tool the agent wants to call.

    Returns:
        needs_approval: True when the operator has to say yes first.
    """
    if tool_name in READ_ONLY_TOOLS or mode is PermissionMode.BYPASS:
        return False
    if tool_name in EDIT_TOOLS:
        return mode is PermissionMode.MANUAL
    return True


type ToolGate = Callable[[str, dict[str, str]], bool]


def gate_for(mode: Callable[[], PermissionMode], ask: ToolGate) -> ToolGate:
    """Builds the gate a run checks every tool call against.

    The mode is read on every call rather than captured once, so switching
    modes while a run is in flight applies from its very next tool call.

    Args:
        mode: Returns the mode in force at the moment of the call.
        ask: Asks the operator about one call; True means approved.

    Returns:
        gate: True when the call may run.
    """

    def gate(tool_name: str, tool_args: dict[str, str]) -> bool:
        if not needs_approval(mode(), tool_name):
            return True
        return ask(tool_name, tool_args)

    return gate
