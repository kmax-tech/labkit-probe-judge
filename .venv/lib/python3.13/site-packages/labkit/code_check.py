#!/usr/bin/env python3
"""code-check — the mechanical half of the preflight, before the model looks.

The preflight audit (LAB-015 Preflight audit before freezing) used to do three jobs in one
pass: mechanics, compliance, judgement. The mechanics are the cheap half and
they do not need a model — an id that no script mentions, a field the
analysis reads and no producer writes, a protocol still full of placeholders
are all decidable from the source. Deciding them here leaves the model the
one question worth its cost: does the code MEAN what the registration says.

Five automated checks; the rest are extracted as facts for the
code-check agent (via ``--bundle``), not verified by this command:

  1. **intent ids against the code** (LAB-004 Identifiers make the intent addressable, AUTOMATED). Every registered
     [C1]/[A1]/[B1] must appear as a key literal in the area's scripts.
     Report time has `intent-check` for the metrics; before the run the same
     promise goes unchecked exactly when repairing it is still cheap.
  1a. **[A] keys decide something** (STATIC EVIDENCE, 2026-10-14). An
     admissibility key the code writes and never tests (`if`, `and`,
     `all()`, …) permits nothing: the C verdict is reported either way. A
     test is not proof of a branch, so each finding is a WARNING.
  1b. **parser fixtures** (AUTOMATED, 2026-10-05). Every `parse_*` function in
     the area's scripts is exercised by a test under the repo's tests/ — five
     audit findings in three repos were "this parser has no fixture test on
     real raw answers", and a parser fails silently into a wrong number.
  1c. **prompt drift** (AUTOMATED, 2026-10-05). The protocol's prompt block
     is the `PROMPT` constant, not a transcript of it: every line of the
     constant without a `{placeholder}` must appear in the block. The most
     frequent provenance blocker in the audit corpus.
  1d. **stamp coverage** (STATIC EVIDENCE, 2026-10-12). The audit stamp
     follows `import` statements into `lib/` and `src/` (`scope_sha`); it
     cannot follow a `sys.path` edit, `importlib`/`runpy`/`exec`, or an
     import that resolves to a repo file outside those roots — another
     area's script, `tools/`. Each is a WARNING naming the line: code that
     determines the number and that no stamp sees (LAB-019 The stamp covers
     everything that determines the number). Five audits in uniagent
     (areas 15, 16, 17, 22, 23) found this by reading; the agent should
     not have to.

The following are extracted into the audit bundle but NOT checked by this
command — the code-check agent judges them:

  2. **schema contract** (LAB-015 Preflight audit before freezing, preflight scope). Every field the analysis
     READS must be written somewhere — in the materialized data if it exists,
     otherwise as a write site in the producer's source.
  3. **gate labels** (LAB-038 What the prompt demands). String comparisons in evaluation code — both
     resolved literals and named constants — extracted as facts for the agent.
  4. **protocol placeholders**. Delegated to `protocol-check`, which owns the
     template contract.

Reads and writes are told apart with `ast`, not with a regex: `row["x"]` in
a Load context is a read, in a Store context it is a write, and no pattern
over text gets that right reliably.

Usage:
    code-check <AREA>                    # run the mechanical checks
    code-check <AREA> --bundle FILE      # additionally write the audit bundle
                                         # (protocol + scripts + imported
                                         #  repo-local lib modules) for the
                                         #  code-check agent to read in one go

Exit code 1 if any check reports a finding, 2 on usage errors.
"""

from __future__ import annotations

import ast
import json
import re
from collections.abc import Iterable
from pathlib import Path

from labkit import console, promises, protocol_block, rules
from labkit.intent_check import ID_IN_PROTOCOL, code_ids, code_keys
from labkit.repo import area_path, choose_protocol, layout_root, no_such_area
from labkit.scope_sha import LOCAL_ROOTS, area_files, imported_repo_helpers


# --- source analysis ------------------------------------------------------


def _name_of(node: ast.expr) -> str | None:
    """A bare name's identifier, None for any other expression — the one
    reader both visitors used to carry (`_name_of`, `_var_name`)."""
    return node.id if isinstance(node, ast.Name) else None


def _string_constants(nodes: Iterable[ast.expr | None]) -> list[str]:
    """The string literals among `nodes`, in order (a dict's `**spread` key is None)."""
    return [
        n.value
        for n in nodes
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    ]


class _FieldVisitor(ast.NodeVisitor):
    """Reads, writes, and which names this file builds as dicts itself.

    `reads` maps field -> (site, holder): the holder is the variable the
    field was read from, so a read out of a dict the same file assembles can
    be told from a read out of a data row.
    """

    BUILDERS = {"dict", "defaultdict", "Counter", "OrderedDict"}

    def __init__(self, filename: str) -> None:
        self.filename = filename
        self.reads: dict[str, tuple[str, str | None]] = {}
        self.writes: set[str] = set()
        self.built: set[str] = set()

    def _site(self, lineno: int) -> str:
        return f"{self.filename}:{lineno}"

    def visit_Assign(self, node: ast.Assign) -> None:
        """`R = {}` / `R = defaultdict(list)` marks R as locally built."""
        val = node.value
        builds = isinstance(val, (ast.Dict, ast.DictComp)) or (
            isinstance(val, ast.Call)
            and isinstance(val.func, ast.Name)
            and val.func.id in self.BUILDERS
        )
        if builds:
            for target in node.targets:
                name = _name_of(target)
                if name:
                    self.built.add(name)
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        key = node.slice
        if isinstance(key, ast.Constant) and isinstance(key.value, str):
            holder = _name_of(node.value)
            if isinstance(node.ctx, ast.Load):
                self.reads.setdefault(key.value, (self._site(node.lineno), holder))
            else:  # Store / Del — the field is being produced here
                self.writes.add(key.value)
                if holder:
                    self.built.add(holder)
        self.generic_visit(node)

    def visit_Dict(self, node: ast.Dict) -> None:
        for k in node.keys:
            if isinstance(k, ast.Constant) and isinstance(k.value, str):
                self.writes.add(k.value)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if isinstance(func, ast.Attribute) and node.args:
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                if func.attr == "get":
                    self.reads.setdefault(
                        first.value,
                        (self._site(node.lineno), _name_of(func.value)),
                    )
                elif func.attr in ("setdefault", "pop"):
                    self.writes.add(first.value)
        for kw in node.keywords:  # dict(alpha=1) / Row(alpha=1) build fields
            if kw.arg:
                self.writes.add(kw.arg)
        self.generic_visit(node)


