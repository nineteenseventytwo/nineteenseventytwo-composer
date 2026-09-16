"""Split a piano score into separate voice parts (melody, harmony, bass)."""

from dataclasses import dataclass

import music21


@dataclass
class SplitParts:
    """Result of splitting a piano score into voices."""

    melody: music21.stream.Part
    harmony: music21.stream.Part
    bass: music21.stream.Part
    metadata: dict


def split_voices(score: music21.stream.Score) -> SplitParts:
    """Split a piano score into melody (top), harmony (middle), and bass (bottom).

    Strategy:
    - If the score has separate treble/bass staves, use them as starting points.
    - In the treble staff: highest voice → melody, remaining → harmony.
    - In the bass staff: lowest voice → bass, remaining → added to harmony.

    Args:
        score: A music21 Score, typically a piano score with treble and bass clefs.

    Returns:
        SplitParts with melody, harmony, and bass as separate Part objects.
    """
    metadata = _extract_metadata(score)
    parts = list(score.parts)

    if len(parts) == 0:
        raise ValueError("Score has no parts")

    if len(parts) == 1:
        # Single staff — split by pitch register
        return _split_single_staff(parts[0], metadata)

    # Typical piano: parts[0] = treble (right hand), parts[1] = bass (left hand)
    treble_part = parts[0]
    bass_part = parts[1]

    melody = _extract_top_voice(treble_part, "Alto Sax")
    bass = _extract_bottom_voice(bass_part, "Bass")
    harmony = _extract_harmony(score, melody, bass, "Piano")

    return SplitParts(melody=melody, harmony=harmony, bass=bass, metadata=metadata)


def _measure_events(measure: music21.stream.Measure):
    """Yield a measure's notes and rests, including any nested inside Voices.

    ``Measure.notesAndRests`` does **not** descend into ``music21.stream.Voice``,
    so a voiced staff silently loses every note inside its voices — 36% of the
    notes on one of the reference scores (finding C11). Flattening first lifts
    voice contents up with their measure-relative offsets intact, and is a
    no-op on measures that have no voices.
    """
    return measure.flatten().notesAndRests


def _extract_metadata(score: music21.stream.Score) -> dict:
    """Extract score metadata (title, tempo, key, time signature)."""
    meta = {
        "title": _extract_title(score),
    }

    # Get tempo
    tempos = score.flatten().getElementsByClass(music21.tempo.MetronomeMark)
    if tempos:
        meta["tempo"] = tempos[0].number
    else:
        meta["tempo"] = 120  # default

    # Get key. Two separate facts, reported separately: the analysed tonal
    # centre and the signature as written. Key analysis is a heuristic and can
    # disagree with the signature — on the reference corpus it does — so
    # collapsing them into one field would hide a real ambiguity from the model.
    meta["key"] = _extract_key_name(score)
    meta["key_signature"] = _extract_key_signature_name(score)

    # Get time signature
    time_sigs = score.flatten().getElementsByClass(music21.meter.TimeSignature)
    if time_sigs:
        meta["time_signature"] = time_sigs[0].ratioString
    else:
        meta["time_signature"] = "4/4"

    # A pickup bar has to be carried explicitly. Offsets alone cannot express
    # it: every later measure sits 1.5 beats early, and a reconstruction that
    # bars from zero assuming full measures mis-bars the entire score. Common
    # enough in the target repertoire to be worth a field of its own.
    meta["pickup"] = _extract_pickup(score)

    return meta


def _extract_pickup(score: music21.stream.Score) -> float:
    """Length of a partial opening bar, or 0.0 if the score starts on beat 1."""
    for part in score.parts:
        measures = list(part.getElementsByClass(music21.stream.Measure))
        if not measures:
            continue
        first = measures[0]
        content = float(first.duration.quarterLength)
        full = float(first.barDuration.quarterLength)
        if 0 < content < full:
            return content
        return 0.0
    return 0.0


_SCORE_SUFFIXES = (".mxl", ".musicxml", ".xml")


def _extract_title(score: music21.stream.Score) -> str:
    """Best available title, falling back through movement name.

    When a file carries no title of its own, music21 populates ``title`` from
    the filename — extension included — so strip a trailing score suffix
    rather than telling the model the piece is called "... .mxl".
    """
    md = score.metadata
    if md:
        for candidate in (md.title, md.movementName):
            if not candidate:
                continue
            text = str(candidate).strip().strip('"')
            for suffix in _SCORE_SUFFIXES:
                if text.lower().endswith(suffix):
                    text = text[: -len(suffix)]
                    break
            if text.strip():
                return text.strip()
    return "Untitled"


