"""labkit-init — stamp a lab repo and its experiment areas from the templates that ship with labkit.

    labkit-init lab [DIR] [--name NAME] [--labkit-ref REF]
    labkit-init exp NAME [--repo DIR] [--cost seconds|minutes|hours] [--model [ALIAS]]
                         [--report] [--explore]

`lab` lays out a lab repo: `AGENTS.md` (and `CLAUDE.md` pointing at it),
`requirements.txt` pinning this labkit at its release tag on GitHub,
`models.toml`, the editor and type-checker settings, `experiments/`,
`data/raw` → `data/prepared`, `lib/`, `notes/{theorie,messung,results}` with the
lab's empty glossary `notes/theorie/terms.md` (the one home of a lab term,
LAB-084 Double-coinage check), and a test that the shared helpers resolve to
the package. The lab standard is not
copied: it comes with the pin (`python -m labkit.rules show LAB-nnn`).

`exp` stamps one self-contained area `experiments/NN-<name>/`: the protocol
(the pilot part by default; `--report` adds the † fields, now or when the run
graduates; `--cost seconds` stamps the seconds cut instead), the script
skeletons (`00_prepare`, `01_measure`, `02_analyze`, or the counting skeleton
at seconds without a model), the area README and the area's test under
`tests/`. `--explore` stamps only `experiments/explore/<name>.py`, the entry
before an area exists; the plain command later moves it into the area.

Every file is written only if absent: rerunning never overwrites. The pin
names the release tag `v<version>` of the installed labkit; until that tag is
pushed the pin does not install, so `--labkit-ref` names another ref (a pushed
commit) for development and tests.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import os
import re

from labkit import console
import uuid
from pathlib import Path

from labkit import protocol_block
from labkit.repo import area_protocols, git_run
from labkit.repo_check import PYPROJECT_VERSION_RE

PACKAGE = Path(__file__).resolve().parent
TEMPLATES = PACKAGE / "templates"
PROTOCOL_TEMPLATE = PACKAGE / "experiment-protocol.md.template"
#: where every lab installs labkit from — a lab has no checkout of the package
LABKIT_REMOTE = "https://github.com/kmax-tech/labkit.git"

GITIGNORE = """\
# stamped by labkit-init — what a lab repo never commits
.venv
__pycache__/
*.pyc
.pytest_cache/
.DS_Store
.runs.tsv.lock
"""

REQUIREMENTS = """\
# Shared lab helpers come as a PINNED package — never as file copies, never
# editable (a run records its environment; helpers that can change under a
# finished run make that record a lie). Install:
#   python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
#   .venv/bin/labkit-hooks install    (the hooks of this labkit)
# Raise the pin on purpose, never silently.
{pin}