def scan(path: Path) -> _FieldVisitor | None:
    """Parse one file; None if it does not parse (never fail the whole run)."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError):
        return None
    v = _FieldVisitor(path.name)
    v.visit(tree)
    return v


FIELDISH = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _harvest(obj: object, out: set[str], depth: int = 0) -> None:
    """Every dict key at every level, lists included.

    Flat top-level harvesting missed both real shapes in the areas: the
    anchors file keeps its fields inside a `pairs: [...]` list, and reading
    only the outer keys reported `must_contradict` as unwritten (2026-09-10).
    Over-approximating the known set is the safe direction — a field too many
    costs a missed finding the model still catches, a field too few costs a
    false blocker that gets the whole check switched off.
    """
    if depth > 6:
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.add(str(k))
            _harvest(v, out, depth + 1)
    elif isinstance(obj, list):
        for v in obj[:20]:
            _harvest(v, out, depth + 1)


def data_keys(area: Path) -> tuple[set[str], list[str]]:
    """Keys of every data row the area has on disk, at every nesting level.

    Every JSON(L) file, not just `data/prepared`: the pipeline is staged, so
    `03_evaluate` legitimately reads fields that `01_generate` invented and
    that never existed in the prepared data. Holding a consumer against the
    prepared file alone reported eight blockers in area 64 and found no
    defect (2026-09-10).

    Several lines per file, not one: a producer may write a `_meta` header
    line first, and harvesting only that reports every real field as missing
    (2026-09-10, area 68).
    """
    keys: set[str] = set()
    seen: list[str] = []
    for pattern in (
        "data/**/*.jsonl",
        "data/**/*.json",
        "output/**/*.jsonl",
        "output/**/*.json",
    ):
        for f in sorted(area.glob(pattern)):
            before = len(keys)
            try:
                with f.open(encoding="utf-8") as fh:
                    if f.suffix == ".json":
                        _harvest(json.load(fh), keys)
                    else:
                        for i, line in enumerate(fh):
                            if i >= 5:
                                break
                            line = line.strip()
                            if line:
                                _harvest(json.loads(line), keys)
            except (OSError, json.JSONDecodeError, RecursionError):
                continue
            if len(keys) > before:
                seen.append(f.name)
    return keys, seen


CONSUMER = re.compile(r"^(0[23]_|analysis)")

# --- gate-label extraction ------------------------------------------------

INFRA_VARS = frozenset(
    {
        "mode",
        "ext",
        "suffix",
        "key",
        "status",
        "encoding",
        "sep",
        "format",
        "lang",
        "language",
        "scheme",
        "protocol",
        "method",
        "dtype",
        "compression",
        "engine",
        "__name__",
    }
)

_NOISE_LITERAL = re.compile(
    r"^(\.[a-z]{1,6}"  # file extensions: .json, .csv, .jsonl
    r"|--?"  # CLI flags: -v, --dry-run
    r"|.*/"  # paths: data/prepared/x
    r"|https?:)"  # URLs
)


class _ComparisonVisitor(ast.NodeVisitor):
    """String comparisons in evaluation code — facts for the agent.

    Collects both resolved string literals (``answer == "yes"``) and named
    constants (``answer in VALID_ANSWERS``), so the agent can distinguish
    "gate via shared constant" from "gate via hardcoded literals".
    """

    def __init__(self, filename: str, source: str) -> None:
        self.filename = filename
        self._source = source
        self.entries: list[tuple[int, str, str, str]] = []
        self._filtered: list[str] = []
        self._const_defs: dict[str, tuple[int, set[str]]] = {}
        self._imports: dict[str, str] = {}
        self._prepass(source)

    def _prepass(self, source: str) -> None:
        """Collect module-level constant definitions and imports."""
        try:
            tree = ast.parse(source, filename=self.filename)
        except SyntaxError:
            return
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                target = node.targets[0]
                if isinstance(target, ast.Name):
                    vals = self._literal_strings(node.value)
                    if vals is not None:
                        self._const_defs[target.id] = (node.lineno, vals)
            elif isinstance(node, ast.ImportFrom) and node.module:
                for alias in node.names or []:
                    name = alias.asname or alias.name
                    self._imports[name] = node.module

    @staticmethod
    def _literal_strings(node: ast.expr) -> set[str] | None:
        """The string elements of a set/list/tuple literal, or a dict's string keys."""
        if isinstance(node, (ast.Set, ast.List, ast.Tuple)):
            return set(_string_constants(node.elts)) or None
        if isinstance(node, ast.Dict):
            return set(_string_constants(node.keys)) or None
        return None

    @staticmethod
    def _node_label(node: ast.expr) -> str | None:
        """Human-readable label: ``Name`` or ``Name.attr``."""
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            return f"{node.value.id}.{node.attr}"
        return None

    def _add(self, lineno: int, var: str, op: str, value_desc: str) -> None:
        if var.lower() in INFRA_VARS:
            self._filtered.append(var)
            return
        self.entries.append((lineno, var, op, value_desc))

    def _add_literal(self, lineno: int, var: str, op: str, val: str) -> None:
        if not val or _NOISE_LITERAL.match(val):
            self._filtered.append(var)
            return
        self._add(lineno, var, op, repr(val))

    def _resolve(self, name: str) -> str:
        """Annotate a named operand with its definition or import source."""
        base = name.split(".")[0]
        if base in self._const_defs:
            defline, vals = self._const_defs[base]
            resolved = ", ".join(repr(v) for v in sorted(vals))
            return f"{name} [Name, resolved: {{{resolved}}}, def. line {defline}]"
        if base in self._imports:
            return f"{name} [Name, imported from {self._imports[base]}]"
        return f"{name} [Name, unresolved]"

    def visit_Compare(self, node: ast.Compare) -> None:  # noqa: C901 complexity baseline 2026-10-08
        for op, comparator in zip(node.ops, node.comparators):
            if isinstance(op, (ast.Eq, ast.NotEq)):
                op_str = "==" if isinstance(op, ast.Eq) else "!="
                left_var = _name_of(node.left) or "?"
                if isinstance(comparator, ast.Constant) and isinstance(
                    comparator.value, str
                ):
                    self._add_literal(node.lineno, left_var, op_str, comparator.value)
                else:
                    label = self._node_label(comparator)
                    if label:
                        self._add(node.lineno, left_var, op_str, self._resolve(label))
                right_var = _name_of(comparator) or "?"
                if isinstance(node.left, ast.Constant) and isinstance(
                    node.left.value, str
                ):
                    self._add_literal(node.lineno, right_var, op_str, node.left.value)

            elif isinstance(op, (ast.In, ast.NotIn)):
                op_str = "in" if isinstance(op, ast.In) else "not in"
                left_var = _name_of(node.left) or "?"
                if isinstance(comparator, (ast.Set, ast.List, ast.Tuple)):
                    strs = _string_constants(comparator.elts)
                    if strs:
                        if all(_NOISE_LITERAL.match(s) for s in strs):
                            self._filtered.append(left_var)
                        else:
                            vals = ", ".join(repr(s) for s in strs)
                            self._add(node.lineno, left_var, op_str, f"{{{vals}}}")
                else:
                    label = self._node_label(comparator)
                    if label:
                        self._add(node.lineno, left_var, op_str, self._resolve(label))
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "get"
            and len(node.args) >= 2
        ):
            default = node.args[1]
            if isinstance(default, ast.Constant) and isinstance(default.value, str):
                holder = _name_of(func.value) or "?"
                self._add_literal(node.lineno, holder, ".get default", default.value)
        self.generic_visit(node)


