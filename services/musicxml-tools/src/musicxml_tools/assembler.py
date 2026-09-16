"""Assemble individual parts into a complete MusicXML score."""

import re
from pathlib import Path

import music21

# General MIDI puts all percussion on channel 10. music21 cannot express that
# for more than one instrument: `autoAssignMidiChannel` hands channel 10 to the
# first UnpitchedPercussion it sees, and the exporter's channel deduplication
# then treats every later percussion instrument as a collision and pushes it
# onto a pitched channel. A three-piece kit came out as hi-hat on 10 and the
# cross-stick and bass drum on 4 and 5 — melodic patches playing MIDI notes 37
# and 36, which is very low and sustaining, and sounds like a boomy thud rather
# than a drum.
#
# Setting `midiChannel` on the instruments does not survive: the exporter
# reassigns on the way out. So the correction is applied to the written file,
# by the rule that identifies percussion unambiguously — any `midi-instrument`
# carrying a `midi-unpitched` element belongs on channel 10.
_PERCUSSION_CHANNEL = 10
_MIDI_INSTRUMENT = re.compile(r"<midi-instrument\b.*?</midi-instrument>", re.S)
_MIDI_CHANNEL = re.compile(r"(<midi-channel>)(\d+)(</midi-channel>)")

# MusicXML's <instrument-sound> is how a reader identifies a percussion voice
# without guessing from its name. music21 never emits it — the attribute exists
# on the Instrument and is silently dropped on export — so a reader falls back
# to <instrument-name>, and a part whose first instrument is called "Bass Drum"
# gets matched to a *concert* bass drum: one boomy sustaining instrument
# playing the whole staff, which is why the kit had no timekeeper sound and
# every note read as a bass drum.
#
# Keyed by instrument name, which is what appears in the exported file.
_INSTRUMENT_SOUNDS = {
    "Bass Drum 1": "drum.bass-drum",
    "Side Stick": "drum.snare-drum",
    "Shaker": "rattle.shaker",
    "Square Synthesizer": "synth.tone.square",
    "Alto Saxophone": "wind.reed.saxophone.alto",
}
_INSTRUMENT_NAME = re.compile(r"<instrument-name>([^<]*)</instrument-name>")
_SCORE_INSTRUMENT = re.compile(r"<score-instrument\b.*?</score-instrument>", re.S)
_MIDI_UNPITCHED = re.compile(r"<midi-unpitched>(\d+)</midi-unpitched>")
_SCORE_PART = re.compile(r'<score-part id="([^"]+)">(.*?)</score-part>', re.S)
_PART = re.compile(r'(<part id="([^"]+)">)(.*?)(</part>)', re.S)
_NOTE = re.compile(r"<note\b.*?</note>", re.S)
_DURATION_END = re.compile(r"</duration>")

from musicxml_tools.splitter import SplitParts

# Practical ranges. Melody and bass are derived by taking the top or bottom
# note of a piano texture, which spans far more than either instrument can
# play — on the reference score 30 of 258 melody notes and 80 of 336 bass
# notes fell outside, which a reader flags in red. Harmony is folded into a
# comping register because that is what the arrangement asks for: middle
# voices under the melody, rootless, out of the bass's way.
#
# The sax range is in WRITTEN pitch, since that is what ends up on the page.
ALTO_SAX_WRITTEN_RANGE = ("Bb3", "F6")
BASS_RANGE = ("E1", "G4")
HARMONY_RANGE = ("C3", "C5")


def _square_synth(name: str, abbreviation: str) -> music21.instrument.Instrument:
    """A pulse-wave voice.

    Harmony and bass are both destined for the Game Boy's two pulse channels
    (docs/performance-context.md), so notating them as piano and electric bass
    described a performance that will never happen. General MIDI program 81 is
    "Lead 1 (square)"; the name is what a reader matches against its own
    instrument list.
    """
    instrument = music21.instrument.Instrument()
    instrument.instrumentName = name
    instrument.instrumentAbbreviation = abbreviation
    instrument.midiProgram = 80  # 0-indexed; GM 81, Lead 1 (square)
    return instrument