# The stamped areas carry a test (tests/test_<NN>_<name>.py); preflight and
# finalize run it, and without pytest they only warn (cloud probe 2026-10-12).
pytest
"""

#: (template, destination) of the files `lab` copies verbatim
LAB_FILES = (
    ("models.toml.template", "models.toml"),
    ("pyrightconfig.json.template", "pyrightconfig.json"),
    ("vscode-settings.json.template", ".vscode/settings.json"),
    ("vscode-launch.json.template", ".vscode/launch.json"),
    (
        "test-shared-helpers.py.template",
        "tests/test_shared_helpers_come_from_labkit.py",
    ),
    (
        "terms.md.template",
        "notes/theorie/terms.md",
    ),  # the lab's glossary (LAB-084 Double-coinage check)
)
LAB_DIRS = (
    "experiments",
    "data/raw",
    "data/prepared",
    "lib",
    "notes/theorie",
    "notes/messung",
    "notes/results",
)


def write_if_absent(path: Path, content: str, log: list[str]) -> bool:
    """Write CONTENT to PATH unless it exists; log either way. True when written."""
    if path.exists() or path.is_symlink():
        log.append(f"  skip (exists)  {path}")
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    log.append(f"  created        {path}")
    return True


def template(name: str) -> str:
    """The text of a shipped template; a missing one is a broken install, said so."""
    path = PROTOCOL_TEMPLATE if name == PROTOCOL_TEMPLATE.name else TEMPLATES / name
    if not path.is_file():
        raise FileNotFoundError(
            f"{path} is missing — labkit was installed without its templates"
        )
    return path.read_text(encoding="utf-8")


def source_version() -> str | None:
    """The version `pyproject.toml` declares when labkit runs from a source
    checkout (an editable install: the file sits beside the package); None
    from a wheel in site-packages."""
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    if not pyproject.is_file():
        return None
    m = PYPROJECT_VERSION_RE.search(pyproject.read_text(encoding="utf-8"))
    if m is None:
        raise RuntimeError(f"{pyproject} has no version line")
    return m.group(1)


def labkit_pin(ref: str | None = None) -> str:
    """The requirements line pinning labkit: the release tag of the installed
    version on GitHub, or REF when given (a pushed commit, for development).

    Refuses when the installed metadata and the source checkout disagree: an
    editable install keeps the version of its last `pip install -e` while
    the templates are read live, and the first re-stamp after the 0.88.7
    release pinned v0.88.5 under 0.88.7 templates (2026-10-13)."""
    version = importlib.metadata.version("labkit")
    source = source_version()
    if source is not None and source != version:
        raise SystemExit(
            f"labkit-init: the installed metadata say {version}, the source "
            f"checkout declares {source} — an editable install keeps the "
            f"version of its last install; run `pip install -e '.[dev]'` "
            f"there, or the pin names a tag the templates do not belong to"
        )
    return f"labkit @ git+{LABKIT_REMOTE}@{ref or 'v' + version}"


# --- lab ----------------------------------------------------------------------


def stamp_lab(root: Path, name: str, ref: str | None = None) -> list[str]:
    """Lay out a lab repo in ROOT (see the module docstring); returns the log."""
    log: list[str] = []
    write_if_absent(
        root / "AGENTS.md",
        template("AGENTS.md.template").replace("<project>", name),
        log,
    )
    claude = root / "CLAUDE.md"
    if not (claude.exists() or claude.is_symlink()):
        os.symlink("AGENTS.md", claude)  # one entry file for every agent
        log.append(f"  created        {claude} -> AGENTS.md")
    write_if_absent(root / ".gitignore", GITIGNORE, log)
    write_if_absent(
        root / "requirements.txt", REQUIREMENTS.format(pin=labkit_pin(ref)), log
    )
    for tmpl, dest in LAB_FILES:
        write_if_absent(root / dest, template(tmpl), log)
    for d in LAB_DIRS:
        if write_if_absent(root / d / ".gitkeep", "", log):
            log[-1] = f"  created        {root / d}/"
    return log


# --- the protocol's three cuts ------------------------------------------------

# Report-grade fields live IN their section and carry a dagger in the label; a
# whole section is report-grade when its heading carries one. The pilot part
# leaves them out; `--report` fills them into their sections when a run
# graduates, so one topic never sits in two places.
DAGGER = "†"
SECONDS_TAG = "<!-- s -->"
SECONDS_MODEL_TAG = "<!-- sm -->"  # owed at seconds only with a model in the loop
#: which template section a heading is about — a report field is placed by topic
SECTION_KEYS = (
    "summary",
    "intent",
    "result",
    "context",
    "setup",
    "checks",
    "runs",
    "follow-up",
    "notes",
)
FIELD_LABEL = re.compile(r"^-\s+\*\*(.+?)\s*:?\*\*")
ProtocolBlocks = list[tuple[str, str, list[list[str]]]]


def section_key(heading: str) -> str | None:
    """Which template section a '## …' heading corresponds to, by its first word."""
    low = heading.lstrip("#").strip().lower()
    return next((k for k in SECTION_KEYS if low.startswith(k)), None)


def _segments(text: str) -> list[tuple[str, list[str]]]:
    """[(heading line or '', body lines)] — the preamble comes as heading ''."""
    segs: list[tuple[str, list[str]]] = [("", [])]
    for line in text.splitlines():
        if line.startswith("## "):
            segs.append((line, []))
        else:
            segs[-1][1].append(line)
    return segs


def _items(body: list[str]) -> list[list[str]]:
    """A section body as bullet items; continuation lines stay with their item."""
    items: list[list[str]] = []
    fence = False
    for line in body:
        starts = line.startswith("- ") and not fence
        if line.lstrip().startswith("```"):
            fence = not fence
        if starts or not items:
            items.append([line])
        else:
            items[-1].append(line)
    return items


def _label_of(item: list[str]) -> str:
    m = FIELD_LABEL.match(item[0])
    return (m.group(1) if m else item[0]).replace(DAGGER, "").strip().lower()


def _untag(line: str) -> str:
    for tag in (SECONDS_TAG, SECONDS_MODEL_TAG):
        line = line.replace(" " + tag, "").replace(tag, "")
    return line


def seconds_cut(tmpl: str, model: bool = False) -> str:
    """The `seconds` cut: the preamble, and of every section only the items tagged
    `<!-- s -->` (with a model also `<!-- sm -->`), under their heading."""
    tags = (SECONDS_TAG, SECONDS_MODEL_TAG) if model else (SECONDS_TAG,)
    out: list[str] = []
    for heading, body in _segments(tmpl):
        if not heading:
            out.extend(line for item in _items(body) for line in item)
            continue
        kept = [item for item in _items(body) if any(t in item[0] for t in tags)]
        if not kept:
            continue
        if out and out[-1].strip():
            out.append("")
        out += [heading, ""] + [_untag(line) for item in kept for line in item]
    return "\n".join(out).rstrip() + "\n"


CONSTANTS_HINT = (
    "# constants = { <name> = <value> }  # every threshold the sentence names, read "
    "with promises.all_constants() — none for a plain count"
)


def quick_block(tmpl: str, model: bool) -> str:
    """The promise tables of the seconds cut: the example constants become a
    commented hint (a count reads no thresholds, and runlog refuses a run whose
    config lacks a registered constant — but a criterion with a threshold must
    name it, and the cloud probe of 2026-10-12 read the promises docstring to
    learn the field), and without a model the null-lane table A2 goes (there is
    no null lane; the probe deleted it by hand)."""
    out = re.sub(r"\nconstants = \{[^}\n]*\}", "\n" + CONSTANTS_HINT, tmpl)
    if not model:
        # a deterministic count has no bar to clear: no promise tables, no
        # criterion — five cold agents each invented a tautological [C1]
        # (cloud probes 2026-10-12); the number is held by --check and finalize
        out = re.sub(r"\n\n# The promises as data[^\n]*\n(?:#[^\n]*\n)*", "\n", out)
        out = re.sub(r"\n\[\[promise\]\]\n(?:[^\n]+\n)*", "\n", out)
        out = re.sub(r"\n{3,}```", "\n```", out)
    return out


PLACEHOLDER_WIDTH = 72  # a one-line hint; the long form is `protocol-check --guide`


def short_placeholders(text: str) -> str:
    """Every stamped `<…>` placeholder on one line. The template's placeholders
    carry the field guide's prose — a third of a cold agent's reading time
    (cloud probes 2026-10-12, five of five); the stamped protocol keeps the
    label and a one-line hint, `protocol-check --guide` the long form.
    Fenced blocks and the TOML head are untouched."""
    out: list[str] = []
    lines = text.split("\n")
    i = 0
    fence = False
    while i < len(lines):
        line = lines[i]
        if line.startswith("```"):
            fence = not fence
        head = re.match(
            r"^(- \*\*[^*]+\*\*:?\s*(?:<!-- sm? -->\s*)?|\s+(?:[^<*]*\*\*:?\s*)?)<(?!!--)(.*)$",
            line,
        )
        if fence or head is None or line.rstrip().endswith(">"):
            out.append(line)
            i += 1
            continue
        # a placeholder opened on this line and not closed: gather its continuation
        body = [head.group(2)]
        j = i + 1
        while (
            j < len(lines)
            and lines[j].startswith("  ")
            and not lines[j].startswith("  ```")
        ):
            body.append(lines[j].strip())
            j += 1
        full = " ".join(body).rstrip(">").strip()
        cut = full
        for mark in (" — ", "; ", " (", ": "):
            k = cut.find(mark)
            if 0 < k < PLACEHOLDER_WIDTH:
                cut = cut[:k]
        if len(cut) > PLACEHOLDER_WIDTH:
            cut = cut[:PLACEHOLDER_WIDTH].rsplit(" ", 1)[0]
        out.append(f"{head.group(1)}<{cut.rstrip(' ,.')}…>")
        i = j
    return "\n".join(out)


def pilot_and_report(tmpl: str) -> tuple[str, ProtocolBlocks]:
    """(pilot part, report blocks) of the template. A report block is (section key,
    heading, items): a daggered section whole, or the daggered items of a section."""
    pilot: list[str] = []
    report: ProtocolBlocks = []
    for heading, body in _segments(tmpl):
        if not heading:
            # the preamble may MENTION the dagger (legend) — it stays pilot
            pilot.extend(line for item in _items(body) for line in item)
            continue
        if DAGGER in heading:
            report.append((section_key(heading) or heading, heading, _items(body)))
            continue
        keep = [
            i for i in _items(body) if not (i[0].startswith("- ") and DAGGER in i[0])
        ]
        moved = [i for i in _items(body) if i[0].startswith("- ") and DAGGER in i[0]]
        pilot.append(heading)
        pilot.extend(line for item in keep for line in item)
        if moved:
            report.append((section_key(heading) or heading, heading, moved))
    return "\n".join(_untag(line) for line in pilot).rstrip() + "\n", report


def insert_report_fields(text: str, blocks: ProtocolBlocks) -> tuple[str, int]:
    """Fill the daggered fields into their sections; (text, fields added).
    A section the protocol lacks comes in whole, before the next one it has."""
    order = [key for key, _, _ in blocks]
    segs = _segments(text)
    keys = [section_key(h) if h else None for h, _ in segs]
    present = {lab for _, body in segs for lab in map(_label_of, _items(body))}
    added = 0
    pending: ProtocolBlocks = []
    for key, heading, items in blocks:
        fresh = [
            i for i in items if i[0].startswith("- ") and _label_of(i) not in present
        ]
        if not fresh:
            continue
        added += len(fresh)
        if key not in keys:
            pending.append((key, heading, items))
            continue
        body = segs[keys.index(key)][1]
        while body and not body[-1].strip():
            body.pop()
        body.extend(line for item in fresh for line in item)
        body.append("")
    for key, heading, items in pending:
        later = [k for k in order[order.index(key) + 1 :] if k in keys]
        at = keys.index(later[0]) if later else len(segs)
        body = [line for item in items for line in item]
        while body and not body[-1].strip():
            body.pop()
        segs.insert(at, (heading, body + [""]))
        keys.insert(at, key)
    out = [
        line for heading, body in segs for line in ([heading] if heading else []) + body
    ]
    return "\n".join(out).rstrip() + "\n", added


# A protocol that names no model has no seed, no temperature and nothing to
# parse; asking for those fields cost a fix cycle each on a deterministic run
# (2026-10-05). --report fills them when the Model / tool field says so.
NO_MODEL = re.compile(r"\*\*model / tool:\*\*\s*(none|no model|-|n/a)\b", re.I)
DETERMINISTIC_NA = {
    "Randomness controls": "n/a — deterministic, no model: no seed, no temperature, one run (auto-filled by --report)",
    "Noise ceiling → threshold": (  # the protocol field's label (the standard says noise floor)
        "n/a — deterministic, repetition spread 0; the threshold comes from the null "
        "condition of this run (auto-filled by --report)"
    ),
    "Parser cases harvested": "n/a — no model, nothing to parse (auto-filled by --report)",
}


def _replace_placeholder(lines: list[str], label: str, value: str) -> bool:
    """In place: the stamped `<…>` placeholder of LABEL (one line or wrapped)
    becomes VALUE on the label line; False when the field is not stamped."""
    head = re.compile(r"^(\s*-\s*\*\*" + re.escape(label) + r"\s*†?:\*\*\s*)<")
    for i, line in enumerate(lines):
        if m := head.match(line):
            j = i
            while ">" not in lines[j]:
                j += 1
            lines[i : j + 1] = [m.group(1) + value]
            return True
    return False


def auto_fill_deterministic(text: str) -> tuple[str, int]:
    """Fill the placeholders a model-free protocol cannot answer; (text, fields filled)."""
    if not NO_MODEL.search(text):
        return text, 0
    lines = text.split("\n")
    filled = sum(
        _replace_placeholder(lines, lb, v) for lb, v in DETERMINISTIC_NA.items()
    )
    return "\n".join(lines), filled


#: What a count's registration owes, said in the placeholder: three cold
#: agents (Haiku, 2026-10-13) wrote a Terms sentence for a plain count — "n/a"
#: was allowed by the check but unsaid by the stamp — and one read
#: "hypothesis" as an expectation to invent, then reworded it with --force.
COUNT_PLACEHOLDERS = {
    "Terms of this protocol": '<one line per coined house word — or "n/a — no coinage">',
    "Question / hypothesis": (
        "<the one question: what is counted, over which items — a count tests no hypothesis>"
    ),
}


def count_placeholders(text: str) -> str:
    """The seconds cut without a model, its Terms and Question placeholders
    replaced by COUNT_PLACEHOLDERS. Raises when the cut lacks one of them."""
    lines = text.split("\n")
    for label, value in COUNT_PLACEHOLDERS.items():
        if not _replace_placeholder(lines, label, value):
            raise ValueError(
                f"count_placeholders: the cut has no stamped `{label}` field"
            )
    return "\n".join(lines)


def new_protocol_id(root: Path) -> str:
    """`p-` + 16 hex, checked against every protocol id already in the repo.

    Not derived from name or path: renaming a protocol or moving an area must
    leave the identity a run bound to intact; the scan catches a protocol
    copied as the start of the next one.
    """
    taken = {
        protocol_block.id_of(f.read_text(encoding="utf-8"))
        for f in root.rglob("PROTOCOL-*.md")
    }
    while True:
        pid = "p-" + uuid.uuid4().hex[:16]
        if protocol_block.ID_SHAPE.match(pid) and pid not in taken:
            return pid


# --- exp ----------------------------------------------------------------------


def next_experiment_number(experiments: Path) -> str:
    """Next free NN prefix ('01' when empty); archived areas keep their number reserved."""
    used = [
        int(m.group(1))
        for d in (experiments, experiments / "_archiv")
        if d.is_dir()
        for p in d.iterdir()
        if p.is_dir() and (m := re.match(r"^(\d+)-", p.name))
    ]
    return f"{max(used) + 1 if used else 1:02d}"


def area_slug(name: str) -> str:
    """The area name as a slug, without a typed `NN-` prefix (labkit owns the number)."""
    slug = re.sub(r"^\d+-", "", re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-"))
    if not slug:
        raise SystemExit(f"labkit-init: unusable experiment name: {name!r}")
    return slug


def area_readme(nn: str, slug: str, skeleton: bool) -> str:
    """The area README: the one question, the route through the area, the contract on one page.

    A count (`skeleton=False`: cost seconds without a model) carries no blank:
    its question and contract live in the protocol, and a README placeholder
    was the one gate line left in the cloud probe (draw 11, 2026-10-13)."""
    question = (
        "**The one question.** <one sentence — the same question as in the protocol's\n"
        'Intent; if it needs an "and", it is two experiments>'
        if skeleton
        else f"**The one question** is the protocol's Question field (`PROTOCOL-{slug}.md`);\n"
        "a count asks one and reports one number."
    )
    returns = (
        "**What `evaluate_rows()` returns.** <per registered promise its key, in the order\n"
        "of the decision — from the protocol's [[promise]] sentences, not from the\n"
        "skeleton: [A1] a1_pass …, [C1] c1_pass …, [B1] b1_branch; what comes back when\n"
        "an admissibility condition fails>. The formula lives once, in\n"
        "`scripts/01_measure.py` (`evaluate_rows()`); `02_analyze.py --check` and the\n"
        "test call it there, and `intent-check` holds the protocol's ids to these keys."
        if skeleton
        else "**What `evaluate_rows()` returns.** The number under `METRIC_KEY` of\n"
        "`scripts/01_measure.py`; a count registers no ids. The formula lives once, there;\n"
        "`--check` and the test call it, and `finalize` holds the protocol's Answer line\n"
        "to the run's `metrics.json`."
    )
    recheck = "`02_analyze.py --check`" if skeleton else "`01_measure.py --check`"
    return f"""# Experiment {nn}: {slug}

