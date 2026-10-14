# The labkit lab standard

These are the rules an experiment area is held to — before a run, during it,
and before a number leaves the lab. labkit's checks enforce what can be
checked mechanically and cite the rule they enforce by identifier and name;
the rest is for the author, the audits and the reviewer. A lab refers to this
standard through its pinned labkit version instead of copying it:
`python -m labkit.rules show LAB-015` prints one rule. A lab's own rules live in
its repository (`docs/`); they add to these rules and never override them.

**Evidence lives alongside.** If a rule comes from a concrete failure, a lab
keeps the case in its own evidence file under the same identifier; this
standard ships the rule text only. The rule text says what applies, and in a
half-sentence why; the evidence says where it went wrong. Anyone who doubts a
rule or wants to change it reads the evidence first.

**Identifiers.** Every rule carries an identifier `LAB-nnn` and a name. The
ledger is `rules.tsv` next to this file, and labkit assigns every `LAB` number.
A lab's own rules carry `LOCAL-nnn` in the lab's own ledger, the coding rules
`CODE-nnn` in the coding style; the three families never mix. Before the first
public release (labkit 0.82.0, 2026-10-11) the families were renamed from
`AS`/`HS`/`CS` to `LAB`/`LOCAL`/`CODE`, number for number, and the seven house
numbers left this ledger for the lab's `LOCAL` ledger; the rules below apply to
the published families, and material written before that keeps what it was
written with. The following applies:

1. Every identifier is assigned exactly once.
2. An identifier is never reused; a new rule gets the highest number ever
   assigned + 1, even if one has been dropped in between.
3. An identifier never changes — not when renaming, not when moving.
   A deleted rule stays in the ledger as `retired`, a moved one as
   `moved:<where>`.
4. Every old §-identifier remains resolvable as an alias: in the rule head
   (`*(was §2.A12)*`) and in the ledger.
5. Identifier and name fit together: a reference gives the title or its
   start (at least two words or the first clause).
6. Current references are identifier + name: `LAB-015 Preflight audit before
   freezing`. In answers to the user, only the name appears.
7. Historical material is never rewritten: run snapshots, patches, raw output,
   archives and frozen protocols keep the identifiers they were written with
   (§, `AS`).
8. New §-identifiers are no longer created.

`python -m labkit.rules check` holds 1–4 against the ledger;
`python -m labkit.rules refs <paths>` holds 5, 6 and 8 at the references.

---

## 1. Evidence

- Factual claims come from the **primary source** (paper: read the PDF; dataset:
  inspect the structure). Never from notes/memory.
- Quote all load-bearing evidence **verbatim** in `## Sources` (+ location).
- Mark *sketch* vs. *settled*; name tensions; do not over-claim.
- **A claim requires evidence:** support interpretation with data — or mark it as
  speculation (clearly: we do not know) + an idea of how to substantiate it.

### LAB-001 · A negative finding is a claim *(was §1.A)*

"Does not occur" is not an observation but a statement about the search tool. It holds only once it has been shown that the tool **could have found** the case — using a positive example that it does find.

**Mnemonic:** A pattern that is too narrow does not lose precision — it reverses the conclusion. Before every "does not occur": find a case that is known to be there, and check whether the pattern catches it. For small sets (under ~50), look at the raw data instead of counting; there you notice it immediately.

## 2. Intent first

*Terms of this section, coined once (everyday word first):*

- **Intent** — the intention before the run: question, success criterion,
  admissibility conditions (English field label: *admissibility condition*) and
  registered branches (LAB-004 Identifiers make the intent addressable).
- **Render check** — only look at finished prompts, zero model calls (`--show`).
- **Instrument check** — ~10 real calls through the real pipeline (`--probe`).
- **Area** — one experiment directory under `experiments/`: protocol, scripts,
  data references, runs; the unit every labkit check works on.
- **Pilot** — small run, checkable by hand, before scaling up.
- **Freezing (frozen)** — fixing hypothesis and criteria in writing; from then on
  the run counts as a test, before that it is exploration.
- **Null condition / anchor** — companion checks with a known target; if they do not show
  what is expected, the instrument measures nothing.
- **Gold label** — the label in the data that is taken to be correct.
- **Free knobs** — every selectable parameter: threshold, filter, wording,
  answer form.
- **Yield** — expected vs. obtained per processing step.
- **Producer** — the script that produces a dataset (`data/raw` →
  `data/prepared`).
- **run_id** — identifier of a run from `runlog`; every reported number carries
  one.
- **Confound (rival explanation)** — another cause that would produce the same number.
- **Throwaway test** — trying something out without keeping a number; needs neither protocol
  nor runlog.
- **Research** — collecting, reading, organizing ideas; produces notes, not
  protocols. Not an experiment, even if a prompt or a taxonomy stands at the end.
- **Promise** — a registration that the code must honor:
  a criterion, an admissibility condition or a branch (LAB-004 Identifiers make the intent addressable).
- **Head** — the TOML block of the protocol (`[protocol]`: `standard`,
  `id`, `type`, `cost`, `frozen`, `preflight_audit`): the fields that a
  machine reads, as data instead of prose; plus the `[[promise]]` tables.
- **Cost tier** — `cost` in the head (`seconds` · `minutes` · `hours`): what
  a repetition of the run costs; it determines how many audits an
  area gets (LAB-017 The number of audits follows the cost tier).
- **Gate** — a check that a tool enforces (it refuses the run or the commit), as opposed to a rule that exists only in the text.
- **Stamp** — the check value `scope sha` over all files that determine a number; it shows which code an audit has seen (LAB-019 The stamp covers everything).
- **Scar table** — the table of error classes in LAB-015 Preflight audit before freezing: each row is an
  error that has happened before.
- **Promotion** — the moment a number leaves the lab: for a
  note, a paper or a decision.

*Every rule carries an ID (`LAB-003 No run without an intent paragraph`) that code and templates can point to.
IDs are assigned once and are not recomputed when rules are reordered; a new
rule goes at the end of its group. The case behind a rule is in the
evidence file under the same ID (top of this document).*

### 2A · Before the run — setting and freezing the intent

- **LAB-003 · No run without an intent paragraph:** *(was §2.A1)* before every experiment, 5 lines — hypothesis,
  success criterion, admissibility condition — as `PROTOCOL-<task>.md` next to the
  script, if need be in the docstring. Intent first, then code.
  `labkit-init exp <name>` generates it from the template; the template lives with its checker in the
  labkit package.

- **LAB-004 · Identifiers make the intent addressable.** *(was §2.A1a)* Every promise to
  the code carries an identifier in the protocol text, depending on its kind:

  | Identifier | Kind          | what it fixes                                                                                                                     |
  |------------|---------------|-----------------------------------------------------------------------------------------------------------------------------------|
  | `[C1]`…    | Criterion     | which value of which metric supports the hypothesis                                                                               |
  | `[A1]`…    | Admissibility | whether a C verdict may be issued at all: an outcome-neutral check in the same run (control, anchor, yield, coverage, resolution) |
  | `[B1]`…    | Branch        | what follows from a result: which conclusion or which follow-up analysis                                                          |

  The separation rule: **C judges, A permits the verdict, B says what
  follows from it.** If a condition depends on the outcome of the hypothesis,
  it is C, otherwise A. Prose without a promise gets no identifier — otherwise
  the protocol turns into bookkeeping. The contract: every identifier appears
  as a lowercase key in the `metrics.json` of the reportable run
  (`c1_pass`, `a1_pass`, `b1_branch`); `intent-check <PROTOCOL>` (labkit)
  checks set equality in both directions. The command only sees whether the
  key is there, never whether it is correct — the audit checks that per identifier.
  Identifiers are also the handover unit between agents: a build order
  names them, the report cites them, the audit checks them.

  The promises are also present as data in the head: the `[[promise]]` tables
  (key, sentence, code region, constants). Protocol standard 0.19
  (labkit 0.72) requires them when `frozen = true` and for every full run
  — so with `cost = "seconds"` always. A constant is named like the
  config key (`margin`, lowercase) and appears in exactly one table; the
  script reads it with `promises.all_constants()`, never as a copy, and
  `runlog` refuses, before creating the run directory, a run
  whose config omits a registered constant or records a different value. An
  admissibility condition says why its failure invalidates the measurement
  (instrument, never the hypothesis); a registered branch is decided on its own
  condition, "n/a" is the honest registered branch when none is known before the run.
  `labkit-params <area>` shows every value of a run
  with its home. Contract: `~/projects/labkit/docs/promise-block.md`. The old letters
  `[K]`/`[S]`/`[W]`/`[N]` are no longer read by labkit; they cannot be translated
  1:1, frozen protocols stay as they are, and their repo
  stays on its labkit pin until new work begins there. F, P, R, Q and H are barred
  as letters, because `f1`, `p1`, `r1`, `q1` and `h1` are common
  metric names.

- **LAB-005 · Pilot before scaling:** *(was §2.A2)* first run on a small, validatable subset (e.g. 8 items), check against hand analysis/anchors, *then* scale.

- **LAB-006 · Does the gold label measure what you are measuring?** *(was §2.A3)* Before the first run, check whether the positive class denotes the property the instrument detects — otherwise you measure correctly but miss the question.

