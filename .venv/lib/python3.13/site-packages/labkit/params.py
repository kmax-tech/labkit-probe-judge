"""labkit-params — the values a run ran with, each with its home and what the line proves.

    labkit-params <AREA> [--run RUN_ID] [--protocol PROTOCOL-*.md]

"Which value held in this run, and where was it decided?" took four files
(the script's constants, its design object, the run's config.json,
models.toml) — code-navigation round 13, 2026-10-08: "protocols, measure
and runs with their configs — where to start". This is the one view, a
projection of the canonical sources, never a source itself: the first line
names the run and the protocol it reads; every row says where the value
has its home and which tier the claim belongs to.

What a row claims — and no more:

  recorded            the run recorded this key with this value          guaranteed
  registered constant the protocol's constant and the recorded value
                      are equal / differ                                  guaranteed
                      the record carries no key of that name: its absence
                      is certain, reading it as a fault is                static evidence
  model               the model that answered these rows, from the
                      `models_resolved` of the run that recorded it —
                      a derived run records none, so the walk along
                      `derived_from` names the ancestor (`runs.
                      model_provenance_run`); a chain without one says so  guaranteed
  module constant     an UPPER_CASE constant in scripts/01_measure.py with
                      no key of its name in the record — whether it moves
                      the number is not claimed                           static evidence

Whether the record is COMPLETE is not a claim this view can make: an old
run and a new one carry the same schema, and only the area's own test (the
record held to the config object's fields) proves completeness. The model
is read from the run's record, never resolved against today's models.toml.
"""

from __future__ import annotations

import ast
import json
from dataclasses import dataclass
from pathlib import Path

from labkit import console, promises, protocol_block
from labkit.intent_check import protocol_id_of
from labkit.repo import area_path, choose_protocol, no_such_area
from labkit.runs import (
    bound_answering_run,
    model_provenance_run,
    read_run_config,
)

GUARANTEED = "guaranteed"
EVIDENCE = "static evidence"
MEASURE_SCRIPT = Path("scripts") / "01_measure.py"


@dataclass(frozen=True)
class ParamRow:
    """One line of the table: a value, where it lives, what the line proves.

    Attributes:
        name: The parameter (a config key, a promise constant, an alias).
        value: The value as the home states it.
        home: The authoritative source — the run's record, the protocol's
            promise, the ancestor's `models_resolved`, the script line.
        meaning: What the value is to the measurement (registered constant,
            recorded parameter, the answering model, an unrecorded constant).
        in_run: The value the run recorded under that name, or "—".
        tier: `guaranteed` or `static evidence`.
    """

    name: str
    value: str
    home: str
    meaning: str
    in_run: str
    tier: str


def _shown(value: object, width: int = 38) -> str:
    """A value as one short cell."""
    text = value if isinstance(value, str) else json.dumps(value, sort_keys=True)
    return text if len(text) <= width else text[: width - 1] + "…"


def _looks_like_model_spec(value: object) -> bool:
    """A dict shaped like `llm.resolve`'s spec (alias/model/endpoint) — a
    resolved model recorded under a key runlog does not read."""
    return (
        isinstance(value, dict)
        and "model" in value
        and ("alias" in value or "endpoint" in value)
    )


def recorded_rows(run_config: dict, run_name: str) -> list[ParamRow]:
    """Every key the run recorded under `config`: certain, and nothing more.
    A resolved model spec under a key other than `model`/`*_model` is
    marked: the run recorded it, but it is not provenance labkit holds
    (runlog resolves `model` keys into `models_resolved`; uniagent 14–17
    recorded `judge`)."""
    rows = []
    for key, value in sorted(run_config.items()):
        spec = _looks_like_model_spec(value) and not (
            key == "model" or key.endswith("_model")
        )
        rows.append(
            ParamRow(
                name=key,
                value=_shown(value),
                home=f"{run_name}/config.json: config.{key}",
                meaning=(
                    "looks like a resolved model spec under a key runlog does not read "
                    "(`model`, `*_model`) — recorded, not provenance labkit holds"
                    if spec
                    else "recorded parameter of this run"
                ),
                in_run=_shown(value),
                tier=EVIDENCE if spec else GUARANTEED,
            )
        )
    return rows