def _extract_key_name(score: music21.stream.Score) -> str:
    """A human-readable key name — never a Python repr.

    ``str()`` on a bare ``KeySignature`` yields
    ``"<music21.key.KeySignature of 3 sharps>"``, which was being sent to the
    model as if it were a key (finding C1). Prefer an explicit ``Key`` in the
    score, then analysis, then the signature interpreted as major.
    """
    flat = score.flatten()

    explicit = list(flat.getElementsByClass(music21.key.Key))
    if explicit:
        return explicit[0].name

    try:
        analysed = score.analyze("key")
        if analysed is not None:
            return analysed.name
    except Exception:  # analysis is best-effort; a signature is still better than a repr
        pass

    signatures = list(flat.getElementsByClass(music21.key.KeySignature))
    if signatures:
        return signatures[0].asKey().name

    return "C major"


def _extract_key_signature_name(score: music21.stream.Score) -> str:
    """The key signature as written, interpreted as major — never a repr."""
    signatures = list(score.flatten().getElementsByClass(music21.key.KeySignature))
    if not signatures:
        return "C major"
    first = signatures[0]
    if isinstance(first, music21.key.Key):
        return first.name
    return first.asKey().name


def _bar_length(measure: music21.stream.Measure) -> float:
    """The notated length of a bar, falling back to its actual content."""
    try:
        return float(measure.barDuration.quarterLength)
    except Exception:
        return float(measure.duration.quarterLength)


def _insert_monophonic(
    measure: music21.stream.Measure,
    selections: list[tuple[float, object]],
    bar_length: float,
) -> None:
    """Insert selected events, trimming each so it ends before the next begins.

    Melody and bass are single lines. Recovering notes from inside voices
    (finding C11) means an event can now start while a longer one is still
    sounding, and a Part holding overlapping notes cannot be engraved on one
    staff — a reader drops or mangles it, which is why two of the reference
    scores rendered with no sax and no bass at all. Trimming each event to the
    next onset makes the line monophonic by construction.
    """
    offsets = [offset for offset, _ in selections]

    for index, (offset, element) in enumerate(selections):
        limit = offsets[index + 1] if index + 1 < len(offsets) else bar_length
        length = min(float(element.quarterLength), max(limit - offset, 0.0))
        if length <= 0:
            continue
        element.quarterLength = length
        measure.insert(offset, element)


def _extract_top_voice(part: music21.stream.Part, name: str) -> music21.stream.Part:
    """Extract the highest notes from a part to form the melody line."""
    new_part = music21.stream.Part()
    new_part.partName = name

    for measure in part.getElementsByClass(music21.stream.Measure):
        new_measure = music21.stream.Measure(number=measure.number)

        # Copy time signatures, key signatures, clefs
        for elem in measure.getElementsByClass(
            (music21.meter.TimeSignature, music21.key.KeySignature, music21.clef.Clef)
        ):
            new_measure.insert(elem.offset, elem)

        # Group notes by offset to find the highest at each beat
        notes_by_offset: dict[float, list[music21.note.Note]] = {}
        for elem in _measure_events(measure):
            offset = elem.offset
            if isinstance(elem, music21.note.Note):
                notes_by_offset.setdefault(offset, []).append(elem)
            elif isinstance(elem, music21.chord.Chord):
                # Take the highest note from chords
                top = elem.sortAscending()[-1]
                n = music21.note.Note(top.pitch, quarterLength=elem.quarterLength)
                notes_by_offset.setdefault(offset, []).append(n)
            elif isinstance(elem, music21.note.Rest):
                notes_by_offset.setdefault(offset, []).append(elem)

        selections: list[tuple[float, object]] = []
        for offset in sorted(notes_by_offset.keys()):
            notes = notes_by_offset[offset]
            actual_notes = [n for n in notes if isinstance(n, music21.note.Note)]
            if actual_notes:
                highest = max(actual_notes, key=lambda n: n.pitch.midi)
                selections.append((float(offset), music21.note.Note(
                    highest.pitch, quarterLength=highest.quarterLength
                )))
            else:
                # Only rests at this offset. Build a fresh Rest rather than
                # reusing the source object, which _insert_monophonic trims.
                selections.append((float(offset), music21.note.Rest(
                    quarterLength=notes[0].quarterLength
                )))

        _insert_monophonic(new_measure, selections, _bar_length(measure))

        # insert, never append: append() places a measure at the stream's
        # current highestTime, so any measure whose content is shorter than a
        # full bar drags every later measure earlier and the part drifts out of
        # alignment with the rest of the score. Sparse harmony drifts worst.
        new_part.insert(measure.offset, new_measure)

    return new_part


