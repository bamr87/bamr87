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
#
# Agent-context kit awareness (FF-0017):
#   - AGT renders '~' (amber) when CLAUDE.md is still the unfilled kit scaffold
#     (template TODO fingerprint) — present, but says nothing. Non-gating.
#   - Each row is annotated when its seeded claude.yml is on a stale kit
#     version (stamp `# kit: agent-context vX.Y.Z` vs templates/agent-context/
#     VERSION; unstamped copies byte-identical to archive/claude-0.1.0.yml
#     report as ≤0.1.0). Hand-modified copies are never flagged.
#     Upgrade path: fanout.yml (kit=standardize) with upgrade=true.
# ============================================================================
set -uo pipefail
# DASH_ROOT lets a test (or a checkout without submodules) point the audit at
# another hub tree; the default is the hub this script lives in.
ROOT="${DASH_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
PY="${PYTHON:-python3}"

exec "$PY" - "$ROOT" "$@" <<'PY'
import sys, os, json, glob as _glob

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
overrides   = std.get('tier_overrides', {}) or {}
kind_overrides = std.get('kind_overrides', {}) or {}

# ---- override hygiene (FF-0028) ----
# A tier_overrides key that matches no registry name silently no-ops — the exact
# way a renamed or retired repo loses its tier unnoticed. Report every offender;
# --json carries them as `stale_overrides` and drift check (f) fails on them.
reg_names = {p.get('name') for p in reg if isinstance(p, dict)}
stale_overrides = []
for k, v in overrides.items():
    if k not in reg_names:
        stale_overrides.append({'key': k, 'tier': v, 'reason': 'not a registry name'})
    elif v not in tiers:
        stale_overrides.append({'key': k, 'tier': v, 'reason': f"unknown tier (declared: {', '.join(tiers)})"})

ART_ORDER = ['readme','license','gitignore','editorconfig','ci','agent_context','claude_workflow','tests','container','release']
ART_SHORT = {'readme':'RDM','license':'LIC','gitignore':'GIT','editorconfig':'EDC',
             'ci':'CI','agent_context':'AGT','claude_workflow':'CLW','tests':'TST','container':'CNT','release':'REL'}
TIER_ORDER = ['active','experiment','content','fork','archived']

def tier_for(p):
    if p.get('tier'): return p['tier']
    n = p.get('name')
    if n in overrides and overrides[n] in tiers: return overrides[n]
    return status_tier.get(p.get('status'), 'experiment')

# ---- kinds (FF-0028) ----
# Registry `kinds:` → .github/sdlc.yml (`kinds:`, else `type:` mapped exactly as
# the sdlc kit documents) → detection: a root _config.yml is a Jekyll site.
SDLC_TYPE_KINDS = {'app': ['app'], 'library': ['lib'], 'site': ['site'], 'docs': ['content'],
                   'demo': ['site'], 'control-plane': ['site', 'hub'], 'fork': ['fork']}
def kinds_for(p, base):
    k = p.get('kinds')
    if k: return [str(x) for x in k]
    sd = os.path.join(base, '.github', 'sdlc.yml')
    if os.path.isfile(sd):
        try:
            with open(sd) as fh:
                d = yaml.safe_load(fh) or {}
            if d.get('kinds'): return [str(x) for x in d['kinds']]
            if d.get('type') in SDLC_TYPE_KINDS: return list(SDLC_TYPE_KINDS[d['type']])
        except (OSError, yaml.YAMLError):
            pass
    if os.path.isfile(os.path.join(base, '_config.yml')): return ['site']
    return []

LEVEL_RANK = {'required': 2, 'recommended': 1, 'na': 0}
def effective_levels(tier, kinds):
    """The tier's levels, LOWERED (never raised) by kind_overrides for each of the
    repo's kinds. Returns (levels, {artifact: kind that lowered it})."""
    lv = dict(tiers.get(tier, {})); lowered = {}
    for k in kinds:
        for aid, level in (kind_overrides.get(k) or {}).items():
            if aid not in ART_ORDER: continue
            if LEVEL_RANK.get(level, 0) < LEVEL_RANK.get(lv.get(aid, 'na'), 0):
                lv[aid] = level; lowered[aid] = k
    return lv, lowered

# ---- agent-context kit awareness (FF-0017) ----
KIT_VERSION = None
try:
    with open(os.path.join(root, 'templates/agent-context/VERSION')) as fh:
        for ln in fh:
            if ln.startswith('version:'):
                KIT_VERSION = ln.split(':', 1)[1].strip(); break
except OSError:
    pass

SCAFFOLD_MARKS = ('<!-- TODO: one paragraph', '<!-- TODO: fill in the real commands')