*Self-contained: data, scripts, output and this description live here.*

{question}

<!-- labkit:route -->
**Trace it.**
- Contract and reported answer: `PROTOCOL-{slug}.md`
- Runs and provenance: `runlog .`
- Effective values: `labkit-params .`
- Where the ids are decided: `scripts/01_measure.py:evaluate_rows`
- Immutable record: `config.json` of the chosen run under `runs/`
<!-- /labkit:route -->

## Contract

{returns}

**The gates, in order.** `code-check` after every code change · at
`minutes`/`hours`: `preflight` + the preflight audit, then freeze · the run
through `runlog` · `finalize` · `protocol-fill --from-run` writes the number back · {recheck}.

## State

- [ ] Registration written in the protocol (**before** the first run)
{"- [ ] `--probe` read, parser cases in the test" if skeleton else "- [ ] the area test green (`.venv/bin/python -m pytest tests/test_" + nn + "_" + slug.replace("-", "_") + ".py`)"}
- [ ] Run, `protocol-fill --from-run`, `finalize` green
"""


def stamp_explore(experiments: Path, slug: str) -> list[str]:
    """`experiments/explore/<slug>.py` only — the entry before an area exists."""
    log: list[str] = []
    write_if_absent(
        experiments / "explore" / f"{slug}.py",
        template("explore-script.py.template").replace("<name>", slug),
        log,
    )
    return log


def promote(area: Path, blocks: ProtocolBlocks) -> list[str]:
    """Fill the report-grade fields into an existing area's protocols."""
    protos = area_protocols(area)
    if not protos:
        raise SystemExit(f"labkit-init: no PROTOCOL-*.md in {area}")
    log = []
    for proto in protos:
        text = proto.read_text(encoding="utf-8")
        if protocol_block.head(text).cost == "seconds":
            log.append(
                f"  skip (cost seconds: nothing freezes, no report fields)  {proto}"
            )
            continue
        new, added = insert_report_fields(text, blocks)
        if not added:
            log.append(f"  skip (report fields already there)  {proto}")
            continue
        new, auto = auto_fill_deterministic(new)
        proto.write_text(new, encoding="utf-8")
        log.append(
            f"  filled in      {proto} ({added} report field(s), each in its section)"
        )
        if auto:
            log.append(
                f"  n/a stamped    {auto} field(s): no model, nothing to draw, nothing to parse"
            )
    return log


