#!/usr/bin/env python3
"""
setup_panel.py --- onboarding card: pick a provider, then paste its API key

Contains:
    CredentialStatus: whether one provider has a usable credential
    detect_missing(): lists providers whose credential is unset
    all_providers(): lists every provider, configured or not
    persist_key(): writes one provider credential into the .env file
    confirmation_line(): renders a save confirmation carrying no credential
    display_name(): the name a provider is listed under
    KeyInput: masked key field that reports a paste
    SetupPanel: card that picks a provider, then takes its key
    SetupPanel.target(): the provider this panel is currently collecting for
    SetupPanel.is_needed(): whether any provider still requires a key
    SetupPanel.compose(): builds the provider stage and the key stage
    SetupPanel.on_mount(): puts the keyboard on the provider dropdown
    SetupPanel.choose(): picks a provider and swaps to the key field
    SetupPanel.on_select_changed(): moves on once a provider is picked
    SetupPanel.on_key_input_pasted(): saves a key as soon as it is pasted
    SetupPanel.on_input_submitted(): verifies and saves when Enter is pressed
    SetupPanel.on_button_pressed(): skips setup
    SetupPanel.submit_key(): verifies whatever is currently typed
    SetupPanel.action_skip(): dismisses setup from the keyboard
    SetupPanel.Saved: reports which variable was written, never its value
    SetupPanel.Skipped: reports that setup was dismissed without a key
    Verification: whether a key was refused, and what to tell the operator
    verify_credential(): asks the provider whether a key works
"""

import os
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

import httpx
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.message import Message
from textual.widgets import Button, Input, Label, Select, Static

from agent.llm_client import (
    CREDENTIAL_ENV_VARS,
    MissingCredentialError,
    Provider,
    build_client,
)
from agent.llm_client import (
    Message as LLMMessage,
)
from tui.redaction import redact_secrets

ENV_FILENAME = ".env"
ENV_FILE_MODE = 0o600
KEY_INPUT_ID = "setup-key"
SKIP_BUTTON_ID = "setup-skip"
PROVIDER_SELECT_ID = "setup-provider"
STATUS_LABEL_ID = "setup-status"
PROVIDER_PROMPT = "Select your inference provider"
SELECT_PLACEHOLDER = "Choose a provider"
SKIP_LABEL = "Skip for now"
KEY_PROMPT = "Paste your key"
EMPTY_KEY_NOTICE = "Paste a key first, or press esc to skip."
VERIFYING_NOTICE = "Verifying…"
REFUSED_TEMPLATE = "That key was refused ({reason}). Paste another."
VERIFIED_TEMPLATE = "Saved to {path}"
UNVERIFIED_TEMPLATE = "Saved to {path}. The provider could not be reached ({reason})."
REJECTED_STATUSES = frozenset({401, 403})
# The dropdown lists providers by product name, not by identifier.
DISPLAY_NAMES: dict[Provider, str] = {
    Provider.ANTHROPIC: "Anthropic",
    Provider.OPENAI: "OpenAI",
}
VERIFY_TIMEOUT_S = 30.0


@dataclass(frozen=True)
class CredentialStatus:
    """Records whether one provider can be used without further setup.

    Attributes:
        provider: Provider the status describes.
        env_var: Environment variable holding that provider's credential.
        is_present: True when the credential is set and non-empty.
    """

    provider: Provider
    env_var: str
    is_present: bool


def detect_missing(environ: Mapping[str, str] | None = None) -> list[CredentialStatus]:
    """Lists the providers whose credential is absent from the environment.

    Args:
        environ: Environment to inspect; defaults to the process environment.

    Returns:
        missing: Status entries for providers that still need a key.
    """
    source: Mapping[str, str] = os.environ if environ is None else environ
    statuses = [
        CredentialStatus(provider, env_var, bool(source.get(env_var, "").strip()))
        for provider, env_var in CREDENTIAL_ENV_VARS.items()
    ]
    return [status for status in statuses if not status.is_present]


