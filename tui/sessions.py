#!/usr/bin/env python3
"""
sessions.py --- saves a conversation under an id so it can be resumed later

Contains:
    SESSIONS_SUBDIR: the folder sessions live in, inside the state directory
    SESSION_FILE_MODE: owner-only permissions for a saved session
    SESSION_ID_PATTERN: what a session id looks like
    sessions_dir(): where sessions are kept on this machine
    new_session_id(): a fresh id for a session
    save_session(): writes a session's conversation to disk
    load_session(): reads a saved session's conversation back
"""

import json
import os
import re
import uuid
from collections.abc import Mapping
from pathlib import Path

from agent.llm_client import Message

SESSIONS_SUBDIR = "sessions"
SESSION_FILE_MODE = 0o600
SESSION_ID_PATTERN = re.compile(r"^[0-9a-f]{12}$")
STATE_DIR_ENV = "SHIPWRIGHT_STATE_DIR"
# Outside the installed launcher there is no state directory, so a run from a
# checkout keeps its sessions where the install would.
FALLBACK_STATE_DIR = Path.home() / ".local" / "share" / "shipwright" / "state"


def sessions_dir(environ: Mapping[str, str] | None = None) -> Path:
    """Returns where sessions are kept on this machine.

    Sessions live in the install's state directory, so uninstalling removes
    them along with everything else.

    Args:
        environ: Environment to read the state directory from.

    Returns:
        path: Directory holding one file per session.
    """
    source = os.environ if environ is None else environ
    state = source.get(STATE_DIR_ENV, "").strip()
    return (Path(state) if state else FALLBACK_STATE_DIR) / SESSIONS_SUBDIR


def new_session_id() -> str:
    """Returns a fresh id, short enough to type back in.

    Returns:
        session_id: Twelve lowercase hex characters.
    """
    return uuid.uuid4().hex[:12]


def save_session(
    session_id: str, repo_path: Path, conversation: list[Message], directory: Path
) -> Path:
    """Writes a session's conversation to disk, replacing any earlier save.

    Args:
        session_id: Id the session is saved under.
        repo_path: Directory the session worked in.
        conversation: Messages exchanged so far, oldest first.
        directory: Folder sessions are kept in.

    Returns:
        path: File the session was written to.
    """
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{session_id}.json"
    payload = {
        "id": session_id,
        "repo": str(repo_path),
        "messages": [{"role": m.role, "content": m.content} for m in conversation],
    }
    path.write_text(json.dumps(payload, indent=2))
    path.chmod(SESSION_FILE_MODE)
    return path


def load_session(session_id: str, directory: Path) -> list[Message]:
    """Reads a saved session's conversation back.

    Args:
        session_id: Id the session was saved under.
        directory: Folder sessions are kept in.

    Returns:
        conversation: The saved messages, oldest first.

    Raises:
        LookupError: The id is malformed or no session was saved under it.
    """
    if not SESSION_ID_PATTERN.match(session_id):
        raise LookupError(f"not a session id: {session_id}")
    path = directory / f"{session_id}.json"
    if not path.is_file():
        raise LookupError(f"no saved session {session_id}")
    payload = json.loads(path.read_text())
    return [Message(role=m["role"], content=m["content"]) for m in payload["messages"]]
