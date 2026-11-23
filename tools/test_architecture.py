#!/usr/bin/env python3
"""Tests for tools/architecture.py — the hub's structure contract (ADR 0016): each
rule on a fixture tree built in a temp directory, the ledger writer, and the live
tree itself, which is how the contract gates every pull request (python-tests.yml
runs every tools/test_*.py). Offline, no pytest:  python3 tools/test_architecture.py"""
from __future__ import annotations

import ast
import contextlib
import io
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import architecture as arch  # noqa: E402

HUB = Path(__file__).resolve().parents[1]

CONTRACT = """\
schema: architecture/v1
limits:
  module_lines: 20
  data_file_kb: 1
  ledger_headroom_lines: 10
sources:
  - tools/**/*.py
  - .github/scripts/**/*.py
layers:
  - id: generators
    paths:
      - .github/scripts/dash-gen
  - id: core
    paths:
      - tools/fleetcore
  - id: surfaces
    paths:
      - tools/console
layer_exceptions: []
ledger:
  sizes: {}
  sys_path: {}
"""


class Tree:
    """A throwaway hub checkout: write files into it, then check it."""

    def __init__(self, contract: str = CONTRACT):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.write(arch.CONTRACT, contract)
        self.write("tools/fleetcore/__init__.py", "")

    def write(self, rel: str, text: str) -> Path:
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(text), encoding="utf-8")
        return p

    def contract(self, **replace: str) -> None:
        text = CONTRACT
        for old, new in replace.items():
            self.assertion_guard(old in text, old)
            text = text.replace(old, new)
        self.write(arch.CONTRACT, text)

    @staticmethod
    def assertion_guard(ok: bool, what: str) -> None:
        if not ok:
            raise AssertionError(f"fixture contract has no {what!r} to replace")

    def problems(self) -> list[str]:
        return arch.check(self.root)

    def close(self) -> None:
        self._tmp.cleanup()


class ArchitectureCase(unittest.TestCase):
    def setUp(self):
        self.t = Tree()
        self.addCleanup(self.t.close)

    def assertProblem(self, needle: str, problems: list[str] | None = None):
        problems = self.t.problems() if problems is None else problems
        self.assertTrue(any(needle in p for p in problems), f"no problem mentions {needle!r}: {problems}")


class LayerTests(ArchitectureCase):
    def test_importing_down_a_layer_is_fine(self):
        self.t.write(".github/scripts/dash-gen/atlas.py", "X = 1\n")
        self.t.write("tools/fleetcore/views.py", "import atlas\n")
        self.t.write("tools/console/app.py", "from fleetcore import views\nimport atlas\n")
        self.assertEqual(self.t.problems(), [])

    def test_importing_up_a_layer_fails_and_names_the_file(self):
        self.t.write("tools/console/pr_queue.py", "def live_row(): ...\n")
        self.t.write(".github/scripts/dash-gen/readiness.py", """\
            def live():
                import pr_queue
                return pr_queue.live_row()
            """)
        problems = self.t.problems()
        self.assertEqual(len(problems), 1)
        self.assertProblem(".github/scripts/dash-gen/readiness.py imports `pr_queue`", problems)
        self.assertProblem("tools/console (surfaces)", problems)

    def test_a_package_unit_is_imported_by_its_directory_name(self):
        self.t.write("tools/fleetcore/graph.py", "X = 1\n")
        self.t.write(".github/scripts/dash-gen/lake.py", "from fleetcore import graph\n")
        self.assertProblem("imports `fleetcore`")
        # the `tools.` prefix is the same unit
        self.t.write(".github/scripts/dash-gen/lake.py", "from tools.fleetcore import graph\n")
        self.assertProblem("imports `fleetcore`")

    def test_a_recorded_exception_passes_and_a_stale_one_fails(self):
        self.t.write("tools/console/pr_queue.py", "X = 1\n")
        self.t.write(".github/scripts/dash-gen/readiness.py", "import pr_queue\n")
        self.t.contract(**{"layer_exceptions: []": (
            "layer_exceptions:\n  - file: .github/scripts/dash-gen/readiness.py\n    imports: pr_queue\n    why: shared row logic\n")})
        self.assertEqual(self.t.problems(), [])
        self.t.write(".github/scripts/dash-gen/readiness.py", "X = 2\n")
        self.assertProblem("no longer matches the tree")

    def test_an_exception_needs_a_reason(self):
        self.t.contract(**{"layer_exceptions: []": "layer_exceptions:\n  - file: a.py\n    imports: b\n    why: ''\n"})
        with self.assertRaises(arch.ContractError):
            self.t.problems()

    def test_stdlib_names_tests_and_shared_names_are_not_edges(self):
        # a console module called `secrets` must not turn `import secrets` into an edge
        self.t.write("tools/console/secrets.py", "X = 1\n")
        self.t.write(".github/scripts/dash-gen/gen.py", "import secrets\nimport json\n")
        # a test may import anything
        self.t.write("tools/console/core.py", "X = 1\n")
        self.t.write(".github/scripts/dash-gen/test_gen.py", "import core\n")
        # a name two units both provide cannot be resolved, so it is not guessed
        self.t.write("tools/console/common.py", "X = 1\n")
        self.t.write(".github/scripts/dash-gen/common.py", "X = 1\n")
        self.t.write("tools/fleetcore/views.py", "import common\n")
        self.assertEqual(self.t.problems(), [])

    def test_loose_tools_scripts_are_not_layered(self):
        self.t.write("tools/console/core.py", "X = 1\n")
        self.t.write("tools/voices.py", "import core\n")
        self.assertEqual(self.t.problems(), [])