def gate_labels(area: Path) -> str:
    """String comparisons in evaluation code — facts, not findings.

    The prompt↔gate scar (LAB-038 What the prompt demands) was the most frequent error class (4× in one
    area). The mechanics extract what the gate compares against; the agent
    judges whether it matches the prompt.
    """
    _producers, consumers = split_stages(area)
    all_entries: list[tuple[str, int, str, str, str]] = []
    all_filtered: list[str] = []
    for c in consumers:
        try:
            source = c.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=c.name)
        except (OSError, SyntaxError):
            continue
        v = _ComparisonVisitor(c.name, source)
        v.visit(tree)
        for lineno, var, op, value_desc in v.entries:
            all_entries.append((c.name, lineno, var, op, value_desc))
        all_filtered.extend(v._filtered)

    lines = [
        "## Gate labels (mechanically extracted — judge them against the prompt)",
        "",
    ]
    if all_entries:
        lines.append(
            "Comparisons in evaluation code (variable · operator · value · source):"
        )
        for fname, lineno, var, op, value_desc in all_entries:
            lines.append(f"  {fname}:{lineno}  {var} {op} {value_desc}")
    else:
        lines.append("No string comparisons found in evaluation code.")

    if all_filtered:
        vars_summary = ", ".join(sorted(set(all_filtered)))
        lines.append(
            f"\n({len(all_filtered)} comparison(s) filtered as "
            f"infrastructure: {vars_summary})"
        )
    lines.append("")
    return "\n".join(lines) + "\n"


def split_stages(area: Path) -> tuple[list[Path], list[Path]]:
    """(producers, consumers) — the numbering IS the pipeline order."""
    scripts = sorted(area.glob("scripts/*.py"))
    analysis = sorted(area.glob("analysis/*.py"))
    consumers = [p for p in scripts if CONSUMER.match(p.name)] + analysis
    producers = [p for p in scripts if p not in consumers]
    return producers, consumers


def check_intent_ids(area: Path, protocol: Path) -> list[str]:
    """Registered promises against the code, before any run exists.

    `intent-check` asks the same question of the metrics at report time, when
    the tokens are already spent. Here the answer is still cheap.
    """
    text = protocol.read_text(encoding="utf-8")
    findings = promise_block_findings(area, protocol, text)
    registered = {m.group(1).lower() for m in ID_IN_PROTOCOL.finditer(text)}
    if not registered:
        return findings
    in_code = code_ids(area)
    unmistakable = code_ids(area, suffixed_only=True)
    for i in sorted(registered - set(in_code)):
        findings.append(
            f"BLOCKER · {protocol.name} · [{i.upper()}] is registered, but no "
            f"script mentions a '{i}'/'{i}_*' key · the run reports nothing "
            f"for this promise and the metrics check fails after the tokens "
            f"are spent · LAB-004 Identifiers make the intent addressable · implement the key or drop the id"
        )
    for i in sorted(set(unmistakable) - registered):
        findings.append(
            f"WARNING · {unmistakable[i][0]} · key '{i}_*' is in the intent-id "
            f"namespace, but the protocol registers no [{i.upper()}] · a "
            f"number gets reported that nobody registered · LAB-004 Identifiers make the intent addressable · register "
            f"it or rename the key"
        )
    return findings


