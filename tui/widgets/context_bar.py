#!/usr/bin/env python3
"""
context_bar.py --- compact readout of context fullness, the model and the mode

Contains:
    RING_GLYPHS: the fill states the context ring cycles through
    WARN_AT / CRITICAL_AT: fractions at which the ring changes colour
    MODE_SWITCH_HINT: the key named beside the permission mode
    ring_for(): picks the glyph representing one fullness fraction
    ContextBar: the bar drawn under the composer
    ContextBar.set_usage(): records how full the context is
    ContextBar.set_model(): records which model is answering
    ContextBar.set_mode(): records which permission mode is in force
    ContextBar.render_text(): renders the ring, the percentage, the model and the mode
"""

from textual.widgets import Static

from tui.theme import Palette, palette_for

RING_GLYPHS = ("○", "◔", "◑", "◕", "●")
WARN_AT = 0.70
CRITICAL_AT = 0.90
MODE_SWITCH_HINT = "shift+tab"


def ring_for(usage: float) -> str:
    """Picks the glyph representing one fullness fraction.

    Args:
        usage: How full the context is, between 0 and 1.

    Returns:
        glyph: Ring glyph for that fraction.
    """
    clamped = min(1.0, max(0.0, usage))
    index = round(clamped * (len(RING_GLYPHS) - 1))
    return RING_GLYPHS[index]


class ContextBar(Static):
    """Draws context fullness and the active model under the composer.

    Attributes:
        usage: How full the working context is, between 0 and 1.
        model_label: Model currently answering.
        mode_label: Permission mode in force, empty to leave it out.
        palette: Colours the bar draws from.
    """

    def __init__(
        self, model_label: str = "", palette: Palette | None = None, mode_label: str = ""
    ) -> None:
        """Builds the bar for one model, showing an empty context.

        Args:
            model_label: Model currently answering.
            palette: Colours to draw from; detected from the terminal when None.
            mode_label: Permission mode in force, empty to leave it out.
        """
        super().__init__()
        self.usage = 0.0
        self.model_label = model_label
        self.mode_label = mode_label
        self.palette: Palette = palette_for() if palette is None else palette

    def colour_for_usage(self) -> str:
        """Returns the colour the ring is drawn in.

        Returns:
            colour: Muted while there is room, warning then error as it fills.
        """
        if self.usage >= CRITICAL_AT:
            return self.palette.status_error
        if self.usage >= WARN_AT:
            return self.palette.hunk
        return self.palette.accent

    def render_text(self) -> str:
        """Renders the ring, the percentage, and the model.

        Returns:
            line: Compact readout for the bar under the composer.
        """
        percent = int(round(self.usage * 100))
        parts = [f"{ring_for(self.usage)} {percent}% context"]
        if self.model_label:
            parts.append(self.model_label)
        if self.mode_label:
            parts.append(f"{self.mode_label} · {MODE_SWITCH_HINT}")
        return "   ".join(parts)

    def set_usage(self, usage: float) -> None:
        """Records how full the context is and repaints.

        Args:
            usage: Fraction of the working context in use.
        """
        self.usage = usage
        self.styles.color = self.colour_for_usage() or None
        self.update(self.render_text())

    def set_model(self, model_label: str) -> None:
        """Records which model is answering and repaints.

        Args:
            model_label: Model currently answering.
        """
        self.model_label = model_label
        self.update(self.render_text())

    def set_mode(self, mode_label: str) -> None:
        """Records which permission mode is in force and repaints.

        Args:
            mode_label: Permission mode in force.
        """
        self.mode_label = mode_label
        self.update(self.render_text())
