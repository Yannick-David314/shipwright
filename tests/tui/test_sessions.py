#!/usr/bin/env python3
"""
test_sessions.py --- covers saving and resuming a session's conversation

Contains:
    test_saved_session_loads_back(): a round trip keeps every message in order
    test_session_file_is_owner_only(): other users cannot read a session
    test_unknown_or_malformed_id_is_refused(): bad ids fail with a clear error
    test_sessions_live_in_the_state_directory(): uninstalling removes them
    test_new_ids_are_well_formed_and_distinct(): ids are short and unique
"""

from pathlib import Path

import pytest

from agent.llm_client import Message
from tui.sessions import (
    SESSION_ID_PATTERN,
    load_session,
    new_session_id,
    save_session,
    sessions_dir,
)

CONVERSATION = [Message("user", "hi"), Message("assistant", "Hi! What are we building?")]


def test_saved_session_loads_back(tmp_path: Path) -> None:
    """Asserts a saved conversation reads back identically, oldest first."""
    session_id = new_session_id()
    save_session(session_id, Path("/workspace"), CONVERSATION, tmp_path)

    assert load_session(session_id, tmp_path) == CONVERSATION


def test_session_file_is_owner_only(tmp_path: Path) -> None:
    """Asserts a session file is readable by its owner alone."""
    path = save_session(new_session_id(), Path("/workspace"), CONVERSATION, tmp_path)

    assert path.stat().st_mode & 0o777 == 0o600


def test_unknown_or_malformed_id_is_refused(tmp_path: Path) -> None:
    """Asserts an id with no saved session, or a path-like one, is refused."""
    with pytest.raises(LookupError):
        load_session(new_session_id(), tmp_path)
    with pytest.raises(LookupError):
        load_session("../../etc/passwd", tmp_path)


def test_sessions_live_in_the_state_directory(tmp_path: Path) -> None:
    """Asserts sessions are kept inside the install's state directory."""
    assert sessions_dir({"SHIPWRIGHT_STATE_DIR": str(tmp_path)}) == tmp_path / "sessions"


def test_new_ids_are_well_formed_and_distinct() -> None:
    """Asserts new ids match the id pattern and do not repeat."""
    ids = {new_session_id() for _ in range(50)}

    assert len(ids) == 50
    assert all(SESSION_ID_PATTERN.match(session_id) for session_id in ids)