def stamp_scripts(
    root: Path, area: Path, nn: str, slug: str, quick: bool, model: bool | str
) -> list[str]:
    """The script skeletons and the area's test under tests/."""
    log: list[str] = []
    (area / "scripts").mkdir(exist_ok=True)
    alias = model if isinstance(model, str) else "TODO-alias"
    if quick and not model:
        scripts = (("measure-quick-script.py.template", "01_measure.py"),)
        test = "test-quick.py.template"
    else:
        scripts = (
            ("prepare-script.py.template", "00_prepare.py"),
            ("measure-script.py.template", "01_measure.py"),
            ("analyze-script.py.template", "02_analyze.py"),
        )
        test = "test-area.py.template"
    for tmpl, dest in scripts:
        text = template(tmpl).replace("<name>", slug).replace("<model>", alias)
        if write_if_absent(area / "scripts" / dest, text, log):
            (area / "scripts" / dest).chmod(
                0o755
            )  # a shebang nobody can run is a lint finding
    tname = (f"test_{nn}_{slug}" if nn else f"test_{slug}").replace("-", "_") + ".py"
    text = (
        template(test)
        .replace("<area>", str(area.relative_to(root)))
        .replace("<NN>_<name>", tname[len("test_") : -3])
        .replace("<name>", slug)
    )
    write_if_absent(root / "tests" / tname, text, log)
    return log


