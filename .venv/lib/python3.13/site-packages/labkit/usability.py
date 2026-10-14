"""usability — stage a probe lab repo for a cold agent, then score the trace.

    usability stage <dir> [--venv PATH]     a fresh lab repo with one kept-number task
    usability stage <dir> --restamp [--keep PATH ...]   the same probe stamped again with this labkit
    usability log TAG TEXT [--log FILE] [-- CMD ...]     one step line with the time, then CMD
    usability score <dir> [--transcript F] [--agent M]  number · binding · log (· transcript) → one table, one JSON
    usability trace <transcript>            the agent's timeline, one line per tool call

Reading a protocol (protocol_reading), each a prompt for a cold reader and
its score against the run:

    usability reader <dir> / read-score <dir>     the whole protocol
    usability glance <dir> / glance-score <dir>   only its first ten lines
    usability terms <dir>                         the reader's unclear terms vs Summary and Terms

Finding one's way in code (code_navigation):

    usability nav <repo> --questions Q --out P / nav-score ...   "where does the code do X?"
    usability human <repo> --questions Q --out P   a person answers the behaviour questions, timed

Why this exists (2026-10-05): the doctrine grew by scars, every scar added
a gate, and nobody measured what the whole chain costs for the simplest
case — one deterministic number, kept. uniagent area 01 needed four days,
three freezes and three agent audits for a seven-second run. A rule that
costs more than the error it prevents is a rule to cut, but only a trace
shows which one; this is the trace.

stage
    Stamps a lab repo with labkit's own scaffold (`labkit-init lab`, then
    `labkit-init exp <area>`), commits it, plants the task's fixture —
    `--task count` (default): twelve cases and their files, a deterministic
    mean; `--task judge`: twelve sentences with a gold label, a model's
    accuracy, no truth, only a range and a null condition to report — with a
    known answer (twelve cases, their input files; the answer is recounted
    from the files at score time, never written down) and TASK.md — the
    task sheet, from `usability-task-<task>.md.template`, with the log
    contract and the metrics key the number must land under — and
    `<dir>.prompt.md`, the prompt a cold agent gets: the repo's AGENTS.md
    as a session loads it, then the pointer to TASK.md. A venv with
    labkit is created unless `--venv` links an existing one. What was
    measured is pinned in `<dir>.probe.json`: the labkit the probe venv
    holds, a sha over the scaffolder and the templates it stamps, the flags.
    Side effects: a git repo with three commits, a venv or a symlink, three
    sidecar files next to <dir> (probe.json, log.md, prompt.md).

log
    The agent's step log, one call per step: appends `HH:MM:SS · TAG · TEXT`
    to the log (`--log`, default `log.md` in the working directory) and then
    runs CMD, whose exit code is the command's. Without CMD it only logs (a
    read or an edit done with a tool). Why: logging by hand, with `date` and
    `>>`, tempted every cold agent to batch — three draws wrote their first
    lines after the reads they describe (Haiku H5–H7, 2026-10-13), and the
    log is the measurement.

stage --restamp
    The probe stamped again with this labkit, in place: a fresh stamp with
    the task and flags `<dir>.probe.json` records is laid over <dir> file by
    file — a stamped file whose bytes changed is overwritten, a new one
    added, and every path named with `--keep` (the probe's hand edits: the
    task sheet, the ignore list, a hook of the cloud) stays as it is. The
    kept paths are recorded in `<dir>.probe.json` and are the default next
    time. The probe's venv is rebuilt from the stamped pin (or linked with
    `--venv`), so `requirements.lock` and `labkit-check` agree, and the
    change is committed past the hook (the stamped protocol is placeholders
    by design). The push stays with the operator. Why (2026-10-13): eight
    re-stamps were done by hand, each from memory, and two sessions
    reconstructed the recipe differently — one would have copied the task
    sheet and lost the cloud edits. Refuses a dirty tree and a `--keep`
    path the stamp does not produce.

score
    Reads the latest run of the stamped area — the number under the named
    key, the protocol the run is bound to (and whether it is frozen), the
    cost tier — and the agent's log (`<dir>.log.md`, one line per step:
    `HH:MM:SS · <tag> · text`, tag in read/run/edit/unsure/gate). Prints
    wall-clock (first to last stamp; the agent's time outside the log is
    not seen), counts per tag and whether the kept number equals the truth.
    Writes `<dir>.score.json`. Exit 0 when the number is right and bound.
    `--transcript` adds what the agent's session transcript shows — the
    log is self-report, the transcript a measurement (agent_transcript).
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import random
import re
import subprocess
import sys
import time
import shutil
import tempfile
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path

from labkit import (
    agent_transcript,
    code_navigation,
    console,
    protocol_reading,
    repo,
    runs,
    scaffold,
    scope_sha,
)

#: What the scaffold stamps into a repo and an area; their sha pins the measured
#: condition. All of it ships with labkit — the probe needs no house machinery.
STAMPED = (
    Path(scaffold.__file__).resolve(),
    scaffold.PROTOCOL_TEMPLATE,
    *(
        scaffold.TEMPLATES / t
        for t in (
            "AGENTS.md.template",
            "prepare-script.py.template",
            "measure-script.py.template",
            "analyze-script.py.template",
            "test-area.py.template",
            "measure-quick-script.py.template",
            "test-quick.py.template",
        )
    ),
)
#: files per case — twelve cases; the truth is their mean, recounted at score time
DOCS_PER_CASE = (4, 4, 3, 4, 4, 3, 2, 3, 4, 3, 2, 6)
#: twelve sentences, six causal, six not — the judge task's items; the kept
#: number (accuracy) is the model's, so it has no truth to recount, only a range
CLAIMS = (
    ("c01", "Because the road was icy, the bus arrived twenty minutes late.", "causal"),
    ("c02", "The bus arrived twenty minutes late, and the road was icy.", "not_causal"),
    (
        "c03",
        "Sales rose after the price was cut, so the cut drove the demand.",
        "causal",
    ),
    ("c04", "Sales rose in March; the price was cut in the same month.", "not_causal"),
    ("c05", "The bridge collapsed due to corrosion in its main cables.", "causal"),
    ("c06", "The bridge was inspected in May and collapsed in June.", "not_causal"),
    ("c07", "Switching to the new compiler made the build twice as fast.", "causal"),
    (
        "c08",
        "The build is twice as fast on the new machine with the new compiler.",
        "not_causal",
    ),
    ("c09", "Her headache went away because she drank water.", "causal"),
    ("c10", "Her headache went away; she had also drunk some water.", "not_causal"),
    (
        "c11",
        "The vaccine prevented the outbreak from spreading beyond the village.",
        "causal",
    ),
    (
        "c12",
        "The outbreak stayed within the village, where most people were vaccinated.",
        "not_causal",
    ),
)
#: The tasks the harness stages: area name, metrics key, task template.
TASKS = {
    "count": {
        "area": "docs-per-case",
        "metric_key": "mean_docs_per_case",
        "template": "usability-task-count.md.template",
    },
    "judge": {
        "area": "causal-claims-judge",
        "metric_key": "c1_accuracy",
        "template": "usability-task-judge.md.template",
    },
}
#: (cost tier, model in the loop) per task: what the house route stamps for
#: it (`labkit-init exp --cost seconds`, plus `--model` with a model in the loop).
#: Staged without them, the count got the full form and the model skeleton
#: and every agent spent its time deleting it (probe 2026-10-07) — a cost
#: of the staging, not of the route.
TASK_STAMP: dict[str, tuple[str, bool]] = {
    "count": ("seconds", False),
    "judge": ("seconds", True),
}
LOG_TAGS = ("read", "run", "edit", "unsure", "gate")
LOG_LINE = re.compile(r"^(\d\d):(\d\d):(\d\d)\s*·\s*(\w+)\s*·\s*(.*)$")
#: a `read` of these is the agent learning the contract from the wrong place
#: — the area's README card should have sufficed (2026-10-05, four of four read on)
SOURCE_READ = re.compile(
    r"labkit/\w+\.py|labkit[ /](runlog|recheck|protocol_check|llm|batch|finalize|preflight)"
    r"|labkit/docs/standard|labkit\.rules",
    re.I,
)
#: The bar: one kept number in this many minutes. Set by hand (2026-10-05),
#: not derived — the first traces decide whether it is the right one.
TARGET_MINUTES = 5
TOL = 1e-9


def _sh(args: list[str], cwd: Path) -> str:
    """Run a command in `cwd`; a non-zero exit is a refusal with its output."""
    r = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(
            f"usability: `{' '.join(args)}` failed in {cwd}:\n{r.stdout}{r.stderr}"
        )
    return r.stdout


def _commit(root: Path, title: str, body: str | None = None) -> None:
    """The probe's own commit of what is staged. It skips the pre-commit
    hook: a freshly stamped protocol is all placeholders by design, and the
    hook is the agent's gate, not the stamper's (`labkit-init exp` sets
    core.hooksPath, 2026-10-05)."""
    _sh(
        [
            "git",
            "commit",
            "-q",
            "--no-verify",
            "-m",
            title,
            *(["-m", body] if body else []),
        ],
        root,
    )


def _read_probe(path: Path) -> Probe:
    """`<dir>.probe.json` as the record `stage` wrote."""
    return Probe(**json.loads(path.read_text(encoding="utf-8")))


def _answer_text(path: Path, who: str) -> str:
    """The answer file a scorer holds to the truth; missing means `who` has
    not answered yet — said so, not a traceback."""
    if not path.is_file():
        raise SystemExit(f"usability: {path} missing — has the {who} answered?")
    return path.read_text(encoding="utf-8")


def other_requirements(text: str) -> list[str]:
    """The requirement lines of a stamped `requirements.txt` besides labkit —
    `pytest` since 0.86.0. They go into the probe venv before the lock is
    frozen: the cloud probe's venv came from requirements.txt, the stamped
    lock knew only labkit, and runlog reported a drift on the first run
    (2026-10-12, draws 1 and 2)."""
    return [
        ln.strip()
        for ln in text.splitlines()
        if ln.strip()
        and not ln.lstrip().startswith("#")
        and not re.match(r"^\s*labkit\b", ln)
    ]


def _labkit_spec(python: Path) -> str:
    """The labkit line of `pip freeze` under `python` — the one this
    interpreter would import, named the way pip names it."""
    out = _sh([str(python), "-m", "pip", "freeze"], python.parent)
    lines = repo.requirement_lines(out, "labkit")
    if len(lines) != 1:
        raise SystemExit(
            f"usability: expected one labkit line in `pip freeze` of "
            f"{python}, got {lines!r}"
        )
    return lines[0].strip()


def scaffold_sha() -> str:
    """sha256 (12 hex) over the scaffold and the templates it stamps."""
    for p in STAMPED:
        if not p.is_file():
            raise SystemExit(f"usability: stamped master missing: {p}")
    return scope_sha.tree_digest((p.name, p.read_bytes()) for p in STAMPED)


@dataclass(frozen=True)
class Probe:
    """What was staged — pinned so two scores can be told apart."""

    staged: str
    task: str  # key into TASKS
    area: str  # the stamped area's directory name
    metric_key: str
    labkit_installed: str  # pip's name for the labkit in the probe venv
    scaffold_sha: str  # scaffolder + stamped templates
    scaffold_flags: list[str]
    target_minutes: int
    restamped: str | None = None  # the last `stage --restamp`, if any
    kept: list[str] = field(default_factory=list)  # hand edits a restamp leaves alone


def plant_fixture(root: Path) -> float:
    """Twelve cases with a known number of input files each under
    data/raw/inputs/<case>/ and data/raw/cases.jsonl; returns the mean.
    Side effects: writes those files."""
    inputs = root / "data" / "raw" / "inputs"
    rows = []
    for i, n in enumerate(DOCS_PER_CASE, 1):
        case = f"antrag-{i:02d}"
        d = inputs / case
        d.mkdir(parents=True, exist_ok=True)
        for k in range(1, n + 1):
            (d / f"document-{k}.txt").write_text(
                f"case {case}, document {k} of {n}\n", encoding="utf-8"
            )
        rows.append({"case_id": case, "inputs": "data/raw/inputs"})
    (root / "data" / "raw" / "cases.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8"
    )
    return recount(root)


def plant_claims(root: Path) -> None:
    """The judge task's items: data/raw/claims.jsonl. Side effects: writes it."""
    raw = root / "data" / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    (raw / "claims.jsonl").write_text(
        "".join(
            json.dumps({"id": i, "text": t, "gold": g}) + "\n" for i, t, g in CLAIMS
        ),
        encoding="utf-8",
    )


