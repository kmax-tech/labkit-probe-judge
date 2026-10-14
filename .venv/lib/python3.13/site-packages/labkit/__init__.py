"""labkit — the shared helpers every experiment repo imports.

Stdlib only. Modules, layers and the one home of each question:
`docs/architecture.md`; console commands: README.

    from labkit import runlog, llm, batch

**Pin the version, never install editable in an experiment repo.** A run
records its environment; if the helpers can change under a finished run, that
record is a claim about an environment that no longer exists. Editable installs
belong here, in this repo, where the tests are.

New code imports the package directly (`from labkit import runlog`) and
creates no shims. Shims are the documented legacy bridge for repos whose
frozen run snapshots import the modules flat (`import runlog`, via a path
entry) — hand over the module object itself, never `import *` (star imports
drop the private helpers and make monkeypatching land on a copy):

    # lib/runlog.py  (legacy repos only)
    import sys
    from labkit import runlog as _mod
    sys.modules[__name__] = _mod
"""

# The submodules are deliberately NOT imported here: `import labkit` must stay
# free of side effects (llm reads models.toml when it is used, not when the
# package is loaded). `from labkit import runlog` works regardless.