def kit_state(base):
    """State of the repo's seeded @claude workflow vs the agent-context kit.
    Returns (state, version): absent | current | stale | unstamped | modified.
    Never raises — unparseable files report as 'modified', not errors."""
    p = os.path.join(base, '.github', 'workflows', 'claude.yml')
    if not os.path.isfile(p):
        return 'absent', None
    try:
        with open(p, encoding='utf-8', errors='replace') as fh:
            head = fh.read(4096)
    except OSError:
        return 'modified', None
    for ln in head.splitlines():
        if ln.startswith('# kit: agent-context v'):
            v = ln.split('agent-context v', 1)[1].strip()
            if not v:
                return 'modified', None
            return ('current' if v == KIT_VERSION else 'stale'), v
    # No stamp: a byte-exact archived machine seed reports its real vintage;
    # anything else is hand-modified/hand-authored and is left alone.
    try:
        import filecmp, glob as _glob
        for a in _glob.glob(os.path.join(root, 'templates/agent-context/archive/claude-0.1.0*.yml')):
            if filecmp.cmp(p, a, shallow=False):
                return 'unstamped', '0.1.0'
    except OSError:
        pass
    return 'modified', None

def is_scaffold(base):
    """True when CLAUDE.md is still the unfilled kit scaffold (template TODO
    fingerprint — not the mere word TODO)."""
    p = os.path.join(base, 'CLAUDE.md')
    if not os.path.isfile(p):
        return False
    try:
        with open(p, encoding='utf-8', errors='replace') as fh:
            txt = fh.read(8192)
    except OSError:
        return False
    return any(m in txt for m in SCAFFOLD_MARKS)

def has_artifact(base, aid):
    if aid == 'ci':
        d = os.path.join(base, '.github', 'workflows')
        if os.path.isdir(d):
            return any(f.endswith(('.yml', '.yaml')) for f in os.listdir(d))
        return False
    for pth in artifacts[aid]:
        pth = str(pth)
        if any(ch in pth for ch in '*?['):          # glob: multi-surface layouts
            if _glob.glob(os.path.join(base, pth)):
                return True
        elif os.path.exists(os.path.join(base, pth)):
            return True
    return False

def col(s, c):
    if no_color: return s
    codes = {'red':31,'green':32,'yellow':33,'grey':90,'bold':1,'cyan':36}
    return f"\033[{codes[c]}m{s}\033[0m"

GLYPH = {'ok':('✓','green'),'bad':('✗','red'),'warn':('!','yellow'),'na':('·','grey'),
         'scaffold':('~','yellow')}

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
    if not os.path.isdir(base) or not os.listdir(base):
        skipped.append((name, tier))
        continue
    kinds = kinds_for(p, base)
    treq, lowered = effective_levels(tier, kinds)
    cells, fails, warns = {}, [], []
    for aid in ART_ORDER:
        level = treq.get(aid, 'na')
        present = has_artifact(base, aid)
        if present:                    state = 'ok'
        elif level == 'required':      state = 'bad';  fails.append(aid)
        elif level == 'recommended':   state = 'warn'; warns.append(aid)
        else:                          state = 'na'
        cells[aid] = state
    ks, kv = kit_state(base)
    scaffold = False
    if cells.get('agent_context') == 'ok' and is_scaffold(base):
        cells['agent_context'] = 'scaffold'   # present but unfilled — amber, non-gating
        scaffold = True
        warns.append('agent_context(scaffold)')
    if fails:
        gate_fail += 1
    rows.append({'name': name, 'tier': tier, 'kinds': kinds, 'kind_lowered': lowered,
                 'cells': cells, 'fails': fails, 'warns': warns,
                 'kit_state': ks, 'kit_version': kv, 'claude_md_scaffold': scaffold})

if as_json:
    print(json.dumps({'rows': rows, 'not_checked_out': skipped, 'stale_overrides': stale_overrides,
                      'summary': {'audited': len(rows), 'with_required_gaps': gate_fail,
                                  'not_checked_out': len(skipped),
                                  'stale_overrides': len(stale_overrides)}}, indent=2))
    sys.exit(1 if (gate and (gate_fail or stale_overrides)) else 0)

