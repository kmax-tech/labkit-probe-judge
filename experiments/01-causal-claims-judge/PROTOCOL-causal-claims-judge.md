# Experiment protocol: causal-claims-judge

## Summary (after the run, for a person)

- **Result:** Haiku judged 10 of 12 sentences correctly (c1_accuracy 0.8333, run 2026-10-14T15-49-10_4f76), above the bar of 0.75 (null 0.5 + margin 0.25): the criterion passes.
- **Limits:** Twelve items, one draw, one prompt: one item moves accuracy by 8 percentage points (1/12), and the sampling spread is not measured.
- **Next step:** none planned; a larger item set would be the next measurement.
- **Question †:** Does haiku recognise whether a sentence makes a causal claim?
- **Did †:** Ran 12 matched sentences through haiku in a registered and a null lane, 24 calls.


## Intent (before the run)

- **Terms of this protocol:** causal claim: a sentence stating that one thing causes, produces or prevents another (gold: causal), as against mere co-occurrence or sequence (not_causal). Registered lane: asks that question; null lane: asks 'is this English?' (true for every item, so it maps to causal for all). margin: 0.25 accuracy above the null lane. max_empty: 2 unreadable answers tolerated on the registered lane. null_band_items: null accuracy may differ from 0.5 by 1 item. Model alias: haiku (models.toml). Items: c01–c12.
- **Question / hypothesis:** Does the model behind the alias haiku recognise whether a sentence makes a causal claim? Expected: yes, well above chance.
- **Success / failure criterion:** [C1] registered accuracy over all 12 items (empty answer counts as not correct) is at least the null lane's accuracy plus margin 0.25.
- **Admissibility condition:** [A1] at most 2 empty or unreadable answers on the registered lane; [A2] the null lane sits at chance 6/12 within 1 item. If either fails, [C1] has no verdict.
- **Registered branch:** none — the result is reported as it is; no analysis branches on it.
- **Timebox:** 30 min.
- **Split touched:** n/a — no train/dev/test split; all 12 items are measured.
- **Why this design †:** Twelve matched pairs (a causal sentence and a near-identical non-causal one) with a constant-answer null lane in the same run.
- **Rival explanations †:** Surface cues (words such as because, due to, made) could carry the answer without understanding; N=12 is small, so one item moves accuracy by 8 points.
- **Out of scope †:** Other models, other prompts, a larger item set.


## Result (after the run — write back, don't go quiet)

- **Answer to the question:** n_items = 12, n_rows = 24, a1_empty = 0, a1_pass = True, a2_accuracy = 0.5, a2_empty = 0, a2_pass = True, c1_accuracy = 0.8333333333333334, c1_threshold = 0.75, c1_pass = True (run 2026-10-14T15-49-10_4f76)
- **Answering run:** 2026-10-14T15-49-10_4f76
- **Deviations after freeze:** none.
- **Raw output:** registered:c08 'Does the following text make a causal claim...? Text: The build is twice as fast on the new machine with the new compiler.' -> 'Yes' (gold not_causal).
- **Interpretation / next step:** Both misses (c08, c12) are non-causal sentences that name a plausible cause next to the effect.
- **Outcome †:** c1_accuracy 0.8333 (10/12) against null 0.5 + margin 0.25 = 0.75: C1 passes; A1 and A2 pass.
- **Rival check †:** Not tested: surface cues could explain the hits; the two misses are both non-causal sentences that mention a possible cause.
- **Caps/drops †:** none — 24 of 24 answers kept, 0 empty.
- **Analysis audit †:** 2026-10-14T15-51 analysis audit: 0 blockers, 2 warnings (single draw, case-sensitive parser) accepted, 4 notes decided; see audits/.

<!-- APPARATUS — this part gets LOOKED UP, not read. -->


## Context (self-contained)

- **Problem in one sentence:** Can a small language model tell a sentence that claims a cause from one that only reports things side by side?
- **Prior threads:** n/a — first area in this repo.

## Setup

- **Data / scope:** data/raw/claims.jsonl, N=12 (6 causal, 6 not_causal), copied unchanged to data/prepared/claims_v1.jsonl by scripts/00_prepare.py; no pilot subset.
- **Model / tool:** haiku via labkit.llm.complete (alias in models.toml); two lanes, registered and null, one call per item per lane.
- **Prompt (verbatim, per variant):**

  ```text
  ── PROMPT ──
  Does the following text make a causal claim, i.e. does it state that one thing causes, produces or prevents another?

  Text: {text}

  Answer with a single word, Yes or No.

  Answer:
  ── PROMPT_NULL ──
  Is the following text written in English?

  Text: {text}

  Answer with a single word, Yes or No.

  Answer:
  ```