def constant_rows(
    block: promises.PromiseTables,
    run_config: dict,
    protocol_name: str,
    copies: dict[str, tuple[object, int]],
) -> list[ParamRow]:
    """The protocol's registered constants against the record: equal,
    different, or missing — the state is certain; a missing one is a fault
    only as evidence, and the strongest evidence is a literal of the same
    name in the script, in either case (`copies`: name -> (value, line);
    `min_f1` is copied as `MIN_F1`)."""
    rows = []
    for rec in promises.constant_records(block, run_config):
        if rec.state == "missing":
            copy_name = next(
                (n for n in (rec.name, rec.name.upper()) if n in copies), None
            )
            held = (
                f"; {MEASURE_SCRIPT}:{copies[copy_name][1]} holds "
                f"{copy_name} = {copies[copy_name][0]!r}"
                if copy_name
                else ""
            )
            in_run = f"— (not recorded{held})"
            tier = f"{GUARANTEED}: absent; as a fault {EVIDENCE}"
        else:
            in_run = _shown(rec.recorded) + (
                "" if rec.state == "equal" else "  ≠ DIFFERS"
            )
            tier = GUARANTEED
        rows.append(
            ParamRow(
                name=rec.name,
                value=_shown(rec.promised),
                home=f"{protocol_name} [{rec.promise_id}] constants",
                meaning="registered constant",
                in_run=in_run,
                tier=tier,
            )
        )
    return rows


def _lineage(run_dir: Path) -> list[str]:
    """The run and its ancestors along `derived_from`, newest first — after
    `model_provenance_run` has already refused a loop or a missing parent."""
    names, here = [], run_dir
    while True:
        names.append(here.name)
        cfg = read_run_config(here) or {}
        parent = cfg.get("derived_from")
        if not isinstance(parent, str) or not parent:
            return names
        here = here.parent / parent


def model_rows(run_dir: Path) -> list[ParamRow]:
    """The model that answered the rows, from the record that holds it.

    Raises:
        ValueError: From `runs.model_provenance_run` — a missing ancestor or
            a loop in `derived_from`.
    """
    found = model_provenance_run(run_dir)
    chain = _lineage(run_dir)
    if found is None:
        return [
            ParamRow(
                name="model",
                value="—",
                home="no run in the lineage recorded models_resolved",
                meaning="model provenance: not recorded in models_resolved along lineage "
                + " → ".join(chain),
                in_run="—",
                tier=GUARANTEED,
            )
        ]
    resolved = (read_run_config(found) or {}).get("models_resolved") or {}
    via = chain[: chain.index(found.name)]
    home = f"models_resolved of {found.name}" + (
        f", inherited through {' → '.join(via)}" if via else ""
    )
    rows = []
    for alias, spec in sorted(resolved.items()):
        model = spec.get("model", "?") if isinstance(spec, dict) else "?"
        endpoint = spec.get("endpoint") if isinstance(spec, dict) else None
        rows.append(
            ParamRow(
                name=f"model {alias}",
                value=f"{alias} → {model}" + (f" @ {endpoint}" if endpoint else ""),
                home=home,
                meaning="the model that answered these rows",
                in_run="recorded"
                if found == run_dir
                else f"inherited from {found.name}",
                tier=GUARANTEED,
            )
        )
    return rows


def script_literals(area: Path) -> dict[str, tuple[object, int]]:
    """Names assigned a literal at module level of scripts/01_measure.py:
    name -> (value, line). Empty without the script. A registered constant's
    copy is looked up here under its own name; the evidence rows take the
    UPPER_CASE ones."""
    script = area / MEASURE_SCRIPT
    if not script.is_file():
        return {}
    out: dict[str, tuple[object, int]] = {}
    for node in ast.parse(script.read_text(encoding="utf-8")).body:
        if not (isinstance(node, ast.Assign) and len(node.targets) == 1):
            continue
        target, value = node.targets[0], node.value
        if isinstance(target, ast.Name) and isinstance(value, ast.Constant):
            out[target.id] = (value.value, node.lineno)
    return out


def script_constant_rows(
    literals: dict[str, tuple[object, int]], run_config: dict, registered: set[str]
) -> list[ParamRow]:
    """Module constants with no key of their name (either case) in the record
    and no registered row of their own (either case: `MIN_F1` is the copy of
    the registered `min_f1` and stands in its row) — evidence of a value the run may
    have used without recording it, not a proof."""
    return [
        ParamRow(
            name=name,
            value=_shown(value),
            home=f"{MEASURE_SCRIPT}:{line}",
            meaning="module constant not in the record — whether it moves the number is not claimed",
            in_run="—",
            tier=EVIDENCE,
        )
        for name, (value, line) in literals.items()
        if name.isupper()
        and name not in run_config
        and name.lower() not in run_config
        and name not in registered
        and name.lower() not in registered
    ]