class SizeTests(ArchitectureCase):
    def big(self, lines: int) -> str:
        return "".join(f"x{i} = {i}\n" for i in range(lines))

    def test_a_new_file_past_the_limit_fails(self):
        self.t.write("tools/big.py", self.big(21))
        self.assertProblem("tools/big.py is 21 lines, past the 20-line limit")
        self.t.write("tools/big.py", self.big(20))
        self.assertEqual(self.t.problems(), [])

    def test_tests_are_not_counted(self):
        self.t.write("tools/test_big.py", self.big(500))
        self.assertEqual(self.t.problems(), [])

    def test_a_ledgered_file_is_held_to_its_number(self):
        self.t.write("tools/big.py", self.big(50))
        self.t.contract(**{"sizes: {}": "sizes:\n    tools/big.py: 50"})
        self.assertEqual(self.t.problems(), [])
        self.t.write("tools/big.py", self.big(51))
        self.assertProblem("grew to 51 lines; the ledger holds it to 50")

    def test_a_gain_must_be_recorded(self):
        self.t.contract(**{"sizes: {}": "sizes:\n    tools/big.py: 50"})
        self.t.write("tools/big.py", self.big(31))  # inside twice the headroom: nothing to do
        self.assertEqual(self.t.problems(), [])
        self.t.write("tools/big.py", self.big(30))  # 20 under: record it
        self.assertProblem("to hold the gain")
        self.t.write("tools/big.py", self.big(20))  # under the limit: drop the entry
        self.assertProblem("drop its entry")
        (self.t.root / "tools/big.py").unlink()
        self.assertProblem("not a source file any more")


class PathTests(ArchitectureCase):
    def test_counts_every_way_of_changing_sys_path(self):
        tree = ast.parse(textwrap.dedent("""\
            import sys
            sys.path.insert(0, "a")
            sys.path.append("b")
            sys.path.extend(["c"])
            sys.path[:0] = ["d"]
            sys.path = ["e"] + sys.path
            sys.path += ["f"]
            note = "sys.path.insert(0, 'not code')"
            print(sys.path)
            other.path.insert(0, "g")
            """))
        self.assertEqual(arch.count_path_changes(tree), 6)

    def test_a_new_module_that_changes_sys_path_fails(self):
        self.t.write("tools/voices.py", "import sys\nsys.path.insert(0, 'x')\n")
        self.assertProblem("tools/voices.py changes sys.path (1x) and is not in the ledger")

    def test_a_test_file_may_change_sys_path(self):
        self.t.write("tools/test_voices.py", "import sys\nsys.path.insert(0, 'x')\n")
        self.assertEqual(self.t.problems(), [])

    def test_a_ledgered_module_is_held_and_a_gain_must_be_recorded(self):
        self.t.write("tools/voices.py", "import sys\nsys.path.insert(0, 'x')\nsys.path.insert(0, 'y')\n")
        self.t.contract(**{"sys_path: {}": "sys_path:\n    tools/voices.py: 2"})
        self.assertEqual(self.t.problems(), [])
        self.t.write("tools/voices.py", "import sys\n" + "sys.path.insert(0, 'x')\n" * 3)
        self.assertProblem("changes sys.path 3x; the ledger holds it to 2")
        self.t.write("tools/voices.py", "import sys\nsys.path.insert(0, 'x')\n")
        self.assertProblem("changes sys.path 1x now; the ledger still allows 2")


class DataTests(ArchitectureCase):
    def test_a_committed_data_file_past_the_limit_fails(self):
        self.t.write("_data/snapshot.yml", "x" * 1024)
        self.assertEqual(self.t.problems(), [])
        self.t.write("_data/snapshot.yml", "x" * 2048)
        self.assertProblem("_data/snapshot.yml is 2 KB, past the 1 KB limit")