def stamp_area(
    root: Path,
    name: str,
    cost: str | None = None,
    model: bool | str = False,
    report: bool = False,
) -> tuple[Path, str]:
    """Stamp `experiments/NN-<name>/` (or promote it with REPORT): the area
    and the report to print (what was written, then the next steps) — the
    caller prints; `stamp_lab` returns its log the same way."""
    slug = area_slug(name)
    experiments = root / "experiments"
    if not (root / "models.toml").is_file() or not experiments.is_dir():
        raise SystemExit(
            f"labkit-init: {root} is not a lab repo (no models.toml / experiments/) — run `labkit-init lab` first"
        )
    quick = cost == "seconds"
    tmpl = (
        template(PROTOCOL_TEMPLATE.name)
        .replace("<name>", slug, 1)
        .replace("<protocol-id>", new_protocol_id(root))
    )
    if cost:
        tmpl = tmpl.replace('cost = "<seconds | minutes | hours>"', f'cost = "{cost}"')
    clean = re.sub(
        r" ?<!-- sm? -->", "", tmpl
    )  # every written protocol is free of the cut markers
    pilot, blocks = pilot_and_report(clean)
    if quick:
        pilot, blocks = (
            seconds_cut(quick_block(tmpl, bool(model)), model=bool(model)),
            [],
        )
        if not model:
            pilot = count_placeholders(pilot)
    existing = [
        p
        for p in experiments.iterdir()
        if p.is_dir() and re.sub(r"^\d+-", "", p.name) == slug
    ]
    if existing:
        if not report:
            raise SystemExit(
                f"labkit-init: experiment already exists: {existing[0]} (add report fields: --report)"
            )
        return existing[0], "\n".join(promote(existing[0], blocks))
    nn = next_experiment_number(experiments)
    area = experiments / f"{nn}-{slug}"
    log: list[str] = []
    for d in ("data/raw", "data/prepared", "output"):
        write_if_absent(area / d / ".gitkeep", "", log)
    write_if_absent(
        area / "README.md",
        area_readme(nn, slug, skeleton=not quick or bool(model)),
        log,
    )
    pre = experiments / "explore" / f"{slug}.py"
    if pre.is_file():  # an explore file stamped before the area graduates with it
        (area / "explore").mkdir(exist_ok=True)
        pre.rename(area / "explore" / pre.name)
        log.append(f"  moved          {pre} -> {area / 'explore' / pre.name}")
    write_if_absent(
        area / f"PROTOCOL-{slug}.md",
        # a heading right after a cut item gets its blank line back
        re.sub(
            r"([^\n])\n(## )",
            r"\1\n\n\2",
            short_placeholders(clean if report else pilot),
        ),
        log,
    )
    log += stamp_scripts(root, area, nn, slug, quick, model)
    _point_hooks_at(root)
    return area, (
        f"{'Measurement' if quick else 'Experiment'} -> {area}\n"
        + "\n".join(log)
        + "\n"
        + next_steps(area.relative_to(root), slug, nn, quick, bool(model))
    )