def _extract_bottom_voice(part: music21.stream.Part, name: str) -> music21.stream.Part:
    """Extract the lowest notes from a part to form the bass line."""
    new_part = music21.stream.Part()
    new_part.partName = name

    for measure in part.getElementsByClass(music21.stream.Measure):
        new_measure = music21.stream.Measure(number=measure.number)

        for elem in measure.getElementsByClass(
            (music21.meter.TimeSignature, music21.key.KeySignature, music21.clef.Clef)
        ):
            new_measure.insert(elem.offset, elem)

        notes_by_offset: dict[float, list[music21.note.Note]] = {}
        for elem in _measure_events(measure):
            offset = elem.offset
            if isinstance(elem, music21.note.Note):
                notes_by_offset.setdefault(offset, []).append(elem)
            elif isinstance(elem, music21.chord.Chord):
                bottom = elem.sortAscending()[0]
                n = music21.note.Note(bottom.pitch, quarterLength=elem.quarterLength)
                notes_by_offset.setdefault(offset, []).append(n)
            elif isinstance(elem, music21.note.Rest):
                notes_by_offset.setdefault(offset, []).append(elem)

        selections: list[tuple[float, object]] = []
        for offset in sorted(notes_by_offset.keys()):
            notes = notes_by_offset[offset]
            actual_notes = [n for n in notes if isinstance(n, music21.note.Note)]
            if actual_notes:
                lowest = min(actual_notes, key=lambda n: n.pitch.midi)
                selections.append((float(offset), music21.note.Note(
                    lowest.pitch, quarterLength=lowest.quarterLength
                )))
            else:
                selections.append((float(offset), music21.note.Rest(
                    quarterLength=notes[0].quarterLength
                )))

        _insert_monophonic(new_measure, selections, _bar_length(measure))

        # insert, never append: append() places a measure at the stream's
        # current highestTime, so any measure whose content is shorter than a
        # full bar drags every later measure earlier and the part drifts out of
        # alignment with the rest of the score. Sparse harmony drifts worst.
        new_part.insert(measure.offset, new_measure)

    return new_part


def _merged_chords(measure: music21.stream.Measure, claims: dict) -> list[list]:
    """Chords in a chordified measure, with runs of identical pitch sets merged.

    ``chordify()`` emits a chord at every rhythmic event anywhere in the score,
    so a harmony held under a moving melody becomes a run of identical chords.
    Collapsing each run into one longer chord keeps the harmony readable and
    cuts the size of the intermediate representation, which is the binding
    constraint on this pipeline (finding C1).

    Returns:
        A list of ``[offset, quarterLength, pitches]``, pitches ascending.
    """
    runs: list[list] = []

    for elem in measure.flatten().notesAndRests:
        if not isinstance(elem, music21.chord.Chord):
            continue
        offset = float(elem.offset)
        pitches = tuple(
            p.nameWithOctave for p in elem.sortAscending().pitches
            if not _is_claimed(claims, measure.number, p.nameWithOctave, offset)
        )
        if not pitches:
            continue
        if runs and runs[-1][2] == pitches:
            runs[-1][1] += float(elem.quarterLength)
        else:
            runs.append([float(elem.offset), float(elem.quarterLength), pitches])

    return runs


def _claimed_intervals(*parts: music21.stream.Part) -> dict:
    """Map ``(measure number, pitch)`` to the spans where a part already owns it.

    Harmony is whatever the melody and bass did **not** take. Deciding that by
    position — dropping the top and bottom pitch of each chord — is wrong
    whenever fewer than three pitches sound: at a moment where only two treble
    notes sound and the bass is silent, both get dropped and the lower one
    belongs to nothing. Spans rather than instants, because a melody note
    sustains across the onsets at which ``chordify()`` re-articulates it.
    """
    claims: dict = {}
    for part in parts:
        for measure in part.getElementsByClass(music21.stream.Measure):
            for elem in measure.flatten().notes:
                start = float(elem.offset)
                end = start + float(elem.quarterLength)
                for pch in elem.pitches:
                    claims.setdefault((measure.number, pch.nameWithOctave), []).append(
                        (start, end)
                    )
    return claims


def _is_claimed(claims: dict, measure_number, pitch_name: str, offset: float) -> bool:
    """True if a part already owns this pitch at this moment in this bar."""
    for start, end in claims.get((measure_number, pitch_name), ()):
        if start <= offset < end:
            return True
    return False


