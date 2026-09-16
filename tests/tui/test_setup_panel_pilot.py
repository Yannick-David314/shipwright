#!/usr/bin/env python3
"""
test_setup_panel_pilot.py --- drives the setup panel through a headless Textual pilot

Contains:
    SetupHarness: minimal app hosting just the setup panel
    test_saving_a_key_writes_the_env_file(): a pasted key reaches .env
    test_pasted_key_is_never_displayed(): the input masks what was typed
    test_key_field_waits_for_a_provider(): the key stage opens only after a choice
    test_dropdown_lists_product_names_only(): no identifiers or model names shown
    test_heading_stands_apart_from_the_options(): bold, underlined, own colour
"""

import asyncio
from pathlib import Path

from textual import events
from textual.app import App, ComposeResult
from textual.widgets import Input, Select

from agent.llm_client import Provider
from tui.widgets.setup_panel import CredentialStatus, SetupPanel, Verification

ANTHROPIC_MISSING = CredentialStatus(Provider.ANTHROPIC, "ANTHROPIC_API_KEY", False)
SAMPLE_KEY = "sk-ant-api03-Qr7TbV3wKd8ZnH2yPcE5uJf0RgXa91Lm"


class SetupHarness(App[None]):
    """Hosts the setup panel on its own so a pilot can drive it.

    Attributes:
        repo_path: Checkout the panel writes its .env into.
    """

    def __init__(self, repo_path: Path) -> None:
        """Builds the harness around one checkout.

        Args:
            repo_path: Checkout the panel writes its .env into.
        """
        super().__init__()
        self.repo_path = repo_path

    def compose(self) -> ComposeResult:
        """Mounts the setup panel with a single missing provider."""
        yield SetupPanel(
            self.repo_path,
            [ANTHROPIC_MISSING],
            verifier=lambda p, k: Verification(is_rejected=False, message=""),
        )


async def _save_key(repo_path: Path, key: str) -> str:
    """Picks the provider, pastes a key, and waits for it to be saved.

    Args:
        repo_path: Checkout the panel writes its .env into.
        key: Credential to type into the masked input.

    Returns:
        rendered: What the input widget would display after typing.
    """
    app = SetupHarness(repo_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.query_one(SetupPanel).choose(0)
        await pilot.pause()
        entry = app.query_one("#setup-key", Input)
        entry.post_message(events.Paste(key))
        await pilot.pause()
        rendered = str(entry.render())
        for _ in range(30):
            await pilot.pause()
            await asyncio.sleep(0.02)
            if (repo_path / ".env").exists():
                break
    return rendered


def test_saving_a_key_writes_the_env_file(keyless_repo: Path) -> None:
    """Asserts pasting a key persists it into the checkout's .env, once."""
    asyncio.run(_save_key(keyless_repo, SAMPLE_KEY))

    assert (keyless_repo / ".env").read_text() == f"ANTHROPIC_API_KEY={SAMPLE_KEY}\n"


def test_pasted_key_is_never_displayed(keyless_repo: Path) -> None:
    """Asserts the masked input does not render the credential on screen."""
    rendered = asyncio.run(_save_key(keyless_repo, SAMPLE_KEY))

    assert SAMPLE_KEY not in rendered


def test_key_field_waits_for_a_provider(keyless_repo: Path) -> None:
    """Asserts the key field is hidden until a provider is picked, then focused."""

    async def drive() -> tuple[bool, bool, bool, bool]:
        app = SetupHarness(keyless_repo)
        async with app.run_test() as pilot:
            await pilot.pause()
            entry = app.query_one("#setup-key", Input)
            before = (entry.display and entry.region.height > 0, app.focused is entry)
            app.query_one(SetupPanel).choose(0)
            await pilot.pause()
            after = (entry.region.height > 0, app.focused is entry)
            return (*before, *after)

    assert asyncio.run(drive()) == (False, False, True, True)


def test_dropdown_lists_product_names_only(keyless_repo: Path) -> None:
    """Asserts the dropdown offers provider names, without identifiers or models."""

    async def drive() -> list[str]:
        app = SetupHarness(keyless_repo)
        async with app.run_test() as pilot:
            await pilot.pause()
            select = app.query_one(Select)
            return [str(prompt) for prompt, _ in select._options if _ is not Select.NULL]

    assert asyncio.run(drive()) == ["Anthropic"]


def test_heading_stands_apart_from_the_options(keyless_repo: Path) -> None:
    """Asserts the provider heading is bold, underlined and not the option colour."""

    async def drive() -> tuple[str, bool, bool, bool]:
        app = SetupHarness(keyless_repo)
        async with app.run_test() as pilot:
            await pilot.pause()
            heading = app.query_one(".setup-heading")
            style = heading.styles.text_style
            label = app.query_one("SelectCurrent #label")
            different = heading.styles.color != label.styles.color
            return str(heading.render()), style.bold, style.underline, different

    assert asyncio.run(drive()) == ("Select your inference provider", True, True, True)
