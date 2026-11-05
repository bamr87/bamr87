#!/usr/bin/env python3
"""
The bashOS shell the console's Desktop page runs on is bashOS's own file.

tools/console/web/src/vendor/bashos/shell.js is a byte-identical copy of
bamr87/bashos src/bashos/gui/web/shell.js (the layout reducer of the bashOS
desktop). The copy is what makes the browser desktop *the* bashOS OS shell
rather than a look-alike, so three things are held here:

  * the copy is not edited in the hub (its SHA-256 is recorded below);
  * where the projects/bashos submodule is checked out, the copy has not
    fallen behind it — improve the reducer upstream, then re-vendor;
  * the hub's type declarations name every export the module has, and nothing
    it does not.

Offline, no pytest:  python3 tools/console/test_bashos_shell.py
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
HUB = HERE.parent.parent
VENDOR = HERE / "web" / "src" / "vendor" / "bashos"
UPSTREAM = HUB / "projects" / "bashos" / "src" / "bashos" / "gui" / "web" / "shell.js"
# Re-vendoring is one change: copy the file, then record its hash here.
SHELL_SHA256 = "c2c1be8cc042069cbc391948626e617c6c6ad46842f24a47af68146072f48f4a"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_the_vendored_shell_is_not_edited_in_the_hub():
    assert _sha(VENDOR / "shell.js") == SHELL_SHA256, \
        "vendor/bashos/shell.js differs from the recorded copy — change it in bamr87/bashos, then re-vendor and update SHELL_SHA256"


def test_the_vendored_shell_matches_the_submodule_when_it_is_checked_out():
    if not UPSTREAM.is_file():
        print("    (skipped: projects/bashos is not checked out)")
        return
    assert _sha(UPSTREAM) == _sha(VENDOR / "shell.js"), \
        "bashos's shell.js has moved on — copy it to tools/console/web/src/vendor/bashos/ and update SHELL_SHA256"


def test_the_type_declarations_name_exactly_the_modules_exports():
    js = (VENDOR / "shell.js").read_text(encoding="utf-8")
    dts = (VENDOR / "shell.d.ts").read_text(encoding="utf-8")
    exported = set(re.findall(r"^export (?:const|function) ([A-Za-z_]\w*)", js, re.M))
    declared = set(re.findall(r"^export (?:const|function) ([A-Za-z_]\w*)", dts, re.M))
    assert exported, "no exports found in shell.js"
    assert exported == declared, f"shell.d.ts and shell.js disagree: {sorted(exported ^ declared)}"
    # The reducer's actions, as the module handles them, are the union the types offer.
    handled = set(re.findall(r'case "([a-zA-Z]+)":', js[js.index("export function reduce"):js.index("function arrangeReducer")]))
    typed = set(re.findall(r"'([a-zA-Z]+)'", dts[dts.index("export type ShellAction"):dts.index("/** Scene ids")]))
    missing = handled - typed
    assert not missing, f"shell.d.ts has no action type for: {sorted(missing)}"


def test_the_module_stays_pure():
    """No DOM, no fetch, no import: that is why it can be vendored and trusted."""
    js = (VENDOR / "shell.js").read_text(encoding="utf-8")
    code = re.sub(r"/\*.*?\*/|//[^\n]*", "", js, flags=re.S)
    for banned in ("document.", "window.", "fetch(", "localStorage", "sessionStorage", "import ", "require(", "eval("):
        assert banned not in code, f"shell.js uses {banned!r}"


def main() -> int:
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  ✓ {name}")
            except AssertionError as exc:
                failures += 1
                print(f"  ✗ {name}: {exc}")
    print(f"{'FAIL' if failures else 'OK'} — vendored bashOS shell tests")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