class LedgerTests(ArchitectureCase):
    def big(self, lines: int) -> str:
        return "".join(f"x{i} = {i}\n" for i in range(lines))

    def plan(self, accept_new: bool = False):
        return arch.planned_ledger(self.t.root, arch.load_contract(self.t.root), accept_new)

    def test_a_new_entry_needs_accept_new(self):
        self.t.write("tools/big.py", self.big(101))
        self.t.write("tools/voices.py", "import sys\nsys.path.insert(0, 'x')\n")
        ledger, refused = self.plan()
        self.assertEqual(ledger, {"sizes": {}, "sys_path": {}})
        self.assertEqual(len(refused), 2)
        ledger, refused = self.plan(accept_new=True)
        self.assertEqual(ledger, {"sizes": {"tools/big.py": 110}, "sys_path": {"tools/voices.py": 1}})
        self.assertEqual(refused, [])

    def test_it_lowers_and_drops_and_never_raises(self):
        self.t.write("tools/grew.py", self.big(120))
        self.t.write("tools/shrank.py", self.big(60))
        self.t.write("tools/fixed.py", self.big(10))
        self.t.contract(**{"sizes: {}": "sizes:\n    tools/grew.py: 100\n    tools/shrank.py: 300\n    tools/fixed.py: 200\n    tools/gone.py: 200"})
        ledger, refused = self.plan()
        self.assertEqual(ledger["sizes"], {"tools/grew.py": 100, "tools/shrank.py": 65})
        self.assertEqual(len(refused), 1)
        self.assertIn("tools/grew.py is 120 lines, over its number 100", refused[0])

    def test_write_replaces_only_the_ledger_block(self):
        self.t.write("tools/big.py", self.big(101))
        before = (self.t.root / arch.CONTRACT).read_text()
        ledger, _ = self.plan(accept_new=True)
        arch.write_ledger(self.t.root, ledger)
        after = (self.t.root / arch.CONTRACT).read_text()
        head = before.split("ledger:")[0]
        self.assertTrue(after.startswith(head))
        self.assertEqual(arch.load_contract(self.t.root)["ledger"]["sizes"], {"tools/big.py": 110})
        self.assertEqual(self.t.problems(), [])

    def test_a_fresh_entry_has_room_and_is_never_already_stale(self):
        for lines in (21, 25, 26, 99, 100, 101, 1000, 4299, 4300, 4301):
            for headroom in (1, 2, 3, 10, 100):
                held = arch.recorded_size(lines, headroom)
                self.assertGreaterEqual(held - lines, max(1, headroom // 2), f"{lines} lines recorded as {held}")
                self.assertLessEqual(held - lines, headroom, f"{lines} lines recorded as {held}")
                self.assertFalse(arch.is_stale(lines, held, headroom))
        self.assertEqual(arch.recorded_size(4299, 100), 4350)

    def test_write_refuses_when_ledger_is_not_the_last_key(self):
        self.t.write(arch.CONTRACT, CONTRACT + "extra: 1\n")
        with self.assertRaises(arch.ContractError):
            arch.write_ledger(self.t.root, {"sizes": {}, "sys_path": {}})


class ContractTests(ArchitectureCase):
    def test_bad_contracts_are_refused_with_exit_2(self):
        for bad in ("", "schema: other/v1\n", CONTRACT.replace("module_lines: 20", "module_lines: 0"),
                    CONTRACT.replace("module_lines: 20", "module_lines: true"), CONTRACT.replace("  - id: core", "  - name: core")):
            self.t.write(arch.CONTRACT, bad)
            with self.assertRaises(arch.ContractError):
                arch.load_contract(self.t.root)
            self.assertEqual(self.cli("check"), 2)

    def cli(self, *args: str) -> int:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return arch.main([args[0], "--root", str(self.t.root), *args[1:]])

    def test_cli_exit_codes(self):
        self.assertEqual(self.cli("check"), 0)
        self.t.write("tools/voices.py", "import sys\nsys.path.insert(0, 'x')\n")
        self.assertEqual(self.cli("check"), 1)
        self.assertEqual(self.cli("ledger"), 1)
        self.assertEqual(self.cli("ledger", "--write", "--accept-new"), 0)
        self.assertEqual(self.cli("check"), 0)
        self.assertEqual(self.cli("report", "--json"), 0)


class LiveTreeTests(unittest.TestCase):
    """The hub itself. This is the gate: a pull request that breaks the contract fails here."""

    def test_the_hub_meets_its_contract(self):
        self.assertEqual(arch.check(HUB), [], "run `python3 tools/architecture.py check` for each problem and its fix")

    def test_every_exception_and_ledger_entry_points_at_a_file(self):
        contract = arch.load_contract(HUB)
        for item in contract.get("layer_exceptions") or []:
            self.assertTrue((HUB / item["file"]).is_file(), item["file"])
        for section in ("sizes", "sys_path"):
            for path in contract["ledger"].get(section) or {}:
                self.assertTrue((HUB / path).is_file(), path)

    def test_the_ledger_is_the_last_key_so_it_can_be_rewritten(self):
        ledger, refused = arch.planned_ledger(HUB, arch.load_contract(HUB), accept_new=False)
        self.assertEqual(refused, [])
        text = (HUB / arch.CONTRACT).read_text(encoding="utf-8")
        tail = text[text.index("\nledger:") + 1:].splitlines()[1:]
        self.assertTrue(all(not line or line[0].isspace() or line.startswith("#") for line in tail))


if __name__ == "__main__":
    unittest.main()