def all_providers(environ: Mapping[str, str] | None = None) -> list[CredentialStatus]:
    """Lists every provider, whether or not it already has a credential.

    Re-running setup is for changing a key or switching provider, so it must
    offer the ones already configured too.

    Args:
        environ: Environment to inspect; defaults to the process environment.

    Returns:
        statuses: One entry per provider, in catalogue order.
    """
    source: Mapping[str, str] = os.environ if environ is None else environ
    return [
        CredentialStatus(provider, env_var, bool(source.get(env_var, "").strip()))
        for provider, env_var in CREDENTIAL_ENV_VARS.items()
    ]


def persist_key(env_var: str, key: str, repo_path: Path) -> Path:
    """Writes one provider credential into the checkout's .env file.

    The file is created with owner-only permissions so a key never lands in a
    world-readable file, and an existing entry for the same variable is
    replaced rather than duplicated.

    Args:
        env_var: Environment variable name to write.
        key: Credential value to store.
        repo_path: Checkout whose .env file is updated.

    Returns:
        env_path: Path of the .env file that was written.
    """
    env_path = repo_path / ENV_FILENAME
    lines = env_path.read_text().splitlines() if env_path.exists() else []
    kept = [line for line in lines if not line.startswith(f"{env_var}=")]
    kept.append(f"{env_var}={key}")
    env_path.write_text("\n".join(kept) + "\n")
    env_path.chmod(ENV_FILE_MODE)
    return env_path


@dataclass(frozen=True)
class Verification:
    """Records what a provider said about a credential.

    Attributes:
        is_rejected: True only when the provider actively refused the key.
        message: What to tell the operator; empty when it verified cleanly.
    """

    is_rejected: bool
    message: str


def verify_credential(provider: Provider, key: str) -> Verification:
    """Asks a provider whether a credential works, with one tiny completion.

    A key is only discarded when the provider actually refuses it. Being
    unable to reach the provider at all -- offline, behind a proxy, inside a
    container with no egress -- says nothing about the key, and refusing to
    store it there would leave the operator retyping it on every launch.

    Args:
        provider: Provider the credential belongs to.
        key: Credential to test.

    Returns:
        result: Whether the key was refused, and what to report.
    """
    previous = os.environ.get(CREDENTIAL_ENV_VARS[provider])
    os.environ[CREDENTIAL_ENV_VARS[provider]] = key
    try:
        client = build_client(provider)
        client.complete([LLMMessage(role="user", content="hi")], "Reply with one word.", 16)
    except MissingCredentialError as exc:
        return Verification(is_rejected=True, message=str(exc))
    except httpx.HTTPStatusError as exc:
        refused = exc.response.status_code in REJECTED_STATUSES
        detail = f"provider returned {exc.response.status_code}"
        return Verification(is_rejected=refused, message=detail)
    except Exception as exc:  # noqa: BLE001 - anything else is a reachability problem
        return Verification(is_rejected=False, message=f"{type(exc).__name__}: {exc}")
    finally:
        if previous is None:
            with suppress(KeyError):
                del os.environ[CREDENTIAL_ENV_VARS[provider]]
        else:
            os.environ[CREDENTIAL_ENV_VARS[provider]] = previous
    return Verification(is_rejected=False, message="")


def confirmation_line(env_var: str, env_path: Path, key: str) -> str:
    """Renders the line the timeline shows once a key has been saved.

    The entered key is passed only so it can be scrubbed: the panel feeds the
    result straight into the visible timeline, which is persisted with the
    rest of the transcript.

    Args:
        env_var: Environment variable that was written.
        env_path: File the credential was written to.
        key: Credential the operator pasted, removed from the output.

    Returns:
        line: Confirmation text with no credential left in it.
    """
    return redact_secrets(f"Saved {env_var} to {env_path}", [key])


def display_name(provider: Provider) -> str:
    """Returns the name a provider is listed under in the dropdown.

    Args:
        provider: Provider to name.

    Returns:
        name: Its product name, or its identifier in title case.
    """
    return DISPLAY_NAMES.get(provider, provider.value.title())