def promise_block_findings(area: Path, protocol: Path, text: str) -> list[str]:
    """The promise block against the code, before any run (guaranteed tier).

    Three things a run would otherwise discover after the tokens are spent:
    the block does not parse, a declared scope names code that is not there
    (runlog refuses the run), a declared key appears nowhere in the code
    (intent-check fails after the run). Exact key, not id: `"c1_passed"`
    does not answer a promise declaring `c1_pass` (Durchstich 2026-10-06).
    """
    try:
        block = promises.parse_block(text)
    except promises.PromiseError as exc:
        return [
            f"BLOCKER · {protocol.name} · promise block: {exc} · LAB-004 Identifiers make the intent addressable · fix the block"
        ]
    if block is None:
        return []
    out = []
    keys = code_keys(area)
    out += admissibility_reads(area, protocol, block, keys)
    for p in block.promises:
        try:
            promises.declared_scope_sha(area, p.scope)
        except promises.PromiseError as exc:
            out.append(
                f"BLOCKER · {protocol.name} · [{p.id}] declared scope: "
                f"{exc} · runlog refuses the run · fix the scope"
            )
        out += constant_copies(area, protocol, p)
        if p.key not in keys:
            near = sorted(k for k in keys if k.startswith(p.id.lower()))
            hint = f" (the code has {', '.join(near)})" if near else ""
            out.append(
                f"BLOCKER · {protocol.name} · [{p.id}] declares key "
                f"'{p.key}', which no script mentions{hint} · intent-check "
                f"fails after the run · report the declared key or fix "
                f"the block"
            )
    return out


_DECIDING_CALLS = frozenset({"all", "any"})


def _decides(node: ast.AST, parents: dict[int, ast.AST]) -> bool:
    """Does NODE sit where a decision is taken: the test of an `if`, `while`,
    `assert` or conditional expression, an operand of `and`/`or`/`not`, or
    an argument of `all()`/`any()`? Climbs to the enclosing statement."""
    child, here = node, parents.get(id(node))
    while here is not None and not isinstance(child, ast.stmt):
        if isinstance(here, (ast.If, ast.While, ast.Assert, ast.IfExp)):
            if child is here.test:
                return True
        elif isinstance(here, ast.BoolOp) or (
            isinstance(here, ast.UnaryOp) and isinstance(here.op, ast.Not)
        ):
            return True
        elif isinstance(here, ast.Call) and _name_of(here.func) in _DECIDING_CALLS:
            return True
        child, here = here, parents.get(id(here))
    return False


def _loop_keys(
    name: str, node: ast.AST, parents: dict[int, ast.AST], tuples: dict[str, list[str]]
) -> list[str]:
    """The string literals the loop variable NAME runs over, for the nearest
    enclosing `for` or comprehension that binds it: an inline tuple, list or
    set, or a name this file binds to one (`ADMISSIBILITY = ("a1_pass", …)`)."""
    here = parents.get(id(node))
    while here is not None:
        loops = (
            here.generators
            if isinstance(
                here, (ast.GeneratorExp, ast.ListComp, ast.SetComp, ast.DictComp)
            )
            else [here]
            if isinstance(here, (ast.For, ast.AsyncFor))
            else []
        )
        for loop in loops:
            if _name_of(loop.target) == name:
                it = loop.iter
                if isinstance(it, (ast.Tuple, ast.List, ast.Set)):
                    return _string_constants(it.elts)
                return tuples.get(_name_of(it) or "", [])
        here = parents.get(id(here))
    return []


