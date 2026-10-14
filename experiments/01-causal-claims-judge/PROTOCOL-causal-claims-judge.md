# Experiment protocol: causal-claims-judge

## Summary (after the run, for a person)

- **Result:** <the answer to the question above, in at most two plain sentences…>
- **Limits:** <how far it holds, one sentence…>
- **Next step:** <what follows…>

## Intent (before the run)

- **Terms of this protocol:** Causal claim: the sentence says or implies that one thing brings about another (because, so, due to, drove, prevented). Not causal: the sentence only orders events or co-occurs them (after, in the same month, and). Registered lane: the question under test. Null lane: an English-language question whose answer is Yes for every item, so its expected accuracy is 6/12 = 0.5. Coinages: margin = 0.25 (C1); max_empty = 1 (A1: 12 items, a second empty answer already makes the parser the finding); null_band_items = 2 (A2: within 2 items of 6/12).
- **Question / hypothesis:** Does the model behind the alias haiku recognise from one sentence whether it makes a causal claim? Expectation: it answers Yes for the six causal sentences and No for the six others, at least 9 of 12 correct.
- **Success / failure criterion:** C1: registered-lane accuracy over all 12 items (an empty answer counts as not correct) is at least the null-lane accuracy plus margin 0.25. Fails otherwise.
- **Admissibility condition:** A1: at most max_empty = 1 empty or unreadable answer on the registered lane. A2: the null lane is within null_band_items = 2 items of 6 of 12. If either fails, C1 has no verdict.
- **Registered branch:** If C1 passes, the model's recognition of causal claims on these 12 sentences is reported as above null; if it fails, the result is 'no reliable recognition on this set', with no claim about other sets.
- **Timebox:** 30 minutes wall-clock for the whole lane, including audits; then log and stop.
- **Split touched:** test (the 12 items are the only split; no tuning on them beyond the instrument check).

## Result (after the run — write back, don't go quiet)

- **Answer to the question:** <per registered id its verdict, and the run_id…>
- **Answering run:** none yet — the run `finalize` holds this protocol to,
  written with the number by `protocol-fill PROTOCOL-<name>.md --from-run`
  after `finalize`; `finalize` refuses any other run_id here (a readable
  projection of `runs.bound_answering_run`, never a second binding)
- **Deviations after freeze:** none yet (not frozen).
- **Raw output:** <one real prompt+answer pair per finding>
- **Interpretation / next step:** <one sentence…>

## Context (self-contained)

- **Problem in one sentence:** Can a small language model tell, from one sentence, whether it says that one thing causes another?
- **Prior threads:** [[terms]] — defines the words 'causal claim' and 'null lane' as used here, so the gold labels mean one thing.

## Setup

- **Data / scope:** data/raw/claims.jsonl: 12 hand-written English sentences (ids c01–c12), six gold causal, six gold not_causal. 00_prepare.py copies them into data/prepared/claim_sentences_v1.jsonl unchanged (producer: scripts/00_prepare.py). No pilot subset: the probe runs the whole set once per lane.
- **Model / tool:** alias haiku from models.toml (backend claude-cli), called through labkit.llm.complete_many; no endpoint or model id in the code. Two lanes in the same call: registered and null.
- **Prompt (verbatim, per variant):**

  ```text
  ── PROMPT ──
  Does this sentence make a causal claim, that one thing brings about another?

  Text: {text}

  Answer with a single word, Yes or No.

  Answer:
  ── PROMPT_NULL ──
  Is this text written in English?

  Text: {text}

  Answer with a single word, Yes or No.

  Answer:
  ```

- **Model I/O:** In: one prompt per item per lane, the sentence in the prompt, the answer vocabulary Yes / No. Out: the model's text; the first token decides, empty or unreadable is its own state.
- **Null condition / anchors (in the same run):** null lane: 'Is this text written in English?' on the same 12 sentences; expected accuracy 6/12 = 0.5 (the gold share of Yes, known before any call); checked by A2 within 2 items.
- **Exclusions / filters:** None. All 12 rows enter both lanes; an empty answer is dropped from neither lane but counted as not correct and in a1_empty.
- **Unit:** One sentence judged once in each lane. Accuracy per lane = correct / 12.

