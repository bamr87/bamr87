#!/usr/bin/env bash
# ============================================================================
# tools/audit-standards.sh — per-repo standardization conformance audit
#
# Reads _data/projects.yml (registry) + _data/standards.yml (the tiered baseline)
# and checks each submodule's checked-out working tree for the artifacts its tier
# requires. Powers `tools/dash audit`.
#
# Usage:
#   tools/audit-standards.sh                 full conformance matrix
#   tools/audit-standards.sh <name>          one repo, verbose
#   tools/audit-standards.sh --json          machine-readable
#   tools/audit-standards.sh --gate          exit non-zero if a REQUIRED artifact
#                                             is missing (for gating in CI)
#   tools/audit-standards.sh --no-color      plain output
#
# Note: filesystem-based — most complete when submodules are checked out. Repos
# whose working tree is absent/empty are reported as "not checked out" and are
# excluded from the gate (they can't be judged without a checkout).
# ============================================================================
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${PYTHON:-python3}"

exec "$PY" - "$ROOT" "$@" <<'PY'
import sys, os, json

try:
    import yaml
except ImportError:
    sys.stderr.write("audit-standards: PyYAML required (pip install pyyaml)\n")
    sys.exit(2)

root = sys.argv[1]
argv = sys.argv[2:]
as_json  = '--json' in argv
gate     = '--gate' in argv
no_color = ('--no-color' in argv) or (not sys.stdout.isatty())
positional = [a for a in argv if not a.startswith('-')]
only = positional[0] if positional else None

with open(os.path.join(root, '_data/projects.yml')) as fh:
    reg = yaml.safe_load(fh) or []
with open(os.path.join(root, '_data/standards.yml')) as fh:
    std = yaml.safe_load(fh) or {}

artifacts   = std['artifacts']
tiers       = std['tiers']
status_tier = std.get('status_tier', {})
overrides   = std.get('tier_overrides', {})

ART_ORDER = ['readme','license','gitignore','editorconfig','ci','agent_context','tests','container','release']
ART_SHORT = {'readme':'RDM','license':'LIC','gitignore':'GIT','editorconfig':'EDC',
             'ci':'CI','agent_context':'AGT','tests':'TST','container':'CNT','release':'REL'}
TIER_ORDER = ['active','experiment','content','fork','archived']

def tier_for(p):
    if p.get('tier'): return p['tier']
    n = p.get('name')
    if n in overrides: return overrides[n]
    return status_tier.get(p.get('status'), 'experiment')

def has_artifact(base, aid):
    if aid == 'ci':
        d = os.path.join(base, '.github', 'workflows')
        if os.path.isdir(d):
            return any(f.endswith(('.yml', '.yaml')) for f in os.listdir(d))
        return False
    for pth in artifacts[aid]:
        if os.path.exists(os.path.join(base, pth)):
            return True
    return False

def col(s, c):
    if no_color: return s
    codes = {'red':31,'green':32,'yellow':33,'grey':90,'bold':1,'cyan':36}
    return f"\033[{codes[c]}m{s}\033[0m"

GLYPH = {'ok':('✓','green'),'bad':('✗','red'),'warn':('!','yellow'),'na':('·','grey')}

rows, skipped, gate_fail = [], [], 0
for p in reg:
    sp = p.get('submodule_path')
    if not sp:  # external repo (not a submodule, not on disk)
        continue
    name = p.get('name')
    if only and only not in (name, p.get('slug')):
        continue
    base = os.path.join(root, sp)
    tier = tier_for(p)
    treq = tiers.get(tier, {})
    if not os.path.isdir(base) or not os.listdir(base):
        skipped.append((name, tier))
        continue
    cells, fails, warns = {}, [], []
    for aid in ART_ORDER:
        level = treq.get(aid, 'na')
        present = has_artifact(base, aid)
        if present:                    state = 'ok'
        elif level == 'required':      state = 'bad';  fails.append(aid)
        elif level == 'recommended':   state = 'warn'; warns.append(aid)
        else:                          state = 'na'
        cells[aid] = state
    if fails:
        gate_fail += 1
    rows.append({'name': name, 'tier': tier, 'cells': cells, 'fails': fails, 'warns': warns})

if as_json:
    print(json.dumps({'rows': rows, 'not_checked_out': skipped,
                      'summary': {'audited': len(rows), 'with_required_gaps': gate_fail,
                                  'not_checked_out': len(skipped)}}, indent=2))
    sys.exit(1 if (gate and gate_fail) else 0)

# ---- single-repo verbose ----
if only:
    if not rows:
        print(f"'{only}' is not a checked-out submodule in the registry.")
        sys.exit(2)
    r = rows[0]
    print(f"\n{col(r['name'], 'bold')}  tier={col(r['tier'], 'cyan')}  ({tiers.get(r['tier'],{}).get('label','')})\n")
    for aid in ART_ORDER:
        level = tiers.get(r['tier'], {}).get(aid, 'na')
        g, c = GLYPH[r['cells'][aid]]
        note = '' if r['cells'][aid] == 'ok' else f"  <- {level} & missing" if level in ('required','recommended') else ''
        print(f"  {col(g, c)}  {aid:<14} [{level}]{note}")
    if r['fails']:
        print("\n" + col(f"  FAIL: missing required: {', '.join(r['fails'])}", 'red'))
    elif r['warns']:
        print("\n" + col(f"  OK (required met); recommended missing: {', '.join(r['warns'])}", 'yellow'))
    else:
        print("\n" + col("  ✓ meets its tier baseline", 'green'))
    sys.exit(1 if (gate and r['fails']) else 0)

# ---- full matrix ----
w = 22
head = ' ' * w + '  ' + ' '.join(f"{ART_SHORT[a]:>3}" for a in ART_ORDER)
print("\n" + col("Standardization conformance", 'bold') + col("   (✓ ok  ✗ required-missing  ! recommended-missing  · n/a)", 'grey'))
print(col(head, 'grey'))
for tier in TIER_ORDER:
    trows = [r for r in rows if r['tier'] == tier]
    if not trows:
        continue
    print(col(f"\n{tier.upper()} — {tiers.get(tier,{}).get('label','')}", 'cyan'))
    for r in sorted(trows, key=lambda x: (len(x['fails']) == 0, len(x['warns']) == 0, x['name'])):
        line = f"  {r['name']:<{w-2}}  "
        cellstr = []
        for a in ART_ORDER:
            g, c = GLYPH[r['cells'][a]]
            cellstr.append(col(f"{g:>3}", c))
        print(line + ' '.join(cellstr))

print()
tot = len(rows)
clean = sum(1 for r in rows if not r['fails'] and not r['warns'])
reqgaps = gate_fail
recgaps = sum(1 for r in rows if not r['fails'] and r['warns'])
msg = (f"  {tot} audited  ·  " + col(f"{clean} clean", 'green') + "  ·  " +
       col(f"{reqgaps} with required gaps", 'red' if reqgaps else 'grey') + "  ·  " +
       col(f"{recgaps} recommended-only gaps", 'yellow' if recgaps else 'grey'))
print(msg)
if skipped:
    print(col(f"  {len(skipped)} not checked out (excluded): " + ', '.join(n for n, _ in skipped), 'grey'))
print()
sys.exit(1 if (gate and gate_fail) else 0)
PY
