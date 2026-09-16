"""Tests for form detection and the arrangement plan."""

from musicxml_tools.chords import BarChord
from musicxml_tools.form import detect_form, phrase_for, summarise
from musicxml_tools.plan import plan_from_form


def _chords(figures: list[str]) -> list[BarChord]:
    return [BarChord(bar=i, root=f[0], tones=[f[0]], figure=f) for i, f in enumerate(figures)]


def test_repeated_phrases_share_a_label():
    form = detect_form(_chords(["C", "F", "G", "C"] * 3), phrase=4)
    assert summarise(form) == "A A A"
    assert [p.occurrence for p in form] == [0, 1, 2]


def test_different_phrases_get_different_labels():
    form = detect_form(_chords(["C"] * 4 + ["F"] * 4 + ["C"] * 4), phrase=4)
    assert summarise(form) == "A B A"
    assert form[2].is_repeat and not form[1].is_repeat


def test_a_trailing_part_phrase_is_kept():
    form = detect_form(_chords(["C"] * 6), phrase=4)
    assert [p.length for p in form] == [4, 2]


def test_phrase_lookup_spans_its_bars():
    form = detect_form(_chords(["C"] * 8), phrase=4)
    assert phrase_for(form, 5).start == 4
    assert phrase_for(form, 99) is None


def test_repeats_are_played_differently():
    """A repeat played identically is what makes an arrangement a loop."""
    plan = plan_from_form(_chords(["C", "F", "G", "C"] * 3), phrase_length=4)
    by_bar = {b.bar: b.density for b in plan.bars}
    assert by_bar[0] != by_bar[4], "second time through should not match the first"


def test_a_chord_change_at_a_phrase_end_is_led_into():
    plan = plan_from_form(_chords(["C", "C", "C", "C", "F", "F", "F", "F"]), phrase_length=4)
    assert {b.bar: b.bass for b in plan.bars}[3] in ("walk", "anticipate")


def test_plan_covers_every_bar():
    chords = _chords(["C", "F", "G", "C"] * 4)
    plan = plan_from_form(chords)
    assert {b.bar for b in plan.bars} == {c.bar for c in chords}