def _extract_harmony(
    score: music21.stream.Score,
    melody: music21.stream.Part,
    bass: music21.stream.Part,
    name: str,
) -> music21.stream.Part:
    """Reduce the whole texture to its inner harmonic content.

    Replaces the previous hand-rolled inner-voice extraction, which only looked
    at ``Chord`` elements with more than one pitch and ignored bare ``Note``s
    entirely — so a two-part texture written as independent notes lost its
    lower line completely, and harmony came out starved (finding C11).

    ``chordify()`` sees every note at every offset, across both staves and
    inside voices. Harmony is then everything the melody and bass did not
    already claim — subtracted by identity rather than by position, so a
    two-note treble moment with a silent bass keeps its lower voice. This is
    also the harmonic reduction the decision-based architecture wants as input
    (finding C5), so it is the fix and the groundwork in one.
    """
    chordified = score.chordify(removeRedundantPitches=True)
    claims = _claimed_intervals(melody, bass)

    new_part = music21.stream.Part()
    new_part.partName = name

    for measure in chordified.getElementsByClass(music21.stream.Measure):
        new_measure = music21.stream.Measure(number=measure.number)

        for elem in measure.getElementsByClass(
            (music21.meter.TimeSignature, music21.key.KeySignature, music21.clef.Clef)
        ):
            new_measure.insert(elem.offset, elem)

        bar_length = _bar_length(measure)

        for offset, length, pitches in _merged_chords(measure, claims):
            inner = tuple(
                p for p in pitches
                if not _is_claimed(claims, measure.number, p, offset)
            )
            if not inner:
                continue
            # Clamp to the bar. chordify() emits chords that tie across
            # barlines, so an unclamped chord near the end of a bar spills past
            # it — the bar then engraves as 4.25 or 6.5 quarter notes and the
            # harmony staff drifts out of alignment with every other part.
            length = min(length, bar_length - offset)
            if length <= 0:
                continue
            if len(inner) == 1:
                elem = music21.note.Note(inner[0], quarterLength=length)
            else:
                elem = music21.chord.Chord(list(inner), quarterLength=length)
            new_measure.insert(offset, elem)

        # insert, never append: append() places a measure at the stream's
        # current highestTime, so any measure whose content is shorter than a
        # full bar drags every later measure earlier and the part drifts out of
        # alignment with the rest of the score. Sparse harmony drifts worst.
        new_part.insert(measure.offset, new_measure)

    return new_part


def _split_single_staff(part: music21.stream.Part, metadata: dict) -> SplitParts:
    """Split a single-staff score by pitch register."""
    melody = music21.stream.Part()
    melody.partName = "Alto Sax"
    harmony = music21.stream.Part()
    harmony.partName = "Piano"
    bass = music21.stream.Part()
    bass.partName = "Bass"

    # Use C4 (middle C, MIDI 60) as the split point
    mid_split = 60

    for measure in part.getElementsByClass(music21.stream.Measure):
        mel_m = music21.stream.Measure(number=measure.number)
        har_m = music21.stream.Measure(number=measure.number)
        bas_m = music21.stream.Measure(number=measure.number)

        for elem in _measure_events(measure):
            if isinstance(elem, music21.note.Note):
                if elem.pitch.midi >= mid_split + 12:
                    mel_m.insert(elem.offset, elem)
                elif elem.pitch.midi >= mid_split:
                    har_m.insert(elem.offset, elem)
                else:
                    bas_m.insert(elem.offset, elem)
            elif isinstance(elem, music21.chord.Chord):
                high = [p for p in elem.pitches if p.midi >= mid_split + 12]
                mid = [p for p in elem.pitches if mid_split <= p.midi < mid_split + 12]
                low = [p for p in elem.pitches if p.midi < mid_split]

                if high:
                    mel_m.insert(elem.offset, music21.note.Note(
                        max(high, key=lambda p: p.midi), quarterLength=elem.quarterLength
                    ))
                if mid:
                    if len(mid) == 1:
                        har_m.insert(elem.offset, music21.note.Note(
                            mid[0], quarterLength=elem.quarterLength
                        ))
                    else:
                        har_m.insert(elem.offset, music21.chord.Chord(
                            mid, quarterLength=elem.quarterLength
                        ))
                if low:
                    bas_m.insert(elem.offset, music21.note.Note(
                        min(low, key=lambda p: p.midi), quarterLength=elem.quarterLength
                    ))
            elif isinstance(elem, music21.note.Rest):
                mel_m.insert(elem.offset, elem)
                bas_m.insert(elem.offset, music21.note.Rest(quarterLength=elem.quarterLength))

        melody.insert(measure.offset, mel_m)
        harmony.insert(measure.offset, har_m)
        bass.insert(measure.offset, bas_m)

    return SplitParts(melody=melody, harmony=harmony, bass=bass, metadata=metadata)
