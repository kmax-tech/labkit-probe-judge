"""The shared helpers must resolve to the labkit package — nothing shadows it.

Why this test exists: shared helpers used to live in lab repos as file
copies, and a fix in the master reached a repo only if someone remembered to
copy it — audits found copies silently stale by hundreds of lines. New code
therefore imports the package directly (`from labkit import runlog`); shims
are a legacy bridge in old repos only. This test fails the moment a file
named like a shared helper appears where it could shadow or fork the
package — that file would be the second truth all over again.

What is NOT tested here: the behaviour of the helpers themselves. That lives
with the code, in labkit's own test suite.

Run:  .venv/bin/python -m unittest discover -s tests
"""
from __future__ import annotations

import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SHARED = ["runlog", "llm", "batch"]


class TestHelpersResolveToPackage(unittest.TestCase):
    def test_the_package_imports(self):
        from labkit import batch, llm, runlog
        for mod, name in ((runlog, "runlog"), (llm, "llm"), (batch, "batch")):
            with self.subTest(module=name):
                self.assertEqual(mod.__name__, f"labkit.{name}")
                self.assertIn("labkit", Path(mod.__file__ or "").parts)

    def test_private_names_are_reachable(self):
        """Monkeypatching in tests must land on the one real module."""
        from labkit import llm, runs
        self.assertTrue(callable(runs._command_of))
        self.assertTrue(callable(llm._find_models_toml))


class TestNothingShadowsThePackage(unittest.TestCase):
    def test_no_helper_named_file_outside_the_package(self):
        stale = [str(p.relative_to(REPO))
                 for d in ("lib", "experiments", "tools", "resources/templates")
                 for p in (REPO / d).glob("*.py")
                 if p.stem in SHARED or p.stem == "protocol-check"]
        self.assertEqual(stale, [], "a file shadows/forks a shared helper — "
                                    "shared code lives in labkit only")


if __name__ == "__main__":
    unittest.main()
