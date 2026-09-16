"""Bossa nova percussion generators.

Two parts, not one, because the target is a Game Boy: the kit (bass drum and
cross-stick) is programmed on the wave channel as an LSDj kit, and the shaker
is the noise channel. They are separate voices on separate hardware, so they
are separate parts in the score. See docs/performance-context.md.
"""

import music21

# Three things decide how a percussion note comes out, and conflating any two
# of them is what kept this module broken (findings C14, C16):
#
#   storedInstrument   *which* drum — resolves to the General MIDI sound
#   percMapPitch       the GM note number that instrument maps to
#   displayStep/Octave *where* it sits on the staff
#
# music21's `Unpitched.displayName` is the third of those: it returns a
# position such as "G5". It is not a label, and since music21 10 it is
# read-only.
#
# Critically, a note's `storedInstrument` only reaches the MusicXML output when
# the *part* holds more than one instrument — `setNoteInstrument` short-circuits
# otherwise, and every hit collapses onto a single sound. So all three
# instruments are inserted into the part, not just one.
#
# music21's own percMapPitch defaults are not the sounds a bossa kit wants
# (HiHatCymbal is 44, the pedal hi-hat; SnareDrum is 38, a centre hit), so the
# GM numbers are set explicitly here.
# General MIDI note numbers. A shaker rather than a hi-hat: it is the
# idiomatic bossa timekeeper, and a kit hi-hat is a samba/swing sound.
SHAKER = 82
SIDE_STICK = 37
BASS_DRUM = 36

# General MIDI reserves channel 10 for percussion. music21 assigns channels
# sequentially and only gave 10 to the *first* percussion instrument in the
# part, leaving the other two on pitched channels 4 and 5 — so the cross-stick
# and bass drum played as melodic patches at MIDI notes 37 and 36, which is
# very low and sustaining. That is the boomy "bass drums with lots of echo".
# midiChannel is 0-indexed here and exported as +1.
PERCUSSION_CHANNEL = 9

# Staff positions follow the usual percussion-clef convention: timekeeper
# above the staff, side stick on the snare line, bass drum low.
SHAKER_POSITION = ("G", 5)
SIDE_STICK_POSITION = ("C", 5)
BASS_DRUM_POSITION = ("F", 4)

# Pattern as data rather than control flow, so it can be clamped to the bar.
# Offsets are in quarter notes from the start of the bar.
#
# The cross-stick carries the clave and the bass drum holds the pulse. The
# first version of this module had the two the other way round — a clave-shaped
# kick under a backbeat cross-stick on 2 and 4 — which is a rock pattern
# wearing bossa clothing, and is why the groove read as only "vaguely bossa".
#
# Bossa clave, 3-2, over two bars. It differs from the son clave in its second
# bar: beat 2 and the and-of-3, where son plays beats 2 and 3. That one
# displaced note is most of what makes it sound Brazilian rather than Cuban.
SIDE_STICK_CLAVE = (
    (0.0, 1.5, 3.0),  # bar 1, the "three" side: beat 1, and-of-2, beat 4
    (1.0, 2.5),       # bar 2, the "two" side: beat 2, and-of-3
)

# Two-feel underneath: half-note pulse, unchanging bar to bar. The steadiness
# is the point — it is what the clave syncopates against.
BASS_DRUM_BEATS = (0.0, 2.0)

SHAKER_SUBDIVISION = 2  # hits per quarter note

EIGHTH = 0.5


def _kit() -> tuple:
    """The three instruments, mapped to the General MIDI sounds we want.

    Names matter beyond the label. music21 does not export MusicXML's
    `<instrument-sound>` element, so a reader falls back to matching on
    `<instrument-name>` — and "Bass Drum" matches a *concert* bass drum, one
    boomy sustaining instrument that then plays the whole staff. The names here
    are chosen to read as kit pieces, and `write_score` adds the sound ids.
    """
    shaker = music21.instrument.Maracas()  # no Shaker class in music21
    shaker.percMapPitch = SHAKER
    shaker.instrumentName = "Shaker"
    shaker.instrumentAbbreviation = "Shk"

    side_stick = music21.instrument.SnareDrum()
    side_stick.percMapPitch = SIDE_STICK
    side_stick.instrumentName = "Side Stick"
    side_stick.instrumentAbbreviation = "S.Stk"

    bass_drum = music21.instrument.BassDrum()
    bass_drum.percMapPitch = BASS_DRUM
    bass_drum.instrumentName = "Bass Drum 1"
    bass_drum.instrumentAbbreviation = "B.Dr"

    kit = (shaker, side_stick, bass_drum)
    for instrument in kit:
        instrument.midiChannel = PERCUSSION_CHANNEL

    return kit


def _hit(
    position: tuple[str, int],
    instrument: music21.instrument.Instrument,
    quarter_length: float,
    notehead: str | None = None,
) -> music21.note.Unpitched:
    """One unpitched percussion note at a given staff position."""
    note = music21.note.Unpitched()
    note.displayStep, note.displayOctave = position
    note.storedInstrument = instrument
    note.quarterLength = quarter_length
    if notehead:
        note.notehead = notehead
    return note