def _point_hooks_at(root: Path) -> None:
    """`core.hooksPath = .githooks` where the repo has both: the hook runs
    only where that setting points at it (2026-10-05)."""
    if not ((root / ".git").exists() and (root / ".githooks").is_dir()):
        return
    r = git_run(["config", "core.hooksPath", ".githooks"], root)
    if r.returncode != 0:
        raise SystemExit(
            f"labkit-init: git config core.hooksPath failed: {r.stderr.strip()}"
        )


def next_steps(rel: Path, slug: str, nn: str, quick: bool, model: bool) -> str:
    """What to do after `exp`, in order — the lane of AGENTS.md for this area."""
    if quick:
        return f"""
Next (cost = "seconds" — no freeze, no audit per run, the first run is the probe):
  1. PROTOCOL-{slug}.md: fill the seconds cut — `type` in the head, then question, unit,
     {"criterion, admissibility condition, prompt, null condition" if model else "data, exclusions — no criterion, no promise table: a count has no bar to clear"}; `protocol-check --contract` names the labels.
  2. scripts/01_measure.py: {"PROMPT, parse_answer(), evaluate_rows(); --show 2, then the run" if model else "expected_ids(), rows(), evaluate_rows()"}.
  3. git add + commit, then scripts/01_measure.py, then `protocol-fill PROTOCOL-{slug}.md --from-run <run_id>`.
  4. finalize {rel} checks the provenance; the agent audit comes when the number is promoted."""
    test = f"tests/test_{nn}_{slug.replace('-', '_')}.py"
    return f"""
Next (light pilot, heavy report):
  1. PROTOCOL-{slug}.md: fill the pilot part (head: type, cost; question, success, admissibility, prompt, null condition).
  2. scripts/00_prepare.py: raw -> prepared   ({rel}/scripts)
  3. scripts/01_measure.py --show 3    read the prompts, no call
  4. scripts/01_measure.py --probe 4   instrument check in the real pipeline; raw answers into {test}
  5. reportable? `labkit-init exp {slug} --report` adds the report fields; then `frozen = true` in the head
  6. git add + commit, THEN scripts/01_measure.py   (untracked code is in no diff)
  7. result note + scripts/02_analyze.py --check; running processes: .venv/bin/runlog {rel}"""


