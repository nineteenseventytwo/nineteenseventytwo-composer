# Service: musicxml-tools

**Role:** Music processing library
**Language:** Python 3.12
**Key dependency:** [music21](https://web.mit.edu/music21/) — MIT's music analysis toolkit

## What It Does

All rule-based music processing lives here. No AI — this library knows music theory and MusicXML structure. It is the bridge between the file format world and the LLM world.

## music21 Background

music21 is a Python library for computational musicology from MIT. It parses MusicXML, MIDI, ABC notation, and others into an object model:

```
Score → Part → Measure → Note / Chord / Rest
```

You query and manipulate scores programmatically. Key types used in this codebase:

| Type | What it is |
|---|---|
| `music21.stream.Score` | Full score containing all parts |
| `music21.stream.Part` | One instrument's part |
| `music21.stream.Measure` | One bar |
| `music21.note.Note` | A pitched note — has `.pitch`, `.quarterLength`, `.offset` |
| `music21.chord.Chord` | Multiple simultaneous notes |
| `music21.note.Rest` | Silence |
| `music21.note.Unpitched` | Percussion note |

Offsets are in **quarter notes**. A note at `offset=1.0` starts on beat 2 of a 4/4 measure. `quarterLength=0.5` is an eighth note.

## Key Files

Two groups. The first turns a score into a representation and back again; the
second works out what to play.

### Reading and writing a score

| File | Responsibility |
|---|---|
| `parser.py` | MusicXML → a music21 `Score`. Handles `.mxl` (zipped) as well as plain XML |
| `splitter.py` | A piano texture → melody, harmony, bass. Descends into `Voice` objects, trims melody and bass to single lines, and takes harmony from `chordify()` with the pitches melody and bass already claimed subtracted |
| `intermediate.py` | ↔ compact JSON, carrying metre and any pickup bar so a rebuilt part can be re-barred correctly |
| `schema.py` | One definition of that JSON, used to constrain decoding, validate replies, and render the prompt's example |
| `chunking.py` | Bar-aligned slices that split and merge exactly, so a long score can be transformed in pieces |
| `assembler.py` | Parts → a score a reader can play: instruments, ranges, clefs, transposition, and the percussion repairs music21 will not emit |

### Deciding what to play

| File | Responsibility |
|---|---|
| `chords.py` | Which chord each bar sits on. Viterbi over the diatonic sevenths of the detected key, weighted toward the bass and charged for changing |
| `form.py` | Which phrases repeat, and how often each has been heard |
| `reharmonise.py` | Which substitutions a bar could legitimately take |
| `plan.py` | How each bar is played — density, bass treatment, substitution — as an object a model can produce and a validator can check |
| `comping.py` | Rootless voicings on a rhythmic grid, and the bass line |
| `drums.py` | The kit and the shaker, on the bossa clave |

The split matters: everything in the first group is reversible mechanics, and
everything in the second is a musical decision. Only the second group has
anything a model could usefully be asked about.
