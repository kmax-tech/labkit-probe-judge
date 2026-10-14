"""labkit-calltree — the call tree of one real run, cut to one package.

    labkit-calltree [--depth N] [--out FILE] TARGET [-- ARGS...]

"Where is this module called from, and what does this command actually
run?" The editor's call hierarchy answers what the code COULD call; this
answers what one run DID call, from its entry point down. TARGET is a
console script name (`labkit-audit`) or `module:function`
(`labkit.audit:cli`); ARGS become the command's `sys.argv[1:]`.

What the tree shows — and no more:

  - only functions whose source lies inside the target's top-level package
    (for `labkit.audit:cli`: everything under `labkit/`); a package function
    called through the stdlib (a sort key, a callback) hangs under the
    nearest package function above it
  - one line per distinct call path: `module.qualname  path:line  ×N`, where
    N counts the entries along that path (a generator counts each resume)
  - the main thread only; code run at import time (`<module>`) is left out,
    because the module is imported before tracing starts

The command's own output stays on stdout; the tree goes to stderr or to
`--out FILE`. The exit code is the command's own. A command that raises
still prints the tree, then the exception propagates.
"""

from __future__ import annotations

import importlib
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from importlib.metadata import entry_points
from pathlib import Path
from types import FrameType

USAGE = "usage: labkit-calltree [--depth N] [--out FILE] TARGET [-- ARGS...]"


class CalltreeError(Exception):
    """A target that cannot be resolved, or a malformed command line."""


@dataclass
class Node:
    """One function on one call path; `calls` counts its entries on that path."""

    label: str
    path: str
    line: int
    calls: int = 0
    children: dict[tuple[str, int, str], Node] = field(default_factory=dict)


def resolve_target(target: str) -> tuple[str, str]:
    """`module:function` or a console script name → (module, function)."""
    if ":" in target:
        module, _, func = target.partition(":")
        if not module or not func:
            raise CalltreeError(f"target {target!r} is not of the form module:function")
        return module, func
    found = entry_points(group="console_scripts", name=target)
    if not found:
        raise CalltreeError(
            f"no console script named {target!r} is installed; "
            "give it as module:function instead"
        )
    ep = next(iter(found))
    module, _, func = ep.value.partition(":")
    if not func:
        raise CalltreeError(
            f"console script {target!r} points at {ep.value!r}, not a function"
        )
    return module, func


def package_root(module: str) -> Path:
    """The directory (or single file) of the module's top-level package."""
    top = importlib.import_module(module.split(".")[0])
    if top.__file__ is None:
        raise CalltreeError(
            f"package {top.__name__!r} has no file on disk to cut the tree to"
        )
    path = Path(top.__file__).resolve()
    return path.parent if path.name == "__init__.py" else path


def trace_calls(
    func: Callable[[], object], root: Path
) -> tuple[Node, BaseException | None]:
    """Run `func` under a profiler; the tree of calls into `root`, and what it raised."""
    tree = Node(label="<root>", path="", line=0)
    # one entry per open frame: the package node it opened, or None for a frame
    # outside the package — keeps 'call' and 'return' aligned
    stack: list[Node | None] = []
    root_str = str(root)

    def current() -> Node:
        for node in reversed(stack):
            if node is not None:
                return node
        return tree

    def profile(frame: FrameType, event: str, _arg: object) -> None:
        if event == "call":
            code = frame.f_code
            filename = str(Path(code.co_filename).resolve()) if code.co_filename else ""
            inside = filename.startswith(root_str) and code.co_name != "<module>"
            if not inside:
                stack.append(None)
                return
            key = (filename, code.co_firstlineno, code.co_qualname)
            parent = current()
            node = parent.children.get(key)
            if node is None:
                module = frame.f_globals.get("__name__", "?")
                node = Node(
                    label=f"{module}.{code.co_qualname}",
                    path=filename,
                    line=code.co_firstlineno,
                )
                parent.children[key] = node
            node.calls += 1
            stack.append(node)
        elif event == "return" and stack:
            stack.pop()

    raised: BaseException | None = None
    sys.setprofile(profile)
    try:
        func()
    except (
        BaseException
    ) as exc:  # handed back to the caller, which re-raises or exits with it
        raised = exc
    finally:
        sys.setprofile(None)
    return tree, raised


