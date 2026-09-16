# nineteenseventytwo-composer

Turns a piano score into a chill bossa nova arrangement, scored for a Game Boy
backing track with a live alto sax over the top.

Feed it a piano transcription — the game-music scores from sites like
nintendosheetmusic.com are the target material — and it works out what should
become bass, what should become harmony and what should become melody, then
arranges each part in the style.

## What it produces

Five staves, **one per performer**:

| Part | Played by | Notes |
|---|---|---|
| Alto Sax | you, live | the melody, carried through unchanged |
| Harmony | Game Boy pulse 1 | rootless voicings on a partido alto grid |
| Bass | Game Boy pulse 2 | root and fifth on the bossa syncopation |
| Drum Kit | Game Boy wave (LSDj kit) | cross-stick clave over a two-feel |
| Shaker | Game Boy noise | the timekeeper |

Four programmed parts, four channels, one live part. It fits exactly, with
nothing spare — which is why the score is laid out one staff per channel, and
why the harmony is notated as chords even though a pulse channel is
monophonic (LSDj Tables supply the chord character).

**Read [docs/performance-context.md](docs/performance-context.md) before
changing how parts are split, voiced or notated.** It is the constraint that
shapes every arrangement decision here.

## How it arranges

The harmony is **derived from the source, never generated**. Each bar's chord
is decoded from the score with Viterbi over the diatonic sevenths of the
detected key, weighted toward what the bass is actually playing and carrying a
cost for changing — so a walking bass does not drag the harmony with it. The
parts are then rendered from that chord by rule, because bossa bass and comping
are rule-shaped.

What is *not* rule-shaped — which phrases to thin, where a turnaround earns its
place, which substitution a moment wants — is what a model is asked for.

Three strategies, selected by `COMPOSER_ARRANGER`:

- **`deterministic`** (default) — no model, nothing to run, a complete and
  harmonically sound arrangement.
- **`plan`** — the model reads the form and chooses density, bass feel and
  chord substitutions from options the library derived. A few hundred tokens
  per score.
- **`notes`** — the original approach, where the model rewrote the note lists.
  Kept for the comparison write-up: it preserved the source's harmony in 8 bars
  of 32 and took 577s to do it.

## Layout

```
services/
  musicxml-tools/   parsing, voice splitting, harmony detection, rendering
  composer/         the API, the arrangers, the arrangement metrics
  training/         fine-tuning pipeline (parked — see the plan's D-C)
docs/
  plan/             the standup plan and every finding behind it
examples/           score corpus (not committed — see examples/README.md)
```

## Running it

```bash
pip install -e services/musicxml-tools -e "services/composer[dev]"
uvicorn composer.app:app --reload
curl -F file=@score.mxl localhost:8000/arrange -o arrangement.musicxml
```

Accepts `.mxl`, `.musicxml` and `.xml`, detected from content. The response
headers report how much of the piece was actually arranged.

To use the model-driven arranger, run Ollama and set `COMPOSER_ARRANGER=plan`
and `LLM_BASE_URL`.

## Measuring a change

```bash
python -m composer.eval_cli examples/input/*.mxl
```

Reports root grounding, harmonic fidelity, bar coverage and harmonic rhythm
against the source. Built because listening caught things every mechanical
check had passed — and because one metric, harmonic rhythm, was missing
entirely while an arrangement scored perfectly and still sounded restless.

## Infrastructure

Composer's API runs in the cluster on arm64; inference runs off-cluster on the
GPU host. The cluster does not gain a GPU node — see the platform repo's
`07-completion-plan.md` D1(b), and
[docs/plan/01-composer-standup.md](docs/plan/01-composer-standup.md) D-A.

Manifests and host provisioning live in the **platform** repo, not here
(ADR-0012).
