#!/usr/bin/env python3
"""
test_app.py --- covers the app's four-region composition and command routing

Contains:
    _app(): builds the app against a temporary checkout
    test_core_regions_mount(): the mark, transcript and composer all mount
    test_slash_command_is_routed(): a breaker command reaches the breaker
    test_unknown_command_is_reported(): an unknown command is reported, not raised
    test_plain_text_starts_a_turn(): ordinary text opens a turn on the timeline
    test_setup_panel_appears_without_any_key(): a keyless env prompts for setup
    test_blank_line_starts_nothing(): whitespace never opens a turn
    test_palette_reaches_textual_tokens(): the project palette themes the app
    test_chat_box_border_is_the_wordmark_blue(): focused or not, the box is brand blue
    test_working_line_has_its_own_colour(): the status line is not the blue
"""

import asyncio
from pathlib import Path

import pytest
from textual.color import Color
from textual.widgets import Input

from tui.app import ShipwrightApp
from tui.screens.composer import Composer
from tui.screens.timeline import Timeline
from tui.theme import BRAND_BLUE, DARK
from tui.widgets.wordmark import Wordmark


def _app(tmp_path: Path) -> ShipwrightApp:
    """Builds the app against a temporary checkout.

    Args:
        tmp_path: Checkout the app is pointed at.

    Returns:
        app: Configured application instance.
    """
    return ShipwrightApp(tmp_path, provider="anthropic", palette=DARK)


def test_core_regions_mount(tmp_path: Path) -> None:
    """Asserts the mark, transcript and composer all mount headless."""

    async def _boot() -> list[str]:
        app = _app(tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            return [
                type(app.query_one(widget)).__name__ for widget in (Wordmark, Timeline, Composer)
            ]

    assert asyncio.run(_boot()) == ["Wordmark", "Timeline", "Composer"]


def test_slash_command_is_routed(tmp_path: Path) -> None:
    """Asserts a breaker slash command reaches the live circuit breaker."""

    async def _run() -> float:
        app = _app(tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.handle_line("/max-cost 7.5")
            return app.breaker.max_cost_usd

    assert asyncio.run(_run()) == 7.5


def test_unknown_command_is_reported(tmp_path: Path) -> None:
    """Asserts an unregistered command is reported instead of crashing the app."""

    async def _run() -> str:
        app = _app(tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            return app.handle_line("/teleport now")

    assert "unknown command" in asyncio.run(_run())


def test_plain_text_starts_a_turn(tmp_path: Path) -> None:
    """Asserts ordinary text opens a turn on the timeline rather than routing."""

    async def _run() -> int:
        app = _app(tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.handle_line("add a health endpoint")
            for _ in range(40):
                await pilot.pause()
                await asyncio.sleep(0.05)
                if app.query_one(Timeline).turns[-1].is_finished:
                    break
            return len(app.query_one(Timeline).turns)

    assert asyncio.run(_run()) == 1


def test_setup_panel_appears_without_any_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Asserts the setup panel is offered when no provider credential is set."""
    from agent.llm_client import CREDENTIAL_ENV_VARS

    for env_var in CREDENTIAL_ENV_VARS.values():
        monkeypatch.delenv(env_var, raising=False)

    assert _app(tmp_path).needs_setup() is True


def test_blank_line_starts_nothing(tmp_path: Path) -> None:
    """Asserts a blank submission neither routes nor opens a turn."""

    async def _run() -> int:
        app = _app(tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.handle_line("   ") == ""
            return len(app.query_one(Timeline).turns)

    assert asyncio.run(_run()) == 0


def test_palette_reaches_textual_tokens(tmp_path: Path) -> None:
    """Asserts the palette the app was given is fed into Textual's design tokens."""
    variables = _app(tmp_path).get_css_variables()

    assert variables["panel-border"] == DARK.panel_border


def test_monochrome_palette_emits_no_tokens(tmp_path: Path) -> None:
    """Asserts a colourless terminal falls back to Textual's own defaults."""
    from tui.theme import MONOCHROME

    app = ShipwrightApp(tmp_path, provider="anthropic", palette=MONOCHROME)

    assert "panel-border" not in app.get_css_variables()


def test_chat_box_border_is_the_wordmark_blue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Asserts the chat box border is the wordmark blue, focused and unfocused."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-configured")

    async def _borders() -> list[Color]:
        app = _app(tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            box = app.query_one(Composer).query_one(Input)
            focused = box.styles.border_top[1]
            box.blur()
            await pilot.pause()
            return [focused, box.styles.border_top[1]]

    assert asyncio.run(_borders()) == [Color.parse(BRAND_BLUE)] * 2


def test_working_line_has_its_own_colour(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Asserts the working indicator is drawn in the activity colour, not the blue."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-configured")

    async def _colour() -> Color:
        app = _app(tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            return app.query_one("#region-status").styles.color

    colour = asyncio.run(_colour())

    assert colour == Color.parse(DARK.activity)
    assert colour != Color.parse(BRAND_BLUE)