def recount(root: Path) -> float:
    """The truth, from the planted files — not from a number on disk."""
    rows = [
        json.loads(line)
        for line in (root / "data" / "raw" / "cases.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    counts = [
        sum(
            1
            for f in (root / r["inputs"] / r["case_id"]).iterdir()
            if not f.name.startswith(".")
        )
        for r in rows
    ]
    return sum(counts) / len(counts)


def stamp_flags(task: str, cost: str | None, model: bool) -> tuple[str | None, bool]:
    """(cost tier or None, model) the scaffolder gets: the task's route stamp
    (TASK_STAMP) unless `cost` names a tier; "unset" stamps none."""
    default_cost, default_model = TASK_STAMP[task]
    if cost is None:
        cost = default_cost
    return (None if cost == "unset" else cost), (model or default_model)


def tier_sentence(cost: str | None) -> str:
    """The task sheet's sentence on the stamped cost tier. Without it a cold
    Sonnet agent, staged at `minutes`, read "twelve calls take about a
    minute", set the head to `seconds` and took the short lane — the probe
    measured a lane it was not staged for (2026-10-14)."""
    if cost is None:
        return "Its protocol head names no cost tier: declaring it is part of the task."
    return (
        f'Its protocol head says `cost = "{cost}"`: the number is owed at that '
        f"tier — keep it, and follow the lane AGENTS.md gives for it."
    )


def agent_prompt(root: Path) -> str:
    """The prompt a cold agent gets: the repo's AGENTS.md first, the way a
    session started in the repo loads it into context, then the pointer to
    TASK.md. AGENTS.md is the entry file every agent reads; CLAUDE.md is
    only Claude Code's link to it, and naming it made the probe read as
    Claude-only to a Codex agent (2026-10-14). Handed only a pointer, every
    agent fetched the file with `cat` and read all of it before any section
    marker could steer it — a cost of the probe, not of a real session
    (re-measure 2026-10-07, rounds 1 to 4)."""
    entry = root / "AGENTS.md"
    if not entry.is_file():
        raise SystemExit(f"usability: {entry} missing — the scaffolder stamps it")
    return (
        f"Contents of {entry} (project instructions, loaded the way a "
        f"session in this repository loads them):\n\n"
        f"{entry.read_text(encoding='utf-8')}\n"
        f"---\n\n"
        f"Your working directory is {root} — a lab repository. Read TASK.md "
        f"there and do exactly what it says; it names the log file you keep. "
        f"Every shell command must first `cd` into that directory (your shell "
        f"does not start there). Work only inside it; do not touch sibling "
        f"directories. When done, give the report TASK.md asks for.\n"
    )


def _sidecar(root: Path, suffix: str) -> Path:
    return root.parent / f"{root.name}.{suffix}"


def stage(
    root: Path,
    venv: Path | None,
    cost: str | None = None,
    task: str = "count",
    model: bool = False,
) -> int:
    """Side effects: see module docstring. `task` picks the fixture, the task
    sheet and the default stamp (TASKS); `cost` overrides the stamped tier
    ("unset" leaves it to the agent), `model` adds the model skeleton."""
    spec = TASKS[task]
    cost, model = stamp_flags(task, cost, model)
    area_name, metric_key = spec["area"], spec["metric_key"]
    if root.exists() and any(root.iterdir()):
        raise SystemExit(
            f"usability: {root} exists and is not empty — stage into "
            f"a fresh directory, the probe must start cold"
        )
    if venv is not None and not (venv / "bin" / "python").is_file():
        raise SystemExit(f"usability: --venv {venv} has no bin/python")
    sha = scaffold_sha()
    root.mkdir(parents=True, exist_ok=True)
    scaffold.stamp_lab(root, root.name)
    _sh(["git", "init", "-q", "."], root)
    _sh(["git", "add", "-A"], root)
    _commit(root, "Scaffold: a probe lab repo for the usability trace")
    _, stamp_report = scaffold.stamp_area(
        root, area_name, cost=cost, model="haiku" if model else False
    )
    print(
        stamp_report, file=sys.stderr
    )  # the stamp's log is for the operator, not the probe
    areas = sorted(p.name for p in (root / "experiments").glob(f"*-{area_name}"))
    if len(areas) != 1:
        raise SystemExit(
            f"usability: expected one stamped area *-{area_name}, got {areas}"
        )
    if task == "count":
        plant_fixture(root)
    else:
        plant_claims(root)
    # the labkit of the staging interpreter, so a probe measures this checkout
    _probe_venv(root, venv, _labkit_spec(Path(sys.executable)))
    if venv is None:
        extra = other_requirements(
            (root / "requirements.txt").read_text(encoding="utf-8")
        )
        if extra:
            _sh([str(root / ".venv" / "bin" / "pip"), "install", "-q", *extra], root)
    # The hooks, as a real setup installs them (`labkit-hooks install`, labkit
    # 0.51): pre-commit with finalize, core.hooksPath, the claude-hook entries.
    _sh([str(root / ".venv" / "bin" / "labkit-hooks"), "install"], root)
    # requirements.lock from the probe venv: runlog warns "env unpinned" without
    # it and every cold agent stopped to generate one (2026-10-05).
    (root / "requirements.lock").write_text(
        _sh([str(root / ".venv" / "bin" / "pip"), "freeze"], root), encoding="utf-8"
    )
    _sh(["git", "add", "-A"], root)
    _commit(root, "Probe: requirements.lock and the hooks of the probe venv")
    probe = Probe(
        staged=time.strftime("%Y-%m-%dT%H:%M:%S"),
        task=task,
        area=areas[0],
        metric_key=metric_key,
        labkit_installed=_labkit_spec(root / ".venv" / "bin" / "python"),
        scaffold_sha=sha,
        scaffold_flags=[
            "lab",
            "exp",
            area_name,
            *(["--cost", cost] if cost else []),
            *(["--model", "haiku"] if model else []),
        ],
        target_minutes=TARGET_MINUTES,
    )
    log = _sidecar(root, "log.md")
    log.write_text("", encoding="utf-8")
    sheet = (Path(__file__).resolve().parent / spec["template"]).read_text(
        encoding="utf-8"
    )
    for key, val in (
        ("<metric_key>", metric_key),
        ("<area>", areas[0]),
        ("<log>", str(log)),
        ("<target>", str(TARGET_MINUTES)),
        ("<tier>", tier_sentence(cost)),
    ):
        sheet = sheet.replace(key, val)
    (root / "TASK.md").write_text(sheet, encoding="utf-8")
    _sh(["git", "add", "-A"], root)
    _commit(root, "Probe: the area, the fixture and TASK.md")
    _sidecar(root, "probe.json").write_text(
        json.dumps(asdict(probe), indent=1), encoding="utf-8"
    )
    prompt = _sidecar(root, "prompt.md")
    prompt.write_text(agent_prompt(root), encoding="utf-8")
    print(
        f"staged {root}\n  task:   {root / 'TASK.md'}\n  log:    {log}\n"
        f"  probe:  {_sidecar(root, 'probe.json')}\n  prompt: {prompt}\n"
        f"next: hand the prompt file's text to a cold agent (fresh context, no "
        f"history), then `usability score {root} --transcript <its transcript>`"
    )
    return 0


def log_step(log: Path, tag: str, text: str, cmd: list[str]) -> int:
    """`usability log`: see the module docstring. Returns CMD's exit code, 0
    without CMD. Refuses a tag outside LOG_TAGS and an empty text."""
    if tag not in LOG_TAGS:
        raise SystemExit(
            f"usability log: tag must be one of {', '.join(LOG_TAGS)}, got {tag!r}"
        )
    if not text.strip():
        raise SystemExit("usability log: the step text is empty")
    with log.open("a", encoding="utf-8") as fh:
        fh.write(f"{time.strftime('%H:%M:%S')} · {tag} · {text.strip()}\n")
    if not cmd:
        return 0
    return subprocess.run(cmd).returncode


@dataclass
class Restamp:
    """What `restamp_files` did, path by path (relative to the probe)."""

    overwritten: list[str]
    added: list[str]
    kept: list[str]  # named in keep and differing from the fresh stamp
    unchanged: list[str]


def restamp_files(
    fresh: Path, target: Path, files: list[str], keep: list[str]
) -> Restamp:
    """Lay the fresh stamp over the probe: FILES (relative paths, the fresh
    stamp's tracked files) are copied from FRESH to TARGET, except that a
    path in KEEP whose bytes differ stays as it is. Side effects: writes
    under TARGET. A KEEP path the stamp does not produce is refused — a typo
    would protect nothing and say so never."""
    unknown = sorted(set(keep) - set(files))
    if unknown:
        raise SystemExit(
            f"usability: --keep names paths the stamp does not produce: "
            f"{', '.join(unknown)}"
        )
    done = Restamp([], [], [], [])
    for rel in sorted(files):
        src, dst = fresh / rel, target / rel
        if src.is_symlink():  # CLAUDE.md -> AGENTS.md: the link, not its text
            if dst.is_symlink() and os.readlink(dst) == os.readlink(src):
                done.unchanged.append(rel)
                continue
            if rel in keep:
                done.kept.append(rel)
                continue
            if dst.exists() or dst.is_symlink():
                dst.unlink()
                done.overwritten.append(rel)
            else:
                done.added.append(rel)
            dst.parent.mkdir(parents=True, exist_ok=True)
            os.symlink(os.readlink(src), dst)
            continue
        new = src.read_bytes()
        if dst.is_file() and dst.read_bytes() == new:
            done.unchanged.append(rel)
            continue
        if rel in keep:
            done.kept.append(rel)
            continue
        existed = dst.is_file()
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(new)
        (done.overwritten if existed else done.added).append(rel)
    return done


def _probe_venv(root: Path, venv: Path | None, labkit_spec: str) -> None:
    """The probe's `.venv`: a link to VENV, or built with `labkit_spec`
    installed (`stage`: the staging interpreter's labkit; `--restamp`: the
    stamped pin). Side effects: removes the old one, creates the new one —
    after the check, so a bad --venv leaves the old one standing."""
    if venv is not None and not (venv / "bin" / "python").is_file():
        raise SystemExit(f"usability: --venv {venv} has no bin/python")
    old = root / ".venv"
    if old.is_symlink():
        old.unlink()
    elif old.is_dir():
        shutil.rmtree(old)
    if venv is not None:
        os.symlink(venv.resolve(), old)
        return
    _sh([sys.executable, "-m", "venv", ".venv"], root)
    _sh([str(old / "bin" / "pip"), "install", "-q", labkit_spec], root)


def restamp(root: Path, keep: list[str] | None, venv: Path | None) -> int:
    """`stage --restamp`: see the module docstring. KEEP None means the
    paths `<dir>.probe.json` recorded last time."""
    probe_file = _sidecar(root, "probe.json")
    if not probe_file.is_file():
        raise SystemExit(
            f"usability: {probe_file} missing — {root} was not staged by "
            f"`usability stage`, nothing to restamp"
        )
    if not (root / ".git").is_dir():
        raise SystemExit(f"usability: {root} is not a git repo")
    dirty = _sh(["git", "status", "--porcelain", "--untracked-files=no"], root)
    if dirty.strip():
        raise SystemExit(
            f"usability: {root} has uncommitted changes — commit or stash "
            f"first:\n{dirty.rstrip()}"
        )
    probe = _read_probe(probe_file)
    kept_paths = probe.kept if keep is None else keep
    flags = probe.scaffold_flags
    cost = flags[flags.index("--cost") + 1] if "--cost" in flags else "unset"
    model = "--model" in flags
    _probe_venv(root, venv, scaffold.labkit_pin())
    with tempfile.TemporaryDirectory() as tmp:
        fresh = Path(tmp) / root.name  # the stamp names the repo after its dir
        with contextlib.redirect_stdout(sys.stderr):  # the stamp's log
            stage(fresh, root / ".venv", cost=cost, task=probe.task, model=model)
        files = _sh(["git", "ls-files"], fresh).split("\n")
        done = restamp_files(fresh, root, [f for f in files if f], kept_paths)
        fresh_probe = _read_probe(_sidecar(fresh, "probe.json"))
    changed = done.overwritten + done.added
    extra = other_requirements((root / "requirements.txt").read_text(encoding="utf-8"))
    if extra and venv is None:
        _sh([str(root / ".venv" / "bin" / "pip"), "install", "-q", *extra], root)
        lock = _sh([str(root / ".venv" / "bin" / "pip"), "freeze"], root)
        if (root / "requirements.lock").read_text(encoding="utf-8") != lock:
            (root / "requirements.lock").write_text(lock, encoding="utf-8")
            if "requirements.lock" not in changed:
                changed.append("requirements.lock")
    probe = replace(
        probe,
        labkit_installed=fresh_probe.labkit_installed,
        scaffold_sha=fresh_probe.scaffold_sha,
        scaffold_flags=fresh_probe.scaffold_flags,
        restamped=time.strftime("%Y-%m-%dT%H:%M:%S"),
        kept=list(kept_paths),
    )
    probe_file.write_text(json.dumps(asdict(probe), indent=1), encoding="utf-8")
    # pip freeze names the commit the tag resolved to; the stamped pin names the tag
    pin = next(
        ln
        for ln in (root / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if ln.startswith("labkit")
    )
    m = re.search(r"@(v\d+\.\d+\.\d+)$", pin)
    label = m.group(1) if m else pin
    report = "\n".join(
        f"  {what:12s}{path}"
        for what, paths in (
            ("overwritten", done.overwritten),
            ("added", done.added),
            ("kept", done.kept),
        )
        for path in paths
    )
    if not changed:
        print(
            f"restamp {root}: nothing to change at labkit {label}"
            + (f"\n{report}" if report else "")
        )
        return 0
    _sh(["git", "add", "--", *sorted(changed)], root)
    _commit(
        root,
        f"Probe re-stamped at labkit {label}",
        f"usability stage --restamp; what changed between the stamps is "
        f"labkit's CHANGELOG.md.\n\n{report}",
    )
    print(
        f"restamp {root}: committed at labkit {label}\n{report}\n"
        f"  probe:      {probe_file}\n"
        f"next: amend the why onto the commit if the changelog is not enough, "
        f"then push — the push stays with you"
    )
    return 0


#: a silence between two stamps this long is not work — an outage, a
#: forgotten agent — and is reported beside the span, not hidden in it
GAP_SECONDS = 600


@dataclass(frozen=True)
class LogTrace:
    """What the agent's log says: stamps and counts per tag."""

    lines: int
    wall_seconds: int | None  # max − min over the stamps; None below two
    gap_seconds: int  # sum of silences ≥ GAP_SECONDS between stamps
    monotonic: bool  # stamps never run backwards
    read: int
    run: int
    edit: int
    unsure: int
    gate: int
    untagged: int  # off-contract lines, counted, never dropped
    source_reads: int  # `read` lines naming labkit's source or the lab standard


def parse_log(text: str) -> LogTrace:
    """Read an agent's step log (`HH:MM:SS · tag · text` per line) into counts and wall-clock."""
    counts = {t: 0 for t in LOG_TAGS}
    untagged = 0
    source_reads = 0
    stamps: list[int] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        m = LOG_LINE.match(line)
        if not m or m.group(4).lower() not in counts:
            untagged += 1
            continue
        counts[m.group(4).lower()] += 1
        if m.group(4).lower() == "read" and SOURCE_READ.search(m.group(5)):
            source_reads += 1
        stamps.append(int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3)))
    wall = (max(stamps) - min(stamps)) if len(stamps) >= 2 else None
    gaps = sum(b - a for a, b in zip(stamps, stamps[1:]) if b - a >= GAP_SECONDS)
    return LogTrace(
        lines=len(stamps) + untagged,
        wall_seconds=wall,
        gap_seconds=gaps,
        monotonic=all(a <= b for a, b in zip(stamps, stamps[1:])),
        untagged=untagged,
        source_reads=source_reads,
        **counts,
    )