# --- command line -------------------------------------------------------------


def main(argv: list[str]) -> int:
    """`labkit-init lab|exp` — see the module docstring."""
    ap = argparse.ArgumentParser(
        prog="labkit-init", description=(__doc__ or "").split("\n\n")[0]
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    lab = sub.add_parser("lab", help="lay out a lab repo")
    lab.add_argument("dir", nargs="?", type=Path, default=Path("."))
    lab.add_argument(
        "--name", help="project name for AGENTS.md (default: the directory's name)"
    )
    lab.add_argument(
        "--labkit-ref",
        help="pin this ref instead of the release tag (a pushed commit, for development)",
    )
    exp = sub.add_parser("exp", help="stamp an experiment area")
    exp.add_argument("name")
    exp.add_argument(
        "--repo",
        type=Path,
        default=None,
        help="the lab repo (default: the nearest directory, here or above, "
        "holding models.toml and experiments/)",
    )
    exp.add_argument(
        "--cost",
        choices=protocol_block.COST_TIERS,
        help="stamp this tier into the head; seconds stamps the seconds cut",
    )
    exp.add_argument(
        "--model",
        nargs="?",
        const=True,
        default=False,
        metavar="ALIAS",
        help="a model in the loop",
    )
    exp.add_argument(
        "--report",
        action="store_true",
        help="add the † fields (now, or to an existing area)",
    )
    exp.add_argument(
        "--explore", action="store_true", help="only experiments/explore/<name>.py"
    )
    a = ap.parse_args(argv)
    if a.cmd == "lab":
        root = a.dir.resolve()
        root.mkdir(parents=True, exist_ok=True)
        log = stamp_lab(root, a.name or root.name, a.labkit_ref)
        print(f"Lab repo -> {root}\n" + "\n".join(log))
        print(
            "\nnext: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt && .venv/bin/labkit-hooks install"
        )
        return 0
    root = a.repo.resolve() if a.repo is not None else lab_root(Path.cwd())
    if a.explore:
        print("\n".join(stamp_explore(root / "experiments", area_slug(a.name))))
        print(
            f"\nNext: fill the cells, read the render, look at real output; when it holds, `labkit-init exp {area_slug(a.name)}`."
        )
        return 0
    _, report = stamp_area(root, a.name, cost=a.cost, model=a.model, report=a.report)
    print(report)
    return 0


def lab_root(start: Path) -> Path:
    """The nearest directory, START or above, that is a lab repo (models.toml
    and experiments/), as git finds its repo; START itself when none is, so
    stamp_area names the directory it was asked about. Run from an area
    directory, `labkit-init exp <name> --report` called the area "not a lab
    repo" (cloud judge probe, 2026-10-14)."""
    here = start.resolve()
    for d in (here, *here.parents):
        if (d / "models.toml").is_file() and (d / "experiments").is_dir():
            return d
    return here


def cli() -> None:
    """Console entry point `labkit-init`."""
    console.exit_with(main)


if __name__ == "__main__":
    cli()