## Checks (render check → instrument check → pilot)

- **Resolution check (ZERO calls, real `evaluate()` on synthetic extremes):** tests/test_01_causal_claims_judge.py, 17 passed: perfect registered lane (12/12) against null at 6/12 fires C1; a null-like registered lane (6/12 against 6/12) stays silent; two empty answers fail A1 and withhold the verdict; the null band is symmetric at 6 ± null_band_items; an empty answer counts as not correct (10/12, not 10/10).
- **Render check (ZERO calls, `--show N`):** `--show 3` read verbatim, both lanes: the registered prompt asks 'Does this sentence make a causal claim, that one thing brings about another?' with the sentence under 'Text:' and the Yes/No line; the null prompt asks 'Is this text written in English?' with the same sentence. No confound, no truncation, no repair of the sentence.
- **Instrument check (real pipeline, ~10 calls, `--probe N`):** `--probe 2`, 4 calls in 7 s, one row per gold class per lane:

```text
registered:c01  'Yes'  -> causal      (gold causal)
registered:c02  'No'   -> not_causal  (gold not_causal)
null:c01        'Yes'  -> causal      (gold causal)
null:c02        'Yes'  -> causal      (gold not_causal)
```

The registered prompt for c01 is the Render-check prompt above; the answer is the model's text as printed.
- **Yield per stage:** 12 rows read -> 12 items -> 24 jobs (12 per lane) -> 4 probe answers: 4 readable, 0 empty, 0 unreadable. Full-run yield is not yet known; A1 decides it.
- **Parser cases harvested:** the four probe forms ('Yes', 'No', 'Yes', 'Yes') pasted into PROBE_CASES in tests/test_01_causal_claims_judge.py; the test passes.
- **Clarified terms:** 'Causal' is taken in the everyday sense of 'X brought about Y', not the formal sense of causal inference; 'not_causal' includes sentences that are only temporal or co-occurrent.
- **Changed — and in which class:** none so far. The TODO stamps (paths, gold names, the two prompts, the answer words) were filled before the first call; no model call has been made.
- **Pilot:** the probe above is the pilot: two items, both lanes, checked by hand against gold. Registered lane right on both; null lane answers Yes on both, as its fixed answer requires. Four calls cannot test the criterion; the full run is the test.

## Runs (documented runs — via `runlog`, cite run_ids instead of retyping numbers)

- <run_id> — <one sentence: what this run was>

## Follow-up

- **Notes updated:** none yet — [[terms]] is the only note this run reads.

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
id = "p-55d21bdf7bdf4af8"
type = "exploratory"
cost = "minutes"
frozen = false
preflight_audit = ""

# The promises as data (labkit 0.71): one table per id — the key the run
# reports, the sentence (this promise stated explicitly — no `<…>` left at the
# freeze), the code region, and the constants the script reads with
# promises.all_constants(). A constant is
# named like the config key (lowercase) and stands in exactly one table;
# `frozen = true` owes these tables, and no run starts whose config lacks a
# constant or carries another value.
[[promise]]
id = "C1"
key = "c1_pass"
sentence = "C1: correct over all 12 items of the registered lane (an empty answer counts as not correct) is at least the null lane's correct over 12 plus margin 0.25."
scope = ["scripts/01_measure.py"]
constants = { margin = 0.25 }

[[promise]]
id = "A1"
key = "a1_pass"
sentence = "A1: at most 1 empty or unreadable answer on the registered lane of 12 items."
scope = ["scripts/01_measure.py"]
constants = { max_empty = 1 }

[[promise]]
id = "A2"
key = "a2_pass"
sentence = "A2: the null lane (is this text in English, expected Yes for all) is within 2 items of 6 of 12 correct."
scope = ["scripts/01_measure.py"]
constants = { null_band_items = 2 }
```