- **Model I/O:** In: the lane prompt with the sentence; out: one word, Yes or No; first token decides, Yes=causal, No=not_causal.
- **Null condition / anchors (in the same run):** A: null lane 'Is the text written in English?' — true for all items, so answering Yes maps to causal for all; expected accuracy = share of causal gold = 6/12 = 0.5, band ±1 item.
- **Exclusions / filters:** none — all 12 items are used.
- **Unit:** one sentence judged once per lane.
- **Gate labels (expected) †:** n/a — no gate labels.
- **Data preparation †:** 00_prepare.py copies data/raw/claims.jsonl unchanged to data/prepared/claims_v1.jsonl.
- **Meaning of the gold label †:** causal: the sentence asserts that one thing causes, produces or prevents another; not_causal: it only reports co-occurrence or sequence.
- **Answer form + resolution †:** One word, Yes or No; resolution is one item = 1/12 = 0.083.
- **How measured †:** Accuracy over all 12 items per lane; an empty answer counts as not correct; C1 compares registered with null plus margin 0.25.
- **Validation †:** Probe on all 12 items (not reported), resolution tests in tests/.
- **Noise ceiling → threshold †:** Null lane expected 0.5 (6/12); bar 0.5 + 0.25 = 0.75, i.e. 9/12.
- **Free knobs †:** none beyond the registered constants margin, max_empty, null_band_items.
- **Randomness controls †:** none — one draw per item, sampling settings are the labkit default for the alias; the spread is not measured.


## Checks (render check → instrument check → pilot)

- **Resolution check (ZERO calls, real `evaluate()` on synthetic extremes):** tests/test_01_causal_claims_judge.py: perfect effect (12/12 vs null 6/12) fires C1; null-like registered lane (6/12) stays silent; 3 empty answers withhold the verdict; null at 12/12 fails A2. A coin-flip registered lane (p=0.5) passes C1 with P about 7.3% at null 6/12 (bar 9/12), 19% at null 5/12 — computed from Bin(12,0.5).
- **Render check (ZERO calls, `--show N`):** --show 1: one registered and one null prompt read verbatim; sentence inserted, answer line 'Yes or No'.
- **Instrument check (real pipeline, ~10 calls, `--probe N`):** --probe 12 (24 calls): every answer a bare Yes or No; null lane all Yes as intended; example: registered c01 'Does the following text make a causal claim...? Text: Because the road was icy, ... Answer:' -> 'Yes' (gold causal). Numbers not reported.
- **Yield per stage:** 24 of 24 answers parsed, 0 empty.
- **Parser cases harvested:** Yes -> causal, No -> not_causal, pasted into PROBE_CASES.
- **Clarified terms:** none.
- **Changed — and in which class:** instrument: none after the probe.
- **Pilot:** none beyond the probe; N=12 is the whole set.

## Runs (documented runs — via `runlog`, cite run_ids instead of retyping numbers)

- 2026-10-14T15-49-10_4f76 — the kept run; its metrics.json is the number

## Follow-up

- **Notes updated:** n/a — no notes written.
- **Prediction for the follow-up run †:** n/a — no follow-up planned.


## Notes (by-catch: ideas, follow-up experiments — cheap now, expensive later)

- <…>

## Head (read by the checks)


*How to fill each field, the cuts by tier and the intent ids:
`protocol-field-guide.md` (`protocol-check --guide`); which fields this
protocol's `cost` owes, and which fall due after a documented run:
`protocol-check --contract` — the one list, never retyped here; fill by
label with `protocol-fill PROTOCOL-<name>.md "<label>" "<value>"`.*

```toml
[protocol]
standard = "0.19"
id = "p-c1b4bd60da684221"
type = "exploratory"
cost = "minutes"
frozen = true
preflight_audit = "2026-10-14T15-48 · scope sha 37402f7695c9"

# The promises as data (labkit 0.71): one table per id — the key the run
# reports, the sentence (the same as the Intent field), the code region, and
# the constants the script reads with promises.all_constants(). A constant is
# named like the config key (lowercase) and stands in exactly one table;
# `frozen = true` owes these tables, and no run starts whose config lacks a
# constant or carries another value.
[[promise]]
id = "C1"
key = "c1_pass"
sentence = "<the criterion in one sentence: registered accuracy >= null accuracy + margin; accuracy over all items of the lane, an empty answer counts as not correct>"
scope = ["scripts/01_measure.py"]
constants = { margin = 0.25 }

[[promise]]
id = "A1"
key = "a1_pass"
sentence = "<the yield condition: at most max_empty empty or unreadable answers on the registered lane>"
scope = ["scripts/01_measure.py"]
constants = { max_empty = 2 }

[[promise]]
id = "A2"
key = "a2_pass"
sentence = "<the null condition: the null lane sits at chance, within null_band_items items>"
scope = ["scripts/01_measure.py"]
constants = { null_band_items = 1 }
```
