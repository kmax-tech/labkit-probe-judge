# Experiment protocol: causal-claims-judge

## Summary (after the run, for a person)

- **Result:** <the answer to the question above, in at most two plain sentences…>
- **Limits:** <how far it holds, one sentence…>
- **Next step:** <what follows…>

## Intent (before the run)

- **Terms of this protocol:** causal claim: a sentence that asserts one thing caused, produced or prevented another (gold causal); not_causal: it only reports things side by side or in sequence. margin = 0.25 (required lead of the registered lane over the null lane); max_empty = 2 (unreadable answers tolerated); null_band_items = 1 (null lane within chance ± 1 item); lanes: registered and null; model alias haiku; item ids c01–c12.
- **Question / hypothesis:** Does the model behind the alias haiku recognise whether a sentence makes a causal claim? Expected: yes, well above the null lane.
- **Success / failure criterion:** [C1] registered-lane accuracy against gold is at least the null-lane accuracy plus margin (0.25).
- **Admissibility condition:** [A1] at most max_empty (2) empty or unreadable answers on the registered lane; [A2] the null lane sits at chance (6 of 12), within null_band_items (1) item; if either fails, [C1] has no verdict.
- **Registered branch:** n/a — no branch hangs on the result.
- **Timebox:** 1h
- **Split touched:** n/a — no split; all twelve items are measured.

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

- **Problem in one sentence:** Can a small language model tell sentences that claim a cause from those that merely list facts?
- **Prior threads:** n/a — none yet

## Setup

- **Data / scope:** data/raw/claims.jsonl, N = 12 (6 causal, 6 not_causal), copied by scripts/00_prepare.py into data/prepared/claims_v1.jsonl.
- **Model / tool:** alias haiku from models.toml, called through labkit.llm; two lanes (registered, null), one call per item per lane.
- **Prompt (verbatim, per variant):**

  ```text
  ── PROMPT ──
  Does the following sentence make a causal claim, that is, does it assert that one thing caused, produced or prevented another?

  Text: {text}

  Answer with a single word, Yes or No.

  Answer:
  ── PROMPT_NULL ──
  Is the following sentence written in English?

  Text: {text}

  Answer with a single word, Yes or No.

  Answer:
  ```

- **Model I/O:** in: the lane's prompt with the sentence; out: free text whose first word (Yes or No) is read; Yes = causal, No = not_causal.
- **Null condition / anchors (in the same run):** A2: the null lane asks 'Is the following sentence written in English?' — true for every item, so a Yes-answering model scores the causal share, 6 of 12 = 0.5; target 0.5 ± 1 item.
- **Exclusions / filters:** none — all twelve items are scored; empty or unreadable answers are counted (a1_empty), not dropped silently.
- **Unit:** one sentence judged once per lane.

## Checks (render check → instrument check → pilot)

- **Resolution check (ZERO calls, real `evaluate()` on synthetic extremes):** tests/test_01_causal_claims_judge.py: perfect registered lane (12/12) vs null 6/12 fires [C1]; a registered lane equal to null stays silent; null outside chance ± 1 item withholds the verdict; more than max_empty empty answers fail [A1].
- **Render check (ZERO calls, `--show N`):** --show 2 read: registered and null prompts render the sentence and the single-word answer line, one per gold class (c01 causal, c02 not_causal).
- **Instrument check (real pipeline, ~10 calls, `--probe N`):** --probe run on all twelve items per lane, throwaway file output/causal-claims-judge_probe.jsonl; answers came back as a bare Yes or No, read correctly by the parser; numbers not reported.
- **Yield per stage:** 12 items → 24 calls → all answers readable in the probe; the run reports a1_empty.
- **Parser cases harvested:** Yes → causal and No → not_causal pasted into PROBE_CASES.
- **Clarified terms:** none.
- **Changed — and in which class:** nothing changed after the probe.
- **Pilot:** n/a — twelve items are the whole run; the probe served as the instrument check.

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
id = "p-4e826cbd37a0451a"
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
sentence = "<the criterion in one sentence: registered accuracy >= null accuracy + margin>"
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
