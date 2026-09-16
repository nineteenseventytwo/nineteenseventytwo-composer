"""Tests for substitution candidates."""

import music21
import pytest

from musicxml_tools.chords import BarChord
from musicxml_tools.plan import is_related, plan_schema, substitution_menu
from musicxml_tools.reharmonise import candidates, normalise_figure


def _chord(figure: str, root: str, tones: list[str], bar: int = 0) -> BarChord:
    return BarChord(bar=bar, root=root, tones=tones, figure=figure)


DM7 = _chord("Dm7", "D", ["D", "F", "A", "C"], bar=0)
CMAJ7 = _chord("Cmaj7", "C", ["C", "E", "G", "B"], bar=1)
G7 = _chord("G7", "G", ["G", "B", "D", "F"], bar=0)


@pytest.mark.parametrize(
    ("spelling", "expected"),
    [("Db7", "D-7"), ("Bbmaj7", "B-maj7"), ("Eb7", "E-7"), ("Cm7b5", "Cm7b5")],
)
def test_flat_spellings_are_normalised(spelling, expected):
    """music21 silently misreads `b` flats — `Db7` parses as `D7`.

    A wrong chord that parses is worse than one that fails, so the rewrite
    happens before anything reads the figure.
    """
    assert normalise_figure(spelling) == expected


def test_every_candidate_is_readable_and_correct():
    for candidate in candidates(DM7, CMAJ7):
        chord = music21.harmony.ChordSymbol(normalise_figure(candidate.figure))
        assert chord.pitches, f"{candidate.figure} produced no pitches"


def test_a_dominant_is_only_offered_the_tritone_substitution():
    """Replacing V7 with the ii that precedes it trades a cadence for an approach."""
    kinds = {c.kind for c in candidates(G7, CMAJ7)}
    assert kinds == {"tritone"}


def test_a_non_dominant_is_offered_the_full_range():
    kinds = {c.kind for c in candidates(DM7, CMAJ7)}
    assert "relative" in kinds
    assert "secondary-dominant" in kinds
    assert "tritone" in kinds


def test_a_substitution_identical_to_the_chord_is_not_offered():
    """A no-op reads as a decision in the plan and changes nothing in the score."""
    figures = {c.figure for c in candidates(DM7, CMAJ7)}
    assert "Dm7" not in figures


def test_the_menu_is_authoritative_over_the_shared_tones_test():
    """A tritone substitution shares one tone with the chord it displaces.

    The generic relatedness check would reject a chord the generator just
    derived, so anything on the menu is accepted outright.
    """
    offered = candidates(DM7, CMAJ7)
    tritone = next(c for c in offered if c.kind == "tritone")
    assert is_related(DM7, tritone.figure, offered)
    assert not is_related(DM7, tritone.figure)


def test_an_invented_chord_is_still_rejected():
    assert not is_related(DM7, "G#maj7", candidates(DM7, CMAJ7))


def test_turnarounds_are_required_once_anything_is_on_offer():
    """Left optional, the model omitted the key on every score in the corpus.

    A constrained decoder takes the shortest legal path, and an absent key is
    shorter than a considered one.
    """
    menu = {3: candidates(DM7, CMAJ7)}
    schema = plan_schema(menu)
    assert "turnarounds" in schema["required"]
    chords = schema["properties"]["turnarounds"]["items"]["properties"]["chord"]["enum"]
    assert "none" in chords, "declining must remain expressible"


def test_no_turnarounds_key_when_nothing_is_offered():
    assert "turnarounds" not in plan_schema({})["required"]


def test_menu_only_covers_phrase_ends_that_change_chord():
    from musicxml_tools.form import detect_form

    chords = [_chord("Dm7", "D", ["D", "F", "A", "C"], bar=b) for b in range(4)]
    chords += [_chord("Cmaj7", "C", ["C", "E", "G", "B"], bar=b) for b in range(4, 8)]
    menu = substitution_menu(chords, detect_form(chords, phrase=4))
    assert set(menu) == {3}, "only the bar that leads into a change"