def latest_run(area: Path) -> Path | None:
    """The newest completed run — run_ids start with the timestamp, so
    their sort order is their start order (runlog.Run)."""
    try:
        done = runs.completed_runs(area)
    except runs.RunConfigError as exc:
        raise SystemExit(f"usability: {exc}") from exc
    return done[-1] if done else None


@dataclass(frozen=True)
class Score:
    """What a probe's score found: the number, its binding, the log and the transcript."""

    probe: Probe
    run_id: str | None
    number: float | None  # metrics[metric_key], or None when absent
    expected: float | None  # the recounted truth (count), None for a model's number
    number_ok: bool  # equals the truth, or (judge) present and within [0, 1]
    null_reported: (
        bool | None
    )  # judge: an a<i>_* key (admissibility, the null lane) in metrics.json
    bound_to: str | None  # config["protocol"]["path"]
    frozen: bool | None
    cost_tier: str | None
    log: LogTrace | None
    form: protocol_reading.Form | None = None  # how the bound protocol reads
    transcript: agent_transcript.TranscriptTrace | None = (
        None  # measured, not self-reported
    )
    agent: str | None = (
        None  # the model that drew, as the operator names it (`--agent`)
    )


def archive(root: Path, transcript: Path, dest: Path) -> list[Path]:
    """Keep a probe for later debugging: the transcript (gzip, mtime 0 so
    the bytes depend on the content only), its timeline and the score, as
    `<dest>/<probe>.jsonl.gz`, `.timeline.txt`, `.score.json`. Claude Code
    deletes transcripts after `cleanupPeriodDays` (30 by default), and a
    transcript is what showed an agent's source reads and detours on
    2026-10-07. A file already there with other bytes is refused, never
    overwritten."""
    import gzip

    dest.mkdir(parents=True, exist_ok=True)
    payload = {
        dest / f"{root.name}.jsonl.gz": gzip.compress(transcript.read_bytes(), mtime=0),
        dest / f"{root.name}.timeline.txt": (
            "\n".join(agent_transcript.timeline(transcript)) + "\n"
        ).encode("utf-8"),
        dest / f"{root.name}.score.json": _sidecar(root, "score.json").read_bytes(),
    }
    clash = [p for p, b in payload.items() if p.exists() and p.read_bytes() != b]
    if clash:
        raise SystemExit(
            f"usability: archive refuses to overwrite {', '.join(map(str, clash))} — "
            f"another probe of the same name? archive into another directory"
        )
    for path, body in payload.items():
        path.write_bytes(body)
    return list(payload)


