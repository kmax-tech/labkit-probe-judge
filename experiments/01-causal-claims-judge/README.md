# Experiment 01: causal-claims-judge

*Self-contained: data, scripts, output and this description live here.*

**The one question.** Does the model behind the alias haiku recognise whether a sentence makes a causal claim?

<!-- labkit:route -->
**Trace it.**
- Contract and reported answer: `PROTOCOL-causal-claims-judge.md`
- Runs and provenance: `runlog .`
- Effective values: `labkit-params .`
- Where the ids are decided: `scripts/01_measure.py:evaluate_rows`
- Immutable record: `config.json` of the chosen run under `runs/`
<!-- /labkit:route -->

## Contract

**What `evaluate_rows()` returns.** c1_pass (registered accuracy ≥ null accuracy + margin) · a1_pass (≤ max_empty unreadable answers) · a2_pass (null lane at chance ± 1 item); c1_pass is None when an admissibility condition fails. The formula lives once, in
`scripts/01_measure.py` (`evaluate_rows()`); `02_analyze.py --check` and the
test call it there, and `intent-check` holds the protocol's ids to these keys.

**The gates, in order.** `code-check` after every code change · at
`minutes`/`hours`: `preflight` + the preflight audit, then freeze · the run
through `runlog` · `finalize` · `protocol-fill --from-run` writes the number back · `02_analyze.py --check`.

## State

- [x] Registration written in the protocol (**before** the first run)
- [x] `--probe` read, parser cases in the test
- [x] Run, `protocol-fill --from-run`, `finalize` green
