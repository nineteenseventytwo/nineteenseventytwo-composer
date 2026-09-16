# Examples

The working corpus for the deterministic pipeline and the P1 eval set.

## The corpus is not committed

`examples/input/` and `examples/output/` are `.gitignore`d. The scores used
during development are transcriptions of copyrighted game music, and this repo
is public — see
[docs/plan/01-composer-standup.md](../docs/plan/01-composer-standup.md)
finding **C9**. The manifest below exists so the eval set is reproducible
without this repo redistributing anything.

## Manifest — the five scores measured on 2026-09-13

All five are two-staff piano transcriptions exported from MuseScore as
compressed MusicXML (`.mxl`). Obtain or re-export your own copies into
`examples/input/`.

| File | Measures | Source notes | IR ~tokens |
|---|---|---|---|
| `Castlevania - Vampire Killer.mxl` | 32 | 598 | ~9,100 |
| `Castlevania - Wicked Child_Sax-Piano.mxl` | 51 | 603 | ~17,900 |
| `Kirbys Dream Land - Bubbly Clouds.mxl` | 88 | 758 | ~22,500 |
| `Kirbys Dream Land - Green Greens.mxl` | 43 | 644 | ~20,800 |
| `Mega Man 2 - Dr Wily Stage 1.mxl` | 112 | 1527 | ~34,600 |

Two of them — Vampire Killer and Dr Wily — contain **voiced staves**, which is
what exposed finding **C11**. Keep at least one voiced score in any replacement
corpus.

## Still missing

Two kinds, per **P0**:

- A **structural stress case**: repeats with first/second endings, a pickup
  bar, a key change, ties across barlines.
- A **deliberately out-of-domain texture**: Alberti bass or contrapuntal
  writing, so the splitter's boundary is a known fact rather than a surprise.
  `music21`'s bundled corpus is the zero-friction source — e.g.
  `music21.corpus.parse('bach/bwv66.6')`.

## For training

`services/training/` is parked (see **D-C**). When it resumes, input/output
pairs go under a `training/` folder:

```
examples/training/
  song1/{input,output}.musicxml
```