- **LAB-007 · Render check before the instrument check.** *(was §2.A4)* The only tier that costs
  nothing: the script renders the finished prompts (`01_measure.py --show N`)
  without querying a model. Read one prompt verbatim per gold class —
  what to look for is whatever is invisible in the template and jumps out in the individual case
  (stacked negation, fields filled with empty values, sentences the question form
  cannot decide) — and check whether the **prompt form itself introduces
  a class-exclusive marker**; the markers of the *data* are already counted by the producer
  (→ "Materialize transformations"). **Examples in the prompt
  are anchors:** each shows the property WITH its basis — an
  example without a basis teaches the surface instead of the relationship
  (LAB-037 Every anchor carries its target and rationale also applies in the prompt).

- **LAB-008 · Instrument check before freezing.** *(was §2.A5)* Between preregistration and
  pilot, there must be a **dry run on the real material**: run the pipeline once for
  a handful of items (`01_measure.py --probe N` — the *real*
  pipeline, not a hand-written copy; copies diverge) and put one
  example pair per gold class into the protocol (LAB-014 One fully rendered example pair per gold class). It does not test the
  hypothesis but **instrument and vocabulary** — terms are clarified by the
  single example, not by the definition.

  The instrument check includes a look at the **validator battery** and its
  failure directions: What does each validator catch, and what does *none* catch? A
  battery that checks only the **form** (length, tokens, markers) lets through
  items that are formally perfect and substantively worthless — at least one validator must
  check the **purpose**: whether the construction has achieved what it is built
  for. This also applies to self-built tools: opened, not just written.

  What it may change: prompt wording, answer form, parser, field names,
  terms. What it may not: hypothesis, success criterion, admissibility conditions,
  primary contrast. If this happens anyway, the run is exploratory, and that belongs
  in `type` of the head.
  Its numbers are **never reported** (throwaway test), otherwise looking
  into the data invalidates the preregistration. `frozen` may only be set to
  `true` after that — `protocol-check` enforces this (`true` without an
  I/O code block is a required-field error): A frozen registration on
  an unchecked instrument freezes the error in with it.

- **LAB-009 · Verdict only at the registered tier.** *(was §2.A6)* ONE place in the measurement script
  decides the tier (`stage_of`: probe · pilot · full · scope:…); it
  controls the output file, the runlog name and whether the frozen criterion is checked.
  Runs that are not the registered contrast (anchor, side stratum,
  second judge) get their numbers WITHOUT PASS/FAIL — a verdict next to a
  number it never applied to later reads like a failed
  preregistration.

- **LAB-010 · Commit before the run.** *(was §2.A7)* An untracked area is in no diff: What is meant to answer
  "which code produced this number?" must be in the history before the run.
  The run snapshot `source-untracked/` is the safety net for the forgotten case, not the intended method.

- **LAB-011 · Required-field check:** *(was §2.A8)* `protocol-check <PROTOCOL-file>` (command from
  the `labkit` package; in the repo venv: `.venv/bin/protocol-check`)
  checks protocols for the required fields of the template (structure flexible, fields
  required; `n/a — <reason>` counts). Runs automatically twice: as a
  Claude hook after every change (`claude-hook post-change` in
  `.claude/settings.json`; it works via `git status`, so also with a
  heredoc, not only with Write/Edit) and as a git pre-commit hook
  (`.githooks/`). All hooks come with the pinned labkit:
  `.venv/bin/labkit-hooks install` writes them along with `core.hooksPath` and is
  run again after every bump of the pin; `preflight` warns if they
  are missing or come from a different labkit version. The stop hook
  (`claude-hook stop`) sends the agent through
  `finalize` before the end of its turn if it has written a number back. The pre-commit hook also sends every protocol whose
  "Answer to the question" cites a run_id through `finalize
  --if-reported` — a number that has been written back does not enter the
  history unchecked, and it must cite the run that the checks hold.
  Deliberate exception: `--no-verify`.

  **What the agent forgets, a gate holds.** A full run (`long=True`) on a protocol
  without `frozen = true` or with an empty `preflight_audit`
  is refused by `runlog` before `mkdir` — long pilot: `LABKIT_UNFROZEN=1`,
  lands as `unfrozen_ack` in `config.json`. In front of that sits the Claude hook
  `claude-hook pre-run` (PreToolUse on Bash): it detects a script that
  opens a run and runs `preflight` on its area —
  frozen + blocker → command blocked; not frozen → only
  reported. `--show`/`--probe`/`--eval-only` pass through unhindered;
  `LABKIT_PREFLIGHT=skip` in the command is the visible exception. Both
  gates follow the cost tier (LAB-017 The number of audits follows the cost tier), which
  lands as `cost_tier` in `config.json`.

- **LAB-012 · Protocol is content.** *(was §2.A9)* A protocol carries decisions with reasons —
  no review drafts, no repetition of this standard's rules, no address to a person.
  Open points are either decided (the rationale
  stays) or attached to the instrument check as a checkpoint; the
  review itself happens in conversation, not in the document.

- **LAB-013 · Registered branch when the run can answer two questions.** *(was §2.A10)*
  If a precondition decides which question the run actually answers
  (e.g. "does the evidence vary enough to measure hardness?"), the registered branch
  belongs BEFORE the run: the condition, and which question each branch answers. Then
  both outcomes are findings and neither is a failure.

- **LAB-014 · One fully rendered example pair per gold class.** *(was §2.A11)* The
  instrument check puts ONE complete prompt+answer pair with real data per gold
  class into the protocol, as a code block rather than a paraphrase. Without these
  examples, the model I/O description is a statement of intent: it says what
  the model should deliver, not what it delivers.