@dataclass(frozen=True)
class ProbeRun:
    """A staged probe and its latest completed run, read once — one home for
    what `score` and the reading probes both need."""

    probe: Probe
    area: Path
    run: Path | None  # None: no completed run yet
    config: dict[str, object]
    metrics: dict[str, object]
    protocol: Path | None  # the protocol the run names, resolved; None: none named
    protocol_as_recorded: str | None  # the path as config.json holds it
    bound: bool  # the run recorded the protocol's id — a path alone goes stale
    cost_tier: str | None


def load_probe_run(root: Path) -> ProbeRun:
    """Read `<dir>.probe.json` and the probe area's latest completed run.
    Raises SystemExit when the probe was not staged here."""
    probe_file = _sidecar(root, "probe.json")
    if not probe_file.is_file():
        raise SystemExit(f"usability: {probe_file} missing — was {root} staged here?")
    probe = _read_probe(probe_file)
    area = root / "experiments" / probe.area
    run = latest_run(area)
    if run is None:
        return ProbeRun(probe, area, None, {}, {}, None, None, False, None)
    config = runs.read_run_config(run)
    if config is None:
        raise SystemExit(f"usability: {run} has no config.json — not a run")
    metrics = runs.read_metrics(run / "metrics.json")
    binding = config.get("protocol") or {}
    named = binding.get("path")
    protocol = None
    if named:
        protocol = Path(named) if Path(named).is_absolute() else area / named
    tier = config.get("cost_tier")
    return ProbeRun(
        probe,
        area,
        run,
        config,
        metrics,
        protocol,
        str(named) if named else None,
        bool(binding.get("id")),
        str(tier) if tier is not None else None,
    )


