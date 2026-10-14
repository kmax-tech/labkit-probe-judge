# Experiment 01: causal-claims-judge

*Self-contained: data, scripts, output and this description live here.*

**The one question.** <one sentence — the same question as in the protocol's
Intent; if it needs an "and", it is two experiments>

<!-- labkit:route -->
**Trace it.**
- Contract and reported answer: `PROTOCOL-causal-claims-judge.md`
- Runs and provenance: `runlog .`
- Effective values: `labkit-params .`
- Where the ids are decided: `scripts/01_measure.py:evaluate_rows`
- Immutable record: `config.json` of the chosen run under `runs/`
<!-- /labkit:route -->

## Contract

**What `evaluate_rows()` returns.** <per registered promise its key, in the order
of the decision — from the protocol's [[promise]] sentences, not from the
skeleton: [A1] a1_pass …, [C1] c1_pass …, [B1] b1_branch; what comes back when
an admissibility condition fails>. The formula lives once, in
`scripts/01_measure.py` (`evaluate_rows()`); `02_analyze.py --check` and the
test call it there, and `intent-check` holds the protocol's ids to these keys.

**The gates, in order.** `code-check` after every code change · at
`minutes`/`hours`: `preflight` + the preflight audit, then freeze · the run
through `runlog` · `finalize` · `protocol-fill --from-run` writes the number back · `02_analyze.py --check`.

## State

- [ ] Registration written in the protocol (**before** the first run)
- [ ] `--probe` read, parser cases in the test
- [ ] Run, `protocol-fill --from-run`, `finalize` green
