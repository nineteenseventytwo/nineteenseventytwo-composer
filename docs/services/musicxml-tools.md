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

### `parser.py`
One function: `parse_score(filepath)`. Calls `music21.converter.parse()` and ensures the result is a `Score` (wrapping it if not). The simplest module.

### `splitter.py`
The most musically interesting module. Takes a piano score and produces three separate parts.

**Strategy for two-staff piano scores:**
- `parts[0]` (treble/right hand) → highest notes become melody, rest becomes harmony
- `parts[1]` (bass/left hand) → lowest notes become bass, upper notes join harmony

**The voice extraction logic:**
Groups notes by their offset (beat position) within each measure. For melody it takes the highest-pitched note at each offset; for bass, the lowest. Everything else goes to harmony.

This is a simplification — real voice leading is more nuanced — but works well as a starting point for the LLM to refine.

### `intermediate.py`
Converts between music21 objects and the JSON format the LLM consumes.

`to_intermediate()` flattens each Part into a list of simple dicts. `part.flatten()` in music21 removes the Measure hierarchy and gives you a linear sequence of notes — useful when you just want "all the notes in order."

`from_intermediate()` reconstructs music21 Parts from the JSON the LLM returns, using `part.insert(offset, element)` to place each note at its beat position.

### `assembler.py`
`assemble_score()` combines the transformed parts back into a full Score, sets instruments (Alto Sax, Piano, Electric Bass), sets tempo and title from the original metadata, and optionally adds the drum part.

`write_score()` calls music21's `score.write("musicxml", fp=...)` to produce the final output file.

### `drums.py`
Generates the bossa drum pattern algorithmically — no AI needed. The classic 2-bar bossa pattern:

```
Hi-hat:      x x x x x x x x   (steady eighth notes)
Cross-stick: . x . . . x . .   (beats 2 and 4)
Bass drum:   x . . x . x . .   (bar 1: beat 1, and-of-2, beat 4)
             . x . . x . . x   (bar 2: and-of-1, beat 3, and-of-4)
```

Uses `music21.note.Unpitched` with General MIDI numbers: bass drum = 36, side stick = 38, closed hi-hat = 42.
