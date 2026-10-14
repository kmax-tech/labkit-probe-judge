# Experiment protocol: causal-claims-judge

## Summary (after the run, for a person)

- **Result:** <the answer to the question above, in at most two plain sentences…>
- **Limits:** <how far it holds, one sentence…>
- **Next step:** <what follows…>

## Intent (before the run)

- **Terms of this protocol:** causal claim: a sentence stating that one thing causes, produces or prevents another (gold: causal), as against mere co-occurrence or sequence (not_causal). Registered lane: asks that question; null lane: asks 'is this English?' (true for every item, so it maps to causal for all). margin: 0.25 accuracy above the null lane. max_empty: 2 unreadable answers tolerated on the registered lane. null_band_items: null accuracy may differ from 0.5 by 1 item. Model alias: haiku (models.toml). Items: c01–c12.
- **Question / hypothesis:** Does the model behind the alias haiku recognise whether a sentence makes a causal claim? Expected: yes, well above chance.
- **Success / failure criterion:** [C1] registered accuracy over all 12 items (empty answer counts as not correct) is at least the null lane's accuracy plus margin 0.25.
- **Admissibility condition:** [A1] at most 2 empty or unreadable answers on the registered lane; [A2] the null lane sits at chance 6/12 within 1 item. If either fails, [C1] has no verdict.
- **Registered branch:** <if a result decides the conclusion or the next analysis, register it…>
- **Timebox:** <hard budget, e.g. 4h — then log and ask>
- **Split touched:** <which split may be touched: train | dev | test>

## Result (after the run — write back, don't go quiet)

- **Answer to the question:** <per registered id its verdict, and the run_id…>
- **Answering run:** none yet — the run `finalize` holds this protocol to,
  written with the number by `protocol-fill PROTOCOL-<name>.md --from-run`
  after `finalize`; `finalize` refuses any other run_id here (a readable
  projection of `runs.bound_answering_run`, never a second binding)
- **Deviations after freeze:** <"none", or what was changed after `frozen = true`…>
- **Raw output:** <one real prompt+answer pair per finding>
- **Interpretation / next step:** <one sentence…>

## Context (self-contained)

- **Problem in one sentence:** <no technical terms — what is being found out?>
- **Prior threads:** <2–3 [[wikilinks]], each with half a sentence on why they lead here…>

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

## Checks (render check → instrument check → pilot)

- **Resolution check (ZERO calls, real `evaluate()` on synthetic
  extremes):** <perfect effect → criterion fires? · null effect → stays silent? Both…>
- **Render check (ZERO calls, `--show N`):** <per gold class ONE rendered prompt, read verbatim…>
- **Instrument check (real pipeline, ~10 calls, `--probe N`):** <per gold class ONE fully rendered prompt+answer pair as a code block…>
- **Yield per stage:** <expected vs. obtained per parse step (→ LAB-023 No silent loss)>
- **Parser cases harvested:** <the probe's answer forms as REAL cases into the parser test…>
- **Clarified terms:** <what was ambiguous, and what is it called now?>
- **Changed — and in which class:** <instrument…>
- **Pilot:** <N items checked against hand analysis or anchors, before scaling>

## Runs (documented runs — via `runlog`, cite run_ids instead of retyping numbers)

- <run_id> — <one sentence: what this run was>

## Follow-up

- **Notes updated:** <[[…]] — reconcile on contradiction>

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
frozen = false
preflight_audit = ""

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