def generate_bossa_drums(
    num_measures: int,
    time_signature: str = "4/4",
) -> music21.stream.Part:
    """Generate a bossa nova drum pattern.

    The kit half of the pattern, over a 2-bar cycle:
    - Cross-stick: the 3-2 bossa clave, which is the figure that identifies
      the style
    - Bass drum: a steady two-feel on beats 1 and 3, for the clave to pull
      against

    The shaker is a separate part — see :func:`generate_bossa_shaker`.

    Laid out as two voices, which is both the drum-notation convention and a
    correctness requirement: simultaneous notes in a measure with no ``Voice``
    objects cannot be represented in MusicXML, and music21 serialises them end
    to end instead — a 4/4 bar then exports as 7.5 quarter notes and every
    other part falls silent waiting for the drums to finish.

    Args:
        num_measures: Number of measures to generate.
        time_signature: Time signature string (default: 4/4).

    Returns:
        A music21 Part with unpitched percussion.
    """
    _, side_stick, bass_drum = _kit()

    part = music21.stream.Part()
    # "Drum Kit", not "Drums": the part name is what a reader matches against
    # its instrument list, and it should land on a kit rather than on a single
    # orchestral percussion instrument.
    part.partName = "Drum Kit"
    part.partAbbreviation = "D. Kit"
    for instrument in (side_stick, bass_drum):
        part.insert(0, instrument)

    ts = music21.meter.TimeSignature(time_signature)
    bar_length = float(ts.barDuration.quarterLength)

    for index in range(num_measures):
        measure = music21.stream.Measure(number=index + 1)
        if index == 0:
            measure.insert(0, music21.clef.PercussionClef())
            measure.insert(0, ts)

        # Clamp every offset to the bar: in 3/4 the clave's "beat 4" does not
        # exist, and an out-of-range hit silently lengthens the bar.
        stick_offsets = [
            o for o in SIDE_STICK_CLAVE[index % 2] if o < bar_length
        ]

        # One voice per instrument. A PercussionChord would read better on the
        # page, but music21's exporter resolves a chord member's instrument
        # from the *chord* rather than the member: every note inside one
        # inherits a single sound. That collapsed the timekeeper and
        # cross-stick onto the bass drum — 224 of 416 notes exported as MIDI
        # 36, one symptom of the "everything sounds like a bass drum" report.
        lines = (
            ("1", stick_offsets, SIDE_STICK_POSITION, side_stick, "x"),
            ("2", [o for o in BASS_DRUM_BEATS if o < bar_length],
             BASS_DRUM_POSITION, bass_drum, None),
        )

        for voice_id, offsets, position, instrument, notehead in lines:
            voice = music21.stream.Voice(id=voice_id)
            for offset in offsets:
                voice.insert(
                    offset,
                    _hit(position, instrument, min(EIGHTH, bar_length - offset), notehead),
                )
            # Fill the voice out to a full bar. Neither of these voices reaches
            # the barline on its own — the clave stops at beat 4 and the kick at
            # beat 3 — and a measure shorter than its bar drags every later
            # measure earlier when appended (the C15 failure). The shaker used
            # to mask this by running to the barline; it is a separate part now.
            voice.makeRests(
                refStreamOrTimeRange=[0.0, bar_length],
                fillGaps=True,
                inPlace=True,
            )
            measure.insert(0, voice)

        part.append(measure)

    return part


def generate_bossa_shaker(
    num_measures: int,
    time_signature: str = "4/4",
) -> music21.stream.Part:
    """Generate the shaker part — straight eighths, the bossa timekeeper.

    Its own part rather than a third voice on the kit staff, because on the
    target hardware it is its own channel: the Game Boy's noise generator,
    while the kit lives on the wave channel as an LSDj kit. Keeping the score
    aligned with the channel layout means the person programming it reads one
    staff per channel.

    Args:
        num_measures: Number of measures to generate.
        time_signature: Time signature string (default: 4/4).

    Returns:
        A music21 Part with one unpitched percussion voice.
    """
    shaker, _, _ = _kit()

    part = music21.stream.Part()
    part.partName = "Shaker"
    part.partAbbreviation = "Shk"
    part.insert(0, shaker)

    ts = music21.meter.TimeSignature(time_signature)
    bar_length = float(ts.barDuration.quarterLength)
    step = 1.0 / SHAKER_SUBDIVISION

    for index in range(num_measures):
        measure = music21.stream.Measure(number=index + 1)
        if index == 0:
            measure.insert(0, music21.clef.PercussionClef())
            measure.insert(0, ts)

        for hit in range(int(bar_length * SHAKER_SUBDIVISION)):
            offset = hit * step
            measure.insert(
                offset,
                _hit(SHAKER_POSITION, shaker, min(step, bar_length - offset), "x"),
            )

        part.append(measure)

    return part
