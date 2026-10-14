# Experiment protocol: causal-claims-judge

## Summary (after the run, for a person)

- **Result:** <the answer to the question above, in at most two plain sentences…>
- **Limits:** <how far it holds, one sentence…>
- **Next step:** <what follows…>

## Intent (before the run)

- **Terms of this protocol:** <first, because the question uses them…>
- **Question / hypothesis:** <the one question — what do we expect?>
- **Success / failure criterion:** <how do we recognise whether it worked? One id per conjunct, written…>
- **Admissibility condition:** <what must hold in the same run before any verdict is issued…>
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

- **Data / scope:** <source, N, producer script; pilot subset first>
- **Model / tool:** <alias from `models.toml` — never hardcode endpoint/ID>
  <two arms…>
- **Prompt (verbatim, per variant):**

  ```text
  <the real prompt — `protocol-fill PROTOCOL-<name>.md --prompts` writes it from the script's PROMPT constants>
  ```

- **Model I/O:** <in…>
- **Null condition / anchors (in the same run):** <one A per anchor…>
- **Exclusions / filters:** <what is dropped from the data or output and why…>
- **Unit:** <what one counted or judged thing is…>

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
id = "p-4e826cbd37a0451a"
type = "<exploratory | confirmatory>"
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