def _bound_protocol(root: Path) -> tuple[Path, protocol_reading.Truth]:
    """The protocol the probe's latest run names, and what the run says."""
    pr = load_probe_run(root)
    if pr.run is None:
        raise SystemExit(f"usability: {pr.area} has no completed run — nothing to read")
    if pr.protocol is None:
        raise SystemExit(f"usability: run {pr.run.name} is bound to no protocol")
    try:
        truth = protocol_reading.truth_from_metrics(pr.metrics, pr.probe.metric_key)
    except ValueError as exc:
        raise SystemExit(f"usability: run {pr.run.name}: {exc}") from exc
    return pr.protocol, truth


def cmd_reader(root: Path) -> int:
    """Write `<dir>.reader-prompt.md`: the bound protocol for a cold reader."""
    protocol, _ = _bound_protocol(root)
    answer = _sidecar(root, "reader-answer.json")
    prompt = _sidecar(root, "reader-prompt.md")
    prompt.write_text(
        protocol_reading.reader_prompt(
            protocol.read_text(encoding="utf-8"), str(answer)
        ),
        encoding="utf-8",
    )
    print(f"reader prompt → {prompt}\nthe reader writes → {answer}")
    return 0


def cmd_glance(root: Path) -> int:
    """Write `<dir>.glance-prompt.md`: only the first lines of the bound protocol."""
    protocol, _ = _bound_protocol(root)
    g = protocol_reading.glance(protocol.read_text(encoding="utf-8"))
    answer = _sidecar(root, "glance-answer.json")
    prompt = _sidecar(root, "glance-prompt.md")
    prompt.write_text(
        protocol_reading.glance_prompt(g.excerpt, str(answer)), encoding="utf-8"
    )
    print(
        f"glance prompt → {prompt} ({g.lines} lines, {g.chars} chars; Summary "
        f"fields inside: {', '.join(g.summary_fields) or 'none'})\n"
        f"the reader writes → {answer}"
    )
    return 0


