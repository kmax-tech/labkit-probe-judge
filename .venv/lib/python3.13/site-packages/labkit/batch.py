"""batch — a resumable, inspectable output file for item-by-item runs.

The three habits every batch script needs and every prototype skips: don't let
a second process write the same file, don't redo what is already done, and be
able to say what is missing without re-running anything. Hand-rolling them
costs ~40 lines each time and gets skipped exactly when it matters — an
interrupted connection then costs the whole run (2026-08-12: a socket timeout
killed a scoring run at 49 of 96 items; only the resume made it a non-event).

    import batch

    with batch.Store(out_path) as store:            # takes <out>.lock
        for rec in store.pending(records):          # skips ids already scored
            store.append(score(rec))                # one line, flushed
    print(store.status(records))

Before a run counts as complete, balance the file against its input — each
item on exactly one row, every row from the current prompt — and let a gap
stop the run (`Store.ledger`, `Ledger.require_complete`).

Resuming is re-running the same command: ids in the output file are skipped.
Records are matched by `id_key` (default "id"), so the input file and the
output file are joined on it — a partial output stays a valid output.

Deliberately NOT here: retries (they belong at the call that fails, see
`llm.complete`) and yield counting (what "complete" means is domain-specific —
count it in the experiment and report it, LAB-023 No silent loss).
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
import time
from pathlib import Path
from typing import Iterable, Iterator, Mapping

# A row without the expected field differs from every expected value, None included.
_ABSENT = object()


def _parse(text: str, path: Path) -> tuple[list[dict], int | None]:
    """(objects, line number of a torn last line or None). Only the LAST
    non-empty line may be unparseable — a process killed mid-write leaves
    exactly that. Any earlier one is a damaged file, and resuming over it
    would treat it as done: raises ValueError with file and line (review
    2026-10-07: a broken line mid-file was skipped and the rows after it
    kept)."""
    lines = text.splitlines()
    last = max((i for i, ln in enumerate(lines) if ln.strip()), default=-1)
    out, torn = [], None
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError as exc:
            if i != last:
                raise ValueError(
                    f"{path}:{i + 1}: unparseable line before the end of the "
                    f"file ({exc.msg}) — not an interrupted write; repair "
                    f"or regenerate the file"
                ) from exc
            torn = i + 1
    return out, torn


@dataclass(frozen=True)
class RowRuns:
    """Which runs wrote a JSONL file's rows, read from their `_prov.run`.

    Attributes:
        runs: run_id -> number of rows that carry it.
        unstamped: rows without a `_prov.run` — written outside a run, or
            by a Store without `prov`.
    """

    runs: dict[str, int]
    unstamped: int


def row_runs(path: Path) -> RowRuns:
    """The runs a JSONL output's rows came from (`_prov.run` per row). A torn
    last line is ignored like everywhere here; a damaged line before it
    raises (`_parse`). The one reading runlog uses to name what a resumed
    file continues, and finalize to hold the rows to the run."""
    rows, _torn = _parse(path.read_text(encoding="utf-8"), path)
    runs: dict[str, int] = {}
    unstamped = 0
    for r in rows:
        prov = r.get("_prov") if isinstance(r, dict) else None
        run_id = prov.get("run") if isinstance(prov, dict) else None
        if isinstance(run_id, str) and run_id:
            runs[run_id] = runs.get(run_id, 0) + 1
        else:
            unstamped += 1
    return RowRuns(runs, unstamped)


def _duplicate_ids(rows: list[dict], id_key: str) -> list:
    """The ids that stand on more than one row, in order of first sight."""
    seen: dict = {}
    for r in rows:
        if id_key in r:
            seen[r[id_key]] = seen.get(r[id_key], 0) + 1
    return [i for i, n in seen.items() if n > 1]


@dataclass(frozen=True)
class Ledger:
    """The balance of an output file against its input: every input item on
    exactly one row, no row without an input item, every row made from the
    current input. Guaranteed tier — exact, by id, no judgement about what
    a row says (that stays the experiment's, LAB-023 No silent loss).

    Attributes:
        path: the output file balanced.
        items: input records.
        rows: output rows read (the `_meta` header and a torn last line
            are not rows).
        missing: input ids without a row, in input order.
        duplicate: ids on more than one row — a set count alone would let
            a missing item and a doubled one cancel out (2026-10-09,
            fallacy-dataset-generation, area 01).
        stray: row ids the input does not have.
        unidentified: rows without the id field.
        stale: field -> ids whose row carries another value than the
            current input expects for it (an older prompt, an edited item).
    """

    path: Path
    items: int
    rows: int
    missing: list
    duplicate: list
    stray: list
    unidentified: int
    stale: dict[str, list]

    @property
    def ok(self) -> bool:
        """True only when no gap of any kind is listed."""
        return not (
            self.missing
            or self.duplicate
            or self.stray
            or self.unidentified
            or any(self.stale.values())
        )

    def counts(self) -> dict[str, int]:
        """The balance as numbers for `run.metrics(**ledger.counts())`."""
        out = {
            "n_items": self.items,
            "n_rows": self.rows,
            "n_missing": len(self.missing),
            "n_duplicate": len(self.duplicate),
            "n_stray": len(self.stray),
            "n_unidentified": self.unidentified,
        }
        for field, ids in self.stale.items():
            out[f"n_stale_{field}"] = len(ids)
        return out

    def require_complete(self) -> None:
        """Raise SystemExit naming every gap, unless the balance holds.
        Called inside `with runlog.run(...)`, the raise keeps the run from
        completing: no completion.json, no runs.tsv row."""
        if self.ok:
            return
        parts = [
            f"{name} {len(ids)} (e.g. {ids[:5]})"
            for name, ids in (
                ("missing", self.missing),
                ("duplicate", self.duplicate),
                ("stray", self.stray),
            )
            if ids
        ]
        if self.unidentified:
            parts.append(f"rows without an id {self.unidentified}")
        parts += [
            f"stale {field} {len(ids)} (e.g. {ids[:5]})"
            for field, ids in self.stale.items()
            if ids
        ]
        raise SystemExit(
            f"{self.path}: the output does not balance its {self.items} input "
            f"items — {'; '.join(parts)}. The run is NOT complete."
        )


class Store:
    """Append-only JSONL output with a lock, resume-by-id and a status view.

    `mode="resume"` (default): appends, `pending()` skips the ids already
    in the file — the same command again continues. `mode="produce"`:
    writes a `.tmp` file, replaces the target on a clean exit, and never
    resumes (`pending()` yields every record).

    `prov`: per-row provenance stamp. Provenance normally lives in the join
    row -> file -> runs.tsv -> config.json; copy, filter or merge the file and
    the join dies — the file goes silent about what produced it (that is how
    old/new hybrid files happen). With `prov` every appended record carries a
    `_prov` object, so each row stays self-contained:

        with batch.Store(out, prov={**llm.provenance("gpt-oss"),
                                    "run": run.run_id}) as store:

    Values may be callables — evaluated at append time, because with a
    multi-endpoint alias the serving endpoint differs per row
    (llm.provenance passes `llm.last_endpoint` as a callable). The stamp
    holds the pointer (run) plus the facts that die with the join (model
    identity, endpoint instance); everything else stays in the run config.
    An explicit `_prov` already present in a record is never overwritten.
    """

    def __init__(
        self,
        path: str | Path,
        id_key: str = "id",
        prov: dict | None = None,
        mode: str = "resume",
    ) -> None:
        if mode not in ("resume", "produce"):
            raise ValueError(f"Store mode must be 'resume' or 'produce', not {mode!r}")
        self.path = Path(path)
        self.id_key = id_key
        self.prov = dict(prov) if prov else {}
        self.mode = mode
        self.lock = self.path.with_suffix(self.path.suffix + ".lock")
        self._tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        self._fh = None
        self._producing = False

    # -- lock -------------------------------------------------------------
    def __enter__(self) -> "Store":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self.lock.open("x", encoding="utf-8") as f:
                f.write(
                    f"pid {os.getpid()} · {time.strftime('%Y-%m-%dT%H:%M:%S')} · "
                    f"{' '.join(sys.argv)}\n"
                )
        except FileExistsError:
            raise SystemExit(
                f"{self.lock} exists — another run is writing this output:\n"
                f"  {self.lock.read_text(encoding='utf-8').strip()}\n"
                f"Use a different output file, or delete the lock if that run "
                f"is dead (`.venv/bin/runlog <area>` shows which "
                f"runs are still alive)."
            )
        if self.mode == "produce":
            # A producer REPLACES its file — running it twice must yield the
            # file of ONE run, never a concatenation (2026-08-19 producer
            # rule; scar 2026-09-09, area 71: a second producer run appended
            # 625+528 rows and only --verify caught it). Writes go to a temp
            # file; the clean exit renames it over the target atomically, a
            # crash leaves the old file untouched and the temp visible.
            self._fh = self._tmp.open("w", encoding="utf-8")
            self._producing = True
        else:
            self._drop_torn_tail()
            self._fh = self.path.open("a", encoding="utf-8")
        return self

    def _drop_torn_tail(self) -> None:
        """Before appending: cut a torn last line, said out loud — appending
        after it would leave it mid-file (or glue the next record onto it)."""
        if not self.path.exists():
            return
        text = self.path.read_text(encoding="utf-8")
        _, torn = _parse(text, self.path)
        if torn is None:
            return
        kept = text.splitlines()[: torn - 1]
        self.path.write_text("".join(ln + "\n" for ln in kept), encoding="utf-8")
        print(
            f"batch: cut the torn last line {torn} of {self.path} (interrupted "
            f"write) — its item will be redone",
            file=sys.stderr,
        )

    def __exit__(self, exc_type: type[BaseException] | None, *exc: object) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None
        if self._producing:
            self._producing = False
            if exc_type is None:
                os.replace(self._tmp, self.path)
            else:
                print(
                    f"batch: produce aborted — {self.path} left unchanged, "
                    f"partial output in {self._tmp}",
                    file=sys.stderr,
                )
        self.lock.unlink(missing_ok=True)

    # -- reading ----------------------------------------------------------
    def records(self) -> list[dict]:
        """Everything written so far. A truncated final line (a process killed
        mid-write) is reported and skipped, never silently dropped; an
        unparseable line anywhere else raises. A `_meta`
        header line (see write_dataset) is documentation, not a record —
        skipped here, so every consumer reading through this sees data only."""
        src = self._tmp if self._producing else self.path
        if not src.exists():
            return []
        objs, torn = _parse(src.read_text(encoding="utf-8"), src)
        if torn is not None:
            print(
                f"batch: skipping the torn last line {torn} of {src} "
                f"(interrupted write) — it will be redone",
                file=sys.stderr,
            )
        return [o for o in objs if not (isinstance(o, dict) and "_meta" in o)]

    def done_ids(self) -> set:
        """The ids of the records already in the output file."""
        return {r[self.id_key] for r in self.records() if self.id_key in r}

    def pending(self, records: Iterable[dict]) -> Iterator[dict]:
        """The input records that have no output line yet, in input order."""
        done = self.done_ids()
        for rec in records:
            if rec[self.id_key] not in done:
                yield rec

    # -- writing ----------------------------------------------------------
    def append(self, record: dict) -> None:
        """One record, one line, flushed — a crash costs the current item only."""
        if self._fh is None:
            raise RuntimeError("Store.append outside the `with` block")
        if self.prov and "_prov" not in record:
            record = {
                **record,
                "_prov": {k: (v() if callable(v) else v) for k, v in self.prov.items()},
            }
        self._fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._fh.flush()

    # -- status -----------------------------------------------------------
    def status(self, records: Iterable[dict] | None = None) -> dict:
        """done / missing / stray / duplicate by id, plus who holds the lock.
        No model load. `done` counts distinct ids; an id on two lines is
        named under `duplicate` — a counted set alone would let a missing
        item and a doubled one cancel out (2026-10-09)."""
        done = self.records()
        done_ids = {r[self.id_key] for r in done if self.id_key in r}
        info: dict = {"path": str(self.path), "done": len(done_ids)}
        duplicate = _duplicate_ids(done, self.id_key)
        if duplicate:
            info["duplicate"] = duplicate[:10]
        if records is not None:
            want = [r[self.id_key] for r in records]
            missing = [i for i in want if i not in done_ids]
            info["total"] = len(want)
            info["missing"] = len(missing)
            info["missing_ids"] = missing[:10]
            stray = sorted(done_ids - set(want))
            if stray:  # output holds ids the input never had
                info["stray"] = stray[:10]
        if self.lock.exists():
            info["locked_by"] = self.lock.read_text(encoding="utf-8").strip()
        return info

    def ledger(
        self,
        records: Iterable[dict],
        expect: Mapping[str, object] | None = None,
    ) -> Ledger:
        """Balance the output against the input `records` (see Ledger).

        `expect`: field -> the value every row must carry in it. A value is
        either a constant (a prompt hash) or a function of the row's input
        record, joined by id (`lambda rec: item_sha(rec)`). Only rows whose
        id is in the input are checked; a row without the field is stale.

            ledger = store.ledger(records, expect={"prompt_sha": PROMPT_SHA})
            run.metrics(**ledger.counts())
            ledger.require_complete()
        """
        records = list(records)
        doubled = _duplicate_ids(records, self.id_key)
        if doubled:
            raise ValueError(
                f"ledger: the input itself carries ids twice ({doubled[:5]}) — "
                f"a balance by id needs unique input ids"
            )
        by_id = {r[self.id_key]: r for r in records}
        rows = self.records()
        row_ids = {r[self.id_key] for r in rows if self.id_key in r}
        stale: dict[str, list] = {}
        for field, want in (expect or {}).items():
            stale[field] = [
                r[self.id_key]
                for r in rows
                if r.get(self.id_key) in by_id
                and r.get(field, _ABSENT)
                != (want(by_id[r[self.id_key]]) if callable(want) else want)
            ]
        return Ledger(
            path=self.path,
            items=len(records),
            rows=len(rows),
            missing=[r[self.id_key] for r in records if r[self.id_key] not in row_ids],
            duplicate=_duplicate_ids(rows, self.id_key),
            stray=[
                i
                for i in dict.fromkeys(r[self.id_key] for r in rows if self.id_key in r)
                if i not in by_id
            ],
            unidentified=sum(1 for r in rows if self.id_key not in r),
            stale=stale,
        )


def write_dataset(
    path: Path, rows: list[dict], *, about: str, fields: dict[str, str], producer: str
) -> None:
    """Write a prepared dataset that explains itself: first line is a `_meta`
    header (about, field legend, producer), then one record per line.

    Store.records() — and everything reading through it, e.g.
    answers.read_jsonl — skips the header, so consumers see data only; a
    human opening the file sees FIRST what it is. Every row is validated
    against the legend: field drift (a renamed or forgotten column) fails
    loudly at write time, not silently at analysis time.
    """
    for i, r in enumerate(rows):
        extra, missing = set(r) - fields.keys(), fields.keys() - set(r)
        if extra or missing:
            raise ValueError(
                f"row {i} does not match the field legend "
                f"(extra: {sorted(extra)}, missing: {sorted(missing)})"
            )
    meta = {"_meta": {"about": about, "fields": fields, "producer": producer}}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in [meta, *rows]),
        encoding="utf-8",
    )