def assemble_score(
    parts: SplitParts,
    drums: music21.stream.Part | None = None,
    title: str | None = None,
    shaker: music21.stream.Part | None = None,
) -> music21.stream.Score:
    """Assemble individual parts into a complete score.

    Args:
        parts: SplitParts with melody, harmony, and bass.
        drums: Optional drum part to include.
        title: Optional title override (defaults to metadata title).

    Returns:
        A music21 Score with all parts.
    """
    score = music21.stream.Score()

    # Set metadata
    md = music21.metadata.Metadata()
    md.title = title or parts.metadata.get("title", "Bossa Arrangement")
    score.metadata = md

    # Set tempo
    tempo_val = parts.metadata.get("tempo", 120)
    score.insert(0, music21.tempo.MetronomeMark(number=tempo_val))

    # Add parts in score order
    _set_instrument(parts.melody, music21.instrument.AltoSaxophone())
    # The alto is in E-flat. music21 streams hold sounding pitch, and the
    # exporter writes a <transpose> element without moving the notes — so a
    # concert-pitch part is read as written pitch and sounds a major sixth
    # low. Convert to written pitch so the notation and the playback agree.
    parts.melody.toWrittenPitch(inPlace=True)
    _fit_to_range(parts.melody, *ALTO_SAX_WRITTEN_RANGE)
    _set_clef(parts.melody, music21.clef.TrebleClef())
    score.insert(0, parts.melody)

    # "Harmony", not "Piano": the part name describes the role now that the
    # sound is a pulse wave, and a reader matching on "Piano" would offer a
    # piano patch for a channel that cannot produce one.
    parts.harmony.partName = "Harmony"
    parts.harmony.partAbbreviation = "Harm."
    _set_instrument(parts.harmony, _square_synth("Square Synthesizer", "Sq. 1"))
    _fit_to_range(parts.harmony, *HARMONY_RANGE)
    _set_clef(parts.harmony, music21.clef.TrebleClef())
    score.insert(0, parts.harmony)

    _set_instrument(parts.bass, _square_synth("Square Synthesizer", "Sq. 2"))
    _fit_to_range(parts.bass, *BASS_RANGE)
    _set_clef(parts.bass, music21.clef.BassClef())
    score.insert(0, parts.bass)

    # Do not rename either percussion part: the part name is what a reader
    # matches against its instrument list. Overwriting the kit's name with
    # "Drums" sent MuseScore looking for a single orchestral percussion
    # instrument rather than a kit.
    if drums is not None:
        score.insert(0, drums)

    if shaker is not None:
        score.insert(0, shaker)

    return score


def write_score(score: music21.stream.Score, filepath: str | Path, fmt: str = "musicxml") -> None:
    """Write a score to a file.

    Args:
        score: The score to write.
        filepath: Output file path.
        fmt: Output format (default: musicxml).
    """
    score.write(fmt, fp=str(filepath))
    if fmt == "musicxml":
        _force_percussion_channel(Path(filepath))


def _force_percussion_channel(filepath: Path) -> None:
    """Correct percussion routing and identification in a written score.

    Two repairs, both for things music21 cannot express on export: every
    unpitched instrument goes back on the General MIDI drum channel, and each
    gains the `<instrument-sound>` element a reader needs to map it to the
    right kit piece.
    """
    try:
        content = filepath.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return

    def channel(match: re.Match) -> str:
        block = match.group(0)
        if _MIDI_UNPITCHED.search(block) is None:
            return block
        return _MIDI_CHANNEL.sub(
            lambda m: f"{m.group(1)}{_PERCUSSION_CHANNEL}{m.group(3)}", block
        )

    patched = _MIDI_INSTRUMENT.sub(channel, content)

    def sound(match: re.Match) -> str:
        block = match.group(0)
        if "<instrument-sound>" in block:
            return block
        name = _INSTRUMENT_NAME.search(block)
        if name is None:
            return block
        value = _INSTRUMENT_SOUNDS.get(name.group(1).strip())
        if value is None:
            return block
        # Schema order: name, abbreviation, then sound.
        return block.replace(
            "</score-instrument>",
            f"<instrument-sound>{value}</instrument-sound>\n    </score-instrument>",
        )

    patched = _SCORE_INSTRUMENT.sub(sound, patched)
    patched = _name_single_instrument_notes(patched)

    if patched != content:
        filepath.write_text(patched, encoding="utf-8")


