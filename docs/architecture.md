# System Architecture

## What this system does

Takes a piano transcription and produces a bossa nova arrangement: a Game Boy
backing track of harmony, bass and two percussion parts, with the melody left
for a live alto sax. See [performance-context.md](performance-context.md) for
why that target shapes everything below.

```
[Piano MusicXML] → [split] → [detect harmony] → [plan] → [render] → [Arrangement MusicXML]
```

## The central idea: derive, don't generate

The first version asked a model to rewrite the note lists — read the whole
score as JSON, return it transformed. That failed in two ways at once, and both
are worth stating because they shaped everything since:

- **It invented the harmony.** The source's root survived in 8 bars of 32. The
  result was a textbook bossa bass in the wrong key, which is worse than a
  clumsy one in the right key because it sounds fine until you play it against
  the tune.
- **It cost ~18 output tokens per event.** A 32-bar score took 577 seconds, and
  every score in the corpus was larger than the model could emit in one reply.

The fix was not a better prompt or a bigger model. It was noticing that the
thing going wrong — harmonic identity — was information the system already had
and was discarding in order to ask a model to guess it back.

So the harmony is **detected from the score**, and the parts are **rendered by
rule**, because bossa bass and comping are rule-shaped: root and fifth on a
fixed syncopation, rootless voicings on a partido alto grid. The model is asked
only for what rules cannot settle.

## Services

### `musicxml-tools`

The library. Everything music-theory-aware, no web surface.

| Module | Responsibility |
|---|---|
| `parser`, `splitter` | MusicXML → melody, harmony, bass |
| `intermediate` | ↔ compact JSON, carrying metre and pickup |
| `schema` | one definition of that JSON, used three ways |
| `chunking` | bar-aligned slices that round-trip exactly |
| `chords` | which chord each bar is on |
| `form` | which phrases repeat, and how often |
| `reharmonise` | which substitutions a bar could take |
| `plan` | how each bar is played |
| `comping`, `drums` | rendering the parts |
| `assembler` | parts → a score a reader can play |

### `composer`

The FastAPI service, the arranger strategies, and the metrics.

### `training`

Fine-tuning, parked. Fine-tuning before an eval set exists is optimising
without a target; the eval set that P1 built is what it would need.

## Chord detection

Each bar's pitch content is weighted by **sounding duration** — a passing
sixteenth and a held half note are not equal evidence — and scored against the
diatonic sevenths of the detected key. Two forces decide the result and they
pull against each other, so they were swept over the corpus together:

- a **cost for changing chord**, so one bar of weak evidence cannot drag the
  harmony away and back;
- a **bonus when a candidate's root is what the bass is playing**, because
  membership alone cannot separate `Cmaj7` from `Fmaj7` in a bar of C and E.

Decoded with Viterbi over the whole piece rather than bar by bar: the best
explanation of a piece is not the concatenation of the best explanations of its
bars, since holding a chord through a thin bar is usually right.

## The plan

The seam between *what the chords are* and *what the parts do*. Every per-bar
decision — comping density, bass treatment, chord substitution — is an object,
which makes it small enough for a model to produce and cheap enough to validate
before use.

```
detect chords → detect form → build a plan → render
                                  ↑
                         fixed policy, or a model
```

A model's plan is constrained three ways, by construction rather than
instruction: density and bass are **enums**; substitutions are chosen from a
**menu the library derived**; and the root is never generated at all. The
failure mode that started all this cannot recur.

Degradation is graded. A rejected substitution costs that bar its
reharmonisation, an unanswered phrase falls back to the fixed policy, and a
model outage falls back to the whole deterministic arrangement — which is a
complete score, not an empty one.

## The intermediate representation

MusicXML is far too verbose for a model — a single note spans ~15 lines — so
the score is converted to compact JSON first:

```json
{
  "metadata": {"title": "...", "key": "g minor", "time_signature": "4/4", "pickup": 1.5},
  "parts": {
    "melody":  [{"pitch": "G4", "duration": 1.0, "offset": 0.0}],
    "harmony": [{"pitches": ["E3", "G3", "B3"], "duration": 2.0, "offset": 0.0}],
    "bass":    [{"pitch": "C2", "duration": 1.0, "offset": 0.0}]
  }
}
```

`metadata` carries metre and any pickup because offsets alone cannot express
them: without the time signature a 3/4 score is re-barred as 4/4, and without
the pickup every bar after an anacrusis lands early.

Its shape is defined once, in `schema.py`, and used to constrain the model's
decoding, validate its replies, and render the worked example in the prompt. It
was previously maintained by hand in those three places, and drifted — the
example taught a shape the parser could not read, so a model that *obeyed* it
crashed the pipeline.

## Measuring

`composer.evaluate` compares an arrangement with its source:

- **root grounded** — was the root we played sounding anywhere in that bar? The
  metric that survives holding a chord, where bar-by-bar exactness scores a
  correctly sustained harmony as a miss.
- **harmonic fidelity** — a drift detector, expected below 1.0 because bossa
  voicings legitimately add tensions.
- **bars per chord** — how long the harmony holds. Its absence is why an early
  version scored full marks on everything else and still sounded restless.
- **coverage**, **offsets** — regression guards.

None of them can say whether an arrangement is any *good*. Every one exists
because listening caught something the previous set of checks had passed.

## Failure handling

Every stage degrades to something playable rather than to nothing. The
arrangement always exists; what varies is how much of it was arranged, and the
response says so in its headers rather than leaving a caller to guess from a
well-formed file that nothing happened to.
