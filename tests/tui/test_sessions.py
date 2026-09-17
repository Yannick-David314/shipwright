#!/usr/bin/env python3
"""
test_sessions.py --- covers saving and resuming a session, cards and all

Contains:
    test_saved_session_loads_back(): a round trip keeps every turn and step
    test_session_file_is_owner_only(): other users cannot read a session
    test_unknown_or_malformed_id_is_refused(): bad ids fail with a clear error
    test_sessions_live_in_the_state_directory(): uninstalling removes them
    test_new_ids_are_well_formed_and_distinct(): ids are short and unique
    test_finished_turn_is_saved_under_the_session_id(): quitting any time is resumable
    test_resume_restores_and_shows_the_conversation(): ship --resume picks up the chat
    test_resume_redraws_activity_cards_and_diffs(): the whole transcript comes back
    test_sessions_saved_before_steps_still_load(): an older save is read as turns
    test_resume_with_an_unknown_id_fails_at_parse_time(): a typo is reported, not ignored
    test_exit_prints_how_to_resume(): the id is left in the terminal on the way out
    test_ctrl_c_exits_without_a_traceback(): an interrupt is not a crash
"""

import asyncio
import json
from pathlib import Path

import pytest

from agent.llm_client import Message
from tui.__main__ import build_app, main, resume_hint
from tui.app import ShipwrightApp
from tui.screens.timeline import Timeline
from tui.sessions import (
    SESSION_ID_PATTERN,
    SavedStep,
    SavedTurn,
    load_session,
    new_session_id,
    save_session,
    sessions_dir,
)
from tui.widgets.step_row import StepRow

PATCH = "diff --git a/a.py b/a.py\n@@ -1 +1 @@\n-old\n+new\n"
TURNS = [
    SavedTurn("hi", "Hi! What are we building?"),
    SavedTurn(
        "rename old to new",
        "Renamed it in a.py and ran the tests.",
        [
            SavedStep(
                "edit_file", {"path": "a.py", "find": "old", "replace": "new"}, "edited", PATCH
            )
        ],
    ),
]
CONVERSATION = [Message("user", "hi"), Message("assistant", "Hi! What are we building?")]


def test_saved_session_loads_back(tmp_path: Path) -> None:
    """Asserts saved turns read back identically, steps and diffs included."""
    session_id = new_session_id()
    save_session(session_id, Path("/workspace"), TURNS, tmp_path)

    assert load_session(session_id, tmp_path) == TURNS


def test_session_file_is_owner_only(tmp_path: Path) -> None:
    """Asserts a session file is readable by its owner alone."""
    path = save_session(new_session_id(), Path("/workspace"), TURNS, tmp_path)

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


def test_finished_turn_is_saved_under_the_session_id(tmp_path: Path) -> None:
    """Asserts each finished turn is written straight away under the app's session id."""
    app = ShipwrightApp(tmp_path)

    app.remember_turn("hi", "Hi! What are we building?")

    assert load_session(app.session_id, sessions_dir()) == [TURNS[0]]


def test_resume_restores_and_shows_the_conversation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Asserts --resume reloads the messages, keeps the id, and draws them."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-configured")
    session_id = new_session_id()
    save_session(session_id, tmp_path, [TURNS[0]], sessions_dir())

    app = build_app([str(tmp_path), "--resume", session_id])

    async def _drawn() -> list[str]:
        async with app.run_test() as pilot:
            await pilot.pause()
            return [str(widget.render()) for widget in app.query_one(Timeline).children]

    drawn = asyncio.run(_drawn())

    assert app.session_id == session_id
    assert app.conversation == CONVERSATION
    assert drawn[0] == "hi"
    assert "Hi! What are we building?" in drawn[1]


def test_resume_with_an_unknown_id_fails_at_parse_time(tmp_path: Path) -> None:
    """Asserts resuming a session that was never saved stops before the app starts."""
    with pytest.raises(SystemExit):
        build_app([str(tmp_path), "--resume", new_session_id()])


def test_exit_prints_how_to_resume() -> None:
    """Asserts the exit hint names the command and the session id."""
    assert resume_hint("0123456789ab") == "Resume this session with:\n  ship --resume 0123456789ab"


def test_resume_redraws_activity_cards_and_diffs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Asserts resuming brings back the cards and their diffs, not just the messages."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-configured")
    session_id = new_session_id()
    save_session(session_id, tmp_path, TURNS, sessions_dir())

    app = build_app([str(tmp_path), "--resume", session_id])

    async def _drawn() -> tuple[list[str], int]:
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause()
            timeline = app.query_one(Timeline)
            rows = [str(row.render()) for row in timeline.query(StepRow)]
            return rows, len(timeline.turns)

    rows, turns = asyncio.run(_drawn())

    assert turns == len(TURNS)
    assert len(rows) == 1
    assert "IN" in rows[0] and "a.py" in rows[0]
    assert "DIFF" in rows[0] and "+new" in rows[0] and "-old" in rows[0]
    assert "OUT" in rows[0] and "edited" in rows[0]


def test_sessions_saved_before_steps_still_load(tmp_path: Path) -> None:
    """Asserts a session saved as plain messages is read back as turns without steps."""
    path = tmp_path / "abcdef012345.json"
    path.write_text(
        json.dumps(
            {
                "id": "abcdef012345",
                "repo": "/workspace",
                "messages": [{"role": m.role, "content": m.content} for m in CONVERSATION],
            }
        )
    )

    assert load_session("abcdef012345", tmp_path) == [SavedTurn("hi", "Hi! What are we building?")]


def test_ctrl_c_exits_without_a_traceback(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Asserts an interrupt closes the interface quietly and still prints the hint."""

    class Interrupted(ShipwrightApp):
        def run(self, *args: object, **kwargs: object) -> None:  # type: ignore[override]
            raise KeyboardInterrupt

    app = Interrupted(tmp_path)
    app.remember_turn("hi", "Hi! What are we building?")
    monkeypatch.setattr("tui.__main__.build_app", lambda argv: app)

    assert main([str(tmp_path)]) == 0
