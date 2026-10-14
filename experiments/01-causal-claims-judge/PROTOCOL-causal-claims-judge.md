# Experiment protocol: causal-claims-judge

## Summary (after the run, for a person)

- **Result:** <the answer to the question above, in at most two plain sentences…>
- **Limits:** <how far it holds, one sentence…>
- **Next step:** <what follows…>

## Intent (before the run)

- **Terms of this protocol:** causal claim: a sentence asserting that one event caused or brought about another (gold causal); not_causal: a sentence that only conjoins or juxtaposes events. Lane: registered asks the causal question, null asks 'is this English?' (always Yes). margin = 0.25: required accuracy lead over null. max_empty = 2: tolerated unreadable answers. null_band_items = 1: null lane may deviate from chance by one item. Alias haiku: claude-haiku-4-5 via labkit.llm. Items c01-c12, balanced 6 causal / 6 not_causal.
- **Question / hypothesis:** Does the model behind alias haiku recognise whether a sentence makes a causal claim? Expected: yes, well above the null lane.
- **Success / failure criterion:** [C1] registered-lane accuracy against gold (c1_accuracy) is at least the null-lane accuracy plus margin 0.25.
- **Admissibility condition:** [A1] at most max_empty=2 empty or unreadable answers on the registered lane; [A2] the null lane sits at chance (6 of 12) within null_band_items=1 item. If either fails, [C1] has no verdict.
- **Registered branch:** n/a — exploratory, no branch
- **Timebox:** 1h
- **Split touched:** n/a — no split, twelve items all used

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

- **Data / scope:** data/raw/claims.jsonl, N=12 (6 causal, 6 not_causal), copied by scripts/00_prepare.py to data/prepared/claims_v1.jsonl.
- **Model / tool:** alias haiku from models.toml (claude-haiku-4-5-20251001), called through labkit.llm.complete_many; one run per item per lane.
- **Prompt (verbatim, per variant):**

  ```text
  ── PROMPT ──
  Does the following text make a causal claim, i.e. does it assert that one thing caused or brought about another?

  Text: {text}

  Answer with a single word, Yes or No.

  Answer:
  ── PROMPT_NULL ──
  Is the following text written in English?

  Text: {text}

  Answer with a single word, Yes or No.

  Answer:
  ```

- **Model I/O:** Input: the prompt with the sentence; output: a single word Yes or No, first token parsed (Yes=causal, No=not_causal).
- **Null condition / anchors (in the same run):** Null lane asks 'Is the following text written in English?' for every item: the true answer is Yes for all, which maps to causal, so expected accuracy is the causal gold share 6/12 = 0.5; tolerance +-1 item.
- **Exclusions / filters:** None; all twelve rows are scored, unreadable answers counted as empty under [A1].
- **Unit:** One sentence (item) per call; accuracy over the 12 items.

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
id = "p-250f12a9d1be4b35"
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
sentence = "[C1] registered-lane accuracy against gold is at least the null-lane accuracy plus margin 0.25"
scope = ["scripts/01_measure.py"]
constants = { margin = 0.25 }

[[promise]]
id = "A1"
key = "a1_pass"
sentence = "[A1] at most max_empty=2 empty or unreadable answers on the registered lane"
scope = ["scripts/01_measure.py"]
constants = { max_empty = 2 }

[[promise]]
id = "A2"
key = "a2_pass"
sentence = "[A2] the null lane sits at chance (6 of 12), within null_band_items=1 item"
scope = ["scripts/01_measure.py"]
constants = { null_band_items = 1 }
```
