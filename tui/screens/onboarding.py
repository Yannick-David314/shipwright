#!/usr/bin/env python3
"""
onboarding.py --- first-run screen: welcome, terms, provider, key

Contains:
    TERMS_TEXT: the one-paragraph terms shown before setup
    ACCEPT_LABEL: the label on the button accepting them
    MARK_MIN_HEIGHT / MARK_MIN_WIDTH: the smallest window that shows the heading
    TermsCard: bordered card holding the terms and the accept button
    TermsCard.Accepted: reports that the terms were accepted
    OnboardingScreen: centred welcome heading above one card at a time
    OnboardingScreen.build_setup(): builds the provider setup card
    OnboardingScreen.compose(): lays out the heading and the first card
    OnboardingScreen.on_resize(): drops the heading when the window is too small
    OnboardingScreen.on_terms_card_accepted(): swaps the terms for provider setup
"""

from collections.abc import Callable
from pathlib import Path

from textual import events
from textual.app import ComposeResult
from textual.containers import Center, Vertical
from textual.message import Message
from textual.screen import Screen
from textual.widgets import Button, Static

from agent.llm_client import Provider
from tui.widgets.setup_panel import CredentialStatus, SetupPanel, Verification
from tui.widgets.wordmark import WELCOME_WORDS, Wordmark

ACCEPT_LABEL = "Accept and continue"
# The heading is 11 rows and 65 columns; below this it would push the card off screen.
MARK_MIN_HEIGHT = 34
MARK_MIN_WIDTH = 70
ACCEPT_BUTTON_ID = "terms-accept"
TERMS_TEXT = (
    "Shipwright is a fun open source side project, built by people who think robots "
    "writing pull requests is a perfectly normal hobby. It comes with no warranty of "
    "any kind, express or implied, so treat every change it makes like a pull request "
    "from a very enthusiastic intern and review it before you merge. The agent runs "
    "inside a gVisor sandbox and only sees the folder you opened, yet you stay "
    "responsible for the commands you approve, the code you ship, and whatever your "
    "model provider bills you for tokens. Your API key stays on this machine and is "
    "only ever sent to the provider you choose. By continuing you accept these terms "
    "and the MIT License, and you agree to be as kind as possible to the agent. "
    "It is doing its best."
)


class TermsCard(Vertical):
    """Shows the terms in a bordered card with one button to accept them."""

    class Accepted(Message):
        """Reports that the operator accepted the terms."""

    DEFAULT_CSS = """
    TermsCard {
        border: round $accent;
        padding: 1 2;
        width: 72;
        max-width: 100%;
        height: auto;
    }
    TermsCard #terms-text {
        color: $accent;
        margin-bottom: 1;
    }
    TermsCard Center {
        height: auto;
    }
    TermsCard Button {
        min-width: 0;
        width: auto;
    }
    """

    def compose(self) -> ComposeResult:
        """Lays out the terms paragraph above the accept button."""
        yield Static(TERMS_TEXT, id="terms-text")
        with Center():
            yield Button(ACCEPT_LABEL, id=ACCEPT_BUTTON_ID, variant="primary", compact=True)

    def on_mount(self) -> None:
        """Puts the keyboard on the accept button, so Enter accepts."""
        self.query_one(f"#{ACCEPT_BUTTON_ID}", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Reports acceptance when the button is pressed.

        Args:
            event: Button press identifying which control was activated.
        """
        if event.button.id == ACCEPT_BUTTON_ID:
            event.stop()
            self.post_message(self.Accepted())


class OnboardingScreen(Screen[None]):
    """Centres the welcome heading above the terms, then provider setup.

    The screen does not decide when it is finished: the setup card's Saved
    and Skipped messages bubble to the app, which closes it.

    Attributes:
        repo_path: Checkout whose .env file the key is written to.
        offered: Providers the setup card lists; detected when None.
        verifier: Proves a key works; injected so tests need no provider.
        show_terms: Whether the terms come before provider setup.
    """

    DEFAULT_CSS = """
    OnboardingScreen {
        align: center middle;
        overflow-y: auto;
    }
    OnboardingScreen #onboarding {
        width: 100%;
        height: auto;
        align: center top;
    }
    OnboardingScreen #onboarding-card {
        height: auto;
    }
    OnboardingScreen #welcome-mark {
        width: 100%;
        content-align: center middle;
        margin-bottom: 1;
    }
    """

    def __init__(
        self,
        repo_path: Path,
        offered: list[CredentialStatus] | None = None,
        verifier: Callable[[Provider, str], Verification] | None = None,
        show_terms: bool = True,
    ) -> None:
        """Builds the screen for one checkout.

        Args:
            repo_path: Checkout whose .env file the key is written to.
            offered: Providers the setup card lists; detected when None.
            verifier: Proves a key works; defaults to a real provider call.
            show_terms: Whether the terms come before provider setup.
        """
        super().__init__()
        self.repo_path = repo_path
        self.offered = offered
        self.verifier = verifier
        self.show_terms = show_terms

    def build_setup(self) -> SetupPanel:
        """Builds the provider setup card.

        Returns:
            panel: Card that picks a provider, then takes its key.
        """
        return SetupPanel(self.repo_path, missing=self.offered, verifier=self.verifier)

    def compose(self) -> ComposeResult:
        """Lays out the heading and whichever card comes first."""
        with Vertical(id="onboarding"):
            yield Wordmark(id="welcome-mark", words=WELCOME_WORDS)
            with Center(id="onboarding-card"):
                yield TermsCard() if self.show_terms else self.build_setup()

    def on_resize(self, event: events.Resize) -> None:
        """Drops the block heading when the window is too small to hold it and a card.

        Args:
            event: The screen's new size.
        """
        fits = event.size.height >= MARK_MIN_HEIGHT and event.size.width >= MARK_MIN_WIDTH
        self.query_one("#welcome-mark", Wordmark).display = fits

    def on_terms_card_accepted(self, event: TermsCard.Accepted) -> None:
        """Swaps the terms card for provider setup.

        Args:
            event: Notice that the terms were accepted.
        """
        event.stop()
        self.query_one(TermsCard).remove()
        self.query_one("#onboarding-card", Center).mount(self.build_setup())