# ---- single-repo verbose ----
if only:
    if not rows:
        print(f"'{only}' is not a checked-out submodule in the registry.")
        sys.exit(2)
    r = rows[0]
    kinds_s = ','.join(r['kinds']) or 'unknown'
    print(f"\n{col(r['name'], 'bold')}  tier={col(r['tier'], 'cyan')}  kinds={col(kinds_s, 'cyan')}  ({tiers.get(r['tier'],{}).get('label','')})\n")
    levels, _ = effective_levels(r['tier'], r['kinds'])
    for aid in ART_ORDER:
        level = levels.get(aid, 'na')
        g, c = GLYPH[r['cells'][aid]]
        state = r['cells'][aid]
        if state == 'scaffold':
            note = '  <- present but unfilled kit scaffold'
        elif state != 'ok' and level in ('required', 'recommended'):
            note = f"  <- {level} & missing"
        else:
            note = ''
        if aid in r['kind_lowered']:
            note += f"  (lowered by kind: {r['kind_lowered'][aid]})"
        print(f"  {col(g, c)}  {aid:<14} [{level}]{note}")
    kdesc = {'absent': 'no claude.yml', 'current': f'current (v{KIT_VERSION})',
             'stale': f"stale (v{r['kit_version']}; latest v{KIT_VERSION})",
             'unstamped': 'unstamped (≤0.1.0 machine seed; latest v' + str(KIT_VERSION) + ')',
             'modified': 'hand-modified (unstamped) — never auto-upgraded'}
    print(f"\n  agent-context kit: {kdesc[r['kit_state']]}")
    if r['fails']:
        print("\n" + col(f"  FAIL: missing required: {', '.join(r['fails'])}", 'red'))
    elif r['warns']:
        print("\n" + col(f"  OK (required met); recommended missing: {', '.join(r['warns'])}", 'yellow'))
    else:
        print("\n" + col("  ✓ meets its tier baseline", 'green'))
    if stale_overrides:
        print("\n" + col("  stale tier_overrides: " + ', '.join(f"{o['key']} ({o['reason']})" for o in stale_overrides), 'red'))
    sys.exit(1 if (gate and (r['fails'] or stale_overrides)) else 0)

# ---- full matrix ----
w = 22
head = ' ' * w + '  ' + ' '.join(f"{ART_SHORT[a]:>3}" for a in ART_ORDER)
print("\n" + col("Standardization conformance", 'bold') + col("   (✓ ok  ✗ required-missing  ! recommended-missing  ~ scaffold-unfilled  · n/a)", 'grey'))
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
        note = ''
        if r['kit_state'] in ('stale', 'unstamped'):
            note = col(f"  kit v{r['kit_version'] or '?'}→v{KIT_VERSION}", 'yellow')
        print(line + ' '.join(cellstr) + note)

print()
tot = len(rows)
clean = sum(1 for r in rows if not r['fails'] and not r['warns'])
reqgaps = gate_fail
recgaps = sum(1 for r in rows if not r['fails'] and r['warns'])
msg = (f"  {tot} audited  ·  " + col(f"{clean} clean", 'green') + "  ·  " +
       col(f"{reqgaps} with required gaps", 'red' if reqgaps else 'grey') + "  ·  " +
       col(f"{recgaps} recommended-only gaps", 'yellow' if recgaps else 'grey'))
print(msg)
stale_kit = [r['name'] for r in rows if r['kit_state'] in ('stale', 'unstamped')]
if stale_kit and KIT_VERSION:
    shown = ', '.join(stale_kit[:12]) + ('…' if len(stale_kit) > 12 else '')
    print(col(f"  {len(stale_kit)} on a stale agent-context kit (latest v{KIT_VERSION}; upgrade: fanout.yml kit=standardize upgrade=true): {shown}", 'yellow'))
scaff = [r['name'] for r in rows if r.get('claude_md_scaffold')]
if scaff:
    shown = ', '.join(scaff[:12]) + ('…' if len(scaff) > 12 else '')
    print(col(f"  {len(scaff)} CLAUDE.md still an unfilled scaffold (fill: fanout.yml kit=standardize agent_fill, or accept for dormant repos): {shown}", 'yellow'))
lowered_rows = [r for r in rows if r['kind_lowered']]
if lowered_rows:
    print(col(f"  {len(lowered_rows)} judged by kind (standards.yml kind_overrides): " +
              ', '.join(f"{r['name']} [{','.join(r['kinds'])}]" for r in lowered_rows[:12]) +
              ('…' if len(lowered_rows) > 12 else ''), 'grey'))
if stale_overrides:
    print(col("  STALE tier_overrides (drift check (f) fails on these): " +
              ', '.join(f"{o['key']} ({o['reason']})" for o in stale_overrides), 'red'))
if skipped:
    print(col(f"  {len(skipped)} not checked out (excluded): " + ', '.join(n for n, _ in skipped), 'grey'))
print()
sys.exit(1 if (gate and (gate_fail or stale_overrides)) else 0)
PY
