# Performance context — what the output is actually for

_Written 2026-09-15. The constraint that shapes every arrangement decision in
this repo. Read this before changing anything about how parts are split,
voiced, or notated._

## The goal

Take a piano score — the widely-available game-music transcriptions from sites
like nintendosheetmusic.com — and turn it into something **very chill**, with
bossa nova as the target vibe.

That means looking at a piano texture and deciding what should become bass,
what should become harmony, and what should become melody; putting the melody
on alto sax and keeping it in range; adjusting harmony and bass to support the
melody once ranges have moved; and generating a bossa part per bar decomposed
from the original.

## How it gets performed

This is not a score for a jazz quartet. It is a **Game Boy backing track with
one live player over the top**.

The backing track is programmed into a Game Boy using **LSDj**, which exposes
the four channels of the Game Boy sound chip. The alto sax is played live on
top — it is never programmed, so it costs no channel.

| Score part | Channel | LSDj | Notes |
|---|---|---|---|
| **Alto Sax** | — | *none* | Played live over the backing track |
| **Harmony** | Pulse 1 | square synth | |
| **Bass** | Pulse 2 | square synth | |
| **Drum Kit** | Wave | kit, two tracks | Bass drum + cross-stick only |
| **Shaker** | Noise | — | The bossa timekeeper |

Four programmed parts, four channels, one live part. It fits exactly, with
nothing spare.

## What follows from this

### The score should be notated as it will be performed

A part written for piano and electric bass describes a performance that will
never happen. Harmony and bass are notated as **Square Synthesizer** because
that is the sound they will make. The kit keeps a drum-kit instrument
deliberately — it is played from LSDj kit samples, so it should read as a kit —
and the shaker is its own part because it is its own channel.

**One staff per channel.** That is the whole reason the shaker was split out of
the drum staff rather than kept as a third voice on it: the person entering
this into LSDj reads one staff and fills one channel.

### Each pulse channel is monophonic — and chords stay in the score anyway

A Game Boy pulse channel plays **one note at a time**, so the chords in the
harmony part cannot sound as written.

**DECIDED 2026-09-15 — the score stays chordal, and LSDj Tables supply the
chord character.** A table cycles the chord tones fast enough to read as
harmony; the score carries the intent, the table realises it. This is the
idiomatic chiptune answer and it keeps the arrangement readable as music rather
than as a stream of arpeggio steps.

The alternative — having composer resolve each chord into the monophonic line
that will actually sound — was rejected for now. It would move the realisation
into the tool and make the score a literal transcription of the channel, which
is harder to read and harder to revise.

**What this means for composer:** a chord in the harmony part is a *harmonic
intention*, not a literal instruction. So voicing choices still matter — which
tones, in which register — because the table cycles whatever it is given. What
does **not** matter is voice count as a playability limit. Under the plan's
**C5**(b), where the model chooses voicings and the library renders them, that
is exactly the right division: the model picks the chord, the table plays it.

### The exported file needs repairs music21 will not make

`write_score` applies three corrections on the way out, all of them things
music21 does not emit and a notation reader needs: percussion forced onto MIDI
channel 10, `<instrument-sound>` added per instrument, and an explicit
`<instrument>` reference on every note of a single-instrument percussion part.
Each was found by a part sounding wrong despite correct-looking notation. Treat
them as a standing adapter rather than incidental fixes — anything added to the
score that is unpitched will likely need the same treatment.

### Register, not just range

Instrument ranges are already enforced (plan **C17**), but the Game Boy has its
own limits and they are tighter at the bottom: the pulse channels get thin and
buzzy in the low register, which is where a bass line folded down from a piano
left hand tends to land. Worth measuring against the real hardware before
trusting `BASS_RANGE`.

### Chill is a constraint, not a mood

"Very chill" rules things out. Dense harmonic rhythm, busy bass, and constant
sixteenths all work against it — and the source material is chiptune, which
tends to be busy because the original composers were filling four channels with
motion. **Decomposing a busy original into something restful is the actual
creative task**, and it is a subtraction problem more than an addition one.

## What is settled and what is not

**Settled:** the channel mapping above; one staff per channel; square synths
for the two pulse parts; kit and shaker as separate parts; the bossa clave on
the cross-stick over a two-feel kick.

**Open:** how harmony becomes monophonic (above); whether the shaker should be
eighths or sixteenths; whether the bass range should be narrowed for the
hardware; and how much the arrangement should thin out the source to reach
"chill".
