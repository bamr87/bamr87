import copy, sys
from pathlib import Path
import yaml
sys.path.insert(0, str(Path(__file__).parent))
import projects_lint as pl

SPEC = yaml.safe_load(pl.SPEC.read_text())

def test_spec_is_valid():
    assert pl.validate(SPEC) == []

def test_lifecycle_must_match_status():
    s = copy.deepcopy(SPEC); s["lifecycle"].pop("Done")
    assert any("lifecycle" in e for e in pl.validate(s))

def test_label_maps_to_known_value():
    s = copy.deepcopy(SPEC); s["labels"]["canonical"]["P0"]["value"] = "P9"
    assert pl.validate(s)

def test_portfolio_required():
    s = copy.deepcopy(SPEC); s["projects"] = [p for p in s["projects"] if p["key"] != "portfolio"]
    assert pl.validate(s)

if __name__ == "__main__":
    tests = [f for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    for t in tests:
        t()
        print(f"  ok    {t.__name__}")
    print(f"PASS: {len(tests)} test(s)")
