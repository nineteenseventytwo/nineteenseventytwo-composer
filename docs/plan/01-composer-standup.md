# 01 — Composer standup: getting AI work running on the PC

_Written 2026-09-13. The execution plan for the platform repo's
[07-completion-plan.md](https://github.com/nineteenseventytwo/nineteenseventytwo-platform/blob/main/docs/plan/07-completion-plan.md)
**Phase 6.3**, under decision **D1(b)** — "composer's API runs in the cluster on
arm64 and delivers work to the GPU host outside it"._

Verified 2026-09-13 against composer at `7e8390c` plus its uncommitted working
tree, platform at `30da025`, eightbitsaxlounge at `d528c4c`, the cloud repo's
SCPs, and the GitHub API.

⚠️ **Read [performance-context.md](../performance-context.md) first.** The
output is a **Game Boy backing track with one live player over it** — four LSDj
channels, one staff each, plus an alto sax that is never programmed. That
context arrived on 2026-09-15, after most of this plan was written, and it
changes what a correct arrangement *is*. The most consequential open item is
recorded there rather than here: **a pulse channel is monophonic, so the
harmony part cannot be chords.**

**There was nothing to migrate.** Unlike eightbitsaxlounge — six running
services whose manifests moved — composer has never run anywhere. `examples/`
is empty, the only test uses a two-note synthetic score, and no piece of this
has met a real piano part. So this is not a migration plan. It is a standup
plan, and it is sequenced so that the parts which can fail do so on a laptop in
an afternoon rather than on a GPU box three weeks in.

---

## The split: two goals, two repos

The instinct to separate these is right, and it maps cleanly onto
[ADR-0012](https://github.com/nineteenseventytwo/nineteenseventytwo-platform/blob/main/docs/decisions/ADR-0012-platform-owns-app-workloads.md).

| Goal | Nature | Owner |
|---|---|---|
| An AI workflow that re-arranges piano scores | Application | **composer** — this repo: source, image build, prompts, evals |
| The PC accepts and processes AI workloads | Shared infrastructure | **platform** — host prep, firewall, NetworkPolicy, the manifests that consume it |

Concretely, after this plan: this repo keeps `services/`, `.github/workflows/`
(build and publish only), `docs/`, `examples/`. It loses `infra/` entirely —
both halves of it, for two different reasons (**C8**).

---

## Findings — settle these before anything is deployed

Twenty-nine. Eighteen are application bugs — **C1's corpus landed on 2026-09-13;
five were found by running it and seven more by opening the output in MuseScore
and listening to it. C1, C11, C14, C15, C16, C17, C18, C19 and C20 are now
fixed, and C21 realigns the output with its target hardware.**
Each MuseScore round found something the previous fix had masked, which is the
argument for opening the output rather than trusting a green test run.
The original framing follows, since the reasoning is what matters —
**C1's corpus landed on 2026-09-13 and four of them were found by running it**;
three are infrastructure facts that shape the design; three are hygiene items
with precedent from the eightbitsaxlounge migration.

### C1 — The corpus exists now, and it disproves the current design

`examples/input/` held only `.gitkeep` until 2026-09-13. It now holds five
chiptune piano transcriptions — two Castlevania, two Kirby's Dream Land, one
Mega Man 2 — and running the deterministic half over them answered the
questions the rest of this plan was guessing at. Measured with `music21` 10.5.0,
no LLM involved:

| Score | Measures | Source notes | IR ~tokens **as found** | IR ~tokens **after the C11 fix** |
|---|---|---|---|---|
| Castlevania — Vampire Killer | 32 | 598 | ~9,100 | **~9,650** |
| Castlevania — Wicked Child | 51 | 603 | ~17,900 | **~9,400** |
| Kirby — Bubbly Clouds | 88 | 758 | ~22,500 | **~12,600** |
| Kirby — Green Greens | 43 | 644 | ~20,800 | **~10,100** |
| Mega Man 2 — Dr Wily Stage 1 | 112 | 1527 | ~34,600 | **~23,200** |

Most got *smaller* while recovering previously-lost notes, because harmony had
been duplicating pitches the melody and bass already carried, and runs of
identical chords now collapse (**C11**). **The conclusion survives the fix: the
smallest score is still ~9,400 tokens against an 8,192 output cap.**

Three conclusions fall straight out, and each one closes a question that was
open when this plan was written:

- **The IR is 9k–35k tokens.** Against Ollama's default context window of 2048
  or 4096, **95%+ of every score in the corpus is silently discarded** (**C4**).
  This is not a risk any more; it is the current behaviour.
- **Every score is larger than the model's configured maximum output.** The
  smallest is ~9,400 tokens against `num_predict: 8192`. Whole-score echo is
  therefore not merely wasteful (**C5**) — it is **arithmetically impossible on
  100% of the real corpus**. Chunking is mandatory, not an optimisation.
- **Structural loss is now quantified.** Ties: 112, 122, 4, 4, 153 — all
  discarded, so every tied note becomes two struck notes. Repeats: 4 in Wicked
  Child, discarded. Tempo changes: 58 in Green Greens and 4 in Dr Wily, of
  which only the first survives. `from_intermediate` returns Parts with
  **zero** `Measure` objects on every score, which also means `pipeline.py`'s
  `num_measures` branch is dead code — it always falls through to the estimate,
  which over-counts by one, so every output carries a spurious trailing bar.

Two metadata defects, both feeding straight into the prompt — **both fixed
2026-09-13**:

- **`title` is `"Untitled"` on all five.** `_extract_metadata` reads
  `score.metadata.title`, which these files leave unset.
- **`key` is a Python repr on three of five** — literally
  `"<music21.key.KeySignature of 3 sharps>"`. `str()` on a `KeySignature`
  rather than a `Key`. The model is being told the key signature in the form of
  a debugger string.

The corpus is doing its job and should grow, but the priority has shifted: what
it needs next is not more files, it is the two *kinds* still missing — a
structural stress case and a deliberate out-of-domain texture (see the note
under **P0**). What it has now is a consistent, on-brand set of two-staff
chiptune transcriptions, which turns out to be enough to find four bugs.

⚠️ **Licensing.** These are transcriptions of copyrighted game music and this
repo is public and about to move into the organisation under a ruleset. Before
**P4** transfers it, decide whether the corpus is committed, `.gitignore`d as a
local working set, or replaced with public-domain material. Committing it is
the one option that is hard to undo.

### C2 — The prompt's few-shot example teaches a schema the code cannot parse

The uncommitted change to
[llm_client.py](../../services/composer/src/composer/llm_client.py) adds a
worked example in this shape:

```json
{"parts": {"bass": {"notes": [ ... ]}}}
```

`to_intermediate` produces, and `from_intermediate` consumes, this shape:

```json
{"parts": {"bass": [ ... ]}}
```

A part is a **list**, not an object with a `notes` key. A model that follows
the example returns a dict where `_note_list_to_part` expects a list; it
iterates the dict's keys, gets strings, and raises `AttributeError` on
`item.get`. That is not caught anywhere (**C3**), so it surfaces as a 500 from
`/arrange`.

Worse, this is the failure mode you get when the model obeys you.

**DECIDED 2026-09-13.** Fix the example to match
[intermediate.py](../../services/musicxml-tools/src/musicxml_tools/intermediate.py),
then stop hand-maintaining the agreement: **the JSON schema is generated from
the code**, used both to constrain decoding (Ollama's `format`, **D-C**) and to
render the worked example in the prompt. One definition, mechanically derived,
so prompt and parser cannot drift apart again. A hand-written schema would be a
third copy of the same truth and would rot the same way this example did.

### C3 — The fallback hides failure, and does not cover the failures that happen

```python
except (httpx.HTTPError, json.JSONDecodeError) as e:
    return ir
```

Two problems.

**It catches the wrong things.** `_chat` indexes `data["message"]["content"]`
(`KeyError` on an Ollama error payload), and the structural check only tests
that the keys `parts` and `metadata` exist — not that their values have the
right shape. C2's failure passes that check and dies later.

**When it does work, it lies.** Returning `ir` unchanged means `/arrange`
returns 200 with a MusicXML file that is the original score plus a drum track.
The architecture doc frames this as "AI steps should be optional enhancements",
which is a good principle — but an optional enhancement that silently did
nothing is indistinguishable from one that worked. And per **C1** this is not
a rare case: fed a truncated fragment and asked for an output longer than it
can emit, **the fallback is the pipeline's normal path today**. The happy path
is "quietly do nothing and return 200", which is how four bugs sat undetected.

**DECIDED 2026-09-13 — keep the fallback, make it observable, and gate it on a
threshold once chunking lands.**

- Catch what actually fails (`KeyError` on an error payload included), and
  validate the *shape* of `parts`, not just the presence of the key.
- Report per-chunk and per-part status in the response body, plus a log line
  and a counter.
- Return the file when enough chunks succeeded; **return 502 when the
  transformation essentially did not happen**. Whole-score transformation is
  all-or-nothing, which is what made a hard failure tempting; per-section
  chunking (**C5**) makes partial success genuinely meaningful — 30 of 32 bars
  transformed is a real result, 0 of 32 is an error wearing a 200.

The fraction of chunks returning schema-valid output is also exactly the metric
**P1**'s eval needs, so this pays for itself twice.

### C4 — `num_ctx` is unset, so Ollama will silently truncate the input

The request sets `num_predict: 8192` but never `num_ctx`. Ollama applies a
small default context window (2048 in older builds, 4096 in recent ones —
confirm on the installed version with `GET /api/show`), and **silently discards
the overflow**. A score whose IR exceeds that window gets truncated with no
error, no warning, and a plausible-looking response generated from a fragment.

**C1 measured this: the corpus runs 9k–35k tokens.** Against a 4096 window,
between 55% and 88% of the *smallest* score is discarded, and 88–97% of the
largest. Every result produced by the pipeline as it stands today is generated
from a fragment of the opening bars.

This alone would make every result unreliable, and it looks exactly like "the
model is bad at this".

**A second trap sits next to it: `num_predict` is drawn from *within*
`num_ctx`, not in addition to it.** With `num_ctx: 4096` and a 3,500-token
prompt you get 596 output tokens regardless of what `num_predict` says. The two
have to be chosen together, and a generous `num_predict` under a small
`num_ctx` is silently a small one — which reads as "the model stopped early"
and sends you looking at the prompt.

**DECIDED 2026-09-13 — size `num_ctx` to the chunk, not to the score, with a
hard assertion as a backstop.**

- Chunking (**C5**) is the mechanism; a 4–8 bar chunk's IR is hundreds to low
  thousands of tokens, so an 8,192 window is already generous. Leaving VRAM
  unspent buys throughput rather than sitting idle.
- Sizing the window to fit a 35k-token score is the whole-score design wearing
  a different hat, and it does not fit in 8 GB regardless.
- **Count tokens before sending and refuse loudly** if a payload still does not
  fit. Never truncate. The assertion should never fire; an assertion that never
  fires costs nothing, and the failure being eliminated is a *silent* one.
- **Floor the chunk size.** Unbounded subdivision would keep splitting until
  things fit and quietly produce 1–2 bar fragments with no musical context —
  worse arrangements, and not visible as an error. Cap the split depth and fail
  instead.

Note the VRAM interaction: on an 8 GB card, KV cache for a large `num_ctx`
competes with model weights. An 8B model at Q4 leaves roughly 2–3 GB of
headroom. You cannot simply set `num_ctx: 32768` and move on — and the size of
that headroom is itself a consequence of **D-A**, which is most of why the
headless Linux boot was chosen.

### C5 — Whole-score echo is the wrong shape for the task

The pipeline asks the model to read the entire arrangement and return the
entire arrangement, modified. That is the single most expensive and least
reliable thing you can ask an LLM to do: most of the output tokens are verbatim
copying, every copied token is an opportunity to drop a note or drift an
offset, and the cost scales with the length of the piece rather than with the
amount of musical decision-making involved.

On a 4060 at ~40–60 tok/s for an 8B model at Q4, an 8192-token response is two
to three minutes of GPU time, most of it spent retyping notes the model was
never asked to change.

**And it cannot succeed anyway.** Per **C1**, the smallest score in the corpus
serialises to ~9,100 tokens and the largest to ~34,600, against an output cap
of 8,192. There is no score in the corpus the model could return in full even
if it copied perfectly. Raising `num_predict` is not the fix — 35k tokens of
KV cache plus weights does not fit in 8 GB alongside an 8B model, which is why
**C5** is a design change and not a tuning exercise.

Two reshapes, either of which is worth more than any model upgrade:

- **Chunk.** Transform per part and per section (4–8 bars) rather than
  whole-score-at-once. Smaller outputs, independently validatable, retryable in
  isolation, and parallelisable across requests.
- **Emit decisions, not notes.** Have the model return a bossa *plan* — chord
  symbol and voicing per bar, a rhythmic template, anticipation points — and
  let `musicxml-tools` render the notes deterministically. The bass and comping
  patterns are rule-shaped; the *choices* are what needs judgement. This is also
  what turns `musicxml-tools` functions into the tool definitions
  [07's Phase 11](https://github.com/nineteenseventytwo/nineteenseventytwo-platform/blob/main/docs/plan/07-completion-plan.md)
  wants for the agentic version.

**DECIDED 2026-09-13 — chunk first (P1), decisions second (P6), and chunked
echo is explicitly a stepping stone rather than the destination.**

The reason to start at chunking is not caution: the stated minimum is AI work
running through the PC end to end, and chunked echo reaches that fastest while
proving the infrastructure path, which is what the minimum is actually for. The
scaffolding it needs — sectioning, per-chunk validation, retry, reassembly — is
**not discarded** by the decision architecture; it is the same machinery.

What the second reshape buys is visible once the three parts are considered
separately, because only one of them wants an LLM much at all:

| Part | What it needs | LLM involvement under (b) |
|---|---|---|
| **Bass** | Root-and-fifth on a fixed bossa syncopation | Almost none — deterministic from the chords |
| **Harmony** | Rootless voicings, which extensions, what register | **This is where the judgement lives.** Small output, real decisions |
| **Melody** | Preserved, with phrasing applied | Deltas against existing notes (anticipate an eighth, add a grace note), not re-emission |
| **Drums** | Already deterministic | None |

So (b) collapses to: detect the chords, let the model choose voicings and
phrasing, let the library render everything. The model ends up emitting roughly
5–10% of the tokens it does today, and the entire class of "the model corrupted
a note" disappears because it never handles notes.

⚠️ **Record the stepping-stone status where the eval suite is written.** The
risk of (a) alone is not that it fails — it is that it works, mediocrely, and
that an eval built around its assumptions makes (b) look like a regression.

### C6 — The two workloads on the PC are mutually exclusive, and that is accepted

The PC also hosts the eightbitsaxlounge MIDI device service — a *runtime*
dependency of `chat` in both environments (`midi-configmap.yaml` points at it,
`midi-networkpolicy.yaml` opens an egress allow-pair to it, and the whole
Twitch-message-to-effects-pedal path runs through it), deployed as a Windows
service under NSSM by `midi/midi-pc-deploy.yaml`.

Booting the PC to Linux for AI work therefore takes MIDI offline, and vice
versa. **Confirmed 2026-09-13 as a non-issue: MIDI is not required during AI
work.** The two are used at different times — MIDI during a stream, inference
when arranging — so one machine serving both by boot selection is a scheduling
constraint, not a conflict.

It is recorded here rather than dropped because it has two consequences that
outlive the decision:

- **`chat` in both environments will fail its MIDI calls whenever the PC is
  booted to Linux.** That is a recurring, expected condition, not an incident.
  It should be *visible* as such — otherwise every arranging session generates
  alert noise that trains you to ignore the alert. Check what 8BSL's `chat`
  does on an unreachable `MIDI_DEVICE_URL` before the first long inference run.
- **Nothing in the cluster can boot the PC.** If composer sends a request to a
  host that is powered off or sitting in Windows, it gets a connection refusal.
  Composer needs to fail that case cleanly and say *why* (**C3**), and P2 needs
  to decide whether Wake-on-LAN is worth wiring up or whether "boot it first"
  stays a human step.

### C7 — Two repos record the PC's address wrongly

**Settled 2026-09-13.** The PC's addressing was fixed after the
eightbitsaxlounge migration and is now:

| Interface | VLAN | Address | Applies to |
|---|---|---|---|
| **Ethernet** | **20** | **`192.168.20.210`** | **both Windows and Linux boots** |
| Wi-Fi | 10 | — | both boots |

One address, one VLAN, both operating systems — which is what makes **D-A**
simple. The cluster reaches the PC at `192.168.20.210` regardless of which OS
is running, and the only thing that changes across a reboot is *which service*
is listening on it.

Two records contradict that and are stale:

- `platform/ansible/inventory/lab/hosts.yml` — the `midi` group says
  `ansible_host: 192.168.10.50`, and its comment says "VLAN 10 when booted to
  Windows, VLAN 20 when booted to Linux". Both wrong; the host is reachable on
  `192.168.20.210` either way. **Fix in P2**, in the same PR that adds the GPU
  host, since it is the same inventory entry.
- `composer/infra/` — `192.168.68.205` and `.50`, from the pre-VLAN flat LAN.
  Deleted wholesale in **P4** (**C8**).

The platform manifests (`midi-configmap.yaml`, `midi-networkpolicy.yaml`) are
correct and need no change; composer's own NetworkPolicy in **P3** copies their
`192.168.20.210/32` shape.

### C8 — `composer/infra/` documents a cluster that no longer exists

Carried from 07's WP-7, and worse than that ticket suggests. `infra/README.md`
describes 192.168.68.0/24, Flannel, node names that were renamed, a
`1972-home` GPU node that was never built, and instructs the reader to run
`make init-console-config` from `eightbitsaxlounge/server` — **a directory
deleted in commit `fee47a3`**. Following these instructions today fails at
step 4.

`infra/k8s/` is a second, independent problem: it holds `composer`
Deployment/Service/Namespace manifests, which ADR-0012 says the platform repo
owns. A second set in the app repo is precisely the ambiguity that ADR exists
to remove. The `nodeSelector: workload: llm` in it also encodes the rejected
D1(a) architecture.

Delete both. Not correct, not stub — delete, for the same reason `server/` was
deleted rather than archived: it is the only way the stale addresses stop being
found by the next person reading the repo.

**Salvage two things first**, both into the platform repo's GPU-host role
(**D-A**): the NVIDIA driver and container-toolkit tasks from the
already-deleted-but-uncommitted `setup-gpu-node.yaml`, and the storage and
partitioning guidance from `README.md`. Everything else goes.

**DECIDED 2026-09-13 — `services/llm-server/` is retired entirely, not kept as
a home for model notes.** Under **D-A** there is no llm-server Kubernetes
manifest; the platform role owns the runtime, the model pin and the digest. A
directory here holding only a README and a `version.txt` for something this
repo does not deploy is the same ambiguity ADR-0012 exists to remove, one layer
down. `services/training/` is unaffected — it keeps the `Modelfile` for the
fine-tuned model and stays parked (**D-C**).

### C9 — CI targets a retired runner, and the repo has none of the controls

Exactly the eightbitsaxlounge F1/F7 situation, unfixed here:

| | composer | platform / cloud / 8BSL |
|---|---|---|
| Organisation | `mchellmer/` | `nineteenseventytwo/` |
| Visibility | public | public |
| Ruleset on `main` | **none** (API confirms `[]`) | `main` — deletion, non-fast-forward, PR required, signed commits, status checks |
| Runner | `runs-on: self-hosted` in all three workflows | ARC scale sets `lab-dind` / `lab-deploy`, or hosted |
| Deploy path | `deploy.yaml` runs `ansible-playbook deploy-services.yaml` | Argo CD |

All three workflows target the runner retired in 8BSL's Phase 6.2 — composer's
CI has not been able to run since. And `deploy.yaml` deploys via Ansible
straight to a cluster, which is the pre-ADR-0012, pre-Argo-CD model.

⚠️ **A dormant fork-PR RCE path, and it constrains the ordering.**
`composer.yaml` and `musicxml-tools.yaml` both carry `pull_request:` triggers
**and** `runs-on: self-hosted`, on a public repo — precisely the combination
[ADR-0010](https://github.com/nineteenseventytwo/nineteenseventytwo-platform/blob/main/docs/decisions/ADR-0010-fork-pr-self-hosted-runners.md)
exists to prevent, and the one eightbitsaxlounge never had (all 15 of its
workflows were `workflow_dispatch`/`push`). Confirmed dormant 2026-09-13 —
`gh api .../actions/runners` returns `total_count: 0`, so nothing picks the jobs
up. But the configuration is committed, and **the transfer into the org is the
moment it could stop being dormant**, since the org has ARC scale sets
attached. **Repoint the workflows to hosted runners in the same change as the
transfer, or before it** — never after.

**DECIDED 2026-09-13 — the repo stays public, and the corpus is not
committed.** ADR-0013 and ADR-0010 establish public-by-default for org repos
and that reasoning is extended here rather than re-litigated. So `examples/` is
`.gitignore`d as a local working set, with an `examples/README.md` naming the
five scores and where to obtain them — the eval set stays reproducible without
this repo redistributing copyrighted transcriptions. Going public-domain
instead was considered and rejected: it costs the on-brand chiptune corpus for
a problem `.gitignore` already solves.

No multi-arch build is needed anywhere: the cluster is arm64-only and the PC
runs Ollama's own upstream image, so `ubuntu-24.04-arm` hosted runners cover
every build in this repo.

### C10 — Bedrock is permitted by the SCPs; provisioned throughput is not

Checked against `cloud/policies/scp/`:

- `DenyManagedServicesWithFourFigureAnnualCost` denies
  **`bedrock:CreateProvisionedModelThroughput`** — the committed-capacity
  purchase. On-demand `bedrock:InvokeModel` is **not** denied.
- `DenyRegionsOutsideAllowlist` limits everything to `eu-west-2` and
  `us-east-1` (`cloud/config/aws.json`).
- `modules/aws-cluster-oidc-role` already does IRSA on this non-EKS cluster and
  has three live consumers (`role_vault_unseal`, `role_longhorn_backup`,
  `role_prowler`). A composer role is a fourth instance of a working pattern,
  not new ground.

So the Bedrock stretch goal is architecturally clear. Two things to verify
rather than assume: which Claude models are actually available in `eu-west-2`,
and whether a cross-region inference profile (the `eu.` prefixed IDs, which
route across EU regions) satisfies `DenyRegionsOutsideAllowlist` — the SCP
evaluates `aws:RequestedRegion`, which should be the endpoint region, but
confirm it with a real call before designing around it.

**No SCP can cap token spend.** The guardrails here are cost-shaped, not
API-shaped: the existing budget alarm, plus a client-side request and token
budget in composer itself.

### C11 — The splitter silently drops voices, and harmony is under-populated

Two independent defects in
[splitter.py](../../services/musicxml-tools/src/musicxml_tools/splitter.py),
both found by **C1**'s corpus and both invisible without it.

**It does not look inside `Voice` objects.** `_extract_top_voice`,
`_extract_bottom_voice` and `_extract_inner_voices` all iterate
`measure.notesAndRests`, which does **not** recurse into `music21.stream.Voice`.
Two of the five scores have voiced staves — Vampire Killer (58 measures with
voices) and Dr Wily (86) — and both lose notes: Vampire Killer goes from 598
source notes to 384, a **36% loss**, where chord decomposition should have made
the count go *up*. The other three scores have no voices and gain notes as
expected. Multi-voice piano writing is normal, not exotic, so this will keep
happening.

**Non-top treble notes are discarded rather than demoted.** When several
`Note` objects share an offset, `_extract_top_voice` keeps the highest and drops
the rest — and they are never recovered, because `_extract_inner_voices` only
processes `Chord` elements with more than one pitch and ignores bare `Note`s
entirely. So a two-part texture written as two independent notes (rather than
as a chord) loses its lower line completely. That is why harmony is so thin:
90 items across 32 measures on Vampire Killer.

**DECIDED 2026-09-13 — fix the voice recursion as a bug; replace inner-voice
extraction with `chordify()` rather than patching it.**

The two halves get different treatment on purpose:

- **Voice recursion is a straight bug and goes first.** Iterate
  `measure.recurse().notesAndRests` so voice contents arrive with correct
  offsets; the existing group-by-offset logic already handles simultaneous
  notes. Until this lands, every number in **C1** — and every eval number
  after it — is measured against a lossy split, melody included.
- **Harmony is not "inner voices", it is "what chord is sounding".**
  `music21.chordify()` performs exactly that reduction, and it is what **C5**'s
  decision architecture needs as input. Patching `_extract_inner_voices` would
  fix the symptom and then be discarded; going to `chordify()` closes the bug
  and lays the groundwork in one piece of work.

⚠️ `chordify()` on a texture with passing notes emits a chord at every
rhythmic event, including harmonically meaningless ones. A reduction pass —
quantise to the beat or bar, take the prevailing pitch set — is needed on top
before the output means "the chord in this bar". Well-trodden, but not free;
budget for it in **P0**.

**FIXED 2026-09-13**, and the fix needed one correction the finding did not
anticipate. Dropping the top and bottom pitch of each chordified chord is
wrong whenever fewer than three pitches sound: at a moment where two treble
notes sound over a silent bass, both get dropped and the lower one belongs to
nothing. Found by the reconciliation gate — six pitches across the corpus,
e.g. Wicked Child m9 where the chord is `['B4', 'D#5']` and `B4` vanished.

Harmony now subtracts what the melody and bass **actually claimed**, by
identity over a time span rather than by position — spans because a melody
note sustains across the onsets at which `chordify()` re-articulates it.
A run of identical remaining pitch sets is then merged.

**Gate result: 0 pitches absent across all five scores.** Note that the
offset-level version of this check is meaningless and was discarded — both
`chordify()`'s re-articulation of sustained notes and the deliberate merge of
repeated chords move offsets legitimately, so exact-offset comparison reports
~15% "loss" on a correct split. The metric that isolates real loss is whether
a pitch disappears from its bar entirely.

### C12 — The upload path fails on every file in the corpus

`app.py` writes the uploaded bytes to
`tempfile.NamedTemporaryFile(suffix=".musicxml")` regardless of what was
uploaded. All five corpus files are **`.mxl`** — compressed (zipped) MusicXML,
which is what MuseScore exports by default.

`music21.converter.parse` dispatches on the file extension, so it hands zip
bytes to the XML parser and raises:

```
ParseError: not well-formed (invalid token): line 1, column 2
```

Verified 2026-09-13 by reproducing `app.py`'s exact handling. Note the split:
`parse_score` on the original path handles `.mxl` **correctly** — the library
is fine, the HTTP endpoint is not. So the tests pass, the CLI path works, and
the API fails on 100% of real uploads.

**DECIDED 2026-09-13 — sniff the content, cap the size, and clean up after
the response.** Three small changes, all inside `app.py`:

- **Sniff, do not trust the filename.** This is a public endpoint, so the
  client-supplied name is an assertion. Compressed MusicXML begins with the zip
  magic `PK\x03\x04`; uncompressed begins with `<?xml`. Detect from the first
  bytes and write the matching suffix. Accept `.mxl`, `.musicxml`, `.xml`;
  reject anything else with a **400**, not the current 500 — a malformed upload
  is the client's error and should read as one.
- **Cap the request size.** `music21` parsing is unbounded work on
  attacker-supplied input, under a tenant quota where `limits.memory` covers
  the whole tenant. Size the cap from the corpus — the largest file is 28 KB
  compressed, so a generous cap is still tiny — and reject before parsing.
- **Clean up the output file.** The `finally` block unlinks the input, but the
  output is left behind under a comment claiming `FileResponse` removes it.
  It does not. Attach a `BackgroundTask` to delete it after the response is
  sent, or the pod slowly fills its filesystem.

Fold **C13**'s `asyncio.to_thread` fix in at the same time — same file, same
change.

### C13 — The pipeline blocks the event loop

`arrange()` is `async def`, but `parse_score`, `split_voices`,
`to_intermediate` and `assemble_score` are all synchronous, CPU-bound calls
made directly inside it. `await arrange(...)` therefore runs blocking work on
the event loop: concurrent requests serialise, and `/health` stops answering
for the duration — which on a Kubernetes Deployment means the liveness probe
can fail *because the service is busy*, and the kubelet restarts a pod that was
working correctly.

Measured at 50–150 ms on an M-series Mac (**D-E**), so on a Pi this is
sub-second and the practical impact today is small. It stops being small the
moment anything CPU-heavy joins the path — `chordify()` plus a reduction pass
(**C11**) is the obvious candidate.

Wrap the synchronous work in `asyncio.to_thread` (or Starlette's
`run_in_threadpool`). Small fix, and it removes an entire class of
"why did Kubernetes restart my pod" investigation.

### C14 — The drum generator has never run on music21 10.x

Found 2026-09-13 by running the test suite, which had not been run in a long
time because CI points at a retired runner (**C9**).

`drums.py` assigned instrument labels to `Unpitched.displayName`:

```python
hh.displayName = "Closed Hi-Hat"   # AttributeError on music21 10.x
```

Two things were wrong, and the second is the interesting one:

- `displayName` became **read-only** in music21 10, so every call raised
  `AttributeError` and **no bar of drums has ever been generated** on a current
  music21. Both `drums` tests and composer's only pipeline test failed.
- More fundamentally, **`displayName` is a staff position, not a label** — it
  returns something like `"G5"`, derived from `displayStep`/`displayOctave`.
  Passing `"Closed Hi-Hat"` was semantically wrong even on music21 9, where it
  happened not to raise. *Which* drum is `storedInstrument`, which the code was
  already setting correctly; *where it sits on the staff* is `displayStep` and
  `displayOctave`. Conflating them is the bug.

**FIXED 2026-09-13**, then fixed twice more — opening the result in MuseScore
showed the API fix was necessary but nowhere near sufficient:

- **The kit played as pitched notes** — "C5 is a whistle, F4 is like a metal
  pan, G5 is like a viola string". The part carried no percussion clef and no
  instrument (`assemble_score` sets instruments for melody, harmony and bass
  but not drums), so a reader has no reason to treat the staff as percussion
  and simply plays the staff positions. Now the part carries a
  `PercussionClef` and an instrument.
- **A 4/4 bar exported as 7.5 quarter notes.** Three instruments sound
  simultaneously, and a measure holding overlapping notes with no `Voice`
  objects cannot be represented in MusicXML — music21 serialises them end to
  end instead (4.0 + 2.0 + 1.5 = 7.5). Every other part then fell silent
  waiting for the drums to finish, which is exactly what was reported. Each
  instrument now gets its own voice.
- **The pattern ignored the metre.** Side stick on "beat 4" does not exist in
  3/4, and an out-of-range hit silently lengthened the bar. Offsets are now
  data, clamped to the bar length.

Percussion notes are built by one helper taking an explicit staff position and
instrument, with conventional positions (hi-hat G5, side stick C5, bass drum
F4) as named constants and `x` noteheads. Verified: 4/4 and 3/4 both export
with correct bar lengths and a percussion clef.

**The root cause is the dependency floor, not the API change.**
`music21>=9.1` with no upper bound meant a breaking change arrived silently
into a repo whose CI could not run. Pinned to `>=10.5,<11` — the same lesson as
eightbitsaxlounge's unpinned base images (that migration's F6), and the reason
**C9** is not merely tidy-up.

### C15 — Reconstruction lost the metre, and the parts drifted apart

Found 2026-09-13 by opening the output in MuseScore: two scores rendered with
no sax and no bass at all, and the remaining parts did not line up.

Four separate causes, all in the rebuild path, all now fixed:

- **Overlapping notes made parts unrenderable.** Recovering notes from inside
  voices (**C11**) means an event can start while a longer one is still
  sounding. A `Part` holding overlapping notes cannot be engraved on one staff,
  and the reader drops it — which is why Vampire Killer and Dr Wily, *the two
  voiced scores*, lost their sax and bass entirely. Melody and bass are
  monophonic lines by definition, so each event is now trimmed to the next
  onset.
- **`append` instead of `insert`.** `Stream.append` places a measure at the
  stream's current `highestTime`, so any measure whose content is shorter than
  a full bar drags every later measure earlier. Sparse harmony drifted worst —
  32 source bars came out as 30, with bars of 4.25, 5.5 and 6.5 quarter notes.
  Measures are now anchored at their source offset.
- **The IR carried no time signature.** A part rebuilt from it had neither a
  `TimeSignature` nor any `Measure` objects, so music21's notation pass assumed
  4/4 and mis-barred Bubbly Clouds, which is in 3/4. It also meant the
  pipeline's "count the measures" branch could never fire and always fell
  through to an estimate that over-counted by one — hence the spurious trailing
  bar, and a drum part of a different length to everything else.
- **The IR could not express a pickup bar.** Wicked Child opens with a
  1.5-beat anacrusis, so every later measure sits 1.5 beats early; barring from
  zero assuming full measures mis-bars the whole score. Offsets alone cannot
  carry this, so `pickup` is now a metadata field, and reconstruction slides
  the music right by one bar minus the pickup, bars it, and marks the first
  measure as the anacrusis.

**Result across the corpus: every part of every score now has uniform bar
lengths and a measure count matching the source** — 32, 51, 88, 43 and 112 —
with the loss gate still at zero. One cosmetic remainder: Dr Wily's harmony
staff is 111 bars to everything else's 112, because its final bar holds no
harmony and so no measure is emitted for it.

### C16 — Per-note percussion mapping never reached the file

Found 2026-09-13, from a MuseScore screenshot: the kit still played wrong
sounds, the staff was labelled **"B Dr"**, and the notation looked flattened —
after **C14** had already added the clef, the instrument and the voices.

Reading the exported XML showed why. The drum `<score-part>` declared exactly
**one** `<score-instrument>` — Bass Drum, `midi-unpitched 36` — and **not one
`<note>` carried an `<instrument>` reference**. Every hit therefore played the
same sound, and the part inherited that instrument's name.

The cause is a short-circuit in music21's exporter:

```python
def setNoteInstrument(self, n, mxNote, chordParent):
    '''Insert <instrument> tags ... when there is more than one
    instrument anywhere in the same musicxml <part>.'''
    if len(self.parent.instrumentStream) <= 1:
        return
```

`Unpitched.getInstrument()` *does* privilege `storedInstrument`, so the
per-note data was correct all along — it is simply never consulted unless the
**part** holds more than one instrument. C14 inserted a single `BassDrum()`,
so the branch never fired. `storedInstrument` appears nowhere else in the
exporter; it is not an independent channel to the file.

A second defect sat underneath: **music21's own `percMapPitch` defaults are
not the sounds a bossa kit wants.** `HiHatCymbal` is 44 — the *pedal* hi-hat —
and `SnareDrum` is 38, a centre hit rather than the cross-stick the pattern
calls for.

**FIXED 2026-09-13.** All three instruments are inserted into the part, with
General MIDI numbers set explicitly — closed hi-hat 42, side stick 37, bass
drum 36 — and the part's name and abbreviation set rather than inherited.
Hi-hat and cross-stick now share the upper voice as a `PercussionChord` where
they coincide, so the staff carries the conventional two voices rather than
three with a rest thicket, which is what read as "flattened".

Verified in the output: three `<score-instrument>` entries, `midi-unpitched`
43/38/37 (the element is 1-based, so MIDI 42/37/36), and 416 per-note
instrument references on the reference score.

**Worth keeping as a general lesson:** three separate things decide how a
percussion note comes out — `storedInstrument` (which drum), `percMapPitch`
(which GM sound), and `displayStep`/`displayOctave` (where on the staff).
Every round of this bug came from conflating two of them.

### C17 — The parts were unplayable: wrong pitch, wrong range, wrong clef

Found 2026-09-13 from a second MuseScore screenshot — red noteheads on the sax
and bass, harmony stacked on ledger lines above a bass clef, and the drums
still collapsing onto one sound after **C16**. Four distinct defects.

**The alto sax sounded a major sixth low.** The part declared
`<transpose><diatonic>-5</diatonic><chromatic>-9</chromatic></transpose>`
because `instrument.AltoSaxophone` carries that transposition — but music21
streams hold *sounding* pitch and the exporter writes the element **without
moving the notes**. A reader therefore takes concert pitch as written pitch and
plays it a major sixth down. Fixed with `toWrittenPitch()` at assembly, so
notation and playback agree.

**Melody and bass were outside their instruments' ranges** — 30 of 258 melody
notes and 80 of 336 bass notes, which is what MuseScore was flagging in red.
Not a coding error so much as a consequence of the method: the melody is the
top note of a piano texture and the bass is the bottom note, and a piano spans
far more than either instrument plays. Notes are now octave-folded into range,
by the **fewest whole octaves** that bring them inside — folding everything
toward the centre would flatten the line's contour rather than relocate it.

**The first version of that fold oscillated.** A chord wider than the target
window failed both tests in turn, shifting up then down until the iteration
bound, and left harmony spanning C#2 to D7 — further out than it started. Wide
chords are now centred in a single move instead.

**Harmony had a bass clef.** With no explicit clef the reader picks one from
pitch content, and a harmony part spanning two octaves got bass clef with most
of its notes on ledger lines above the staff. Each part now carries one
explicit clef.

**Also fixed here, superseding C16's notation choice:** the `PercussionChord`
that C16 introduced for readability turned out to break the sound. music21's
exporter resolves a chord member's instrument from the **chord**, not the
member (`searchingObject = chordParent if chordParent else n`), so every note
inside one inherits a single instrument — 224 of 416 drum notes exported as
MIDI 36. That is the "sounds like bass drums with lots of echo" symptom. Back
to one voice per instrument: the reference score now exports **256 hi-hat, 64
side stick, 96 bass drum**, exactly as generated.

**Result:** across the corpus, every sax and bass part is fully inside its
instrument's range, every part carries an explicit clef, and the drum kit maps
to three distinct General MIDI sounds.

**One known remainder, recorded rather than fixed.** Vampire Killer's harmony
still has 40 of 228 notes outside the C3–C5 comping window (Dr Wily, 2 of 236;
the other three scores, zero). These are chords `chordify()` produced spanning
more than two octaves, which cannot fit and are centred instead. It is a
stylistic target rather than an instrument limit — a piano plays all of them,
and no reader flags them. Octave folding is in any case a stopgap: under
**C5**(b) the bass line is generated from chord symbols rather than folded down
from a piano part, and the question disappears.

### C18 — Two thirds of the kit played on pitched MIDI channels

The last of the drum defects, and the one that survived three rounds of fixes
because the notation looked right the whole time. Found by reading
`<midi-instrument>` out of every generated file rather than just one:

| Instrument | GM note | Channel |
|---|---|---|
| Hi-Hat Cymbal | 42 Closed Hi-Hat ✓ | **10** ✓ |
| Snare Drum | 37 Side Stick ✓ | **4** ✗ |
| Bass Drum | 36 Bass Drum 1 ✓ | **5** ✗ |

General MIDI reserves channel 10 for percussion. Channels 4 and 5 are melodic,
so the cross-stick and bass drum were played by whatever patch those channels
held, at MIDI notes 37 and 36 — very low and sustaining. A boomy thud, on every
beat, in all five files. The **sounds** were right and the **routing** was not,
which is why fixing `percMapPitch` (**C16**) and the instrument references
(**C17**) both appeared to work and both left the symptom in place.

The cause is a limitation in music21, in `autoAssignMidiChannel`:

```python
if 'UnpitchedPercussion' in self.classes and 9 not in channelFilter:
    self.midiChannel = 9
```

Percussion gets channel 10 **only if nothing else has claimed it**. The first
drum instrument takes it and the exporter appends it to a shared
`midiChannelList`; every later percussion instrument then trips the
deduplication branch — written for pitched instruments, which do each need
their own channel — and is pushed onto a free melodic channel. music21 cannot
express a kit sharing channel 10, which is the one thing GM percussion
requires. Setting `midiChannel` on the instruments does not help: the exporter
reassigns on the way out.

**FIXED 2026-09-13** in `write_score`, by the rule that identifies percussion
unambiguously: **any `midi-instrument` carrying a `midi-unpitched` element
belongs on channel 10.** Applied to the written file, since that is the only
point after the exporter has finished reassigning. Verified across all five
scores: three instruments on channel 10 with GM 42/37/36, pitched parts on
channels 1–3.

**The process lesson is the one worth keeping.** Three fixes in a row were
verified by checking that the notation was correct and the tests were green,
and the defect was in neither place. What found it was reading the actual
output of *every* file rather than the one that had been examined by hand.

### C19 — The kit was never identified as a kit

Reported 2026-09-15, after **C18** put every drum on channel 10 with the right
GM note and the symptom *still* did not go: no timekeeper sound at all, and the
eighth notes on the G position "all sound like bass drums", with the bass drum
itself too boomy.

The routing was right by then. The **identification** was not.

**music21 never emits `<instrument-sound>`.** The attribute exists and is
correctly populated (`metal.hi-hat`, `drum.bass-drum`, `rattle.maraca`), and
the exporter silently drops it — verified by round-tripping a part with the
values explicitly set and finding the element absent. That element is how a
reader identifies a percussion voice without guessing.

Left guessing, MuseScore matched on `<instrument-name>` — and the part was
offering it `"Bass Drum"`. That matches a **concert bass drum**: a single
sustaining orchestral instrument, which then plays every note on the staff.
Hence one boomy sound everywhere, no timekeeper, and "two bass drum sounds
essentially". `assemble_score` was also overwriting the part name with
`"Drums"`, sending the same search after a lone percussion instrument rather
than a kit.

**FIXED 2026-09-15**, and the kit changed on the same pass at the owner's
direction — a **shaker** rather than a hi-hat, which is the idiomatic bossa
timekeeper; a kit hi-hat is a samba or swing sound.

| Voice | GM | `instrument-sound` | Staff |
|---|---|---|---|
| Shaker | 82 | `rattle.shaker` | G5, `x` notehead |
| Side Stick | 37 | `drum.snare-drum` | C5, `x` notehead |
| Bass Drum 1 | 36 | `drum.bass-drum` | F4 |

`write_score` now injects `<instrument-sound>` alongside the channel fix,
keyed by **GM note** so the mapping cannot drift from the kit, and the part
names itself `"Drum Kit"` — which `assemble_score` no longer overwrites.
Verified across all five scores: three voices, channel 10, correct GM numbers,
sound ids present, part name `Drum Kit`.

**Four rounds on one staff, and the lesson repeats: at each round the thing
that was checked was correct, and the defect was one layer further out.**
Notation → sounds → routing → identification. Only the last of those is
visible to the person listening, and none of it is visible to a test that
asserts the notes are in the right places.

### C20 — The two drum voices had their musical roles swapped

Reported 2026-09-15, once the kit finally sounded like a kit and the *groove*
became audible for the first time: the pattern was only "vaguely bossa".

It was a rock pattern in bossa clothing. The original had:

| Voice | Played | Should play |
|---|---|---|
| Cross-stick | beats 2 and 4 | **the clave** |
| Bass drum | `(0.0, 1.5, 3.0)` / `(0.5, 2.0, 3.5)` | **a steady two-feel** |

Beats 2 and 4 on the rim is a backbeat. And the kick's figure was, of all
things, *the three-side of the clave itself* — the right rhythm on the wrong
drum. The two voices needed exchanging, not rewriting.

**FIXED 2026-09-15:**

```
cross-stick  bar 1 (three-side): 0.0, 1.5, 3.0   beat 1, and-of-2, beat 4
             bar 2 (two-side):   1.0, 2.5        beat 2, and-of-3
bass drum    every bar:          0.0, 2.0        beats 1 and 3
shaker       every bar:          straight eighths
```

The clave is 3-2 **bossa**, not son: its second bar is beat 2 and the
and-of-3, where son clave plays beats 2 and 3. That single displaced note is
most of what makes the figure read as Brazilian rather than Cuban, and it is
the kind of detail that is invisible to every mechanical check in this repo.

The bass drum's steadiness is the point rather than a simplification — it is
what the clave syncopates *against*. In 3/4 the clave's beat 4 falls outside
the bar and is dropped, leaving `0.0, 1.5` and `1.0, 2.5`, which degrades
sensibly.

**This is the fourth kind of defect found on one staff**, after notation,
routing and identification: *musical* correctness. Worth noting what caught
each — a test suite caught none of them, reading the XML caught two, and only
listening caught this one. An eval measuring note counts and schema validity
would pass a backbeat labelled as bossa without complaint. **P1's eval set
has to include at least one judgement that a machine cannot make.**

### C21 — The score described a performance that will never happen

Context established 2026-09-15 and written up in
[performance-context.md](../performance-context.md): the backing track is
programmed into a **Game Boy via LSDj** and the alto sax is played live over
it. Four channels, four programmed parts, one live part — it fits exactly, with
nothing spare.

| Part | Channel | Was | Now |
|---|---|---|---|
| Alto Sax | *live* | Alto Saxophone | unchanged |
| Harmony | Pulse 1 | **Piano** | **Square Synthesizer** |
| Bass | Pulse 2 | **Electric Bass** | **Square Synthesizer** |
| Drum Kit | Wave (LSDj kit) | kit + shaker | **kit only** — bass drum, cross-stick |
| Shaker | Noise | *third voice on the kit staff* | **its own part** |

**One staff per channel** is the organising rule, and it is why the shaker was
split out rather than left as a third voice: the person entering this into LSDj
reads one staff and fills one channel. Notating harmony as piano and bass as
electric bass described sounds that hardware cannot make.

**FIXED 2026-09-15.** Five parts; `generate_bossa_shaker` alongside
`generate_bossa_drums`; square synths (GM 81, `synth.tone.square`) on the two
pulse parts; the harmony part renamed from "Piano" to "Harmony" so a reader
does not offer a piano patch for a pulse channel.

Splitting the shaker out immediately exposed a latent bug of the **C15** family:
neither kit voice reaches the barline on its own — the clave stops at beat 4,
the kick at beat 3 — so the measure came out 3.5 quarter notes long and every
later measure drifted earlier. The shaker had been masking it by running to the
barline. Both voices are now filled to the bar.

**The monophony question is settled.** A pulse channel plays one note at a
time, and the harmony part emits chords — **decided 2026-09-15: the score stays
chordal and LSDj Tables supply the chord character.** A chord is therefore a
harmonic *intention* rather than a literal instruction, which leaves voicing
choices meaningful (the table cycles whatever it is given) while removing voice
count as a playability limit. That is the right division of labour for
**C5**(b): the model picks the chord, the table plays it. Full reasoning in
performance-context.md, since it is a property of the target rather than a
defect in the code.

### C22 — Splitting the shaker out re-broke its sound

Reported 2026-09-15, immediately after **C21** gave the shaker its own part: it
went back to sounding like a pitched instrument — "kind of sounds like a string
instrument and not shaker".

The XML looked correct and was correct: percussion clef, `<unpitched>` notes,
channel 10, `midi-unpitched` 83 (GM 82), `instrument-sound` `rattle.shaker`.
One structural difference separated it from the drum kit part, which worked:

| | Drum Kit | Shaker |
|---|---|---|
| Instruments in part | 2 | **1** |
| Per-note `<instrument>` refs | present | **absent** |

`setNoteInstrument` short-circuits when a part holds one instrument, on the
reasoning that a lone instrument is unambiguous:

```python
if len(self.parent.instrumentStream) <= 1:
    return
```

It is unambiguous to a reader of the spec. It is evidently not unambiguous to a
reader building a drum map — the two parts were identical in every other
respect and only the one carrying explicit references resolved to percussion.
This is the same short-circuit as **C16**, reached from the opposite direction:
there, a part had too few instruments because the kit was collapsed into one;
here, because the shaker legitimately *is* one.

**FIXED 2026-09-15.** `write_score` now adds an explicit `<instrument>`
reference to every unpitched note in any part whose single instrument is
unpitched, positioned per the schema immediately after `<duration>`. Scoped so
nothing pitched is touched. Verified across all five scores: every shaker note
carries a reference — 256, 408, 528, 344 and 896 respectively — on channel 10
at GM 82.

**Three of the export repairs now live in `write_score`** — percussion channel,
`instrument-sound`, and per-note instrument references. All three are things
music21 will not emit and a reader needs. Worth keeping them together and
documented as a group: they are not incidental fixes but a standing adapter
between what music21 writes and what notation software reads.

### C23 — Pretty-printing the payload doubled its cost

Found 2026-09-15 while measuring C4's refusals. The prompt serialised the IR
with `json.dumps(ir, indent=2)`. Against a context window that is pure waste:
the model gains nothing from the whitespace, and it is charged for every space.

| Score | `indent=2` | compact | saved |
|---|---|---|---|
| Vampire Killer | 19,898 | 10,392 | 48% |
| Wicked Child | 17,127 | 8,977 | 48% |
| Bubbly Clouds | 22,677 | 11,788 | 48% |
| Green Greens | 18,248 | 9,629 | 47% |
| Dr Wily | 42,068 | 21,666 | 48% |

**FIXED 2026-09-15** with `separators=(",", ":")`. Worth recording because it
is the cheapest lever available against a context window and it was invisible
until something actually measured the payload — the pipeline had been sending
these for months with no way to notice.

A related trap avoided while implementing chunking: rebasing offsets with
`round(x, 6)` turned a triplet offset of `3.6666666666666665` into `3.666667`.
Musically negligible, but durations carry tuplet information that music21 reads
exactly, and a lossy round trip accumulates. Rebasing now subtracts and re-adds
without rounding, and the split/merge cycle is **exact** at every chunk size
from 1 to 16 bars.

### C24 — First real inference: it arranges, but it does not keep the harmony

2026-09-15. `llama3.1:8b` (Q4_K_M) via local Ollama on an M3 Max, against
Vampire Killer. **The first arrangement this project has produced.**

**The mechanism works.** Ollama's grammar converter accepts the generated
schema — nested `anyOf` and pitch patterns included — and returned conforming
IR first time. After retuning, **8/8 chunks transformed**.

**Constrained decoding is not a cost, it is a saving.** Measured on one 2-bar
chunk:

| | Time | Output | tok/s | Valid JSON |
|---|---|---|---|---|
| No `format` | 64.9s | 2,010 | 31.0 | ❌ |
| Schema, patterns stripped | 31.5s | 1,138 | 36.1 | ✅ |
| Schema, full | 30.2s | 1,138 | 37.7 | ✅ |

It is *faster* than free generation — the grammar stops the model rambling —
and the regex patterns cost nothing measurable. That settles a risk the plan
had carried since **D-C**.

**The binding cost is output volume: ~18 tokens per event.** 63 events produced
1,138 tokens. Eight-bar chunks (~190 events ≈ 3,400 tokens) brushed the 4,096
cap and truncated mid-array; three concurrent requests on one GPU turned ~120s
chunks into timeouts. Retuned to **4 bars** and **concurrency 2**, and
truncation is now a named error rather than a confusing `JSONDecodeError` —
constrained decoding guarantees well-formed JSON *if it finishes*, so a broken
document means it ran out of room.

**It does real arranging.** Bass 336 → 211 events, harmony 202 → 133, melody
258 → 212 — thinned, which is what "chill" asks for. The bass went from busy
16th-note figures leaping D2↔G4 to a textbook root–fifth alternation in long
notes.

⚠️ **But it invents the harmony. The bass keeps the original root in only
8 of 32 bars, and drops several bars entirely.** Stylistically convincing,
harmonically wrong — which makes it unusable as an arrangement *of that piece*.
A plausible-sounding wrong root is worse than a busy correct one.

**Two conclusions follow, and they are the shape of the next phase.**

1. **Root preservation is the eval's first metric**, and it is mechanical —
   25% today, measured per bar against the source. **C20** worried that machine
   checks would pass anything stylistically labelled; this is the
   counter-example, a purely mechanical check that catches exactly the failure
   a listener would call "that's not the tune".
2. **This is the empirical case for C5(b).** Asked to *write the notes*, the
   model invents the harmony and costs 18 tokens an event. Asked to *name the
   chord* while the library renders root–fifth from it, the root cannot drift —
   it is an input, not a generation — and a 4-bar chunk needs perhaps 100
   output tokens instead of 1,700. That is both the quality fix and a ~17×
   speed-up, on the same change. At 577s for 32 bars, the current design is not
   merely imperfect, it is impractical.

### C25 — C5(b) implemented: the root stops drifting because it stops being generated

2026-09-15, in response to **C24**. `musicxml_tools/harmony.py` detects the
chord in each bar of the source and renders bass and comping from it by rule.
No model.

The chord's root is taken from the **composer's own bass line, weighted by
sounding duration** — not from the lowest pitch, which a passing dip
misidentifies, and not counted per event, which lets fast decoration outvote
the harmony. Everything downstream is rule-shaped, because bossa bass and
comping are: root and fifth on a fixed syncopation, rootless voicings on the
same figure so the two lock.

Measured against **C24**'s run on the same corpus:

| | note-echo (llama3.1:8b) | deterministic |
|---|---|---|
| Root preserved | **25%** | **100%** |
| Harmony fidelity | — | **100%** |
| Bar coverage | bars dropped | **100%** |
| Time, 32 bars | **577s** | **0.06s** |

⚠️ **Be precise about what that 100% proves.** Root preservation is now close
to tautological on this path: the detector and the metric read the same
evidence, so it is a **regression guard, not a quality measure**. What it does
prove is that the failure mode C24 found — a convincing bossa bass in the wrong
key — cannot occur by construction, because the root is an input rather than a
generation. Harmony fidelity at 100% is similarly structural: every voiced
pitch class was sounding in that bar of the source.

Whether the result is *good* remains a listening question (**C20**), and the
open ones are musical rather than mechanical: chord detection reduces a bar to
its four strongest pitch classes, which is crude on bars that genuinely change
harmony mid-way, and 26 of 32 bars get a nameable chord symbol — the remainder
are rendered from pitch sets that do not spell a named chord.

**Both strategies are kept**, selected by `COMPOSER_ARRANGER`
(`deterministic`, the default, or `notes`). They are a progression rather than
alternatives: the destination described in **C5**(b) is the model choosing
voicings and substitutions **on top of** detected chords, which is a third
arranger alongside these rather than a replacement for either. That way the
model is asked for judgement it can be checked on, and never for the root.

**The wider lesson, and it generalises past this project:** the fix was not a
better prompt or a bigger model. It was noticing that the thing going wrong —
harmonic identity — was information the system already had, and had been
throwing away in order to ask a model to guess it back.

### C26 — Phase A: making the deterministic arranger musical

2026-09-16. The first deterministic pass scored 100% on every mechanical metric
and still did not sound like music: a chord change in **every bar**, chord
"qualities" like `CsusaddB-,omitG` that nobody can voice, and block chords on
every downbeat. Four changes, anchored on **partido alto** at the owner's
direction.

**A vocabulary instead of a pitch-class count.** Candidates are now the
diatonic sevenths of the detected key plus the borrowings that occur (`V7` and
the major subtonic in minor), rather than "the four loudest pitch classes".
Every chord is nameable and voiceable by construction.

**A cost for changing** — `chords.py` decodes the whole piece with Viterbi:
each candidate is scored on how well it explains the bar, and switching carries
a penalty. A walking bass no longer drags the harmony with it, because one bar
of weak evidence cannot outweigh the cost of moving and moving back.

**A root bonus, which turned out to be the missing piece.** Membership alone
cannot distinguish `Cmaj7` from `Fmaj7` in a bar of C and E — both contain both
— so the chord was chosen by whatever the penalty happened to be holding.
Weighting a candidate whose root *is* the bass note took root accuracy from 45%
to 83% and grounding from 78% to 96% in one change.

The two constants are in tension and were **swept together over the corpus**,
not guessed: the bonus pulls the harmony onto the bass, the penalty holds it
still. `CHANGE_PENALTY = 0.35` sits where root accuracy stops improving and
harmonic rhythm is still 2.7 bars per chord.

**Rootless voicings and a comping grid.** `comping.py` renders third, fifth,
seventh and ninth, placed as a unit and shifted by octaves to fit — built
note-by-note against a ceiling instead, a chord whose lowest tone sat high lost
its upper notes and came out a bare dyad beside a neighbour with four. The
rhythm is a data-driven sixteenth grid, so the pattern is one editable string.

| | before | after |
|---|---|---|
| Root exact | 100%* | 81% |
| **Root grounded** | — | **96%** |
| **Bars per chord** | **1.0** | **2.7** |
| Chord names | `Dpower/C` | `Dm7 B♭maj7 Fmaj7` |

\* The old 100% was tautological — detector and metric read the same evidence
(**C25**). It also actively conflicted with the music: holding a chord while
the bass walks beneath it *should* score as a bar-by-bar miss. **`root_grounded`
replaces it** — is the root we played sounding anywhere in that bar of the
source? A held chord passes; C24's invented bass scores 56% against the
arranger's 96%.

**`bars_per_chord` is the metric whose absence allowed the first pass.** An
arrangement scored perfectly on everything measured and still read as
agitated, because nothing measured how long the harmony held. Detected
progressions now read as music — Bubbly Clouds resolves to `Cmaj7 Dm7 G7
Cmaj7`, a ii-V-I the detector was not told to look for.

⚠️ **The partido alto grid needs a musician's ear.** The mechanism is sound and
the pattern is one string in `comping.py`; the specific cell is my best reading
and I cannot verify it by listening. `BOSSA_COMP` is kept alongside as the
sparser eighth-note alternative.

**The melody is deliberately untouched**, and that is a decision rather than an
omission: it is the tune, the source already has it right, and it is the part
played live — phrasing belongs to the player, not the tool. Worth revisiting
only if the busyness of the source fights the "chill" target in practice.

### C27 — Phase B1/B2: giving the arrangement a shape

2026-09-16. The Phase A output had defensible chords and still read as
"a bunch of bossa chords in a ii-V-I" — repetitive, a harmonisation rather than
an arrangement. Measured, the charge was exact:

| | bars | comping rhythms | bass patterns |
|---|---|---|---|
| Dr Wily | 112 | **2** | **1** |
| Bubbly Clouds | 88 | **2** | **1** |

A loop. Structural, not a tuning problem: the renderer applied the same two-bar
cell to every bar forever and the bass figure never varied. No improvement to
the chords could have fixed it, because nothing in the system knew that bar 97
and bar 1 were the same music.

**`form.py` — what repeats.** Bars are grouped into phrases and phrases sharing
a chord sequence share a label. Derived from the harmony rather than the melody,
because the chord sequence is what defines a section and is the most reliable
thing we compute. The forms it finds are real:

```
Vampire Killer   A B C A  A B C D
Dr Wily          A B A B C D A B A B C E F G   ×2
```

Dr Wily's 112 bars are 56 played twice — which the renderer had no way to know
and therefore no way to vary.

**`comping.py` — something to vary.** Density variants of the same cell (2, 5
and 7 attacks a bar) rather than different patterns, so the groove survives the
variation; and four bass treatments — `root-fifth`, `walk` (semitone approach
to the next root), `pedal`, `anticipate`. A plan saying "thinner here" is
meaningless against a renderer that can only do one thing.

**`plan.py` — the seam.** Every per-bar decision as a separate object, between
"what the chords are" and "what the parts do". The renderer stays dumb and
reliable, the plan carries every choice, and **the plan is small enough for a
model to produce and cheap enough to check before use** — which is the whole
point of the split.

What fills it today is a fixed policy: vary on repeats, lead into chord changes
at phrase ends, allow a pedal on a third hearing. **It is a stand-in that
exists to prove the mechanism and give the model something to beat**, not
because rules are the destination. A policy cannot know that a section has been
heard twice and wants lifting, or that a melody has gone quiet — those are
judgements, and they are why the plan is an object rather than a flag.

| | before | after |
|---|---|---|
| Comping rhythms | 2 | **6** |
| Bass patterns | 1 | **6–10** |
| Root grounded | 96% | 96% |
| Bars per chord | 2.7 | 2.7 |

Variation up, harmony untouched — which is the right shape for the change, and
what having metrics in place makes visible.

**Next is B3**, the plan arranger: the model reads the form, the chords and the
melody and produces the plan, with substitutions validated against the detected
chord so they cannot drift (**C24**). Its output is a handful of tokens a bar —
roughly 800 for Dr Wily against ~50,000 for note-echo.

### C28 — Phase B3: the model plans, the library plays

2026-09-16. The destination **C5**(b) described, reached by the route **C24**
forced: the model is asked for judgement and never for the root.

It reads the key, the harmony bar by bar, the form, and how often each phrase
has been heard. It returns a **plan** — `density` and `bass` per phrase, drawn
from closed sets, plus optional chord substitutions on individual bars. The
library renders it.

**The economics are the argument.** Describing Vampire Killer takes **~130
tokens**; the schema is 152; the response is a few hundred. Note-echo needed
10,392 tokens of prompt and ~14,000 of output for the same piece, and Dr Wily
~50,000. Decisions are per *phrase* rather than per bar — 28 phrases against
112 bars on the longest score, and where the decisions belong musically anyway.

**Three defences against C24, by construction rather than by instruction:**

- `density` and `bass` are **enums**. There is no malformed answer to give.
- A substitution must **share at least two pitch classes** with the chord it
  replaces. Permissive on purpose — a tritone substitution shares only the
  third and seventh, a relative minor three tones, and those are what
  substitutions are *for*. What it rejects is a harmonically unrelated chord
  that sounds fine alone and is in the wrong key.
- The root is never generated. It comes from the source, as in **C25**.

**Degradation is graded rather than total.** A rejected substitution costs that
bar its reharmonisation; a phrase the model ignores falls back to the fixed
policy; a model outage falls back to the whole deterministic arrangement, which
is a complete and harmonically sound score. Nothing about a failure produces an
empty staff — the failure mode C24's note-echo had, where four bars simply
vanished.

Leading into a chord change stays a **rule**, not a choice: it depends on what
the next bar does rather than on taste, and rules should keep the things that
have right answers.

Tested against the failure modes rather than the happy path: an invented
`F#maj7` over `Dm7` is rejected and never reaches the score, a relative-major
`Fmaj7` is accepted, a model outage still yields a playable bass part, and a
sparse phrase renders differently from a busy one.

**Live run, 2026-09-16, `llama3.1:8b`.** The whole corpus arranges in **53
seconds** — one request per score, 6–20s each, against 577s for 32 bars of
note-echo.

The judgements are musically literate. On Vampire Killer's `A B C A A B C D`
the model gave the A phrases `normal → sparse → normal`, thinning the first
repeat and returning for the third — the contextual decision the fixed policy
is structurally unable to make, since it only knows *how many times* a phrase
has been heard, not what to do about it. It also proposed one substitution,
`B♭maj7 → Fmaj7` at bar 10, which passed validation.

| | policy | plan |
|---|---|---|
| Distinct bass patterns | 6–10 | **9–17** |
| Comping rhythms | 6 | 6–8 |
| Root grounded | 88–100% | **unchanged** |
| Bars per chord | 1.8–4.0 | **unchanged** |

Bass variety up as much as 70%; **the harmonic metrics do not move at all**,
which is the result the design was built for — the model changes how the piece
is played and cannot touch what it is.

⚠️ **Substitutions are the weak spot: zero proposed across all five scores** on
the corpus run, against one in an earlier single run. The prompt asks for them
"sparingly" and the model has read that as "never". Nothing is broken — the
validation path is exercised and works — but the reharmonisation half of the
idea is not yet earning its place, and that is a prompt problem rather than an
architectural one.

`COMPOSER_ARRANGER=plan` opts in; **`deterministic` stays the default**, since
it needs no model running and produces a complete, harmonically sound score on
its own.

### C29 — Reharmonisation: offering a menu instead of asking for invention

2026-09-16. **C28** left the reharmonisation half of the plan arranger unused —
zero substitutions proposed across the corpus. The prompt asked for them
"sparingly" and the model read that as "never".

Firmer wording was not the fix. `reharmonise.py` now derives the valid options
— relative major/minor, secondary dominant, tritone substitution, the ii that
sets up a ii-V — and the model **chooses from them**. Same division as
everywhere else here: the library knows what is possible, the model decides
what is good.

**A trap found on the way in, and worth knowing about beyond this project:
music21 silently misparses `b` flats.** `ChordSymbol("Db7")` returns D, F#, A,
C — a D7 — and `Bbmaj7` is rejected outright. Only the `-` spelling is safe. A
wrong chord that *parses* is far worse than one that fails, and the model can
emit either spelling, so `normalise_figure` rewrites the accidental before
anything reads it.

**The menu had to become authoritative over the relatedness check.** A tritone
substitution shares exactly one pitch class with the chord it displaces, so the
two-shared-tones rule from **C28** would reject a chord the generator had just
derived correctly. On-menu figures are now accepted outright; the shared-tones
test remains the fallback for anything nobody offered.

**Two failures of restraint, in opposite directions.** With `substitutions`
optional in the schema, the model omitted the key on all five scores — a
constrained decoder takes the shortest legal path, and an absent key is shorter
than a considered one. Making `turnarounds` **required**, with one answer per
opportunity and `"none"` as an explicit option, flipped it to choosing at
*every* opportunity. Narrowing the menu fixed most of that:

| | offers | chose | declined | kinds |
|---|---|---|---|---|
| Vampire Killer | 2 | 1 | 1 | relative |
| Bubbly Clouds | 19 | 10 | 9 | **tritone ×8**, ii-of-next ×2 |
| Green Greens | 3 | 3 | 0 | secondary-dominant ×2, tritone |
| Dr Wily | 16 | 16 | 0 | relative ×16 |

Bubbly Clouds declining nine of nineteen and reaching for the tritone
substitution eight times is the right bossa instinct. **Dr Wily choosing at
every opportunity and always the same kind is not judgement, it is
pattern-matching** — an 8B model answering each item independently rather than
weighing the piece. Recorded as a limitation rather than smoothed over.

**A musical gap the model exposed.** It kept picking `G7 → Dm7`: replacing a
dominant with the ii that precedes it, which trades a cadence for an approach
and weakens the very moment a turnaround exists to strengthen. A bar that is
already the dominant of what follows is now offered **only** the tritone
substitution, which keeps the dominant function and changes the colour. The
model found that hole by walking into it, which is a decent argument for
letting it choose from a menu rather than constraining it to the safest option.

---

## Decisions

Four. Each has a recommendation and the reason. Record whichever you take in an
ADR in the platform repo, alongside the D1 ADR that 07 §6.3 already owes —
D-A and D-B are amendments to D1, not separate subjects.

### D-A — Where the inference runtime runs on the PC _(blocks P2)_

**DECIDED 2026-09-13 — (c): the dedicated Linux boot, with inference
containerised. Not a cluster node.**

| Option | What it costs |
|---|---|
| **(a)** Ollama as a native Windows service under NSSM | Coexists with the MIDI service and reuses the tooling already on that box. But it leaves a desktop OS holding the GPU, and gives up containers on the one host where they are cheap. |
| **(b)** WSL2 + Docker Desktop, CUDA passthrough | Containers *and* coexistence — but an extra virtualisation layer between the GPU and the model, and WSL2's NAT means the LAN cannot reach a container port without `netsh portproxy` or mirrored networking: a fiddly, silently-breaking dependency underneath a service the cluster calls. |
| **(c)** Dedicated Linux boot, Ollama containerised | **Chosen.** All of the GPU, containers natively, and the standard Ansible path. Cost: MIDI is offline while Linux is up (**C6**, accepted), and the host must be kept out of the cluster deliberately rather than by accident. |
| **(d)** Join the cluster as a GPU node | Rejected by 07's D1(a). **(c)**'s costs plus mandatory multi-arch builds for every cluster image, forever. |

Two reasons decided it, and both are stronger than the argument for (a):

- **The SSD is already there and empty**, installed and partitioned for exactly
  this. (a) leaves it unused and puts the model cache on the Windows volume.
- **A booted Windows desktop holds a standing GPU baseload.** The compositor,
  the browser, anything with hardware acceleration — call it 0.5–1 GB of VRAM
  that is simply gone, plus non-deterministic contention during a run. On an
  **8 GB card that is 6–12% of the budget**, and it is the margin that decides
  whether an 8B model runs at a comfortable `num_ctx` or spills layers to CPU
  and loses an order of magnitude in speed (**C4**). A headless Linux boot
  hands essentially the whole card to the model, and makes the VRAM arithmetic
  in P1 predictable instead of dependent on what else is on screen.

That second point also improves P1's numbers directly: more headroom for
`num_ctx` means larger chunks (**C5**), and it may put a larger model or a
higher quantisation within reach — which is worth re-testing in the bake-off
(**D-C**) once the host exists.

#### What this decision does *not* reopen

**ADR-0011 stands. The PC does not join the cluster.** It becomes an
Ansible-managed Linux host that happens to sit on VLAN 20 and serve HTTP — the
same relationship the cluster has with OPNsense or the console Pi, not the
relationship it has with a worker.

This needs stating explicitly in the ADR, because the platform repo's inventory
currently makes the opposite assumption. `ansible/inventory/lab/hosts.yml`
scaffolds an empty `gpu` group with the comment *"Populating this group makes
multi-arch image builds mandatory the same day, so it is a deliberate decision,
not a config edit."* That is true only of a host that runs cluster workloads.
Populating it with a non-kubelet host does not make multi-arch mandatory,
because no image the cluster schedules will ever land there. **Amend the
comment in the same PR**, or the next person to read it — including you —
concludes ADR-0011 was quietly reopened.

Two mechanical consequences follow from "not a cluster node":

- The GPU host goes in the `gpu` group and **must not** end up in `cluster`.
  `group_vars/cluster.yml` sets `kubelet_node: true` and the kube prereq
  modules and sysctls; inheriting those on this host would install a kubelet
  that never joins anything.
- x86 is fine. The only images it runs are its own (Ollama's official image is
  multi-arch upstream regardless), and nothing in `apps/` is scheduled onto it.

#### What it changes downstream

- **Containerisation now pays.** Your original preference was right for a Linux
  host — `nvidia-container-toolkit` plus a pinned `ollama/ollama` image digest
  is a well-trodden path, and it buys the same reproducibility and image
  pinning every other workload here gets. Manage it as a Compose file or a
  systemd unit rendered by Ansible, not by hand.
- **The reverse proxy (D-B) becomes a second container** alongside it, which is
  what makes "expose only the inference endpoints" a config file rather than a
  service to write.
- **Salvage before deleting.** `infra/ansible/playbooks/setup-gpu-node.yaml` is
  deleted in the working tree but not yet committed. Its kubeadm-join and
  device-plugin halves are correctly dead — but its **NVIDIA driver install,
  `nvidia-container-toolkit` setup and containerd runtime configuration are
  directly reusable** in P2's platform role. Recover it with
  `git show HEAD:infra/ansible/playbooks/setup-gpu-node.yaml` before **C8**'s
  deletion lands, and port those tasks rather than rewriting them.
- **`infra/README.md`'s storage and partitioning section survives the delete.**
  The `/var` sizing for the model cache and the boot-order guidance are the one
  genuinely useful thing in that file. Move them into the platform role's
  README in P2, then delete the file in P4 (**C8**).

### D-B — Does the AI API need its own repo? _(shapes P2)_

**DECIDED 2026-09-13 — no new repo, and no new service. The platform repo owns
the PC's preparation, and Ollama's own HTTP API is the contract.**

The reasoning, in the order it matters:

**There is already an API.** Ollama serves a stable HTTP contract on 11434
(`/api/chat`, `/api/generate`, `/api/tags`). A bespoke service in front of it,
today, would be a proxy with one consumer.

**"Shared resource" is currently one consumer.** Queueing, fairness and
priority are real problems when two tenants compete for 8 GB of VRAM. Composer
is the only tenant. Build the scheduler when there is something to schedule; a
queue with one producer is a queue you are maintaining for free.

**This is exactly the MIDI precedent.** Platform prepares the PC, the app repo
builds the app, the contract between them is plain HTTP over VLAN 20 with a
NetworkPolicy allow-pair and a firewall rule. Composer's inference path is the
same shape as `midi → 192.168.20.210:5001`, and the cluster already knows how
to express it. Consistency here is worth more than novelty.

**The one genuine argument for a service in front, and the cheap answer to
it:** Ollama has *no authentication*, and its API includes model management —
anything that can reach 11434 can `POST /api/pull`, `POST /api/create` and
`DELETE /api/delete`, not just run inference. Exposing the port to the cluster
exposes the admin surface with it.

With one consumer pinned by a NetworkPolicy `podSelector`, the blast radius is
"the composer pod could delete a model", which is acceptable. The cheap
mitigation is not a new service: it is **a reverse proxy on the PC — a few
dozen lines of Caddy or nginx config — that allows only `POST /api/chat` and
`/api/generate`, requires a bearer token from Vault, and refuses everything
else.** That config lives in the platform repo's Ansible role for the GPU host,
next to the firewall rules it belongs with.

**Revisit when, not if.** A real gateway service earns its own home when a
second consumer appears, or when the routing decision becomes interesting —
which is precisely what the Bedrock backend (**D-D**) introduces. When that
happens, put it in `platform/apps/`, not in a new repo: a new repo costs a CI
pipeline, a release process, a ruleset, a Dependabot config and a place for
documentation to go stale, and buys separation that a directory already
provides.

**The assumption underneath all of this, stated so it can be challenged: the
backend-routing decision belongs in composer, not on the PC.** Composer already
has to choose between Ollama and Bedrock for **D-D**'s comparison. Putting that
choice behind an HTTP hop on the GPU host would split one decision across two
machines and make the comparison harder to instrument, not easier.

### D-C — Which model _(shapes P1)_

**DECIDED 2026-09-13 — do not pick a model yet. Pick it with a bake-off, in
P1, against the eval set. Pull one provisional model now so P2's gate can
pass.**

The decoding configuration matters more than the model does, and **C1** shifted
the criteria further: with chunks of hundreds to low-thousands of tokens rather
than whole 9–35k-token scores, **context window largely stops being a
differentiator**. Schema adherence under constraint, instruction-following on
"modify these fields, preserve those", and throughput at chunk size are what
decide it — and under **C5**(b) tool-calling reliability becomes dominant,
since the model's job shifts to emitting small structured decisions.

**D-A** also moved the goalposts favourably: a headless boot hands back the
0.5–1 GB a desktop session was holding, so a larger model or a higher
quantisation may now be in reach. Make that a bake-off axis rather than
assuming the 8B/Q4 shape.

**For P2's gate**, pull a current strong 8B instruct model as an explicitly
provisional placeholder, pinned by digest in the platform role. Replacing it
after the bake-off is a one-line change. Do not spend time choosing it — the
bake-off is the decision; this is scaffolding.

The working tree moved `llama3:8b` to `llama3.1:8b`. That is probably a small
improvement and it is not the lever. Two changes dominate any choice of
open-weights model at this size:

1. **Constrain the output grammar.** Ollama's `format` parameter accepts a JSON
   schema and constrains decoding to it. That removes the entire class of
   "model returned prose / fenced markdown / almost-JSON" failures by
   construction, rather than by prompt-begging in capital letters. Generate the
   schema from `intermediate.py` so **C2** cannot recur.
2. **Set `num_ctx` deliberately** (**C4**), and size the chunks (**C5**) to fit
   it with VRAM headroom.

With those in place, evaluate candidates on what actually matters here:

| Criterion | Why it decides this |
|---|---|
| Fits 8 GB VRAM with KV headroom at the chosen `num_ctx` | Partial CPU offload costs an order of magnitude in speed |
| Reliable structured output under a JSON schema | The whole interface is JSON in, JSON out |
| Instruction-following on "modify these fields, preserve those" | This is the actual task |
| Tool/function calling | Only if you take **C5**'s second reshape |
| Tokens/sec at the chosen chunk size | Determines whether a 32-bar tune arranges in seconds or minutes |

Strong 7–9B candidates as of early 2026 include the Llama 3.1, Qwen 3, Mistral
and Gemma 3 instruct families — but **check `ollama.com/library` at the time you
run the bake-off** rather than trusting that list; this class of model turns
over every few months and the plan should not pin it.

The bake-off is cheap once the eval set exists: same prompts, same schema, same
chunks, three or four models, score on note-count fidelity, offset validity,
schema-valid rate and wall-clock. That is a half-day, and it produces a number
rather than an opinion.

**`services/training/` stays parked — confirmed 2026-09-13.** Fine-tuning
before an eval set exists is optimising without a target. The reason to keep it
rather than delete it is that the eval set **P1** builds is exactly what it
would need, so it becomes viable later rather than never.

### D-D — Claude subscription, or Bedrock _(shapes P5)_

**DECIDED 2026-09-13 — the subscription is dropped; Bedrock stays as a
stretch. These are not two versions of the same option.**

**On the subscription:** a Claude Pro/Max subscription covers interactive use of
Claude — claude.ai and Claude Code. It is not a programmatic API credential, and
there is no supported way to point a long-running unattended service at it. The
supported credentials for a service are an Anthropic API key (billed per token,
separate from the subscription), or a cloud provider's Claude offering —
Bedrock, Vertex, Foundry. So: the subscription keeps earning its keep as the
tool you use to *build* composer, and is not part of composer's runtime.

**On Bedrock**, the path is short because the pieces exist (**C10**):

- The Python SDK's Bedrock client — `AnthropicBedrockMantle(aws_region=...)`,
  from the `anthropic` package — exposes the same `messages.create` surface as
  the first-party client. Bedrock model IDs carry an `anthropic.` prefix
  (e.g. `anthropic.claude-opus-5`).
- Credentials come from IRSA: a fourth `aws-cluster-oidc-role` instance, trust
  scoped to `system:serviceaccount:composer-dev:composer`, policy limited to
  `bedrock:InvokeModel` on the specific model ARNs. No stored secret.
- Bedrock is partner-operated with its own pricing — check the Bedrock pricing
  page for the model you choose rather than the first-party rates.

**Why Bedrock and not simply the Anthropic API.** An API key would be simpler
to set up, but it means a stored secret instead of federated identity and
exercises none of the AWS skills this programme is about. Bedrock is preferred
*specifically because* it uses the IRSA pattern — which is itself one of the
three public write-ups 07's Phase 11 wants ("IRSA on a cluster that is not
EKS"). Recorded so the choice does not read as arbitrary later.

**The deliverable is the comparison, not the backend.** Both backends sit behind
the same interface, run against the same eval set, and produce a table: cost per
arrangement, latency, quality score, and what each costs in control and
operational surface. 07's Phase 11 already names this write-up as the highest
value item in the programme, and it only exists if both backends are measured
on the same inputs — which is the third separate time the eval set has turned
out to be the dependency. Build it early rather than when convenient.

If the local model ends up good enough, Bedrock is a learning and portfolio
exercise rather than a product need. That is a good enough reason — it is kept
as a stretch on exactly that basis — but it should be named rather than
quietly reframed as necessity.

⚠️ **If "useful for training later" means Bedrock's own fine-tuning**, check
the serving path before planning on it: a Bedrock *custom* model has
historically required **Provisioned Throughput** to invoke, and
`bedrock:CreateProvisionedModelThroughput` is exactly what
`DenyManagedServicesWithFourFigureAnnualCost` denies (**C10**). Bedrock's
custom-model options have moved more than once, so verify the current state
rather than trusting either this note or a memory of it — but do it before the
fine-tuning work depends on it. On-demand `InvokeModel` against a *base* model
is unaffected either way.

Add a client-side budget when the Bedrock path lands: a per-request token
ceiling and a daily spend cap in composer itself. No SCP can do this for you.

### D-E — Does composer's parsing belong on the PC rather than the cluster?

Raised 2026-09-13: the Pi nodes have 2 GB each and `music21` is reputed to be
memory-hungry, so would composer be better as a container on the PC next to the
model, where there is far more RAM?

**Answer: no. Measured, `music21` is not the constraint — not on memory, not on
CPU.** Peak RSS and wall-clock for the full deterministic half, per score:

| Score | Measures | Parse cost | **Peak RSS** | **Wall clock** |
|---|---|---|---|---|
| Vampire Killer | 32 | 6.8 MB | 80.5 MB | 0.05 s |
| Wicked Child | 51 | 6.7 MB | 82.5 MB | 0.06 s |
| Bubbly Clouds | 88 | 7.8 MB | 84.4 MB | 0.09 s |
| Green Greens | 43 | 8.0 MB | 84.4 MB | 0.09 s |
| **Dr Wily Stage 1** | **112** | **14.6 MB** | **91.2 MB** | **0.15 s** |

Three things follow:

- **The fixed cost dominates.** Importing `music21` costs 56 MB; the largest
  score adds 14.6 MB on top. That import is paid once per process and shared
  across concurrent requests, so per-request marginal memory is ~15 MB, not
  ~90 MB. Against the dev LimitRange ceiling of 512Mi this is comfortable, and
  a realistic pod peak including FastAPI and uvicorn lands around 150–200 MB.
- **CPU is not the issue either.** 50–150 ms on an M-series Mac. Even assuming
  a Pi 5 is several times slower on single-threaded Python, the deterministic
  half stays under a second — against an inference step measured in tens of
  seconds to minutes. **Parsing is well under 1% of the request.**
- **Payload locality is not an argument.** The IR is 20–78 KB of JSON. Moving
  that across a LAN is free; co-locating it with the model saves nothing
  measurable.

And the costs of moving composer to the PC would be real:

- It reopens **D1(b)** and contradicts **ADR-0012**.
- It forfeits everything the cluster provides — Argo CD reconciliation,
  NetworkPolicy, ExternalSecrets, quota, HTTPRoute and TLS, restart policy —
  and replaces them with hand-rolled deployment on a single unmanaged host.
- Most importantly, **it makes the whole service unavailable whenever the PC is
  booted to Windows**, not just the inference step. Under **D-A** an offline PC
  currently degrades composer to a clear error on one step; this would take the
  API down with it.

What *should* be measured before P3 closes: peak RSS on **arm64**, since these
figures are from x86 macOS, and the same figures after `chordify()` lands
(**C11**), which is the one change likely to move them. Size the tenant quota
from that, per the quota's own instruction to raise it in a PR with a reason.

The real bottleneck in this pipeline is inference, and inference is already on
the PC. That is exactly what **D1(b)** put there.

---

## Sequence

Roughly **42 hours** to the minimum (P0–P4), plus the stretches. The ordering
principle: everything that can be proven on a laptop is proven before anything
touches the PC, and the PC is proven before anything touches the cluster. Each
phase has a gate.

### P0 — Prove the deterministic half on a real score _(~4h, no infrastructure)_

The whole phase runs on the Mac. No GPU, no LLM, no cluster.

- [x] ~~Put four real piano scores in `examples/input/`~~ — **done
      2026-09-13**, five chiptune transcriptions. Settle the licensing question
      before P4 (**C1**)
- [ ] Add the two kinds still missing: a **structural stress case** (repeats
      with first/second endings, pickup bar, key change) and one **deliberately
      out-of-domain texture** (Alberti bass or contrapuntal), so the splitter's
      boundary is a known fact rather than a surprise. `music21`'s bundled
      corpus is the zero-friction source for the second
- [x] **Fix the splitter (C11)** — **done 2026-09-13.** Voice-aware iteration
      plus `chordify()` harmony that subtracts pitches the melody and bass
      already claimed. Reconciliation gate: **0 pitches absent across all five
      scores**
- [x] **Fix the upload path (C12)** and **C13**'s event-loop fix — **done
      2026-09-15**. Content sniffed from magic bytes, 400 on junk, 413 over
      the size cap, `BackgroundTask` cleanup, and every synchronous stage moved
      off the event loop with `asyncio.to_thread`. Verified over HTTP: all five
      corpus scores return 200 where they previously failed 100% of the time,
      and no temp files are left behind
- [x] Fix the two metadata defects (**C1**) — **done 2026-09-13.** `title`
      falls back through `movementName` and strips the score suffix music21
      leaves on a filename-derived title; `key` is a name, with the written
      signature reported separately as `key_signature` since analysis and
      signature genuinely disagree on this corpus
- [x] **Fix the drum generator (C14)** — **done 2026-09-13**, and pin
      `music21` so the next breaking change is caught rather than absorbed
- [x] Run `parse_score → split_voices → to_intermediate → from_intermediate →
      assemble_score` with **no LLM step at all** — **done 2026-09-13**, all
      five produce four-part scores in `examples/output/`
- [ ] **Open those outputs in notation software and listen.** The mechanical
      gate passes; whether the result is *musically* coherent is the part no
      script can answer, and it is the last thing standing between P0 and P1
- [ ] Record what the round-trip loses (**C1**). Decide per item: accept,
      fix in `musicxml-tools`, or carry
- [x] ~~Record the IR size in tokens for each score~~ — **done 2026-09-13**:
      9k–35k, table in **C1**. Re-measure after the C11 fix
- [ ] Fix the schema mismatch in the prompt's worked example (**C2**), or
      delete the example until P1 generates it
- [ ] Listen to `generate_bossa_drums` output on its own. It is the one part
      of the arrangement with no LLM in it and it either sounds like bossa or
      it does not — and until 2026-09-13 it had never produced a note
      (**C14**), so this has genuinely never been heard

**Gate — MET 2026-09-15.** every score in the corpus completes the deterministic round-trip
with **no unexplained note loss** — source-to-split counts reconcile, and any
remaining difference is attributable to chord decomposition rather than to
dropped voices; the losses are written down; the IR token size for the largest
is a known number; `/arrange` accepts an `.mxl` upload.

### P1 — Make the LLM contract reliable _(~10h, still no cluster)_

Runs against Ollama on whatever machine is convenient — the Mac is fine for
correctness work; the PC only becomes necessary for the speed measurements.

- [x] **Generate the JSON schema from `intermediate.py`** and pass it as
      Ollama's `format` (**D-C**) — **done 2026-09-15**,
      `musicxml_tools/schema.py`. One definition drives three uses: constrained
      decoding, response validation, and the prompt's worked example. A test
      asserts the example still conforms, which is what stops **C2** recurring
- [x] **Set `num_ctx` explicitly and assert the payload fits** (**C4**) —
      **done 2026-09-15**. `PayloadTooLarge` is raised rather than letting
      Ollama truncate in silence; all five scores are currently refused, which
      is the correct answer and makes chunking's necessity visible
- [x] **Halve the payload for free** — the prompt serialised the IR with
      `indent=2`, which roughly **doubles** its token count for no benefit.
      Compact separators cut every score by ~48% (Dr Wily 42,068 → 21,666)
- [x] **Chunk by section** (**C5**) — **done 2026-09-15**,
      `musicxml_tools/chunking.py`. Bar-aligned, eight bars per request,
      offsets rebased to zero, each chunk independently schema-valid. Split and
      merge round-trip **exactly** at every chunk size from 1 to 16 bars.
      Chunked by section but **not** by part: harmony and bass decisions depend
      on what the melody is doing in those bars, and voicing is most of the
      judgement being asked for
- [x] **Fix the fallback** (**C3**) — **done 2026-09-15.** Catches
      `KeyError`/`TypeError` (an Ollama error payload has no `message` key),
      validates **shape** against the schema rather than key presence, and
      returns a `TransformResult` carrying per-chunk outcomes. `/arrange`
      reports them as `X-Composer-Chunks-Transformed` / `-Total` headers and
      **returns 502 when nothing could be arranged** — a total failure can no
      longer arrive as a well-formed 200. A failed chunk keeps its original
      bars, so one bad section costs eight bars rather than the piece
- [ ] Build the eval set — the P0 scores plus expected properties: note count
      preserved within tolerance, offsets monotonic and within the bar, pitches
      in range per part, schema-valid rate, wall-clock. Small and mechanical
      beats large and subjective
- [ ] Run the bake-off (**D-C**) and record the winner and the numbers

**Gate:** a real score arranges end to end with no manual intervention; the
schema-valid rate is ≥ 95% across the eval set; a fallback is visible in the
response when it happens. This is the point at which composer does the thing
it exists to do — everything after it is about where it runs.

### P2 — Platform prepares the PC _(~10h, platform repo)_

Nothing in this phase lands in this repo. It is listed here because it is the
other half of the same job, and it blocks P3.

- [ ] Write the ADR: 07's D1 ADR, extended with **D-A** and **D-B** — and
      saying in as many words that the GPU host is Ansible-managed and **not a
      cluster node**, so ADR-0011 is untouched
- [ ] Ubuntu is already installed on the dedicated SSD. **Verify the
      partitioning against the model cache**, which is the one thing the
      install decides that is expensive to change later: several models at
      4–8 GB each, plus container images, all landing under `/var`. If `/var`
      is small, move the Ollama volume to a larger filesystem now rather than
      discovering it mid-pull
- [ ] **Boot management — make Linux the default and Windows a one-shot.**
      The convenient end state is that the PC powers on into Linux and is ready
      to serve inference with nobody at the machine; hopping to Windows for a
      stream is a deliberate, reversible act:
      - `GRUB_DISABLE_OS_PROBER=false` in `/etc/default/grub` (Ubuntu disables
        `os-prober` by default since 22.04, so the Windows entry is missing
        until you turn it back on), then `update-grub` to pick up the Windows
        Boot Manager
      - `GRUB_DEFAULT=saved` + `GRUB_SAVEDEFAULT=true`, with Linux as the
        saved default and a short `GRUB_TIMEOUT` so a headless boot proceeds
        on its own
      - `grub-reboot "Windows Boot Manager" && reboot` for a **one-shot** hop
        to Windows that reverts to Linux on the next boot — this is the piece
        that makes it convenient, and it is drivable over SSH, so it becomes
        an Ansible playbook and a `make` target rather than a trip to the
        machine
      - Confirm the UEFI boot order points at GRUB (`efibootmgr -v`), and note
        that **Windows updates periodically reassert Windows Boot Manager at
        the top** — `efibootmgr -o` puts it back, and knowing this in advance
        stops it looking like a broken GRUB install
      - Disable Windows **Fast Startup**. It hibernates rather than shuts
        down, which leaves the ESP and NTFS volumes in a state that makes
        dual-boot behave unpredictably
      - Pair with Wake-on-LAN (**C6**) and the whole sequence is: magic packet
        → Linux → serving. No human, no boot menu
- [ ] **Populate the `gpu` inventory group** with the host at
      `192.168.20.210`, and **amend the group's comment** so it no longer
      implies multi-arch is now mandatory (**D-A**). Confirm the host does not
      inherit `group_vars/cluster.yml`
- [ ] **Fix the `midi` group's stale `ansible_host` and VLAN comment**
      (**C7**) — same inventory file, same PR, one entry per boot of one
      machine
- [ ] A GPU-host role in `platform/ansible/roles/`: NVIDIA driver,
      `nvidia-container-toolkit`, containerd runtime config — **ported from the
      salvaged `setup-gpu-node.yaml`, not rewritten** (**D-A**) — then Ollama
      as a pinned container with the model cache on a host volume under `/var`.
      The existing `common` and `hardening` roles apply to this host as they do
      to any other; `kube_prereqs` and `kube_worker` do not
- [ ] Bind Ollama to the LAN interface (`OLLAMA_HOST`), and put the reverse
      proxy container in front of it (**D-B**): inference endpoints only,
      bearer token from Vault, everything else refused. Ollama itself should
      not be reachable except through the proxy
- [ ] `ufw` on the host, scoped to the cluster CIDR, plus an OPNsense rule for
      the cluster → PC path — registered in `docs/01-network-validation.md`
      **and** in Phase 7's egress allowlist. A path opened after egress control
      and not registered with it quietly undoes Phase 7
- [ ] Decide the boot and power story (**C6**): BIOS boot order, whether
      Wake-on-LAN is worth wiring up, and what the runbook says when composer
      reports the host unreachable
- [ ] Measure the VRAM headroom with the desktop absent, and feed the number
      back into P1's `num_ctx` and chunk sizing. This is the number **D-A** was
      chosen for — confirm it rather than assume it

**Gate:** `curl` from a cluster pod reaches the proxy and gets a completion;
the same `curl` without the token is refused; `/api/delete` is refused *with*
the token; `nvidia-smi` shows the model resident in VRAM with no desktop
session present, and the measured free VRAM is written down.

### P3 — Composer in the cluster _(~10h, platform repo + this one)_

07 §6.3, now unblocked.

- [ ] `policy/tenants/composer.yaml` — namespaces, quota, LimitRange,
      default-deny, tenant RBAC. Copy the eightbitsaxlounge tenant. Merge and
      let it sync **before** any workload. Size the quota from the measured
      footprint, and note that composer's requests are larger than 8BSL's
      per-service — `music21` parsing is memory-hungry and the 3-node cluster
      has ~6 GB total
- [ ] `apps/composer/dev/` — Deployment, Service, ExternalSecret for the proxy
      token, and the NetworkPolicy egress allow-pair to the PC. `musicxml-tools`
      ships inside the composer image, not as a second Deployment; it is a
      library, not a service
- [ ] Image to `ghcr.io/nineteenseventytwo/composer`, arm64, pinned base image
      by digest. **Build it on arm64 and test it there** — `music21` on arm64
      Linux is the first thing likely to surprise you
- [ ] An `HTTPRoute` + Gateway listener + Certificate + Unbound override, if
      composer gets a UI. Defer if the API is enough for now
- [ ] Promote to `prod/` once dev holds

**Gate:** composer is `Synced/Healthy` in dev; a score uploaded to the
in-cluster endpoint returns an arrangement produced on the PC's GPU; the
NetworkPolicy is the thing permitting it, provably — remove it and watch the
call fail.

### P4 — Repo hygiene _(~4h, this repo)_

Do it with P3, not after. Every item has a worked precedent in the
eightbitsaxlounge migration.

- [ ] Transfer the repo to the `nineteenseventytwo` organisation (**C9**).
      First, before any `image:` points at GHCR, or you repoint them twice
- [ ] Ruleset on `main`; secret scanning, push protection, Dependabot;
      `.github/dependabot.yml`
- [ ] Rewrite the three workflows: build/test on hosted runners
      (`ubuntu-24.04-arm`), publish to GHCR. **Delete `deploy.yaml`** — Argo CD
      deploys now
- [x] **Delete `infra/`** (**C8**) — **done 2026-09-16.** Both `k8s/`
      (ADR-0012) and `ansible/`. The salvage material is recoverable rather
      than lost: `git show 8fdf2da:infra/ansible/playbooks/setup-gpu-node.yaml`
      has the NVIDIA driver and container-toolkit tasks, and
      `git show 8fdf2da:infra/README.md` the storage and partitioning guidance,
      for P2's GPU-host role
- [x] Rewrite `README.md` and `docs/architecture.md` — **done 2026-09-16**,
      along with `services/llm-server/` and `docs/services/llm-server.md`.
      Both documents described the rejected D1(a) architecture, which meant the
      repo's own front page taught a reader the wrong model of the system.
      The doc sweep also caught live code: `DEFAULT_BASE_URL` still pointed at
      `http://llm-server:11434`, a Service that no longer exists in any
      manifest

**Gate:** the repo is in the org, a PR runs CI on a hosted runner, `infra/` is
gone, and no document in the repo describes a cluster that does not exist.

### P5 — Bedrock as a second backend _(stretch, ~8h)_

- [ ] Refactor `LLMClient` into an interface with two implementations behind
      one method. The interface is the deliverable; the second backend is the
      proof it was the right interface
- [ ] The IRSA role in the cloud repo (**C10**, **D-D**), scoped to
      `bedrock:InvokeModel` on named model ARNs
- [ ] Verify model availability in `eu-west-2` and the inference-profile
      question before designing around either
- [ ] Client-side token and daily-spend budget in composer
- [ ] Run the same eval set against both backends and **write the comparison**:
      cost per arrangement, p50/p95 latency, quality score, and what each costs
      in control

**Gate:** the same score arranges through both backends, selected by
configuration alone, and the comparison table has real numbers in it.

### P6 — Agentic composer _(stretch, 07 Phase 11)_

Only worth starting once P1's eval set exists and P5's interface is in place.
`musicxml-tools` functions as tool definitions, the fixed pipeline as a
plan → call → observe → revise loop, a critic pass, and guardrails: max
iterations, schema validation on every tool result, a cost budget, tracing.
**C5**'s second reshape — the model emits decisions, the library renders notes
— is the thing that makes this natural rather than bolted on.

---

## Minimum and stretch, restated

| | What it means concretely | Phases |
|---|---|---|
| **Minimum** | A score uploaded to composer in the cluster comes back arranged, with the inference having run on the PC's GPU | P0 → P4 |
| **Stretch** | The same request can be served by Bedrock instead, chosen by config, with a written comparison | P5 |
| **Stretch** | Composer plans rather than transcribes | P6 |
| **Not in scope** | Claude subscription as a runtime credential (**D-D**) — it is not a backend auth path | — |

---

## Definition of done

1. Four real scores are in `examples/`, and the deterministic round-trip's
   losses are written down rather than discovered.
2. A real piano score arranges end to end, and the result is recognisably
   bossa to a musician who was not told what to expect.
3. The PC serves inference from its Linux boot with the whole GPU available,
   as an Ansible-managed host that is provably *not* a cluster node — no
   kubelet, no multi-arch obligation, ADR-0011 intact.
4. Composer runs in the cluster on arm64, reconciled by Argo CD, with a
   NetworkPolicy that provably gates the inference call.
5. `composer/infra/` does not exist, and no document in this repo describes
   192.168.68.0/24, Flannel, or `eightbitsaxlounge/server`.
6. The repo is in the organisation with the same controls as every other repo.
7. An eval set exists and produces numbers, so "did that change help" is a
   question with an answer.
