#!/usr/bin/env python3
"""
test_status_line.py --- covers the working indicator under the transcript

Contains:
    _line(): a status line parked at one phase and frame
    test_robot_turns_frame_by_frame(): the robot glyph changes as frames advance
    test_dots_count_up_like_typing(): the dots grow to three, then start over
    test_verbs_rotate_within_the_phase(): each phase cycles its own playful verbs
    test_line_width_holds_steady_while_dots_change(): the line does not twitch
    test_finished_run_parks_the_robot(): done stops the animation
"""

from tui.widgets.robot import (
    DOT_EVERY,
    DOTS,
    PHASE_VERBS,
    ROBOT_FRAMES,
    VERB_EVERY,
    Phase,
    StatusLine,
)


def _line(phase: Phase, frame: int) -> str:
    """Renders a status line parked at one phase and frame.

    Args:
        phase: What the agent is doing.
        frame: Animation frame to render.

    Returns:
        line: What the indicator shows at that moment.
    """
    status = StatusLine()
    status.phase = phase
    status.set_reactive(StatusLine.frame_index, frame)
    return status.render_text()


def test_robot_turns_frame_by_frame() -> None:
    """Asserts the robot glyph at the start of the line follows the frames."""
    shown = [_line(Phase.REASONING, frame).split(" ")[0] for frame in range(len(ROBOT_FRAMES))]

    assert shown == [frame.split(" ")[0] for frame in ROBOT_FRAMES]


def test_dots_count_up_like_typing() -> None:
    """Asserts the dots grow one at a time to three, then start over."""
    shown = [
        _line(Phase.REASONING, step * DOT_EVERY).rstrip().count(".")
        for step in range(len(DOTS) + 1)
    ]

    assert shown == [0, 1, 2, 3, 0]


def test_verbs_rotate_within_the_phase() -> None:
    """Asserts the verb changes every VERB_EVERY frames, cycling that phase's list."""
    verbs = PHASE_VERBS[Phase.REASONING]
    shown = [_line(Phase.REASONING, beat * VERB_EVERY) for beat in range(len(verbs))]

    assert all(verb in line for verb, line in zip(verbs, shown, strict=True))
    assert "Vibecoding" in verbs and "Hatching" in verbs


def test_line_width_holds_steady_while_dots_change() -> None:
    """Asserts the rendered width stays the same as the dots come and go."""
    widths = {len(_line(Phase.EDITING, step * DOT_EVERY)) for step in range(len(DOTS))}

    assert len(widths) == 1


def test_finished_run_parks_the_robot() -> None:
    """Asserts done parks the robot facing forward and stops animating."""
    status = StatusLine()
    status.set_phase(Phase.DONE)
    before = status.render_text()
    status.advance()

    assert status.is_animating is False
    assert status.render_text() == before == "[◉‿◉] Done"
