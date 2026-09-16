"""Tests for arrangement metrics."""

from musicxml_tools import arrange_deterministically

from composer.evaluate import evaluate


def _source() -> dict:
    """Eight bars of C C F F G G C C — each chord held for two.

    Two bars per chord, not one. Chord detection carries a penalty for
    changing, tuned so a walking bass does not drag the harmony with it, and a
    fixture that changes chord every bar is precisely the case that penalty
    exists to resist. A four-bar C-F-G-C fixture gets smoothed into two chords
    and the test then measures the fixture's unreality rather than the code.
    """
    roots = ["C", "C", "F", "F", "G", "G", "C", "C"]
    return {
        "metadata": {"time_signature": "4/4", "pickup": 0.0},
        "parts": {
            "melody": [
                {"pitch": f"{r}5", "duration": 4.0, "offset": float(b * 4)}
                for b, r in enumerate(roots)
            ],
            "harmony": [
                {"pitches": [f"{r}4", f"{t}4"], "duration": 4.0, "offset": float(b * 4)}
                for b, (r, t) in enumerate(zip(roots, ["E", "E", "A", "A", "B", "B", "E", "E"]))
            ],
            "bass": [
                {"pitch": f"{r}2", "duration": 4.0, "offset": float(b * 4)}
                for b, r in enumerate(roots)
            ],
        },
    }


def test_identity_scores_perfectly():
    source = _source()
    metrics = evaluate(source, source)
    assert metrics.root_exact == 1.0
    assert metrics.harmony_fidelity == 1.0
    assert metrics.offsets_in_bar == 1.0


def test_transposed_bass_scores_zero_on_root():
    """The failure that mattered: a plausible bass in the wrong harmony."""
    source = _source()
    wrong = {
        **source,
        "parts": {
            **source["parts"],
            "bass": [
                {"pitch": "D2", "duration": 4.0, "offset": float(b * 4)} for b in range(8)
            ],
        },
    }
    assert evaluate(source, wrong).root_exact == 0.0


def test_dropped_bars_lower_coverage():
    source = _source()
    thin = {**source, "parts": {**source["parts"], "bass": source["parts"]["bass"][:4]}}
    assert evaluate(source, thin).coverage["bass"] == 0.5


def test_deterministic_arrangement_grounds_every_root_in_the_source():
    """Grounded, not exact — holding a chord is correct and breaks exactness.

    `root_exact` compares bar by bar, so an arrangement that sustains one
    harmony while the source bass moves beneath it scores as a miss even when
    that is the musical answer. What must hold is the weaker claim: every root
    played was actually sounding in the piece at that moment.
    """
    source = _source()
    metrics = evaluate(source, arrange_deterministically(source))
    assert metrics.root_grounded == 1.0


def test_harmonic_rhythm_is_idiomatic():
    """The metric whose absence let the first pass sound restless.

    Chords changing every bar scored 100% on everything else and still read as
    agitated, because nothing measured how long the harmony held.
    """
    source = _source()
    metrics = evaluate(source, arrange_deterministically(source))
    assert 1.5 <= metrics.bars_per_chord <= 4.0


def test_invented_harmony_scores_badly_on_grounding():
    """C24's failure: a plausible bass in a key the piece never visits."""
    source = _source()
    invented = {
        **source,
        "parts": {
            **source["parts"],
            "bass": [
                {"pitch": "F#2", "duration": 4.0, "offset": float(b * 4)} for b in range(8)
            ],
        },
    }
    assert evaluate(source, invented).root_grounded == 0.0