def render_tree(tree: Node, depth: int | None, cwd: Path) -> list[str]:
    """The tree as indented lines, `path:line` relative to `cwd` where it lies below it."""
    lines: list[str] = []

    def where(node: Node) -> str:
        path = Path(node.path)
        shown = path.relative_to(cwd) if path.is_relative_to(cwd) else path
        return f"{shown}:{node.line}"

    def walk(node: Node, level: int) -> None:
        if depth is not None and level >= depth:
            return
        for child in node.children.values():
            count = f"  ×{child.calls}" if child.calls > 1 else ""
            lines.append(f"{'  ' * level}{child.label}  {where(child)}{count}")
            walk(child, level + 1)

    walk(tree, 0)
    return lines


def exit_code(exc: BaseException | None) -> int:
    """The process exit code Python itself would give for what the command raised."""
    if exc is None:
        return 0
    if isinstance(exc, SystemExit):
        if exc.code is None:
            return 0
        if isinstance(exc.code, int):
            return exc.code
        return 1
    raise exc


def parse_args(argv: list[str]) -> tuple[str, list[str], int | None, Path | None]:
    """Command line → (target, the target's args, depth, out file)."""
    depth: int | None = None
    out: Path | None = None
    rest = list(argv)
    while rest and rest[0].startswith("--") and rest[0] != "--":
        flag = rest.pop(0)
        if flag not in ("--depth", "--out") or not rest:
            raise CalltreeError(f"unknown or incomplete option {flag!r}\n{USAGE}")
        value = rest.pop(0)
        if flag == "--depth":
            if not value.isdigit() or int(value) < 1:
                raise CalltreeError(f"--depth takes a positive integer, got {value!r}")
            depth = int(value)
        else:
            out = Path(value)
    if not rest:
        raise CalltreeError(f"no TARGET given\n{USAGE}")
    target, args = rest[0], rest[1:]
    if args and args[0] == "--":
        args = args[1:]
    return target, args, depth, out


def main(argv: list[str]) -> int:
    """Command line: run TARGET with ARGS, print its call tree, return its exit code."""
    if not argv or argv[0] in ("-h", "--help"):
        print((__doc__ or "").strip().splitlines()[0])
        print(USAGE)
        return 0 if argv else 2
    target, args, depth, out = parse_args(argv)
    module_name, func_name = resolve_target(target)
    module = importlib.import_module(module_name)
    func = getattr(module, func_name, None)
    if not callable(func):
        raise CalltreeError(f"{module_name} has no function {func_name!r}")
    root = package_root(module_name)

    saved_argv = sys.argv
    sys.argv = [target, *args]
    try:
        tree, raised = trace_calls(func, root)
    finally:
        sys.argv = saved_argv
    text = "\n".join(render_tree(tree, depth, Path.cwd())) + "\n"
    if out is None:
        sys.stdout.flush()
        sys.stderr.write(f"--- call tree of {target}, cut to {root} ---\n{text}")
    else:
        out.write_text(text, encoding="utf-8")
        sys.stderr.write(f"call tree of {target} written to {out}\n")
    if isinstance(raised, SystemExit) and isinstance(raised.code, str):
        sys.stderr.write(raised.code + "\n")
    return exit_code(raised)


def cli() -> None:
    """Console entry point of `labkit-calltree`."""
    try:
        code = main(sys.argv[1:])
    except CalltreeError as exc:
        sys.stderr.write(f"labkit-calltree: {exc}\n")
        code = 2
    sys.exit(code)


if __name__ == "__main__":
    cli()