def params_table(area: Path, protocol: Path, run_dir: Path) -> list[ParamRow]:
    """Every row of the view for one run, registered constants first.

    Raises:
        ValueError: An unreadable run config, or a broken lineage.
    """
    cfg = read_run_config(run_dir)
    if cfg is None:
        raise ValueError(f"{run_dir}: no config.json")
    run_config = cfg.get("config") or {}
    if not isinstance(run_config, dict):
        raise ValueError(f"{run_dir.name}: config.json `config` is not an object")
    block = promises.parse_block(protocol.read_text(encoding="utf-8"))
    literals = script_literals(area)
    rows: list[ParamRow] = []
    if block is not None:
        rows += constant_rows(block, run_config, protocol.name, literals)
    # a registered constant's home is the protocol; its recorded value stands
    # in that row, not again as a recorded parameter
    registered = {r.name for r in rows}
    rows += recorded_rows(
        {k: v for k, v in run_config.items() if k not in registered}, run_dir.name
    )
    rows += model_rows(run_dir)
    rows += script_constant_rows(literals, run_config, registered)
    return rows


def render_table(rows: list[ParamRow]) -> str:
    """The rows as one aligned table, a header line first."""
    header = ParamRow("parameter", "value", "home", "meaning", "in run", "tier")
    cols = ("name", "value", "home", "meaning", "in_run", "tier")
    width = {c: max(len(getattr(r, c)) for r in (header, *rows)) for c in cols}
    lines = []
    for r in (header, *rows):
        lines.append("  ".join(getattr(r, c).ljust(width[c]) for c in cols).rstrip())
    return "\n".join(lines)


def main(argv: list[str]) -> int:  # noqa: C901 complexity baseline 2026-10-08
    """Command line: the table for one area's answering run, or a named run."""
    if not argv or argv[0] in ("-h", "--help"):
        print((__doc__ or "").strip().splitlines()[0])
        print("usage: labkit-params <AREA> [--run RUN_ID] [--protocol PROTOCOL-*.md]")
        return 0 if argv else 2
    area = area_path(argv[0])
    protocol_arg: Path | None = None
    run_arg: str | None = None
    rest = argv[1:]
    while rest:
        if rest[0] == "--protocol" and len(rest) >= 2:
            protocol_arg, rest = Path(rest[1]), rest[2:]
        elif rest[0] == "--run" and len(rest) >= 2:
            run_arg, rest = rest[1], rest[2:]
        else:
            print(f"labkit-params: unexpected argument {rest[0]!r}")
            return 2
    if not area.is_dir():
        print(f"labkit-params: {no_such_area(area)}")
        return 2
    protocol = choose_protocol(area, protocol_arg, "labkit-params")
    if protocol is None:
        return 2
    try:
        pid = protocol_id_of(protocol.read_text(encoding="utf-8"))
    except protocol_block.BlockError as exc:
        print(f"labkit-params: {protocol.name}: {exc}")
        return 2
    if run_arg is not None:
        run_dir = area / "runs" / run_arg
        if not run_dir.is_dir():
            print(f"labkit-params: no run {run_arg} under {area / 'runs'}")
            return 2
        how = "named with --run"
    else:
        if pid is None:
            print(
                f"labkit-params: {protocol.name} is unstamped — name a run with --run"
            )
            return 2
        choice = bound_answering_run(area, pid)
        if choice.run_dir is None or choice.blocker:
            print(f"labkit-params: {choice.blocker}")
            for x in choice.exclusions:
                print(f"    {x.run_dir.name}: {x.why}")
            return 2
        run_dir = choice.run_dir
        how = f"the run that answers for {pid}" + (
            f" ({choice.skipped_newer} newer bound run(s) without intent keys skipped)"
            if choice.skipped_newer
            else ""
        )
    print(f"params: {area.name} · {protocol.name} · run {run_dir.name} ({how})")
    try:
        rows = params_table(area, protocol, run_dir)
    except ValueError as exc:
        print(f"labkit-params: {exc}")
        return 2
    print(render_table(rows))
    return 0


def cli() -> None:
    """Console entry point of `labkit-params`."""
    console.exit_with(main)


if __name__ == "__main__":
    cli()