- **LAB-015 · Preflight audit before freezing.** *(was §2.A12)* Between the instrument check
  and `frozen = true`, an *independent* reader reads protocol and code
  against each other. It does not check style but the error classes of the
  scar table below, and it **reports instead of repairing**. The reader is
  the command `labkit-audit <area> --mode preflight` (labkit): it puts the
  protocol, the scripts, the imported `lib/` modules and the rules its
  instructions cite (this one with the scar table among them) into one
  model call via `models.toml`; exit 1 on a blocker **or** a warning, exit 2
  if no audit could be completed. The instructions ship with labkit
  (`experiment-preflight.agent.md`); a copy run as a harness subagent is not
  a second way — it drifted from the shipped text once and read this whole
  standard twice per audit.

  Every finding is decided (fixed / accepted with reason /
  dismissed), the raw report stays in the scratchpad (LAB-012 Protocol is content), and the result
  goes in ONE line in the head; the check value in it is the stamp
  (LAB-019 The stamp covers everything that determines the number):

  ```toml
  preflight_audit = "2026-09-08 · scope sha 3f9a1c2b7e04 (scripts 4 · analysis 1 · lib/bt.py lib/stats.py · labkit==0.7.2) · 4 findings (2 blockers fixed, 1 warning accepted: <reason>, 1 dismissed: <reason>)"
  ```

  **The line is checked, not believed.** `runlog` refuses a full run
  if its `scope sha` is not the stamp the code has
  now (LAB-019 The stamp covers everything that determines the number) — the code changed after the audit, or the
  line was written without an audit — and unless a preflight audit record
  (`audits/*-preflight.toml`, written by `labkit-audit`) carries that same
  `scope sha` with every finding decided. Fixing the findings changes the
  stamp, so the fixed code owes a second audit; writing the new sha into the
  line alone is refused (2026-10-14: a cold agent did, and no audit had seen
  the frozen code). Whoever deliberately waives the audit
  writes `n/a — <reason>`; that is a visible decision.

  **The audit reads the filled-in protocol.** If the required intent fields
  are still placeholders, the agent refuses with one line: an audit of the
  empty template flags an intent nobody has written.

  **The scope follows reversibility.** Before the run, the audit checks what
  invalidates the run and cannot be repaired afterwards: plan,
  prompts, instrument, producer — and the **schema contract**: Does what is
  materialized make the analysis possible at all? (The producer fields cover
  everything the analysis reads; every identifier has its metrics key on every lane, LAB-004 Identifiers make the intent addressable.) Whether the analysis is *correct* is only checked by the
  analysis audit after the run (LAB-050 Analysis audit before reporting): By then the answers are on
  disk, and an analysis error is free to fix — provided the
  contract holds. A schema break therefore remains a preflight finding, even if
  it sits in an analysis file. The scope is narrowed, never
  the depth.

  **Severity levels** (legend here, so that two audits classify the same finding
  the same way — LAB-086 Values rule (codes are names too)): **BLOCKER** materially changes the reported number
  or the validity of the frozen criterion · **WARNING** is
  a real problem with no demonstrated influence on the current number ·
  **NOTE** has a scenario only under a condition ("if X is changed,
  then …"), not triggerable in the present code. The level says how close the
  failure scenario sits to the current run; a finding **without** a scenario ("which
  reported number becomes wrong, with which input") exists at no level.

  **The error classes** — each a scar, with the rule that forbids it.
  Column *Audit*: `preflight` = before the run (LAB-015 Preflight audit before freezing), `analysis` =
  analysis audit (LAB-050 Analysis audit before reporting), `beide` = in both; the same values as
  `labkit-audit --mode`:

  | Class                          | what goes wrong                                                                                                                                                                                                           | Audit     | Rule                                                                                                                                       |
  |--------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|-----------|--------------------------------------------------------------------------------------------------------------------------------------------|
  | Criterion ≠ code               | Threshold, direction or cell comparison in the script deviates from the registered criterion                                                                                                                              | preflight | LAB-003 No run without an intent paragraph, LAB-009 Verdict only at the registered tier                                                      |
  | Prompt↔gate defined twice      | the same rule typed in the prompt text and in the validator instead of rendered from one constant (or held by a test)                                                                                                     | preflight | LAB-038 What the prompt demands                                                                                                             |
  | Null condition only on paper   | registered, not generated in the code or not in the same run                                                                                                                                                              | preflight | LAB-034 Null condition in the same run                                                                                                      |
  | Branch not implemented         | registered fork without a branch in the code                                                                                                                                                                              | preflight | LAB-013 Registered branch                                                                                                                   |
  | Sign/direction                 | the metric assumes concordance where the question form is anticorrelated                                                                                                                                                  | analysis  | —                                                                                                                                          |
  | In-sample fit quality          | Fit and evaluation on the same points (r² without leave-one-out)                                                                                                                                                          | analysis  | —                                                                                                                                          |
  | Gate without anchor/resolution | Instrument gate without positive control; criterion with uncomputed resolution (LAB-016 Resolution check before freezing); anchor without near cases (LAB-039 Anchors include the near cases)                               | beide     | —                                                                                                                                          |
  | One output file = one run      | Instrument check or debug writes into the run's file                                                                                                                                                                      | preflight | LAB-057 One area per idea                                                                                                                   |
  | Parser without fixture test    | Model-output parser without a test with a real raw answer; drops uncounted; empty answer not a state of its own                                                                                                           | beide     | LAB-023 No silent loss, LAB-030 Reasoning models                                                                                             |
  | Spread unknown                 | n = 1 draw, unseeded, temperature implicit — a difference without a noise floor                                                                                                                                           | beide     | LAB-036 Validate                                                                                                                            |
  | Criterion fails on noise       | a criterion on model output that one vote of a component the change does not touch can fail: every rejection counts, no majority over draws, no restriction to the component under test (uniagent 26, 2026-10-12: [C3] fell to a single vote of an unchanged rule) | preflight | LAB-036 Validate, LAB-016 Resolution check before freezing                                                                                   |
  | Shared constant                | Anchor or threshold lives in `lib/` and is shared by several areas; whoever changes it changes other areas' numbers                                                                                                       | beide     | —                                                                                                                                          |
  | Index/assignment               | Join by position instead of id — two stages build their order independently                                                                                                                                               | beide     | —                                                                                                                                          |
  | Provenance incomplete          | `prompt_sha`/config does not cover everything that determines the prompt or the number                                                                                                                                    | beide     | LAB-043 Runs go through `runlog`                                                                                                            |
  | Operations                     | Alias not from `models.toml`, lock/resume missing, retries uncounted; a second alias in parallel is locked by the endpoint lease (LAB-028 An endpoint is a model slot, not a service) — check whether the area bypasses it | preflight | LAB-027 Model discipline, LAB-028 An endpoint is a model slot, not a service, LAB-049 Long runs go through the harness's background mechanism |

  **What no audit sees — and what does.** The audit reads code and
  protocol; it does not run the model. How the model will behave on the
  cases — a limit it applies beyond its stated range, a value it cites
  from a reference table instead of the document — is found by the run,
  never by an audit (uniagent 2026-10-12: four criteria fell to model
  behaviour, no audit had flagged one of them). The probe for that is the
  instrument check on the boundary cases (LAB-008 Instrument check before
  freezing, LAB-014 One fully rendered example pair per gold class), not a
  second audit.

  **Refine by count, not by deadline:** the protocol lines carry
  findings/accepted/dismissed and are greppable
  (`rg -o 'preflight_audit = .*' experiments/*/PROTOCOL-*.md`). After ten audits
  the table is refined based on that rate — a class that produces "dismissed"
  ten times is a false-alarm generator and is removed.

- **LAB-016 · Resolution check before freezing.** *(was §2.A13)* A registered criterion
  has a resolution, and it is computed, not felt: before the freeze,
  the analysis runs on two synthetic extremes — perfect effect
  (the criterion MUST fire) and null effect (it MUST NOT) — with the real
  structure of the run (number of draws, distribution across the units). Zero
  model calls; both numbers go into the field `Resolution check` (the template
  already contains it; if left blank, it fails the checker when freezing). The
  clause without which the rule is worth nothing: **the check calls the real
  `evaluate()` function with synthetic data, never a hand copy of the
  formula** — copies diverge (LAB-008 Instrument check before freezing carries the same scar for the pipeline).
  The permanent form is the template-generated test `tests/test_<NN>_<name>.py` (`lib
  exp` creates it: perfect effect, null effect, parser cases from the
  check); `preflight` runs it as the fifth check, and if left blank it fails —
  a later change to `evaluate()` that silently disables the criterion thus cannot pass the freeze.

- **LAB-102 · Cold reader before freezing.** Whoever has built an area
  can no longer read it like someone opening it for the first time — and that is exactly how the person who later checks the number encounters it. What this reader misses
  sits where the words don't fit together — a term before its definition, a case number without
  a kind, German prose and English code with no word in common, a
  docstring that conceals a conjunct, template leftovers in the README.
  Therefore, before
  freezing, while the prose can still be changed, **another** reader
  reads the area in the order in which a person opens it — README,
  summary and intent, script head, `evaluate_rows` — and reports only what
  this reader would misunderstand, with the line number and smallest correction: the
  agent `code-clarity` (`MODE: area`) or `labkit-audit --mode clarity`.
  Static evidence: it blocks nothing, stamps nothing, proves nothing;
  each issue it names is fixed or left standing with a reason. It replaces
  neither LAB-015 Preflight audit before freezing (correctness) nor LAB-016 Resolution check before freezing (resolution) — it sits
  beside them, with a different question: not "is it right?", but "can
  someone read it who did not write it?".

- **LAB-017 · The number of audits follows the cost tier.** *(was §2.A14)* `cost` in the head
  measures the price of a **repetition**, not whether a model is involved:
  a handful of calls lasting a minute and costing a few cents is `seconds`. The
  audit before freezing protects what cannot be repeated —
  calls, money, annotation time. A run of seconds can be repeated at any time
  and does not need this protection.

  | Tier               | before the run                                                                                                                                             | after the run                                                                                                                                                                                                                                                                                                   |
  |--------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
  | `seconds`          | `code-check` (LAB-018 Routine check after every implementation); no agent audit, `preflight_audit` stays empty; the first run replaces the instrument check | **one** audit in `analysis` mode, which also covers the `preflight` rows of the scar table; it comes at the promotion of the number or immediately if it steers a decision (a branch `[B]`, a lab notebook item) — until then the number is *sketch*; blockers and warnings are reported, notes only as a count |
  | `minutes`, `hours` | `code-check`, then preflight audit (LAB-015 Preflight audit before freezing)                                                                                | Analysis audit (LAB-050 Analysis audit before reporting), before a number is reported                                                                                                                                                                                                                            |

  **At `seconds`, the criterion freezes once, the instrument never.** The
  criterion is fixed before the number exists and does not move afterwards. The
  instrument may change after the first run — one more role, a
  check per computation, a different aggregation. Every change is a commit
  with a test and a new run of the same command: no second
  `frozen = true`, no second audit, no freeze paragraph in the protocol; what
  changed is recorded by the series of commits between the run_ids. If the
  criterion changes, it is a new experiment at any tier (LAB-003 No run without an intent paragraph). The gates
  read the cost tier: `runlog` demands at `seconds` only the written
  criterion instead of the freeze, and the hook `claude-hook pre-run` does not run
  preflight; it only reports whether the criterion is present.

  **At `seconds`, the machine checks the provenance.** Audits of runs
  that take seconds repeatedly found one family of problems: counted unit and denominator. A
  weakness that an agent has to find anew every time is a missing
  invariant; therefore the following applies there:

  - `finalize` refuses a run without a frozen source (`data=`) and
    one with source or output outside git;
  - the skeleton reads directories only via `visible()` (no hidden
    entries, no subfolders), takes the denominator from the source instead of from
    the generated rows, and refuses on a missing entry;
  - the seconds cut carries the required field `Unit`, because no check
    knows whether "document" is the right unit.

- **LAB-018 · Routine check after every implementation.** *(was §2.A15)* A full audit is too
  expensive to run after every implementation step; without a cheap
  intermediate check none ran at all, and errors made it through to the freeze. The
  routine check has two parts:

  1. `code-check <area>` (labkit) decides without a model what can be decided from the
     source: Every identifier appears as a key literal in the
     scripts (LAB-004 Identifiers make the intent addressable; `intent-check` asks the same question only after the
     run, when the tokens have already been paid for). It also extracts schema facts
     — which keys the data rows carry and which fields that are read
     are missing there — and the **gate labels**: which strings the
     analysis code compares with the model's answer, constants resolved.
  2. `code-check <area> --bundle FILE` puts the protocol, scripts,
     imported `lib/` modules, these facts and the severity legend
     (LAB-015 Preflight audit before freezing) into one file. The subagent `code-check` reads only that file and
     answers three questions that no parser answers: Are there obvious
     mistakes? Does the code mean what the registration says? Do the
     gate labels match the literal prompt (LAB-038 What the prompt demands)?

  **The mechanical checks claim only what is provable.** Whether a field access is covered
  depends on the data flow across stages and areas; a model reads that
  well and a parser does not. The mechanics therefore stop at the facts, and
  the judgement stays with the audit. For every check that a script takes over, the
  false-alarm rate is the acceptance criterion, not how many defects it catches: A
  tool that reports false blockers gets switched off.

  **What audits found repeatedly, the machine checks:**

  - `runlog` refuses a run whose control set (`data=` keys
    `anchor*`, `gate*`, `placebo*`, `control*`) shares an id with the measurement set;
  - `code-check` blocks a `parse_*` function without a test and a
    prompt block in the protocol that deviates from the `PROMPT` constant;
  - `finalize` warns when a `c<i>_n` does not correspond to any recorded input count.

  What remains for the agent is what no gate reads: the direction of a control, an
  unnamed confound, whether the number matches the sentence that promises it.

- **LAB-019 · The stamp covers everything that determines the number:** *(was §2.A16)*
  measurement scripts, analysis scripts, the repo-local `lib/` files reached
  by import (shared anchors and thresholds live there), and the labkit pin.
  Otherwise the stamp is itself an incomplete provenance. It is computed by
  `scope-sha` (labkit), never by a shell one-liner; it finds the imported
  `lib/` modules itself, and further files can be included:

  ```bash
  scope-sha --area experiments/<area> [further-file.py ...]
  ```

  It prints the files included in the computation, the pin line, and `scope sha <12 hex>`.
  The path (relative to the repo root) **and** the content of each file are included:
  adding, removing, renaming and editing change the stamp; the working directory and the spelling of the path do not; a missing file aborts instead of silently passing through. `preflight` and `labkit-audit`
  compute the same stamp.

- **LAB-103 · The audit reads by declared scope, not by import graph.** The
  stamp answers "what determines the number" and must cover everything
  (LAB-019 The stamp covers everything that determines the number). The audit
  answers a different question — does the code do what the registration
  promises — and reads what that question needs: the protocol, the area's
  scripts and analysis files, every file a `[[promise]]` table declares as
  its scope, and the repo-local modules those files import directly. Modules
  further down the import graph are the instrument's internals; the auditor
  gets them as an index (path, top-level signatures, first docstring line),
  not as text, and reads one only on an assignment: when a finding or an
  output row points into it, the finding names the module and the caller
  supplies it. The declared scope is the registration's own statement of
  where a promise lives; an audit that reads by import graph instead audits
  the repository, not the promise, and in an area whose scripts import the
  system under test it reads that whole system for every number (uniagent,
  2026-10-10: 280 of 444 kB were the agent under test, the declared scope
  was one function). `labkit-audit` builds the prompt this way; the `scope:`
  list the auditor returns names what it read in full, the caller adds the
  indexed modules before holding the list to the stamp.

### 2B · The Data Path — raw → prepared → Result

- **LAB-020 · Materialize transformations:** *(was §2.B1)* Never perform data formatting or preparation
  on the fly in the experiment script; use a separate step that
  **writes a visible intermediate file** (`data/raw/` → script → `data/prepared/`);
  the experiment reads only `prepared`. Why: to be able to *look at* the data before the
  model sees it; formatting errors can be separated from model errors; diffable;
  the `runs.tsv` config references the prepared file (reproducibility).
  The preparation step also **computes the confounds in advance** — length,
  overlap, and **markers per gold class with an explicit null check**: A
  surface feature (hedge, modal word, template) that occurs in only one class
  is not a correlation but a giveaway rule — the model
  reads the class off the marker without solving the task. One-sided
  filters: LAB-032 Free knobs.

- **LAB-021 · No dataset without a producer.** *(was §2.B2)* The rule above requires a *step* — that is not enough. What is required is a **named, re-runnable script per file** under `data/`, and that includes what looks like an exception: hand-picked seeds, subsets drawn by hand, and above all subsequent **adjustments** (filter changed, balance corrected, column added, file renamed). Changing means changing the script and regenerating, never editing the file; a variant gets a new name, the old one stays in place. Name producers uniformly `scripts/00_*.py` — otherwise a missing producer cannot be found.

- **LAB-022 · Datasets explain themselves.** *(was §2.B3)* Three rules, one helper:
  1. *Name:* The file name says, without context, what ONE row is
     (`world_pairs_v1.jsonl`, `story_cells_v2.jsonl` — never just `pairs`
     or `items`). `_vN` counts regenerations **of the same meaning**;
     if what a row *means* changes (also: field renamed, values
     recoded), that is a **new name** — old analyses against the
     old file remain valid, instead of silently breaking.
  2. *Fields:* English, no mixing of languages, every enum value
     spelled out and self-explanatory.
  3. *Legend at the home:* The producer defines `ABOUT` (one sentence) and
     `FIELDS` (name → half-sentence + values) and writes both as a
     `_meta` header line IN the file — `batch.write_dataset` does this
     and checks every row against the legend (field drift is caught
     at write time, not at analysis time). Reading helpers
     (`Store.records`, `answers.read_jsonl`) skip the header line;
     whoever opens the file reads first what it is.

- **LAB-023 · No silent loss:** *(was §2.B4)* every stage that turns model output into data
  reports its **yield** (expected vs. obtained); discarded rows are
  logged. A silent parser is indistinguishable from a model failure —
  and the pilot does not notice it, because what survives looks good.
  Rescoring produces a **new file** (overwriting in place
  destroys the raw answers of the affected items).

- **LAB-024 · Reproducible:** *(was §2.B5)* Script + data + output together, deterministic where
  possible; save incrementally for long LLM batches.

- **LAB-025 · Two-user rule: the computation is shared, not the verdict.** *(was §2.B6)*
  Experiment-specific material (rendering, construction, evaluation — success and
  admissibility conditions, contrasts) stays in the script of its area: the analysis IS the
  experiment. Mechanically neutral material — statistics, parser cores,
  text normalization, a prompt wording that a second area needs
  verbatim — moves to `lib/` on the SECOND use, with a test first: an
  error there changes reported numbers without any run showing it.
  Scripts that have already run keep their copies (history is not retrofitted);
  the module serves the next area.

- **LAB-026 · A reused component brings its bugs with it.** *(was §2.B7)* Adopting an
  artifact from the system under study (its extraction, its
  splits, its labels) "to avoid building a new source of error" imports
  its bugs instead. Measure the quality of the component first, then
  adopt it.

### 2C · The Instrument — what is asked, and what it is measured against

- **LAB-027 · Model discipline:** *(was §2.C1)* Experiments **never** hard-code an endpoint or model ID — via the project scaffold (`lib/llm.py`) they call an
  **alias** from `models.toml` (repo root; the only place for cluster addresses).
  `llm.resolve(alias)` returns the full spec → it belongs in the runlog config,
  so that `runs.tsv` records **which model** answered. runlog
  handles this itself: config keys `model`/`*_model` are resolved as `models_resolved` when
  freezing, and a missing
  `requirements.lock` triggers a loud warning instead of silently noting "unpinned".
  The `models.toml` template ships with `haiku` (claude-cli, headless-safe);
  Ollama models run on the lab's own servers. Special calls (logprobs) obtain
  endpoint and model via `resolve()`, never as a literal.

- **LAB-028 · An endpoint is a model slot, not a service.** *(was §2.C1a)* At the swap proxy,
  several aliases point to the same GPU slot: whoever requests an alias that is not loaded
  evicts the running model from memory (measured at ~5 minutes per
  switch). **Two stages with different aliases do not run in parallel there;
  they displace each other.** The damage does not stay on the wall clock, it ends up in
  a reported number: swap thrashing → timeouts → exhausted attempts
  return empty answers → rounds without a parsed mechanism → the stop rule
  "more than 2 of 96 empty → the parser is the finding" counts them and calls
  operational noise as parser quality.

  This is gated mechanically, not by good intentions: on its
  first call `llm.complete` takes an **endpoint lease** (labkit `endpoint_lease`: an
  entry that occupies the model slot for this process) — the same
  alias may run concurrently (costs throughput, never a swap), a different alias
  is rejected immediately, a process never locks itself out (a script that runs
  generator and judge one after the other is exactly the sequencing
  that is wanted). Dead leases are collected via the PID check,
  undecidable ones count as alive (a false rejection costs a
  message, a false admission costs the run). Deliberate exception:
  `LABKIT_NO_ENDPOINT_LEASE=1`. Limit: the lease is local — a run from
  another machine is invisible to it.

- **LAB-029 · A harness is not an inference API: its context is isolated
  and stamped.** *(was §2.C1b)* A backend that runs as an agent harness (claude-cli)
  carries the operator's context along on every call — settings,
  memo-pad files, its own system prompt. The prompt in the protocol
  is then not the whole prompt. What is not in the protocol must not
  be in the call: labkit calls claude-cli with an empty settings-source list
  (`--setting-sources ""` — no operator settings, no CLAUDE.md) and
  without tools (`--tools ""` — a judgement is an inference, not an
  agent session), and `llm.provenance()` stamps the CLI version and
  isolation flags on every row.
  Limit: the harness's own system prompt stays in and is not
  recorded; the harness does not control sampling (temperature, exact token budget) — whoever needs that uses the SDK.

- **LAB-030 · Reasoning models: the token budget goes to thinking first.** *(was §2.C2)* In a
  model with a visible thinking trace (gpt-oss and relatives), 
  `max_tokens`/`num_predict` is consumed **first** by the chain of thought and only then by the answer.
  If it does not reach the end of the chain, `response: ""` comes back, with
  `done_reason: "length"` — and that looks like a model failure or a
  parser bug, but is a budget setting. Two consequences: **always check empty
  answers against `done_reason`** before reading them as a model finding;
  and when estimating run time, allow for the fact that heavy items think for a long time
  (the same cause produces timeouts that look like an overloaded server).
  **A binding cap is a defect, not a knob.** As long as `done_reason`
  is never `length`, the budget is invisible and may stay frozen.
  As soon as it binds, it produces *not a different answer, but none at all* — then
  raising it is a **repair** and is legitimate even after freezing, with
  its own output file (two caps do not belong in one file), an entry in the
  protocol and a new freeze. Anyone who says "the knob is registered" instead
  freezes the error in with it. Two duties here: count empty answers as
  **a state of their own** (do not interpret them as "did not refuse" or the like),
  and report their number **per gold class** (LAB-032 Free knobs: vary them and report the curve): If the cap binds
  unevenly, it is the same error as a one-sided filter, only on the
  answer side.

- **LAB-031 · Whoever wants a difference asks for the difference.** *(was §2.C3)* Eliciting two levels
  and subtracting them goes wrong as soon as the levels sit at a boundary
  — and you cannot tell from the difference. The **answer form is a
  free knob** and must be justified before the run: How many distinguishable
  states does the answer have, and where does the expected value lie within them? Rule of thumb: *relative
  beats absolute, categorical beats graded, anchored beats
  free-floating.* The **forced answer** (stalemate default, "only the
  letter") is also such a knob: check the effect of each wording variant
  against anchors.

- **LAB-032 · Free knobs: vary them and report the curve.** *(was §2.C4)* Setting every
  preprocessing parameter (threshold, filter, cutoff, window size) a priori
  is right — but then report the sensitivity sweep, not
  the point; a value validated for purpose A is unchecked for purpose B. A
  filter can prune the classes asymmetrically — then the knob
  itself is part of the measured quantity. Remedy: apply the filter to the **matched pair**
  (if one side drops, the other drops with it) and report the **yield per
  gold class**, not just the total count.

- **LAB-033 · A parameter that is accepted and discarded is the most expensive bug.** *(was §2.C5)*
  The signature accepts it, no error is raised, and because it has a default,
  every call looks right and has no effect. Two rules follow: **tests check the
  payload that is sent, not the signature** — a test is green only once it reads
  the JSON that goes out. And **for unexplained timeouts, read the server log
  first**: it distinguishes "slow" from "writes endlessly" in one line; from the
  outside the two look the same.

- **LAB-034 · Null condition in the same run:** *(was §2.C6)* Every measure includes something whose response *must* be zero — anchors with a known rate, placebo items, a swap control. An instrument that responds at idle is not calibrated, and preregistration does not detect that: it protects against re-tuning, not against a scale that drifts even without a signal.

  > Where a null condition accompanied the run, the error was caught; where none did,
  > a wrong number was close to making it into the report.

- **LAB-035 · Thresholds belong to the run, not to the measure.** *(was §2.C7)* What can be preregistered is the *rule* ("defeating means above the noise floor"), not the *value*. A threshold with no reference to the null condition of the same run is a number without a unit — the same number can be right on other material and wave everything through here.

- **LAB-036 · Validate, don't trust a single run:** *(was §2.C8)* Second model/self-consistency, known
  anchors (items with a known outcome), cross-check against an
  independent second signal source.

- **LAB-037 · Every anchor carries its target and rationale.** *(was §2.C9)* Every
  accompanying anchor needs not only the expected deflection but also a
  half-sentence on why this side must win. An unjustified target is itself
  unchecked — it looks like a control and is a claim.

- **LAB-038 · What the prompt demands, the gate checks — from the same
  constant.** *(was §2.C10)* A rule that both appears in the instruction and is
  enforced by a validator (forbidden list, answer format, value range)
  has ONE home: the constant from which the prompt is rendered and
  which the gate checks. If rendering is not possible, a test holds the RENDERED
  prompt against the gate constant — equality can be checked instead of asserted
  (the same logic as for shared prompts, LAB-067 A prompt has one home, which the run freezes). Two versions of the same
  rule in one script are the two-truths trap in miniature.

- **LAB-039 · Anchors include the near cases.** *(was §2.C11)* A gate that was checked only on clear cases counts as unchecked, because the errors happen at the boundary. Anchor sets therefore carry boundary cases (ideally, verbatim, the cases on which the last version failed), and the report separates near from clear: A missed near anchor is a resolution limit (registered branch, LAB-013 Registered branch when the run can answer two questions), a missed clear anchor an instrument defect.

### 2D · Afterwards — analyzing and reporting

- **LAB-040 · Check the output, not just the numbers.** *(was §2.D1)* In every review, *read* concrete
  examples / raw output to understand the **mechanism** —
  aggregate metrics hide it: an effect can be visible
  in the individual cases while the metric stays unremarkable (and vice versa). **The relevant
  raw output (concrete model answers) belongs IN the measurement note or protocol**, not
  just the metric — otherwise nobody knows what the model did. Scripts save it
  (e.g. to `results/`). **Raw-output duty also in result notes: one real
  prompt+answer pair per finding** — a number without the output behind it can no longer be interpreted
  in three months.

- **LAB-041 · Generate numbers, don't retype them.** *(was §2.D2)* One analysis script per area
  (`scripts/02_analyze.py`, stamped with the area), which prints the table and uses `--check` to
  verify it against the note its `NOTE` names — the protocol, or the result note once the number
  is promoted; `report-check` holds that the check passes. **Every parser that turns model output into data has a
  test with real raw answers**. Freeze data sources via
  `runlog.run(..., data={...})` (path, sha256, rows,
  split-leak check). With `--check`, **normalize the characters** (decimal comma,
  typographic minus U+2212): A checker that trips on the separator instead of
  a real deviation will soon be ignored.

  **Identifiers are exact; descriptive items may be added.** `metrics.json` carries
  two kinds of keys: the registered identifiers (`c1_pass`, `a1_…`,
  `b1_…`, LAB-004 Identifiers make the intent addressable) that `intent-check` holds and that must match
  exactly on a recomputation, and descriptive keys (funnels,
  tables, lists). If `evaluate()` gains a descriptive key,
  that does not force a new run: the recomputation over the same raw rows
  is stamped as a **derived run** (`runlog.run(...,
  derived_from=<run_id>)`) that names its parent run; `--check`
  compares identifiers exactly and requires of descriptive keys only
  that none from the parent run disappear. A new run is made when an
  identifier, a raw row or the instrument changes.

- **LAB-042 · Log the outcome — failures too.** *(was §2.D3)* A negative result (no
  measurement effect, low/chance score, null result, degenerate or
  collapsed behavior) is **signal** and belongs in the documentation — not only the
  successes.

- **LAB-043 · Runs go through `runlog`** *(was §2.D4)* (labkit; run index `runs.tsv`, frozen config, run_ids instead of typed-in numbers). Applies **going forward** from its introduction — do not retrofit old runs/notes. Applies to **every stage whose artifact is reused** — including preparation and analysis, not only the expensive LLM run. The throwaway test is exempt (scope, top of chapter 2): from the moment a number is kept, cited, or becomes the basis of a decision, the protocol and runlog apply.

  **A run names its protocol.** Every protocol carries an `id` in its head, and every run records it; the checks pair protocol and run via this identifier, never via the directory and never via the file path. An area with one protocol binds automatically; with several, it requires the identifier to be given — otherwise the run does not start. A run is complete only with a result **and** a confirmed completion; no number is reported from an aborted run, even if it is on disk. Contract: `~/projects/labkit/docs/protocol-run-binding.md`.

  **Two homes for the run_id, not four.** The reported run_id is in the protocol (sections Runs and Result) and in the `## Sources` line of the result note — there `scripts/02_analyze.py --check` verifies it (with `NOTE` pointing at that note). Every other note (instrument note, lab notebook, theory) cites the result note via wikilink and carries no run_id; otherwise every repeat run drags four places along, and one of them stays behind.

- **LAB-044 · The check on a confound is code, not a paragraph.** *(was §2.D5)* Every rival explanation noted in advance comes with two things: the **error direction** (does the confound run for or against the hypothesis?) and a check computed by `evaluate()`. A check that is only described is a claim.

- **LAB-045 · The forecast comes before the follow-up run.** *(was §2.D6)* The expected number is written into the protocol before the next run starts. Only a recorded forecast can hit or fail; an expectation remembered after the fact always hits.

- **LAB-046 · Notebooks: explore yes, report never.** *(was §2.D7)* Exploratory data views
  (distributions, plots, getting a feel for new material) may go into a notebook —
  but as a git-diffable `.py` (jupytext py:percent or marimo, never `.ipynb`)
  and under `experiments/<NN>/explore/`. The throwaway-test boundary from
  LAB-043 Runs go through `runlog` applies: as soon as a number is kept, cited or becomes a basis for decision,
  the code moves to `scripts/` + runlog — nothing is reported from a notebook.
  The entry point before the area: `labkit-init exp <name> --explore` creates
  `experiments/explore/<name>.py` (cells: question · items · render · check ·
  real `evaluate()` · verdict; helpers via import, never as a copy); the later
  `labkit-init exp <name>` moves the file into the area. Reason: protocol-check,
  runlog, commit-before-run and the layering rule rely on diffable
  plain text with a fixed
  execution order; a kernel with cell state cannot
  freeze what ran.

- **LAB-047 · A partial run is not a random sample — no anchor catches that.** *(was §2.D8)*
  If the input is sorted by anything that correlates with the measured quantity
  (topic, type, source, id ranges), a crashed, aborted
  or `--limit` run covers one corner of the space, and its distribution is an
  artifact. Two habits: process **round-robin over the strata**
  (then every prefix is representative) and **check coverage before** a
  partial result is interpreted.

- **LAB-048 · An intermediate number is not a result.** *(was §2.D9)* Representative sampling
  protects against order bias, not against small cells. Every
  intermediate number comes with its **cell size**; a preregistered criterion counts
  as met or missed only at the preregistered n.

- **LAB-049 · Long runs go through the harness's background mechanism,** *(was §2.D10)* never
  `nohup` plus a foreground wait loop: if the foreground command runs into
  its timeout, the child dies with it (two runs lost this way). Related:
  `script.py | tail` reports the exit code of *tail* — a dead run looks
  successful. Check the artifact, not the shell exit.

- **LAB-050 · Analysis audit before reporting.** *(was §2.D11)* The same procedure as
  LAB-015 Preflight audit before freezing in mode `analysis` (subagent or `labkit-audit <area> --mode
  analysis`), applied to the analysis (`02_*`, `03_*`, `analysis/*.py`) against the
  **frozen** criterion — before any number moves into a note or paper.
  Rationale: The analysis *is* the experiment (section 2G, layering rule); half of the
  scars in LAB-015 Preflight audit before freezing were there rather than in the measurement code. A requested change to the
  criterion is, at this point, itself a finding, not a recommendation.

  So that the rule does not again depend on a person, it has its own gate: a
  report field (†), due when the number is written back —

  ```
  - **Analysis audit †:** 2026-09-09 · scope sha 8b1e6d0a4c31 · 2 findings
    (1 blocker fixed: r² now leave-one-anchor-out, 1 dismissed: <reason>)
  ```

  With `cost = "seconds"` this is the **one** audit of the
  experiment; when it comes and what it also covers is governed by LAB-017 The number of audits follows the cost tier.

### 2E · The LLM Judge as a Measuring Instrument

Scope: **only when an LLM judge is the instrument**. This is not a mandatory part of every research setup. These rules were earned in a judge-screening series (eight instances, four failure modes).

- **LAB-051 · Judge instance, not model name.** *(was §2.E1)* A judge is the tuple
  *model × quantization × chat template × endpoint × readout* —
  every axis has changed the measurement result at least once
  (ollama-Q4 vs. vLLM-AWQ; /v1 halves the temperature scale;
  repo templates broken/missing → pin the template in your own config).
  Instance change = instrument change.

- **LAB-052 · Instance gate before registered use.** *(was §2.E2)* Every new instance
  passes through an anchor gate (~160 calls) before items run;
  the gate does not merely reject, it *diagnoses* (no
  content signal / presence reflex / no midpoint /
  choice refusal). 160 calls instead of 8,000 for the same answer.

- **LAB-053 · Resolution anchor.** *(was §2.E3)* Alongside full-scale and null anchors, a
  deliberately *mild* case that must genuinely land **between** its neighbours
  — it should separate graded judges from binary judges. The text must be
  TRULY mild and must itself be calibrated in an instrument
  check — one that is too strong reads as full-scale even for demonstrably
  graded judges and convicts the innocent;
  the binary diagnosis additionally needs independent evidence (e.g.
  collapsed item distributions).

- **LAB-054 · Self-consistency requirement for logprob readings.** *(was §2.E4)* Per cell:
  argmax of the reported distribution == generated token at
  temperature 0 — as a self-test of the instrument at runtime.

- **LAB-055 · Check polarity symmetry.** *(was §2.E5)* "Which is more likely" and "which
  is less likely" are logically the same, but not in measurement terms; the
  asymmetry signatures are diagnostic
  (priming push, competence collapse, question-driven reflexes). A
  400-call anchor check per instance settles this in advance.

- **LAB-056 · Recompute thresholds unrounded.** *(was §2.E6)* Analysis/`--check` scripts
  rebuild rules and zones from the raw quantities, never from rounded
  metrics (one item sat exactly on 0.775 versus float 0.774999… —
  run and recomputation classified it differently).

Related, but so far supported only one judge deep (caveat, not a rule): The vote scale needs a stochastically responding judge; grading can come from the diversity of sampled reasoning paths rather than from the first-token distribution.

### 2F · Test several ideas in parallel (lightweight)

Goal is **fast evaluation before scaling**, i.e. as little ceremony
as possible. The rules from LAB-057 One area per idea to LAB-060 Look it up
instead of asking cover the only truly shared resources; those from
LAB-061 Sub-experiment series carry their number to LAB-065 No worktree per
experiment govern how a growing area stays readable.

- **LAB-057 · One area per idea** *(was §2.F1)*, self-contained; never share outputs. An
  `--out` file belongs to exactly ONE run: the script places `<out>.lock`
  next to it and aborts if it exists. The output file *is* the
  state, it drives resumption; two writers skip each other's
  items.

- **LAB-058 · `data/prepared/` is read-only after writing.** *(was §2.F2)* First
  prepare, then fan out. A variant gets a **new name**;
  regenerating the same file may leave a concurrent run reading half a
  file.

- **LAB-059 · Use shared helpers, don't modify them within a run.** *(was §2.F3)* `llm`, `runlog`
  (labkit) and `models.toml` carry the discipline (backend resolution,
  run index, raw output); every experiment uses them instead of building its own variants.
  Anyone who *rebuilds* them does so in their own worktree or branch: A
  change **never** reaches running processes and reaches new ones **immediately**, both
  invisibly. (`llm.resolve` freezes the backend setting per process, so that
  a host change in `models.toml` does not redirect a running run.)
  **The same applies to EVERY running script**, including the measuring script of
  your own area: Python keeps the old version in memory, the run does not
  change, but its **traceback points to the new line numbers** and
  thus into nothing. Repair first, then start; what actually ran is recorded
  in `runs/<id>/script-source.py`.

- **LAB-060 · Look it up instead of asking.** *(was §2.F4)* `.venv/bin/runlog <area>` lists
  all runs that are not completed — with pid (running / crashed), script and
  input/output from the `config.json`. Whoever starts an experiment looks
  there and switches to a different output instead of asking.

- **LAB-061 · Sub-experiment series carry their number in the name.** *(was §2.F5)* If an
  area grows beyond ONE protocol, the protocols are named
  `PROTOCOL-s<N>-<slug>.md` (including the first) and the scripts
  `s<N>_prepare.py` / `s<N>_measure.py`. The sub-experiment number IS the
  sort order; a running counter alongside it makes the folder unreadable.

- **LAB-062 · Reorganizing existing material is allowed — as a package.** *(was §2.F6)* Organization
  beats strictness, but in the same commit: update current references (protocols,
  README, docstrings), put an **old→new map** in the README,
  and then run one functional check (`--eval-only`) for each renamed script.
  `runs.tsv`, the `runs/` snapshots and
  `_meta.producer` keep the old names; they describe what ran back then,
  and are never touched.

- **LAB-063 · A research line has one entry point.** *(was §2.F7)* The area README carries an
  **Executive Summary**: the research line's question, one paragraph of history, a table
  gate × question × result × verdict, open threads. The protocols remain the
  evidence layer; the summary stands on its own, without anyone having to open every protocol.
  When a research line concludes (or flips), the overview moves as a
  consolidation note to `notes/`: finding first, numbers with
  run_id references, named open interpretations.

- **LAB-064 · The pilot is resumable too.** *(was §2.F8)* The pilot may be rough
  (`--limit`, little analysis, quick decision), but it does not forgo
  resumption after an interruption: a dropped connection costs a pilot as
  much work as a large run. The shared helpers provide it for free:

  - `llm.complete` retries **transport errors** (timeout, connection drop)
    and **counts** the attempts; `llm.retries()` belongs in the run metrics,
    so that a run that limped along remains distinguishable from one that
    ran straight through.
  - `batch.Store` provides lock, **resumption via `id`** and status:
    `pending()` skips what is already in the output file, `append()` writes
    one flushed line per item, `status()` says what is missing without
    model load time. Resumption is thus *the same command again*.
  - **Orphaned lock after a crash:** The lock file names the PID that held
    it — first check `ps -p <pid>`, then remove it. Deleting blindly risks
    two writers on the same file, waiting blindly blocks on a dead process.

  Custom code in the area is only worth it for what these helpers cannot do:
  checkpointing during training, sharding, special rate limits.

- **LAB-065 · No worktree per experiment.** *(was §2.F9)* The area structure already isolates, and a worktree per run scatters outputs and run index across copies. For refactors of shared code, however, **yes** (LAB-059 Use shared helpers, don't modify them within a run).

### 2G · The layering rule — what is shared, what stays in the script

Shared and tested are **question form and recording**: labkit provides `llm`, `batch` and `runlog` (pinned, imported directly: `from labkit import
runlog`), and repo-local helpers such as `elicit`, `stats` and `prompts` grow in `lib/`. No script ever writes an HTTP call, a logprob sum or an AUC itself.

The **analysis is the experiment** and stays in the script: criteria (success as well as admissibility) and contrasts do not become framework options. Whoever opens the script reads the experiment.

- **LAB-066 · Extract only for the second user** *(was §2.G1)*, with tests as a condition —
  the two-user rule, spelled out in LAB-025 Two-user rule: the computation is shared, not the verdict.

- **LAB-067 · A prompt has one home, which the run freezes** *(was §2.G2)*.
  A prompt is an
  instrument setting, and three things hold for it: **one home**
  (no copy that drifts away), **frozen per run** (which wording
  answered is recorded in the run record — `runlog` freezes the script, the
  profile fingerprint covers named files), **verbatim in the protocol**
  (the field *Prompt* shows what the model saw). The home is the script
  — or a file that the profile names and the fingerprint covers
  (for example `register/prompts/*.md`, `register/rule-texts/*.toml`: a
  rule-text swap there is a diff of two files, not a diff in
  Python strings). If a second area needs the same wording, it is
  shared, not copied (`lib/prompts.py` or the same file); then "identical" is verifiable instead of asserted (`tests/test_prompts.py`).

- **LAB-068 · New areas start from the template-generated skeleton** *(was §2.G3)*
  (`scripts/01_measure.py`: `--show` renders without a call, `--probe` is the
  instrument check in the real pipeline, `--eval-only` re-evaluates without a
  model call).

- **LAB-069 · No LLM cache.** *(was §2.G4)* It silently destroys the repetition spread: identical prompt → cache hit → spread exactly 0, and the resolution lower bound would look perfect. `batch.Store` and `--eval-only` cover the need for later adjustments.

### 2H · The port into the reproduction repo

- **LAB-071 · The proof is the item-wise diff, not a tolerance band.** *(was §2.H2)* If the lab has an item-wise reference run, the port proof is the per-unit diff with the same model, the same quantization and `T = 0`: identity except for the units that a known fix touches; every other deviation is a port bug. In addition, the model state is pinned and recorded: digest (tags are movable), server version, `num_ctx` (ollama silently truncates over-long prompts at the front). The evaluation reports both denominators, scored items and all items with skips counted as wrong. A plan with a "targets" table carries no remnants of older versions: when in doubt the table wins, and then the wrong thing gets built.

- **LAB-072 · Identifiers travel in English.** *(was §2.H3)* All identifiers, registry names,
  file names, data fields and ids are translated during the port; only
  provenance references to real laboratory paths stay German, because they are addresses, not
  vocabulary. Prompt bytes remain untouched (pinned instruments); for
  datasets, update the `.sha256` if ids are part of the bytes.

## 3. Provenance

- **LAB-074 · Note and commit carry the why; reconcile:** *(was §3.1)* new insight
  contradicts old note → fix the old one (never two truths).

- **LAB-075 · Docs carry the state, commits the change:** *(was §3.2)* no history sentences
  ("since <date>", "previously held") in MDs, source-code comments and
  TeX skeletons ("settled <date>", "previously undefined") — only the valid
  rule; the why
  of the change goes in the commit message (`protocol-check` warns).
  Exception: load-bearing old→new tables, as long as the run index and documented
  runs still use the old names.

- **LAB-076 · Restriction convention:** *(was §3.3)* Anyone who qualifies or refutes a note puts
  a blockquote in **the restricted note**, directly under the heading,
  that links the new note — machine-readable for a findings register.

- **LAB-077 · Own commits, others' state stays with the user.** *(was §3.4)* Before the first
  change of your own, run `git status`. A dirty state found there belongs to the
  user: report it, never include it in your commit. Your own commits stage only your own paths
  (`git add <path>`, never `-A`), so that the starting state and your own change
  remain separable. If the task must touch a dirty file, first give the
  user the commit command for the existing state. After that, one commit per
  completed step, as soon as tests and linter are clean; never several
  plan steps in one commit. LAB-010 Commit before the run is the special case that applies before a run.

## 4. Classifying

- **LAB-079 · Self-contained experiment areas:** *(was §4.2)* data + scripts + output + README.

**LAB-082 · In `notes/messung/`, every note carries its kind in the meta line** *(was §4.5)*,
directly after the purpose (schema above; a restriction blockquote *before* the
meta line remains allowed — the findings register reads exactly that one):

| Kind                         | Meaning                                                     | Rule                                                                                                                                                |
|------------------------------|-------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------|
| `Instrument — Entwurf`       | Named measurement procedure, no load-bearing code yet       | Dossier: stays the **same** note until implementation                                                                                               |
| `Instrument — implementiert` | Procedure with load-bearing code                            | MUST name script/function/area path                                                                                                                 |
| `Related-Lesart (<citekey>)` | Lab reading of a paper: what it means for *our measurement* | name the cite-key; **should-rule (no check):** no summary duplicate — the library note is canonical; project-neutral takeaway → its `# Notes:` part |
| `Referenzkarte`              | Glossary, register, terminology, source map                 | —                                                                                                                                                   |
| `Audit`                      | Design/preflight audit as a note                            | —                                                                                                                                                   |

- **Kind is declared, never derived from code mentions** — a
  reference card may name dozens of scripts, a draft may
  cite foreign code. The gate (`notes-check`, labkit) only checks presence and
  inconsistency (declared "implementiert", but names no code).
  Contract regex tolerant of dash variants:
  `Instrument\s*[—–-]\s*(Entwurf|implementiert)`.
- **Instrument dossier lifecycle:** As soon as a measurement idea has a **name +
  procedure** → its own note in `messung/` (draft). The implementation
  flips the status **in the same note** (add code reference) — no second
  note, the design rationale stays with the documentation. Ideas *about this
  instrument* (variants, weaknesses) live in the dossier; loose brainstorms and
  collection notes stay on the work side, but point to any dossiers that have emerged.
- The established genre words ("explainer note", "conjecture note",
  "principle note" …) remain **allowed as a purpose description** — they stand
  after the kind in the purpose slot, but do not replace it.
- The axis *sketch vs. settled* (chapter 1, claim status) is independent of this
  and may additionally appear in the meta line; `superseded → [[…]]`
  marks an outdated note together with its successor.

## 5. Notation standard

**The glossary is the single source of truth for terms — project-wide, not
per experiment.** Every experiment area, every script, every note uses
*the same* terms; anyone who needs a new one enters it in the lab's glossary (`notes/theorie/terms.md`, see LAB-084 Double-coinage check) instead of introducing it locally. Otherwise the areas drift apart in their terminology and
results become incomparable — the same logic as with `models.toml`
(backends in one place) or the run index (`runs.tsv`). Code and prompts in English, notes in the lab's working language; an ambiguous term is pinned in a
definition note.

- **LAB-083 · The name carries what it denotes.** *(was §5.1)* `--distance-cell`,
  not `--cell`; `support_shift`, not `tau`. A symbol (Δ, q_u) is
  a secondary name alongside the plain-language one, never the only name. If a
  workshop term appears in a second area, it is pinned in the glossary —
  area-local terms are covered by the protocol's required field "Begriffe".

- **LAB-084 · Double-coinage check — first the field, then the lab, then the existing stock.** *(was §5.2)* Before any new coinage, two searches. (1) *Field stock:* What does the field call it — in the course material and
  literature the lab works with (a lab may keep a searchable index of it)? If
  there is a term, it is used,
  even if one's own sounds catchier: shared vocabulary is worth more
  than a better individual name. (2) *Lab stock:*
  `grep -ri <candidate + synonyms> notes/`; if a lab term exists, it is inherited, never coined twice. **Four homes, one per kind of term:** *Method* (criterion, admissibility condition, registered branch, arm, draw) →
  the vocabulary table of this standard; *Tool* (answering run, derived
  run, stamp) → labkit README "Terms"; *Lab* (rival, gap case,
  coverage per case) → `notes/theorie/terms.md` of the repo, per line
  everyday word · lab term · code word; *a protocol* → its field
  "Terms of this protocol", first field of the intent. Look up in this
  order: field, method, tool, lab; what is found
  is inherited. If neither of the two searches finds anything, the coinage is free
  and belongs in the core glossary. And if the same word already means two things
  (typically: a technical term and a colloquial usage), *one* of them is renamed and the convention recorded here — not "the context will make it clear".

- **LAB-085 · Mark your own coinages as such.** *(was §5.3)* Where an established term exists, use it (with source); make original coinages recognizable, so that they are not passed off as standard in the paper.

- **LAB-086 · Values rule (codes are names too).** *(was §5.4)* Field values and condition codes
  are subject to the same test questions as identifiers. Compact codes (cells
  of a design) are admissible under three conditions: **fixed slot grammar**
  (same position = same dimension, a slot never changes its
  meaning) · **one legend at the home** (every other place refers to it in at
  most one sentence instead of explaining it anew — growing explanatory prose around
  codes is the warning sign) · **inherit instead of re-coining** (adopted codes
  keep name and meaning; rename bad names at the source,
  never alias them locally).

- **LAB-087 · Term before use.** *(was §5.5)* A term is defined before an experiment uses it in a prompt, field name or file name.

- **LAB-088 · Look up field notation, don't invent it.** *(was §5.6)* For ML/NLP/IR, a lab keeps — or adopts — a ready-made core vocabulary on one
  page (modeling O/γ/α/X/y, feature vector and feature space, running indices
  n/p/k/d, the layers of the ML stack). When writing about ML, look there first
  — the terms are already laid out and do not need to be searched for. What it
  lacks is searched as in LAB-084 Double-coinage check.

How a coinage appears in prose — everyday word first, the coinage at most once in parentheses, English coinages only in code and config keys — is governed by LAB-092 Term layering.

If the project grows, a dedicated **terminology note** (`notes/…`) that maps the project's own terms against the literature (term ↔ standard term ↔ source ↔ status) is worthwhile — what the table below does for labkit's terms.

### Labkit terms and established terminology

*Purpose (LAB-085 Mark your own coinages as such): never present a labkit
coinage as established — a paper uses the established term, and the coinage
remains explanatory prose. Terms without a row here are established (gold
label, confound, pilot, self-consistency, run index). Four coinages are
labkit's own and defined here: area, promise, scar table, free knobs.*

| Labkit term                          | Established term                                                     | Source / note                                                                                                                                            |
|--------------------------------------|----------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------|
| Area                                 | no fixed term; closest: study folder                                 | one directory under `experiments/`: protocol, scripts, data references, runs — the unit every labkit check works on                                      |
| Promise                              | preregistered hypothesis or analysis-plan item                       | one row of the protocol's promise block — a criterion `[C]`, an admissibility condition `[A]` or a registered branch `[B]` — that the code must keep     |
| Scar table                           | taxonomy of known failure modes; checklist                           | the error classes of LAB-015 Preflight audit before freezing that the audit checks, each an error that has happened before, with the rule that forbids it |
| Intent · freeze (frozen)             | preregistration; study protocol                                      | Nosek et al. 2018 (PNAS)                                                                                                                                 |
| Render check · instrument check      | instrument pretest (survey methodology)                              | Dev language as secondary term: dry run / smoke test                                                                                                     |
| Null condition · anchor              | negative / positive control; calibration items — as identifier `[A]` | Laboratory standard; Registered Reports: outcome-neutral condition                                                                                       |
| Resolution anchor                    | no fixed term; closest: known intermediate-intensity item            | Psychophysics: probe near the difference threshold; NOT discriminant validity                                                                            |
| Free knobs                           | researcher degrees of freedom                                        | Simmons et al. 2011                                                                                                                                      |
| Sweep obligation (LAB-032 Free knobs) | sensitivity analysis; multiverse analysis                            | Steegen et al. 2016                                                                                                                                      |
| Yield                                | yield; attrition                                                     | CONSORT flow logic                                                                                                                                       |
| Legend (`_meta`)                     | codebook / data dictionary                                           | Social research / data engineering                                                                                                                       |
| Polarity symmetry                    | framing/valence effect; prompt polarity sensitivity                  | NOT positional bias — that is the swap control                                                                                                           |
| Anchor gate                          | validation gate; sanity checks                                       | Software QA / ML eval                                                                                                                                    |
| Producer                             | build step / pipeline stage                                          | Data engineering                                                                                                                                         |
| Registered branch (`[B]`)            | pre-specified conditional analysis; decision tree (IF-THEN)          | Prereg templates; NOT "decision rule" — C and A also decide                                                                                              |
| Admissibility condition (`[A]`)      | outcome-neutral condition; quality check                             | Registered Reports; NOT stopping rule (= when data collection ends) and NOT futility                                                                     |
| Throwaway test                       | no fixed term; closest: exploratory scratch run                      | —                                                                                                                                                        |
| Judge instance                       | judge configuration                                                  | LLM-as-judge literature                                                                                                                                  |
| Two-user rule                        | rule of three                                                        | Fowler 1999; Metz: "duplication is cheaper than the wrong abstraction"                                                                                   |
| Home                                 | single source of truth                                               | —                                                                                                                                                        |

## 6. Clarity

- **LAB-089 · Tight prose:** *(was §6.1)* Term before use (LAB-087 Term before use); one line of thought per
  section.

- **LAB-090 · Protocols are self-contained:** *(was §6.2)* Orientation block at the very top (problem in
  one sentence · prior history as wikilinks · terms with a half-sentence) — whoever opens the
  file finds their way around without three other files.

- **LAB-091 · Script docstrings are reference, not explanation:** *(was §6.3)* Output,
  pointer to the protocol, for codes a short legend with a pointer to the
  home (LAB-086 Values rule (codes are names too)), invariants as bullet points. The why appears exactly
  once — in the protocol; growing explanatory prose in the docstring signals that names
  or protocol are not doing their job. Formulas and checked invariants
  are reference material and remain.

- **LAB-092 · Term layering:** *(was §6.4)* each layer uses only vocabulary
  that is explained in the layer itself or above it — the Summary (at the top) in
  everyday language without terms from other areas (necessary technical terms
  with a half-sentence gloss, wikilink in addition, never instead), the Context
  defines the vocabulary of this protocol; from Intent onward, that vocabulary may be used freely. The same
  applies in summaries, result sentences and explanatory notes: everyday word first, the
  coinage at most once in parentheses; English coinages live in code and
  config keys, not in German explanatory prose.

- **LAB-093 · Detail budget follows relevance, not analysis effort:** *(was §6.5)* Side findings and
  dead ends shrink to verdict + consequence when updated — speculation
  about undecided matters is dropped ("undecided" suffices), the history
  of the reassessment is told by the commit message (LAB-075 Docs carry the state, commits the change).

- **LAB-094 · Series as list or table, never as a prose chain.** *(was §6.6)* More than
  two examples, mappings or commands in a row are presented as a list
  or small table, not as a prose chain with "·" separators; in terminal Markdown
  the chain is unreadable.

- **LAB-100 · Answer before reasoning.** A note answers one
  question; the purpose in the meta line names it. If it cannot be named in one
  sentence, the note is split: one idea per note. The first paragraph
  after the meta line is the answer in at most three sentences — result, not
  procedure ("None of the examined systems binds …", not "We first
  looked at …"); reasoning, evidence and limits follow. In the sentence:
  concrete subject and verb ("recheck compares …", not "a check is
  performed"), one claim per sentence, the qualification directly at the
  statement it limits. The status of a claim stays visible —
  checked (with evidence), observed (with run), derived, expected; an
  expectation does not sound like a finding (chapter 1, *sketch* vs. *settled*).
  Chronology only where it explains a decision, then as a dated
  decision ("Decision of 2026-10-06: …, because …"), not as a narrative
  (LAB-075 Docs carry the state, commits the change).

- **LAB-101 · Comparison tables.** A table compares several
  objects by the same criteria: one row per object, columns at the same level
  of abstraction, cells carry findings, not mini-essays — if a cell needs
  paragraphs, prose is better. Symbols (●, ◐, ○) are explained directly
  before the table; evidence for individual cells goes in an evidence table or
  under `## Sources`, not hidden in the prose. The same table is
  maintained in exactly one place.

## 7. Parsimony: Core Problem First

- **LAB-095 · Core problem first:** *(was §7.1)* first identify the core problem, then
  the *simplest* model.

- **LAB-096 · "Do I really need this?":** *(was §7.2)* ask before every distinction. **Fold together**
  subsumable factors. Complexity only upon **demonstrated failure** (test,
  don't assume). Warning sign: "too many variations" → back to the core.

- **LAB-097 · Existing work first:** *(was §7.3)* before any addition, check whether one's own documents already answer the question — repetition creates two truths (chapter 3, provenance). Also applies to rules themselves: a rule is spelled out only here; every other place carries one line with a reference.

- **LAB-098 · Separate core and rollout.** *(was §7.4)* A plan that introduces a home or a
  tool covers master, pointer and wiring including tests — not
  the retrofitting of existing copies, third-party or student repos, moved
  notes or `--sync pull --force` onto established trees. The rollout is a
  separate assignment with a different risk profile (other people's work in the repo, `--force`
  as a user decision); the plan lists it under "Deliberately not part of the
  plan" instead of quietly solving it along the way. Only what would create a second truth
  without the step stays in, explicitly marked.