def cmd_glance_score(root: Path) -> int:
    """Hold the glance answer to the run; `<dir>.glance.json`."""
    protocol, truth = _bound_protocol(root)
    text = protocol.read_text(encoding="utf-8")
    g = protocol_reading.glance(text)
    answer = _answer_text(_sidecar(root, "glance-answer.json"), "reader")
    try:
        got = protocol_reading.score_glance_answer(answer, truth)
    except ValueError as exc:
        raise SystemExit(f"usability: {exc}") from exc
    hits = protocol_reading.terms_coverage(text, got.unclear, str(protocol))
    out = {
        **asdict(got),
        "lines": g.lines,
        "chars": g.chars,
        "summary_fields": list(g.summary_fields),
        "terms": [asdict(h) for h in hits],
        "truth": asdict(truth),
    }
    _sidecar(root, "glance.json").write_text(
        json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8"
    )
    print(
        f"  first {g.lines} lines, {g.chars} chars · Summary fields inside: "
        f"{', '.join(g.summary_fields) or 'none'} · number {got.number_ok}, "
        f"criterion {got.criterion_ok} · answered {len(got.answered)}/"
        f"{len(protocol_reading.GLANCE_CONTENT_KEYS)} · "
        f"unclear {len(got.unclear)}, of them in the Summary "
        f"{sum(h.in_summary for h in hits)}"
    )
    return 0 if got.number_ok is not False and got.criterion_ok is not False else 1


def cmd_terms(root: Path) -> int:
    """The full reader's unclear terms against the Summary and Terms."""
    protocol, _ = _bound_protocol(root)
    answer = _answer_text(_sidecar(root, "reader-answer.json"), "reader")
    unclear = json.loads(answer).get("unclear") or []
    hits = protocol_reading.terms_coverage(
        protocol.read_text(encoding="utf-8"), unclear, str(protocol)
    )
    for h in hits:
        where = "Summary" if h.in_summary else "Terms" if h.in_terms else "nowhere"
        print(f"  {where:8} {h.term}")
    print(
        f"  {len(hits)} unclear · in the Summary {sum(h.in_summary for h in hits)} "
        f"· in Terms (occurs, static evidence) {sum(h.in_terms for h in hits)}"
    )
    return 0


def cmd_nav(repo: Path, questions: Path, out: Path, shuffle: int | None = None) -> int:
    """Write `<out>.nav-prompt.md` for a cold agent in `repo`; with `shuffle`
    the questions come in an order drawn from that seed, so agents compared
    across two versions do not all meet them in one order."""
    qs = code_navigation.load_questions(questions)
    for q in qs:
        for t in q.truth:
            code_navigation.symbol_span(repo, t)  # a stale truth refuses now
    answer = out.with_name(out.name + ".nav-answer.json")
    prompt = out.with_name(out.name + ".nav-prompt.md")
    flows_list = code_navigation.load_flows(questions)
    choices_list = code_navigation.load_choices(questions)
    if shuffle is not None:
        rng = random.Random(shuffle)
        rng.shuffle(qs)
        rng.shuffle(flows_list)
        rng.shuffle(choices_list)
    flows, choices = tuple(flows_list), tuple(choices_list)
    if not (qs or flows or choices):
        raise SystemExit(f"usability: {questions} holds no question")
    prompt.write_text(
        code_navigation.nav_prompt(repo, qs, str(answer), flows, choices),
        encoding="utf-8",
    )
    print(f"navigation prompt → {prompt}\nthe agent writes → {answer}")
    return 0