def _key_reads(path: Path) -> set[str]:
    """The keys this file reads where a decision is taken (`_decides`):
    `m["a1_pass"]`, `m.get("a1_pass")`, `m[k]` with `k` running over a
    collection of key literals, and a bare name `a1_pass`. A read anywhere
    else — a print, a copy into another dict — decides nothing.

    Raises:
        ValueError: The file does not parse — a read check over code it
            cannot read would report a missing branch that may be there.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError as exc:
        raise ValueError(f"{path}: does not parse ({exc.msg}, line {exc.lineno})")
    parents = {id(c): n for n in ast.walk(tree) for c in ast.iter_child_nodes(n)}
    tuples = {
        t.id: _string_constants(n.value.elts)
        for n in ast.walk(tree)
        if isinstance(n, ast.Assign)
        and isinstance(n.value, (ast.Tuple, ast.List, ast.Set))
        for t in n.targets
        if isinstance(t, ast.Name)
    }
    reads: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Subscript) and isinstance(n.ctx, ast.Load):
            key = n.slice
        elif (
            isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "get"
            and n.args
        ):
            key = n.args[0]
        elif isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
            if _decides(n, parents):
                reads.add(n.id)
            continue
        else:
            continue
        if not _decides(n, parents):
            continue
        if isinstance(key, ast.Constant) and isinstance(key.value, str):
            reads.add(key.value)
        elif (var := _name_of(key)) is not None:
            reads.update(_loop_keys(var, n, parents, tuples))
    return reads


def admissibility_reads(
    area: Path, protocol: Path, block: "promises.PromiseTables", keys: dict
) -> list[str]:
    """Every [A] key the code writes must also be read (static evidence).

    An admissibility condition permits the C verdict — C judges, A permits
    the verdict (LAB-004 Identifiers make the intent addressable). A key
    that is computed and never read is a label without effect: the
    criterion is reported whether the condition held or not (Opus audit,
    probe 11: "[N1] was a label without effect"; class C, 24 findings over
    six repos). Only a read where a decision is taken counts (`_key_reads`),
    but a decision on the key is not proof that it withholds the verdict,
    and a decision in a form this reader does not follow is missed — so
    the finding is a WARNING, and silence means only "decided on
    somewhere". A key the code does not mention at all is the blocker
    `promise_block_findings` already reports.
    """
    owed = [p for p in block.promises if p.kind == "admissibility" and p.key in keys]
    if not owed:
        return []
    root = layout_root(area)
    files = area_files(area) + imported_repo_helpers(area, root)
    try:
        reads = set().union(*(_key_reads(f) for f in files))
    except ValueError as exc:
        return [
            f"WARNING · {protocol.name} · [A] keys: read check not done — {exc} "
            f"· fix the file"
        ]
    return [
        f"WARNING · {keys[p.key][0]} · [{p.id}] key '{p.key}' is written but "
        f"nothing decides on it · the C verdict is reported whether [{p.id}] held or "
        f"not · LAB-004 Identifiers make the intent addressable · withhold "
        f'the verdict when it fails (`if not m["{p.key}"]: …`)'
        for p in owed
        if p.key not in reads
    ]


def _literal(node: ast.expr) -> object:
    """The value of a literal (`0.7`, `-3`, `"x"`); a `_NOT_LITERAL` otherwise."""
    try:
        return ast.literal_eval(node)
    except (ValueError, SyntaxError, TypeError):
        return _NOT_LITERAL


_NOT_LITERAL = object()


def constant_copies(area: Path, protocol: Path, p: "promises.Promise") -> list[str]:
    """A declared constant the scope's code sets itself, as a literal
    (static evidence — a warning, never a blocker).

    The script is meant to read its thresholds from the block
    (`promises.constants`); a literal copy judges by a value nobody
    registered as soon as the two drift, and intent-check sees it only if
    the run records the value (Durchstich 2026-10-07). A copy under another
    name, or a threshold written inline (`mean >= 1.5`), stays invisible
    here — that is the agent audit's question.
    """
    if not p.constants:
        return []
    out = []
    for path in sorted({area / entry.partition(":")[0] for entry in p.scope}):
        if path.suffix != ".py" or not path.is_file():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            targets = (
                node.targets
                if isinstance(node, ast.Assign)
                else [node.target]
                if isinstance(node, ast.AnnAssign) and node.value
                else []
            )
            for target in targets:
                if not (isinstance(target, ast.Name) and target.id in p.constants):
                    continue
                assert (
                    isinstance(node, (ast.Assign, ast.AnnAssign))
                    and node.value is not None
                )
                value = _literal(node.value)
                if value is _NOT_LITERAL:
                    continue
                declared = p.constants[target.id]
                same = (
                    "the same value"
                    if value == declared
                    else f"the block says {declared!r}"
                )
                out.append(
                    f"WARNING · {protocol.name} · [{p.id}] "
                    f"{path.relative_to(area).as_posix()}:{node.lineno} sets "
                    f"{target.id} = {value!r} itself ({same}) · a copy judges by "
                    f"an unregistered value once they drift · read it with "
                    f'promises.constants(PROTOCOL, "{p.id}")["{target.id}"]'
                )
    return out


def schema_facts(area: Path) -> str:
    """The field table — facts for the agent, not findings of our own.

    Three calibration rounds (2026-09-10, areas 60-73) failed to make this a
    checker. Every narrowing removed one false-blocker class and left the
    next: fields staged into files a later step writes, a `fan_v1.jsonl` that
    is simply not on disk any more, a consumer that reads across area
    boundaries (72 reads 71's prepared data). Deciding whether a read is
    satisfied needs the data FLOW, and that is exactly what a model reads
    well and a parser does not.

    So the mechanics stop at the facts: which fields the analysis reads, and
    which keys the area's data rows actually carry. The agent holds them
    against each other — with the lookup work already done, which is the part
    that used to cost it minutes of grepping.
    """
    producers, consumers = split_stages(area)
    known, files = data_keys(area)
    lines = [
        "## Schema facts (mechanically extracted — judge them, they are not findings)",
        "",
    ]
    lines.append(
        f"Data keys present in the area's own JSON(L) rows "
        f"({', '.join(files) if files else 'no data materialized yet'}):"
    )
    lines.append("  " + (", ".join(sorted(known)) if known else "—"))
    lines.append("")
    lines.append(
        "Fields read by the analysis stage, with the variable read "
        "from — a name absent from the list above is either staged "
        "by an earlier step, read from another area, or a defect:"
    )
    for c in consumers:
        v = scan(c)
        if v is None:
            lines.append(f"  {c.name}: DOES NOT PARSE")
            continue
        unexplained = sorted(
            f
            for f, (_, holder) in v.reads.items()
            if f not in known
            and f not in v.writes
            and FIELDISH.match(f)
            and holder
            and holder not in v.built
        )
        if unexplained:
            for f in unexplained:
                site, holder = v.reads[f]
                lines.append(
                    f"  {site}: '{f}' from `{holder}` — not in the area's data"
                )
        else:
            lines.append(f"  {c.name}: every read field is present in the area's data")
    return "\n".join(lines) + "\n"


# --- the bundle -----------------------------------------------------------


def severity_legend() -> str:
    """The severity legend of LAB-015 Preflight audit before freezing, quoted from the
    lab standard for the bundle: the code-check agent reads only the bundle and
    cannot look the legend up, and both audit agents must grade by the same words."""
    return (
        "## Severity legend (LAB-015 Preflight audit before freezing, labkit standard)\n\n"
        + rules.paragraph("LAB-015", "**Severity levels**")
        + "\n"
    )


def write_bundle(area: Path, repo: Path, protocol: Path, out: Path) -> int:
    """Write the audit bundle for the code-check agent: schema facts, gate labels, intent ids, protocol and code in one file."""
    parts = [
        f"# AUDIT BUNDLE · area {area.name}\n\n",
        severity_legend(),
        "\n",
        schema_facts(area),
        "\n",
        gate_labels(area),
        "\n",
    ]
    files = [protocol]
    files += sorted(area.glob("scripts/*.py")) + sorted(area.glob("analysis/*.py"))
    files += imported_repo_helpers(area, repo)
    for f in files:
        try:
            body = f.read_text(encoding="utf-8")
        except OSError:
            continue
        try:
            label = f.relative_to(repo)
        except ValueError:
            label = f
        parts.append(f"\n===== FILE: {label} =====\n{body}")
    out.write_text("".join(parts), encoding="utf-8")
    return len(files)


# --- cli ------------------------------------------------------------------

DYNAMIC_LOADERS = {
    "import_module",
    "spec_from_file_location",
    "run_path",
    "run_module",
    "__import__",
    "exec",
}


def _call_name(node: ast.Call) -> str:
    """The last name of what a call calls: `importlib.import_module(...)` → import_module."""
    f = node.func
    if isinstance(f, ast.Attribute):
        return f.attr
    if isinstance(f, ast.Name):
        return f.id
    return ""


def _is_sys_path(node: ast.AST | None) -> bool:
    """True for the expression `sys.path`."""
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "path"
        and isinstance(node.value, ast.Name)
        and node.value.id == "sys"
    )


def _outside_roots(name: str, area: Path, repo: Path) -> Path | None:
    """The repo file an import of dotted NAME resolves to when it lies
    outside LOCAL_ROOTS and outside the area's own scripts — None otherwise
    (a stdlib or third-party name resolves to nothing in the repo)."""
    seg = name.split(".")[0]
    if not seg or seg in LOCAL_ROOTS:
        return None
    if (area / "scripts" / f"{seg}.py").is_file() or (
        area / "analysis" / f"{seg}.py"
    ).is_file():
        return None  # a sibling in the area: stamped with it
    for candidate in (repo / f"{seg}.py", repo / seg / "__init__.py"):
        if candidate.is_file():
            return candidate
    if (repo / seg).is_dir() and seg not in ("data", "tests", "notes", "docs", "runs"):
        return (
            repo / seg
        )  # a package without __init__ — a namespace package, or a path import
    return None


#: an area name inside a path string: `14-hotel`, `experiments/14-hotel/scripts/x.py`
AREA_IN_PATH = re.compile(r"(?:^|/)(\d{2}-[a-z0-9][a-z0-9-]*)(?:/|$)")


def _str_constants(node: ast.AST) -> set[str]:
    """Every string literal inside NODE."""
    return {
        n.value
        for n in ast.walk(node)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    }


def _sys_path_target(node: ast.AST) -> ast.AST | None:
    """The expression a `sys.path.<method>(…)` call, `sys.path += …` or
    `sys.path[…] = …` adds — None when NODE is none of these."""
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        if _is_sys_path(node.func.value) and node.args:
            return node.args[-1]
    if isinstance(node, ast.AugAssign) and _is_sys_path(node.target):
        return node.value
    if isinstance(node, ast.Assign) and any(
        _is_sys_path(t) or (isinstance(t, ast.Subscript) and _is_sys_path(t.value))
        for t in node.targets
    ):
        return node.value
    return None


def _import_findings(
    node: ast.Import | ast.ImportFrom,
    area: Path,
    repo: Path,
    where: Path,
    rule: str,
    fix: str,
) -> list[tuple[int, str]]:
    """The imports of NODE that resolve outside lib/ and src/."""
    names = (
        [a.name for a in node.names]
        if isinstance(node, ast.Import)
        else ([node.module] if node.module and not node.level else [])
    )
    out = []
    for name in names:
        found = _outside_roots(name, area, repo)
        if found is not None:
            out.append(
                (
                    node.lineno,
                    (
                        f"WARNING · {where}:{node.lineno} · `{name}` resolves to "
                        f"{found.relative_to(repo)}, outside lib/ and src/ · the stamp does "
                        f"not cover it, a change there moves the number unseen · {rule} · {fix}"
                    ),
                )
            )
    return out


def _path_under_area(expr: ast.expr, area: Path) -> Path | None:
    """`AREA / "scripts" / "01_measure.py"` read as that path; None for any
    other expression (only literal parts after the area's own name)."""
    if isinstance(expr, ast.Name) and expr.id == "AREA":
        return area
    if (
        isinstance(expr, ast.BinOp)
        and isinstance(expr.op, ast.Div)
        and isinstance(expr.right, ast.Constant)
        and isinstance(expr.right.value, str)
    ):
        base = _path_under_area(expr.left, area)
        return base / expr.right.value if base is not None else None
    return None


def _loads_area_file(node: ast.Call, area: Path) -> bool:
    """Does this loader call name, as a literal path, a file the area's stamp
    covers already (`scope_sha.area_files`)? The stamped 02_analyze.py loads
    its own 01_measure.py so; warning on it made every fresh area with a
    model start with a WARNING from labkit's own skeleton (cold Sonnet,
    2026-10-14). A computed path stays a finding."""
    covered = {f.resolve() for f in area_files(area)}
    return any(
        (target := _path_under_area(arg, area)) is not None
        and target.resolve() in covered
        for arg in node.args
    )


def _coverage_in(
    path: Path, area: Path, repo: Path, own: bool
) -> list[tuple[int, str]]:
    """(line, finding) for one file — see stamp_coverage_findings. Dynamic
    loaders and foreign-area paths are read in the area's OWN files only: a
    shared helper's loader is parameterised by its caller, and reporting it
    for every area that imports the helper would be the same line forever."""
    rule = "LAB-019 The stamp covers everything that determines the number"
    fix = (
        "declare the file as a promise's scope (its declared_scope_sha then "
        "sees it) or copy it into the area"
    )
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (SyntaxError, UnicodeDecodeError):
        return []  # scope_sha raises on this file already; one loud place
    root = repo.resolve()
    where = (
        path.resolve().relative_to(root)
        if path.resolve().is_relative_to(root)
        else path
    )
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        line = getattr(node, "lineno", 0)
        target = _sys_path_target(node)
        if target is not None:
            names = _str_constants(target)
            if names and names <= set(LOCAL_ROOTS):
                continue  # the stamped template's `sys.path.insert(0, REPO / "lib")`
            out.append(
                (
                    line,
                    (
                        f"WARNING · {where}:{line} · `sys.path` gains "
                        f"{', '.join(sorted(names)) or 'a computed path'} · imports after it may "
                        f"resolve outside lib/ and src/, which the stamp does not follow · {rule} · {fix}"
                    ),
                )
            )
        elif own and isinstance(node, ast.Call) and _call_name(node) in DYNAMIC_LOADERS:
            if _loads_area_file(node, area):
                continue  # the stamped analysis skeleton loading its own 01_measure.py
            out.append(
                (
                    node.lineno,
                    (
                        f"WARNING · {where}:{node.lineno} · `{_call_name(node)}(…)` loads code at "
                        f"run time · the stamp follows `import` lines only, so what this loads "
                        f"changes the number unseen · {rule} · {fix}"
                    ),
                )
            )
        elif own and isinstance(node, ast.Constant) and isinstance(node.value, str):
            foreign = sorted(
                {m for m in AREA_IN_PATH.findall(node.value) if m != area.name}
            )
            if foreign:
                out.append(
                    (
                        node.lineno,
                        (
                            f"WARNING · {where}:{node.lineno} · names area `{foreign[0]}` · a file "
                            f"of another area determines this number, and this area's stamp does "
                            f"not cover it (uniagent 15–17: the script of 14) · {rule} · {fix}"
                        ),
                    )
                )
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            out += _import_findings(node, area, repo, where, rule, fix)
    return out


def stamp_coverage_findings(area: Path, repo: Path) -> list[str]:
    """Code the stamp cannot follow (static evidence, WARNING only): a
    `sys.path` edit that does not point at `lib/` or `src/`, a dynamic
    loader, a path naming another area, an import resolving outside
    `lib/` and `src/`. The stamp (`scope_sha.area_stamp`) walks static
    imports into LOCAL_ROOTS and nothing else; what these lines pull in
    determines the number without any stamp seeing a change to it."""
    out: list[tuple[str, int, str]] = []
    for path in area_files(area):
        out += [(str(path), n, f) for n, f in _coverage_in(path, area, repo, own=True)]
    for path in imported_repo_helpers(area, repo):
        out += [(str(path), n, f) for n, f in _coverage_in(path, area, repo, own=False)]
    return [
        f for _, _, f in sorted(out)
    ]  # ast.walk is breadth-first; the reader wants source order


PARSE_DEF = re.compile(r"^\s*def (parse_\w+)\s*\(", re.M)
PROMPT_NAME = re.compile(r"^PROMPT(_[A-Z0-9_]+)?$")
PROMPT_FIELD = re.compile(r"^\s*[-*]\s*\*{0,2}prompt\b", re.I)
FENCE = re.compile(r"^\s*```")
PLACEHOLDER_IN_PROMPT = re.compile(r"\{[^{}]*\}")


def check_parser_fixtures(area: Path, repo: Path) -> list[str]:
    """Every `parse_*` in the area's scripts is named in some test file."""
    scripts = (
        sorted((area / "scripts").glob("*.py")) if (area / "scripts").is_dir() else []
    )
    parsers: dict[str, Path] = {}
    for sp in scripts:
        for m in PARSE_DEF.finditer(sp.read_text(encoding="utf-8")):
            parsers.setdefault(m.group(1), sp)
    if not parsers:
        return []
    tests_dir = repo / "tests"
    test_text = (
        "\n".join(
            t.read_text(encoding="utf-8") for t in sorted(tests_dir.glob("test_*.py"))
        )
        if tests_dir.is_dir()
        else ""
    )
    findings = []
    for name, sp in sorted(parsers.items()):
        if not re.search(rf"\b{re.escape(name)}\b", test_text):
            findings.append(
                f"BLOCKER · {sp.name} · {name}() has no test under {tests_dir.name}/ · "
                f"a parser fails silently into a wrong number · give it a fixture "
                f"with real raw answers (LAB-016 Resolution check before freezing, 2026-10-05)"
            )
    return findings


_Value = str | tuple[str, ...]


def _value_of(node: ast.AST, env: dict[str, _Value]) -> _Value | None:  # noqa: C901 complexity baseline 2026-10-08
    """A module-level constant as the script would compute it, or None.

    Read statically, never executed: string literals, names of earlier
    constants, `+`, f-strings over those, `"sep".join(<constant>)`, and the
    keys of a dict or the items of a list/tuple of strings. The stamped
    skeleton builds `PROMPT = "..." + ANSWER_LINE` with
    `ANSWER_LINE = f"... {' or '.join(ANSWERS)}."`; reading literals only
    made every stamped prompt unreadable, so the drift check never ran
    (re-measure 2026-10-07, three of three judge agents)."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return env.get(node.id)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        a, b = _value_of(node.left, env), _value_of(node.right, env)
        return a + b if isinstance(a, str) and isinstance(b, str) else None
    if isinstance(node, ast.JoinedStr):
        parts = []
        for v in node.values:
            if isinstance(v, ast.FormattedValue):
                if v.conversion != -1 or v.format_spec is not None:
                    return None
                v = v.value
            part = _value_of(v, env)
            if not isinstance(part, str):
                return None
            parts.append(part)
        return "".join(parts)
    if isinstance(node, (ast.Dict, ast.List, ast.Tuple)):
        items = node.keys if isinstance(node, ast.Dict) else node.elts
        out = []
        for item in items:
            if item is None:
                return None
            v = _value_of(item, env)
            if not isinstance(v, str):
                return None
            out.append(v)
        return tuple(out)
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "join"
        and len(node.args) == 1
        and not node.keywords
    ):
        sep, seq = _value_of(node.func.value, env), _value_of(node.args[0], env)
        if isinstance(sep, str) and isinstance(seq, tuple):
            return sep.join(seq)
    return None


def _script_prompts(source: str) -> tuple[dict[str, str], list[str]]:
    """(readable PROMPT constants, names of unreadable ones) of one script."""
    env: dict[str, _Value] = {}
    found: dict[str, str] = {}
    unreadable: list[str] = []
    for node in ast.parse(source).body:
        if not (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            continue
        name = node.targets[0].id
        value = _value_of(node.value, env)
        if value is not None:
            env[name] = value
        if PROMPT_NAME.match(name):
            if isinstance(value, str):
                found[name] = value
            else:
                unreadable.append(name)
    return found, unreadable


def prompt_constants(area: Path) -> dict[str, str]:
    """`PROMPT` / `PROMPT_<VARIANT>` string constants across the area's
    scripts, as the scripts compute them (`_value_of`)."""
    return _prompts(area)[0]


def _prompts(area: Path) -> tuple[dict[str, str], list[str]]:
    out: dict[str, str] = {}
    unreadable: list[str] = []
    scripts = (
        sorted((area / "scripts").glob("*.py")) if (area / "scripts").is_dir() else []
    )
    for sp in scripts:
        try:
            found, bad = _script_prompts(sp.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        out.update(found)
        unreadable += [f"{sp.name}:{n}" for n in bad]
    return out, unreadable


_NEXT_FIELD = re.compile(r"^(\s*)[-*]\s+\*\*|^#")


def prompt_blocks(protocol: Path) -> list[str]:
    """Every fenced block under a `Prompt` field, up to the next field or
    heading — one block per variant is a written form, and reading only the
    first made a null prompt in a second block look missing (re-measure
    2026-10-07: five false blockers in twelve protocols once the check ran)."""
    lines = protocol.read_text(encoding="utf-8").splitlines()
    blocks: list[str] = []
    i = 0
    while i < len(lines):
        if not PROMPT_FIELD.match(lines[i]):
            i += 1
            continue
        indent = len(lines[i]) - len(lines[i].lstrip())
        j = i + 1
        while j < len(lines):
            nxt = _NEXT_FIELD.match(lines[j])
            if nxt and (lines[j].startswith("#") or len(nxt.group(1)) <= indent):
                break
            if FENCE.match(lines[j]):
                k = j + 1
                while k < len(lines) and not FENCE.match(lines[k]):
                    k += 1
                blocks.append("\n".join(lines[j + 1 : k]))
                j = k
            j += 1
        i = j
    return blocks


def check_prompt_drift(area: Path, protocol: Path) -> list[str]:
    """The protocol's prompt block against the PROMPT constant(s).

    Compared line by line: every non-empty line of the constant that carries
    no `{placeholder}` must appear, stripped, in some prompt block. A block
    rendered with real data passes; a transcript that drifted does not."""
    consts, unreadable = _prompts(area)
    # A prompt this reader cannot compute is unchecked — said aloud, never a
    # silent pass (re-measure 2026-10-07: the stamped skeleton's were).
    warnings = [
        f"WARNING · {name} is not statically readable (a call or a format "
        f"spec this check does not compute) · prompt drift unchecked for it"
        for name in unreadable
    ]
    # a block that only holds a `<placeholder>` is the template's, not a prompt
    blocks = [b for b in prompt_blocks(protocol) if not b.strip().startswith("<")]
    if not consts or not blocks:
        return warnings
    have = {ln.strip() for b in blocks for ln in b.splitlines() if ln.strip()}
    findings = []
    for name, text in sorted(consts.items()):
        fixed = [
            ln.strip()
            for ln in text.splitlines()
            if ln.strip() and not PLACEHOLDER_IN_PROMPT.search(ln)
        ]
        missing = [ln for ln in fixed if ln not in have]
        if fixed and missing:
            findings.append(
                f"BLOCKER · {protocol.name} · prompt block drifted from {name}: "
                f"{len(missing)} of {len(fixed)} fixed line(s) missing, e.g. "
                f"{missing[0][:60]!r} · paste the rendered `--show` output, not a "
                f"transcript (LAB-007 Render check before the instrument check, 2026-10-05)"
            )
    return warnings + findings


def _cost_of(protocol: Path) -> str | None:
    """The protocol head's cost tier, None when the head does not parse (the
    checker reports that; this is only for the summary's wording)."""
    try:
        return protocol_block.head(protocol.read_text(encoding="utf-8")).cost
    except protocol_block.BlockError:
        return None


def main(argv: list[str]) -> int:  # noqa: C901 complexity baseline 2026-10-08
    """Command line of `code-check`: check an area's code against its protocol, optionally write the bundle."""
    if not argv or argv[0] in ("-h", "--help"):
        print((__doc__ or "").strip().splitlines()[0])
        print("usage: code-check <AREA> [--protocol FILE] [--bundle FILE]")
        print(
            "  --protocol FILE  the PROTOCOL-*.md to check against "
            "(required once the area holds more than one)"
        )
        print(
            "  --bundle FILE    pack sources + schema facts + gate labels "
            "for the audit agent"
        )
        return 0 if argv else 2

    area = area_path(argv[0])
    bundle_to = None
    protocol_arg = None
    rest = argv[1:]
    while rest:
        if rest[0] in ("--bundle", "--protocol") and len(rest) >= 2:
            if rest[0] == "--bundle":
                bundle_to = Path(rest[1])
            else:
                protocol_arg = Path(rest[1])
            rest = rest[2:]
            continue
        print(f"code-check: unexpected argument {rest[0]!r}")
        return 2

    if not area.is_dir():
        print(f"code-check: {no_such_area(area)}")
        return 2

    protocol = choose_protocol(area, protocol_arg, "code-check")
    if protocol is None:
        return 2

    repo = layout_root(area)
    findings = (
        check_intent_ids(area, protocol)
        + check_parser_fixtures(area, repo)
        + check_prompt_drift(area, protocol)
        + stamp_coverage_findings(area, repo)
    )
    for f in findings:
        print(f)

    if bundle_to is not None:
        n = write_bundle(area, layout_root(area), protocol, bundle_to)
        print(
            f"bundle: {n} file(s) -> {bundle_to} "
            f"({bundle_to.stat().st_size // 1024} KB)"
        )

    blockers = sum(1 for f in findings if f.startswith("BLOCKER"))
    warnings = sum(1 for f in findings if f.startswith("WARNING"))
    parts = [
        f"intent-ids: {blockers} blocker(s), {warnings} warning(s) "
        f"(incl. parser fixtures, prompt drift, stamp coverage)"
    ]
    if bundle_to is not None:
        parts.append(
            "schema + gate labels + placeholders extracted into "
            "the bundle for the code-check agent"
        )
    elif _cost_of(protocol) == "seconds":
        parts.append(
            "schema, gate labels, placeholders: not checked — not owed at cost "
            "seconds, the first run is the probe (--bundle hands them to the "
            "code-check agent anyway)"
        )
    else:
        parts.append(
            "schema, gate labels, placeholders: not checked "
            "(need --bundle for the code-check agent)"
        )
    print(" — ".join(parts))
    return 1 if findings else 0


def cli() -> None:
    """Console entry point of `code-check`."""
    console.exit_with(main)


if __name__ == "__main__":
    cli()