class KeyInput(Input):
    """Masked key field that reports a paste, so a pasted key saves itself."""

    class Pasted(Message):
        """Reports that text was pasted into the key field."""

    def on_paste(self, event: events.Paste) -> None:
        """Reports a paste once Input's own handler has inserted the text.

        Textual runs Input._on_paste as well as this handler, so this must not
        insert the text again. It runs first, hence the deferred report.

        Args:
            event: The paste the terminal delivered.
        """
        if event.text.strip():
            self.call_after_refresh(self.post_message, self.Pasted())


class SetupPanel(Static):
    """Collects a provider API key: pick the provider, then paste the key.

    The card starts with a dropdown of providers and a way to skip. Choosing
    one swaps the card to a masked key field. Pasting a key, or pressing
    Enter, verifies and stores it.

    Attributes:
        repo_path: Checkout whose .env file the entered key is written to.
        missing: Providers offered in the dropdown.
        verifier: Proves a key works; injected so tests need no provider.
        chosen: Index into missing of the provider picked, or None before one is.
    """

    class Saved(Message):
        """Reports that a credential was written, without carrying its value.

        Attributes:
            env_var: Environment variable that was written.
            env_path: File the credential was written to.
        """

        def __init__(self, env_var: str, env_path: Path) -> None:
            """Records which variable was written and where.

            Args:
                env_var: Environment variable that was written.
                env_path: File the credential was written to.
            """
            super().__init__()
            self.env_var = env_var
            self.env_path = env_path

    class Skipped(Message):
        """Reports that the operator dismissed setup without entering a key."""

    BINDINGS = [Binding("escape", "skip", "Skip setup")]

    DEFAULT_CSS = """
    SetupPanel {
        border: round $accent;
        padding: 1 2;
        width: 64;
        max-width: 100%;
        height: auto;
    }
    /* The heading is turquoise, bold and underlined, so it cannot be mistaken
       for one of the providers listed beneath it. */
    SetupPanel .setup-heading {
        color: $secondary;
        text-style: bold underline;
        margin-bottom: 1;
    }
    SetupPanel Select { margin-bottom: 1; }
    SetupPanel SelectCurrent:hover { border: tall $accent; }
    SetupPanel SelectOverlay > .option-list--option-hover {
        background: $accent 40%;
        color: $text;
        text-style: bold;
    }
    SetupPanel SelectOverlay > .option-list--option-highlighted {
        background: $accent;
        color: $text;
        text-style: bold;
    }
    SetupPanel #setup-skip { width: 100%; }
    SetupPanel #setup-skip:hover { background: $accent 40%; text-style: bold; }
    SetupPanel .setup-status { color: $accent; }
    SetupPanel .key-stage { display: none; }
    SetupPanel.choosing-key .provider-stage { display: none; }
    SetupPanel.choosing-key .key-stage { display: block; }
    """

    def __init__(
        self,
        repo_path: Path,
        missing: list[CredentialStatus] | None = None,
        verifier: Callable[[Provider, str], Verification] | None = None,
    ) -> None:
        """Builds the card for whichever providers are offered.

        Args:
            repo_path: Checkout whose .env file the entered key is written to.
            missing: Providers to offer; detected from the environment when None.
            verifier: Proves a key works; defaults to a real provider call.
        """
        super().__init__()
        self.repo_path = repo_path
        self.missing = detect_missing() if missing is None else missing
        self.verifier = verify_credential if verifier is None else verifier
        self.chosen: int | None = None

    def is_needed(self) -> bool:
        """Reports whether the panel has anything left to ask for.

        Returns:
            is_needed: True while at least one provider lacks a credential.
        """
        return bool(self.missing)

    def target(self) -> CredentialStatus:
        """Returns the provider whose credential the panel is collecting.

        Returns:
            status: Provider picked in the dropdown, or the first one offered.
        """
        if self.chosen is None:
            return self.missing[0]
        return self.missing[self.chosen]

    def compose(self) -> ComposeResult:
        """Builds the provider stage and the key stage; one is shown at a time."""
        if not self.is_needed():
            yield Label("Every provider already has a key configured.")
            return
        yield Label(PROVIDER_PROMPT, classes="setup-heading provider-stage")
        yield Select(
            [(display_name(status.provider), index) for index, status in enumerate(self.missing)],
            prompt=SELECT_PLACEHOLDER,
            id=PROVIDER_SELECT_ID,
            classes="provider-stage",
        )
        yield Button(SKIP_LABEL, id=SKIP_BUTTON_ID, classes="provider-stage")
        yield Label(KEY_PROMPT, classes="setup-heading key-stage")
        yield KeyInput(placeholder="", password=True, id=KEY_INPUT_ID, classes="key-stage")
        yield Label("", id=STATUS_LABEL_ID, classes="setup-status key-stage")

    def on_mount(self) -> None:
        """Puts the keyboard on the provider dropdown as soon as the card appears."""
        if self.is_needed():
            self.query_one(f"#{PROVIDER_SELECT_ID}", Select).focus()

    def choose(self, index: int) -> None:
        """Picks a provider and swaps the card to the key field.

        Args:
            index: Position of the provider in missing.
        """
        self.chosen = index
        self.add_class("choosing-key")
        self.query_one(f"#{KEY_INPUT_ID}", Input).focus()

    def on_select_changed(self, event: Select.Changed) -> None:
        """Moves on to the key field once a provider is picked.

        Args:
            event: Change carrying the picked provider's index.
        """
        event.stop()
        if isinstance(event.value, int):
            self.choose(event.value)

    def on_key_input_pasted(self, event: KeyInput.Pasted) -> None:
        """Verifies and saves a key as soon as it is pasted.

        Args:
            event: Notice that the key field received a paste.
        """
        event.stop()
        self.submit_key()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Verifies and saves the key when Enter is pressed in the field.

        Args:
            event: Submission carrying the key that was typed.
        """
        if event.input.id != KEY_INPUT_ID:
            return
        event.stop()
        self.submit_key()

    def action_skip(self) -> None:
        """Dismisses setup from the keyboard."""
        self.post_message(self.Skipped())

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Dismisses setup when Skip for now is pressed.

        Args:
            event: Button press identifying which control was activated.
        """
        if event.button.id == SKIP_BUTTON_ID:
            event.stop()
            self.post_message(self.Skipped())

    def submit_key(self) -> None:
        """Verifies whatever is currently in the key field, then stores it if it works."""
        entry = self.query_one(f"#{KEY_INPUT_ID}", Input)
        status = self.query_one(f"#{STATUS_LABEL_ID}", Label)
        key = entry.value.strip()
        if not key:
            status.update(EMPTY_KEY_NOTICE)
            return

        target = self.target()
        status.update(VERIFYING_NOTICE)
        self.run_worker(lambda: self._verify_then_store(target, key), thread=True, exclusive=True)

    def _verify_then_store(self, target: CredentialStatus, key: str) -> None:
        """Checks the key against its provider, then hands the result back.

        Args:
            target: Provider the key belongs to.
            key: Credential the operator entered.
        """
        result = self.verifier(target.provider, key)
        self.app.call_from_thread(self._apply_verification, target, key, result)

    def _apply_verification(self, target: CredentialStatus, key: str, result: Verification) -> None:
        """Stores the key unless the provider refused it.

        Args:
            target: Provider the key belongs to.
            key: Credential the operator entered.
            result: What the provider said about the key.
        """
        status = self.query_one(f"#{STATUS_LABEL_ID}", Label)
        entry = self.query_one(f"#{KEY_INPUT_ID}", Input)
        if result.is_rejected:
            entry.value = ""
            status.update(REFUSED_TEMPLATE.format(reason=result.message))
            return

        env_path = persist_key(target.env_var, key, self.repo_path)
        # Apply it now as well: the run about to start reads the environment,
        # not the file, and re-prompting for a key just saved is nonsense.
        os.environ[target.env_var] = key
        entry.value = ""
        if result.message:
            status.update(UNVERIFIED_TEMPLATE.format(path=env_path, reason=result.message))
        else:
            status.update(VERIFIED_TEMPLATE.format(path=env_path))
        self.post_message(self.Saved(target.env_var, env_path))