def cmd_nav_score(
    repo: Path, questions: Path, out: Path, transcript: Path | None
) -> int:
    """Hold the answers to the truth; `<out>.nav.json`."""
    qs = code_navigation.load_questions(questions)
    answer = _answer_text(out.with_name(out.name + ".nav-answer.json"), "agent")
    try:
        got = code_navigation.score_nav_answer(answer, qs, repo)
    except (ValueError, code_navigation.NavigationError) as exc:
        raise SystemExit(f"usability: {exc}") from exc
    eff = code_navigation.effort(transcript, repo) if transcript else None
    try:
        flows = code_navigation.score_flows(
            answer, code_navigation.load_flows(questions)
        )
        choices = code_navigation.score_choices(
            answer, code_navigation.load_choices(questions)
        )
    except ValueError as exc:
        raise SystemExit(f"usability: {exc}") from exc
    out.with_name(out.name + ".nav.json").write_text(
        json.dumps(
            {
                "found": [asdict(f) for f in got],
                "flows": flows,
                "choices": {k: asdict(v) for k, v in choices.items()},
                "effort": asdict(eff) if eff else None,
            },
            indent=1,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    for f in got:
        mark = "found" if f.found else "file only" if f.file_right else "missed"
        print(f"  {mark:9} {f.id}: {f.answer} (truth {f.truth})")
    for fid, (n, of) in flows.items():
        print(f"  flow {fid}: {n}/{of} steps named in order")
    for cid, cs in choices.items():
        extra = (f" missed {list(cs.missed)}" if cs.missed else "") + (
            f" invented {list(cs.invented)}" if cs.invented else ""
        )
        print(f"  {'right' if cs.right else 'WRONG':9} {cid}{extra}")
    if choices:
        print(
            f"  {sum(cs.right for cs in choices.values())}/{len(choices)} behaviour "
            f"questions right · {sum(len(cs.missed) for cs in choices.values())} "
            f"missed · {sum(len(cs.invented) for cs in choices.values())} invented"
        )
    print(
        f"  {sum(f.found for f in got)}/{len(got)} found"
        + (
            f" · {eff.seconds}s · {eff.calls} calls {eff.by_tool} · "
            f"{len(eff.files_opened)} files opened"
            if eff
            else ""
        )
    )
    return 0


def cmd_human(
    repo: Path, questions: Path, ids: list[str], out: Path, count_help: bool
) -> int:
    """A person answers behaviour questions about `repo` at the keyboard;
    time per question, the answers and the score go to `<out>.human.json`.
    The verdict is shown only at the end, so it cannot steer later answers."""
    by_id = {c.id: c for c in code_navigation.load_choices(questions)}
    unknown = [i for i in ids if i not in by_id]
    if unknown:
        raise SystemExit(f"usability: no choice question {unknown} in {questions}")
    chosen = [by_id[i] for i in ids]
    print(
        f"Open {repo} in your editor. Answer from the code; nothing is scored until the end."
    )
    answers = code_navigation.human_session(chosen, input, time.monotonic, count_help)
    scored = code_navigation.score_choices(
        json.dumps({a.id: list(a.picked) for a in answers}), chosen
    )
    record = [{**asdict(a), **asdict(scored[a.id])} for a in answers]
    out.with_name(out.name + ".human.json").write_text(
        json.dumps(
            {"repo": str(repo), "answers": record}, indent=1, ensure_ascii=False
        ),
        encoding="utf-8",
    )
    print()
    for r in record:
        print(f"  {'right' if r['right'] else 'WRONG':6} {r['id']} · {r['seconds']} s")
    print(
        f"  {sum(r['right'] for r in record)}/{len(record)} right · "
        f"{round(sum(r['seconds'] for r in record))} s"
        + (
            f" · {sum(r['help_questions'] for r in record)} questions asked"
            if count_help
            else ""
        )
    )
    return 0


def cmd_read_score(root: Path, transcript: Path | None) -> int:
    """Hold the reader's answer to the run's number; `<dir>.reader.json`."""
    _, truth = _bound_protocol(root)
    answer = _answer_text(_sidecar(root, "reader-answer.json"), "reader")
    try:
        got = protocol_reading.score_reader_answer(answer, truth)
    except ValueError as exc:
        raise SystemExit(f"usability: {exc}") from exc
    seconds = None
    if transcript is not None:
        _, first, last = agent_transcript.read_calls(transcript)
        seconds = round(last - first)
    out = {**asdict(got), "truth": asdict(truth), "reader_seconds": seconds}
    _sidecar(root, "reader.json").write_text(
        json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8"
    )
    print(
        f"  {got.correct}/{got.checkable} checkable answers right (number "
        f"{got.number_ok}, criterion {got.criterion_ok}, admissibility "
        f"{got.admissible_ok}) · "
        f"effort {got.effort} · unclear {len(got.unclear)}"
        + (f" · {seconds}s" if seconds is not None else "")
    )
    for u in got.unclear:
        print(f"    unclear: {u}")
    return 0 if got.correct == got.checkable else 1


def score(  # noqa: C901 complexity baseline 2026-10-08
    root: Path, transcript: Path | None = None, agent: str | None = None
) -> int:
    """Score a staged probe: its latest run's number against the truth, the binding, the log; write `<dir>.score.json`.

    `agent` names the model that drew (`fable-5.1`, `sonnet-5.5`): a cloud
    session leaves no transcript, so the operator states it and the score
    carries it — twelve score files named the model only in their file name
    (2026-10-13)."""
    pr = load_probe_run(root)
    probe, run, metrics = pr.probe, pr.run, pr.metrics
    expected = recount(root) if probe.task == "count" else None
    number = bound_to = frozen = tier = None
    form: protocol_reading.Form | None = None
    null_reported = None
    if run is not None:
        number = protocol_reading.metric_number(metrics, probe.metric_key)
        bound_to = pr.protocol_as_recorded if pr.bound else None
        tier = pr.cost_tier
        if probe.task != "count":
            null_reported = any(re.match(r"^a\d+_", k) for k in metrics)
        if pr.bound and pr.protocol is not None:
            from labkit import protocol_block  # lazy: labkit modules import each other

            p = pr.protocol
            if p.is_file():
                form = protocol_reading.form(p.read_text(encoding="utf-8"))
            try:
                frozen = (
                    protocol_block.head(p.read_text(encoding="utf-8")).frozen
                    if p.is_file()
                    else None
                )
            except protocol_block.BlockError as exc:
                print(f"  protocol head unreadable — {exc}")
                frozen = None
    log = _sidecar(root, "log.md")
    trace = parse_log(log.read_text(encoding="utf-8")) if log.is_file() else None
    try:
        measured = (
            agent_transcript.trace(transcript, root, SOURCE_READ)
            if transcript is not None
            else None
        )
    except (agent_transcript.TranscriptError, OSError) as exc:
        raise SystemExit(f"usability: transcript: {exc}") from exc
    sc = Score(
        probe=probe,
        run_id=run.name if run else None,
        number=number,
        expected=expected,
        number_ok=(number is not None and abs(number - expected) <= TOL)
        if expected is not None
        else (number is not None and 0.0 <= number <= 1.0),
        null_reported=null_reported,
        bound_to=bound_to,
        frozen=frozen,
        cost_tier=tier,
        log=trace,
        form=form,
        transcript=measured,
        agent=agent,
    )
    _sidecar(root, "score.json").write_text(
        json.dumps(asdict(sc), indent=1), encoding="utf-8"
    )

    rows = [
        ("agent", agent or "not stated (--agent)"),
        ("labkit in probe", probe.labkit_installed),
        ("scaffold sha", probe.scaffold_sha),
        ("run", sc.run_id or "none"),
        (f"number ({probe.metric_key})", "absent" if number is None else str(number)),
        (
            "equals the truth" if expected is not None else "within [0, 1]",
            "yes"
            if sc.number_ok
            else (f"NO (truth {expected})" if expected is not None else "NO"),
        ),
        *(
            [("null condition reported", "yes" if null_reported else "NO")]
            if probe.task != "count"
            else []
        ),
        ("bound to", bound_to or "NOTHING"),
        ("frozen", {True: "yes", False: "no", None: "n/a"}[frozen]),
        ("cost tier", tier or "undeclared"),
    ]
    if trace is None:
        rows.append(("log", "missing — no trace, no measurement"))
    else:
        w = trace.wall_seconds
        rows.append(
            (
                "wall-clock (log span)",
                f"{w // 60}m{w % 60:02d}s" if w is not None else "n/a",
            )
        )
        if trace.gap_seconds:
            g = trace.gap_seconds
            net = (w - g) if w is not None else None
            rows.append(
                (
                    f"silences ≥ {GAP_SECONDS // 60} min",
                    f"{g // 60}m{g % 60:02d}s"
                    + (
                        f" → net {net // 60}m{net % 60:02d}s" if net is not None else ""
                    ),
                )
            )
        if not trace.monotonic:
            rows.append(("log order", "stamps run backwards — span is unreliable"))
        rows += [
            (f"steps · {t}", str(getattr(trace, t))) for t in (*LOG_TAGS, "untagged")
        ]
        rows.append(
            (
                "reads of labkit source / standard",
                str(trace.source_reads)
                + ("" if trace.source_reads == 0 else " — the card did not suffice"),
            )
        )
    if form is not None:
        rows += [
            ("protocol · lines", str(form.lines)),
            (
                "protocol · prose before the first field",
                str(form.prose_before_first_field),
            ),
            ("protocol · · chains (> 2 items)", str(form.chains)),
            ("protocol · longest field (chars)", str(form.longest_field)),
            ("protocol · codes in the Summary", str(form.summary_codes)),
            ("protocol · answer as a table", "yes" if form.answer_has_table else "no"),
        ]
    if measured is not None:
        w, tool = measured.wall_seconds, measured.tool_seconds
        rows += [
            ("transcript · wall-clock", f"{w // 60}m{w % 60:02d}s"),
            ("transcript · in tools / thinking", f"{tool}s / {w - tool}s"),
            ("transcript · tool calls", str(measured.calls)),
            (
                "transcript · labkit commands",
                ", ".join(f"{k} ×{v}" for k, v in sorted(measured.commands.items()))
                or "none",
            ),
            ("transcript · gate refusals", str(measured.refusals)),
            ("transcript · tokens", agent_transcript.describe_tokens(measured.tokens)),
            ("transcript · files opened", str(len(measured.files_read))),
            (
                "transcript · source / standard reads",
                str(len(measured.source_reads))
                + (
                    " — " + "; ".join(measured.source_reads[:3])
                    if measured.source_reads
                    else ""
                ),
            ),
        ]
    width = max(len(k) for k, _ in rows)
    for k, v in rows:
        print(f"  {k:<{width}}  {v}")
    over = (
        trace is not None
        and trace.wall_seconds is not None
        and trace.wall_seconds - trace.gap_seconds > probe.target_minutes * 60
    )
    print(
        f"  target: one kept number under {probe.target_minutes} min"
        + (" — MISSED" if over else "")
    )
    print(f"→ {_sidecar(root, 'score.json')}")
    return 0 if sc.number_ok and bound_to else 1


def main(argv: list[str]) -> int:  # noqa: C901 complexity baseline 2026-10-08
    """Command line of `usability`: stage probes and score what cold agents and readers did."""
    ap = argparse.ArgumentParser(
        prog="usability", description=(__doc__ or "").split("\n\n")[0]
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("stage", help="stamp a probe lab repo with one kept-number task")
    s.add_argument("dir")
    s.add_argument("--venv", help="link this venv instead of creating one")
    s.add_argument(
        "--restamp",
        action="store_true",
        help="stamp the probe in DIR again with this labkit, in place; task "
        "and tier come from <dir>.probe.json",
    )
    s.add_argument(
        "--keep",
        action="append",
        metavar="PATH",
        help="with --restamp: a hand-edited path the stamp leaves alone "
        "(repeatable; default: the paths kept last time)",
    )
    s.add_argument(
        "--cost",
        choices=("seconds", "minutes", "hours", "unset"),
        metavar="TIER",
        help="the cost tier stamped into the protocol (default: the task's, "
        "seconds); unset = the agent declares it, the full form is stamped",
    )
    s.add_argument(
        "--model",
        action="store_true",
        help="a model in the loop: the full measure skeleton (prompt, parser, "
        "probe) and, at seconds, the three model fields in the cut "
        "(default for --task judge)",
    )
    s.add_argument(
        "--task",
        choices=sorted(TASKS),
        help="which task sheet and fixture: count (deterministic, the default) "
        "or judge (a model)",
    )
    lg = sub.add_parser("log", help="append one step line with the time, then run CMD")
    lg.add_argument("tag", choices=LOG_TAGS)
    lg.add_argument("text", help="the step, in a few words")
    lg.add_argument("--log", default="log.md", help="the log file (default: ./log.md)")
    lg.add_argument(
        "cmd_words",
        nargs=argparse.REMAINDER,
        metavar="CMD",
        help="after `--`: the command the line announces",
    )
    c = sub.add_parser("score", help="number, binding and log of a finished probe")
    c.add_argument("dir")
    c.add_argument(
        "--transcript",
        help="the agent's session transcript (JSONL): wall-clock, tool calls, "
        "files and refusals measured instead of self-reported",
    )
    c.add_argument(
        "--agent",
        help="the model that drew, e.g. fable-5.1 — stated by the operator, kept in the score",
    )
    c.add_argument(
        "--archive",
        metavar="DIR",
        help="with --transcript: keep transcript (gzip), timeline and score in DIR",
    )
    tr = sub.add_parser("trace", help="the timeline of one agent transcript")
    tr.add_argument("transcript")
    rd = sub.add_parser(
        "reader", help="write the cold-reader prompt for the probe's protocol"
    )
    rd.add_argument("dir")
    rs = sub.add_parser(
        "read-score", help="hold the reader's answer to the run's number"
    )
    rs.add_argument("dir")
    rs.add_argument("--transcript", help="the reader's transcript: its reading time")
    gl = sub.add_parser(
        "glance", help="write the prompt for a reader who sees only the first lines"
    )
    gl.add_argument("dir")
    gs = sub.add_parser("glance-score", help="hold the glance answer to the run")
    gs.add_argument("dir")
    te = sub.add_parser(
        "terms", help="the reader's unclear terms against the Summary and Terms"
    )
    te.add_argument("dir")
    nv = sub.add_parser(
        "nav", help="write the prompt for a cold agent finding its way in a repo"
    )
    nv.add_argument("repo")
    nv.add_argument("--questions", required=True, help="TOML: questions and truth")
    nv.add_argument(
        "--out", required=True, help="prefix of the prompt and answer files"
    )
    nv.add_argument("--shuffle", type=int, help="seed: draw the question order from it")
    ns = sub.add_parser("nav-score", help="hold the navigation answers to the truth")
    ns.add_argument("repo")
    ns.add_argument("--questions", required=True)
    ns.add_argument("--out", required=True)
    ns.add_argument("--transcript", help="the agent's transcript: its effort")
    hu = sub.add_parser(
        "human", help="a person answers behaviour questions at the keyboard, timed"
    )
    hu.add_argument("repo")
    hu.add_argument("--questions", required=True, help="TOML with [[choice]] questions")
    hu.add_argument(
        "--ids", required=True, help="the question ids to ask, comma-separated"
    )
    hu.add_argument("--out", required=True, help="prefix of the record file")
    hu.add_argument(
        "--count-help",
        action="store_true",
        help="ask after each answer how many questions went to an assistant",
    )
    args = ap.parse_args(argv)
    if args.cmd == "human":
        return cmd_human(
            Path(args.repo).resolve(),
            Path(args.questions).resolve(),
            args.ids.split(","),
            Path(args.out).resolve(),
            args.count_help,
        )
    if args.cmd == "nav":
        return cmd_nav(
            Path(args.repo).resolve(),
            Path(args.questions).resolve(),
            Path(args.out).resolve(),
            args.shuffle,
        )
    if args.cmd == "nav-score":
        return cmd_nav_score(
            Path(args.repo).resolve(),
            Path(args.questions).resolve(),
            Path(args.out).resolve(),
            Path(args.transcript).resolve() if args.transcript else None,
        )
    if args.cmd == "log":
        cmd = args.cmd_words[1:] if args.cmd_words[:1] == ["--"] else args.cmd_words
        return log_step(Path(args.log), args.tag, args.text, cmd)
    if args.cmd == "glance":
        return cmd_glance(Path(args.dir).resolve())
    if args.cmd == "glance-score":
        return cmd_glance_score(Path(args.dir).resolve())
    if args.cmd == "terms":
        return cmd_terms(Path(args.dir).resolve())
    if args.cmd == "reader":
        return cmd_reader(Path(args.dir).resolve())
    if args.cmd == "read-score":
        return cmd_read_score(
            Path(args.dir).resolve(),
            Path(args.transcript).resolve() if args.transcript else None,
        )
    if args.cmd == "trace":
        try:
            lines = agent_transcript.timeline(Path(args.transcript))
        except (agent_transcript.TranscriptError, OSError) as exc:
            raise SystemExit(f"usability: transcript: {exc}") from exc
        print("\n".join(lines))
        return 0
    root = Path(args.dir).resolve()
    if args.cmd == "stage":
        venv = Path(args.venv).resolve() if args.venv else None
        if args.restamp:
            if args.cost or args.task or args.model:
                ap.error("--restamp takes task, tier and model from <dir>.probe.json")
            return restamp(root, args.keep, venv)
        if args.keep:
            ap.error("--keep belongs to --restamp")
        return stage(
            root, venv, cost=args.cost, task=args.task or "count", model=args.model
        )
    if args.archive and not args.transcript:
        ap.error("--archive needs --transcript")
    transcript = Path(args.transcript).resolve() if args.transcript else None
    rc = score(root, transcript, args.agent)
    if args.archive and transcript is not None:
        for path in archive(root, transcript, Path(args.archive)):
            print(f"  archived {path}")
    return rc


def cli() -> None:
    """Console entry point of `usability`."""
    console.exit_with(main)


if __name__ == "__main__":
    cli()
