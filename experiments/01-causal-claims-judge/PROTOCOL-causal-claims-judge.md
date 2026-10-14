# Experiment protocol: causal-claims-judge

## Summary (after the run, for a person)

- **Result:** <the answer to the question above, in at most two plain sentences…>
- **Limits:** <how far it holds, one sentence…>
- **Next step:** <what follows…>
- **Question †:** <the Intent's question in plain words, first — the Result
  below is its answer (a person reading only the Summary did not recognise
  the Result as the answer, 2026-10-08)>
- **Did †:** <what was done, one sentence — for a reader with no context>


## Intent (before the run)

- **Terms of this protocol:** causal claim: a sentence asserting that one event caused or brought about another (gold causal); not_causal: a sentence that only conjoins or juxtaposes events. Lane: registered asks the causal question, null asks 'is this English?' (always Yes). margin = 0.25: required accuracy lead over null. max_empty = 2: tolerated unreadable answers. null_band_items = 1: null lane may deviate from chance by one item. Alias haiku: claude-haiku-4-5 via labkit.llm. Items c01-c12, balanced 6 causal / 6 not_causal.
- **Question / hypothesis:** Does the model behind alias haiku recognise whether a sentence makes a causal claim? Expected: yes, well above the null lane.
- **Success / failure criterion:** [C1] registered-lane accuracy against gold (c1_accuracy) is at least the null-lane accuracy plus margin 0.25.
- **Admissibility condition:** [A1] at most max_empty=2 empty or unreadable answers on the registered lane; [A2] the null lane sits at chance (6 of 12) within null_band_items=1 item. If either fails, [C1] has no verdict.
- **Registered branch:** n/a — exploratory, no branch
- **Timebox:** 1h
- **Split touched:** n/a — no split, twelve items all used
- **Why this design †:** Twelve minimal pairs (causal vs. conjoined) with a placebo null lane in the same run, so accuracy is read against a noise floor.
- **Rival explanations †:** Surface cues (the words because, due to, made) could suffice without understanding; twelve items cannot separate that from recognition.
- **Out of scope †:** Other models, larger item sets, calibration, explanation quality.


## Result (after the run — write back, don't go quiet)

- **Answer to the question:** <per registered id its verdict, and the run_id…>
- **Answering run:** none yet — the run `finalize` holds this protocol to,
  written with the number by `protocol-fill PROTOCOL-<name>.md --from-run`
  after `finalize`; `finalize` refuses any other run_id here (a readable
  projection of `runs.bound_answering_run`, never a second binding)
- **Deviations after freeze:** none
- **Raw output:** <one real prompt+answer pair per finding>
- **Interpretation / next step:** <one sentence…>
- **Outcome †:** <expected or surprising — failures belong here>
- **Rival check †:** <which rivals are ruled out, which still stand?>
- **Caps/drops †:** <what was omitted or limited>
- **Analysis audit †:** <date · scope sha · N findings — the audit of the
  EVALUATION against the frozen criterion, before the number leaves; at
  cost seconds due at promotion or when the number steers a decision
  (→ LAB-050 Analysis audit before reporting, LAB-017 The number of audits follows the cost tier)>

<!-- APPARATUS — this part gets LOOKED UP, not read. -->


## Context (self-contained)

- **Problem in one sentence:** Finding out whether a small language model can tell sentences that assert a cause from sentences that merely mention two events.
- **Prior threads:** n/a — first experiment in this repository

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
- **Gate labels (expected) †:** n/a — no gate label registered beyond [A1], [A2], [C1].
- **Data preparation †:** 00_prepare.py copies the twelve raw rows unchanged to data/prepared/claims_v1.jsonl.
- **Meaning of the gold label †:** causal: the sentence asserts one event caused another; not_causal: it only conjoins or juxtaposes events.
- **Answer form + resolution †:** One word Yes or No, first token parsed case-insensitively; resolution is 1/12 per item.
- **How measured †:** Each item once per lane via labkit.llm.complete_many; accuracy = correct / 12 with unreadable answers counted wrong.
- **Validation †:** Hand check of the 12 gold labels; probe of 3 items per lane parsed correctly.
- **Noise ceiling → threshold †:** Null lane expected 6/12 = 0.5; threshold 0.5 + margin 0.25 = 0.75, i.e. at least 9 of 12 correct.
- **Free knobs †:** None; margin, max_empty, null_band_items are registered constants.
- **Randomness controls †:** None; one draw at the library default sampling, so one answer moves accuracy by 1/12.


## Checks (render check → instrument check → pilot)

- **Resolution check (ZERO calls, real `evaluate()` on synthetic extremes):** tests/test_01_causal_claims_judge.py runs evaluate_rows on synthetic extremes; passes.
- **Render check (ZERO calls, `--show N`):** --show 2 printed both lanes' prompts as registered.
- **Instrument check (real pipeline, ~10 calls, `--probe N`):** --probe 3: six calls, answers Yes./No/Yes and Yes x3, all parsed.
- **Yield per stage:** 12 raw rows -> 12 prepared rows -> 24 calls (2 lanes).
- **Parser cases harvested:** ('Yes.','causal'), ('No','not_causal'), ('Yes','causal') pasted into the test.
- **Clarified terms:** n/a — none
- **Changed — and in which class:** Scoring denominator changed to all 12 rows after the preflight audit (instrument); parser made case-insensitive.
- **Pilot:** n/a — probe of 3 items per lane stands in; its numbers are not reported.

## Runs (documented runs — via `runlog`, cite run_ids instead of retyping numbers)

- <run_id> — <one sentence: what this run was>

## Follow-up

- **Notes updated:** n/a — no notes yet
- **Prediction for the follow-up run †:** Registered accuracy 10-12 of 12; null 6 of 12.


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
frozen = true
preflight_audit = "2026-10-14 · scope sha ff25b350978c · 5 findings (0 blockers, 4 warnings, 1 notes), all decided"

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