def _name_single_instrument_notes(content: str) -> str:
    """Give percussion notes an explicit `<instrument>` reference.

    music21 emits per-note `<instrument>` only when a part holds more than one
    instrument — `setNoteInstrument` short-circuits otherwise, on the reasoning
    that a lone instrument is unambiguous. It is not unambiguous to a reader
    building a drum map: the two-instrument kit part resolved correctly while
    the one-instrument shaker part, identical in every other respect, played as
    a pitched instrument. The reference is what distinguishes them.

    Applied only to parts whose single instrument is unpitched, so nothing
    pitched is touched.
    """
    solo_percussion: dict[str, str] = {}

    for part_id, body in _SCORE_PART.findall(content):
        instrument_ids = re.findall(r'<score-instrument id="([^"]+)"', body)
        if len(instrument_ids) != 1:
            continue
        if _MIDI_UNPITCHED.search(body) is None:
            continue
        solo_percussion[part_id] = instrument_ids[0]

    if not solo_percussion:
        return content

    def rewrite_part(match: re.Match) -> str:
        opening, part_id, body, closing = match.groups()
        instrument_id = solo_percussion.get(part_id)
        if instrument_id is None:
            return match.group(0)

        def rewrite_note(note_match: re.Match) -> str:
            note = note_match.group(0)
            if "<unpitched>" not in note or "<instrument" in note:
                return note
            # Schema order puts <instrument> immediately after <duration>.
            return _DURATION_END.sub(
                f'</duration>\n        <instrument id="{instrument_id}" />',
                note,
                count=1,
            )

        return opening + _NOTE.sub(rewrite_note, body) + closing

    return _PART.sub(rewrite_part, content)


def _fit_to_range(part: music21.stream.Part, lowest: str, highest: str) -> None:
    """Octave-shift notes until they sit inside an instrument's range.

    Shifting by octaves rather than clamping keeps the line's shape and its
    pitch classes intact — the harmony stays the same harmony, just voiced
    where the instrument can play it.
    """
    low = music21.pitch.Pitch(lowest).midi
    high = music21.pitch.Pitch(highest).midi
    window = high - low
    if window < 12:  # nothing sensible to fold into
        return

    for element in list(part.recurse().notes):
        if isinstance(element, music21.note.Unpitched):
            continue
        pitches = element.pitches
        if not pitches:
            continue

        bottom = min(p.midi for p in pitches)
        top = max(p.midi for p in pitches)

        if top - bottom > window:
            # A chord wider than the window can never fit. Centre it in one
            # move rather than shifting up and down forever — the naive
            # version oscillated and left chords further out than it found
            # them, which is how harmony ended up spanning C#2 to D7.
            shift = round((((low + high) / 2) - ((bottom + top) / 2)) / 12) * 12
        else:
            # Shift by the fewest whole octaves that bring it inside. Minimal
            # movement matters: folding every note toward the centre would
            # flatten the line's contour, not just relocate it.
            shift = 0
            while bottom + shift < low:
                shift += 12
            while top + shift > high:
                shift -= 12

        if shift:
            element.transpose(shift, inPlace=True)


def _set_clef(part: music21.stream.Part, clef: music21.clef.Clef) -> None:
    """Put one explicit clef at the head of a part.

    Without this the reader picks a clef from the pitch content, and a harmony
    part spanning two octaves gets a bass clef with most of its notes stacked
    on ledger lines above the staff.
    """
    for existing in list(part.recurse().getElementsByClass(music21.clef.Clef)):
        existing.activeSite.remove(existing)

    measures = list(part.getElementsByClass(music21.stream.Measure))
    (measures[0] if measures else part).insert(0, clef)


def _set_instrument(part: music21.stream.Part, instrument: music21.instrument.Instrument) -> None:
    """Set the instrument for a part."""
    # Remove any existing instruments
    for inst in part.getElementsByClass(music21.instrument.Instrument):
        part.remove(inst)
    part.insert(0, instrument)
