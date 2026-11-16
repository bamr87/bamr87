#!/usr/bin/env python3
"""
pipeline_contracts — the machine-checked contracts between the issue pipeline's
tiers (.github/workflows/issue-pipeline.yml). Standard library only.

The tiers used to hand off by a label plus prose. Tier 1 labelled an issue
`agent:ready` and tier 2 took its word for it; tier 3 wrote that "every
acceptance criterion is satisfied" in its own words and labelled the issue
`agent:done`. Nothing checked either claim (ADP-01 and ADP-11 in
docs/agentic-patterns/). Two contracts close that:

  HANDOFF   tier 1 → tier 2, `issue-pipeline-handoff/v1`
            (pipeline-handoff.schema.json). The issue reference, the repo that
            owns the code, the checkbox acceptance criteria, the evidence
            bundle and the size. A deterministic step after tier 1 builds it
            from the issue as tier 1 left it and records it on the issue; the
            queue builder validates it before an issue reaches the tier-2 work
            order, and a failure moves the issue to `agent:blocked` with the
            reason.
  VERDICT   tier 3 → `agent:done`, `issue-pipeline-verdict/v1`
            (pipeline-verdict.schema.json). One entry per checkbox criterion of
            every issue the PR closes: met, unmet or unverifiable, and for met
            the evidence (a test id, a run URL or `path#Lx-Ly`). Tier 3 may mark
            the PR ready and the issue done only when the check passes, and a
            deterministic step after it reverts both when it does not.

Everything above the `GitHub` section is pure and tested offline by
test_issue_pipeline.py. The GitHub half goes through the `gh` CLI, is planned as
a list of actions, and writes only when the caller passes --apply.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import subprocess
from urllib.parse import quote

HANDOFF_SCHEMA = "issue-pipeline-handoff/v1"
VERDICT_SCHEMA = "issue-pipeline-verdict/v1"
HANDOFF_FIELDS = ("schema", "issue", "owner_repo", "acceptance_criteria",
                  "evidence", "size")
HANDOFF_OPTIONAL = ("built_at", "built_by")
VERDICT_FIELDS = ("issue", "criterion_text", "status", "evidence")
VERDICT_OPTIONAL = ("note",)
VERDICT_STATUSES = ("met", "unmet", "unverifiable")

SCHEMA_BASE = "https://github.com/bamr87/bamr87/blob/main/.github/scripts/dash-gen"
HANDOFF_SCHEMA_URL = f"{SCHEMA_BASE}/pipeline-handoff.schema.json"
VERDICT_SCHEMA_URL = f"{SCHEMA_BASE}/pipeline-verdict.schema.json"

# A comment body over this is refused by GitHub (65,536); appending the handoff
# to a long tier-1 comment falls back to a comment of its own below it.
MAX_COMMENT_CHARS = 60_000

NWO_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
REF_RE = re.compile(r"(?:([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+))?#([1-9][0-9]*)")
TIER1_MARKER_RE = re.compile(r'<!-- issue-pipeline tier="1" key="([^"]+)" -->')
EVIDENCE_MARKER_RE = re.compile(r'<!-- issue-evidence key="([^"]+)"(?: at="([^"]*)")? -->')
HANDOFF_START = '<!-- issue-pipeline-handoff key="{key}" -->'
HANDOFF_END = "<!-- /issue-pipeline-handoff -->"
HANDOFF_BLOCK_RE = re.compile(
    r'<!-- issue-pipeline-handoff key="([^"]*)" -->(.*?)<!-- /issue-pipeline-handoff -->', re.S)
HANDOFF_CHECK_MARKER = '<!-- issue-pipeline-handoff-check key="{key}" -->'
VERDICT_MARKER = "<!-- issue-pipeline-verdict -->"
BACKSTOP_MARKER = "<!-- issue-pipeline-verdict-backstop -->"
JSON_FENCE_RE = re.compile(r"^(`{3,}|~{3,})[ \t]*json[ \t]*\n(.*?)\n\1[ \t]*$", re.M | re.S)
VERDICT_FENCE_RE = re.compile(
    r"^[ \t]{0,3}(`{3,}|~{3,})[ \t]*pipeline-verdict[ \t]*\n(.*?)^[ \t]{0,3}\1[ \t]*$",
    re.M | re.S)

# The house template (tier 1, step 3) keeps the reporter's words below this
# line; their checkboxes were folded into the rewritten criteria above it.
ORIGINAL_MARKER = "<!-- original report preserved verbatim below -->"
FENCE_RE = re.compile(r"^[ \t]*(```|~~~)[^\n]*\n[\s\S]*?^[ \t]*\1[ \t]*$", re.M)
HTML_COMMENT_RE = re.compile(r"<!--[\s\S]*?-->")
CHECKBOX_RE = re.compile(
    r"^(?P<indent>[ \t]*)(?:[-*+]|\d{1,3}[.)])[ \t]+\[(?P<mark>[ xX])\][ \t]+(?P<text>\S.*?)[ \t]*$")
LIST_ITEM_RE = re.compile(r"^[ \t]*(?:[-*+]|\d{1,3}[.)])[ \t]+\S")
HEADING_RE = re.compile(r"^[ \t]{0,3}#{1,6}(?:[ \t]+|$)")
BOLD_LABEL_RE = re.compile(r"^[ \t]{0,3}(\*\*|__)[^\n]+?\1[ \t]*:?[ \t]*$")
ACCEPT_LABELS = ("acceptance", "definition of done", "done when")

# Evidence for a `met` verdict: something a reviewer can open or run.
EVIDENCE_URL_RE = re.compile(r"https?://\S+")
EVIDENCE_ANCHOR_RE = re.compile(r"[\w.@+/-]+#L\d+(?:-L?\d+)?")
# A test id names a test, so a word such as `tested`, `tests` or `manual-test`
# is not one. Either a test file's path, with an optional `::name` chain,
# `[param]` and `:line` (`tools/test_x.py::TestA::test_b[case-1]`,
# `spec/models/user_spec.rb:42`), or a `::`-qualified id
# (`crate::tests::it_works`); see evidence_ok for what a test name is.
EVIDENCE_TEST_FILE_RE = re.compile(
    r"(?P<dirs>(?:[\w.@+-]+/)*)(?P<stem>[\w@+-][\w.@+-]*)\.[A-Za-z0-9]{1,10}"
    r"(?P<names>(?:::[\w.-]+)*)(?:\[[^\]\s]+\])?(?::\d+(?:-\d+)?)?")
EVIDENCE_QUALIFIED_RE = re.compile(r"[\w.-]+(?:::[\w.-]+)+(?:\[[^\]\s]+\])?")
TEST_WORDS = ("test", "tests", "spec", "specs")
CAMEL_TEST_RE = re.compile(r"(?:Test|Spec)s?[A-Z0-9]\w*|\w*[a-z0-9](?:Test|Spec)s?")

# Who may author a recorded handoff or a verdict. Anyone can comment on a
# public issue; a block from a stranger is ignored, never trusted.
TRUSTED_ASSOCIATIONS = {"OWNER", "MEMBER", "COLLABORATOR"}


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------- #
# references
# --------------------------------------------------------------------------- #
def issue_ref(nwo: str, number: int) -> str:
    return f"{nwo}#{int(number)}"


def normalize_ref(ref, default_nwo: str) -> str | None:
    """`#7`, `7` or `owner/repo#7` → `owner/repo#7`; None when it is none of them."""
    if isinstance(ref, int) and not isinstance(ref, bool):
        return issue_ref(default_nwo, ref) if ref > 0 else None
    s = str(ref or "").strip()
    if s.isdigit() and int(s) > 0:
        return issue_ref(default_nwo, int(s))
    m = REF_RE.fullmatch(s)
    if not m:
        return None
    return issue_ref(m.group(1) or default_nwo, int(m.group(2)))


def is_trusted(association: str | None, user_type: str | None = None) -> bool:
    return (str(association or "").upper() in TRUSTED_ASSOCIATIONS
            or str(user_type or "") == "Bot")


# --------------------------------------------------------------------------- #
# acceptance criteria — the checkboxes both contracts are judged against
# --------------------------------------------------------------------------- #
def _label_text(line: str) -> str:
    s = re.sub(r"^[ \t]{0,3}#{1,6}[ \t]*", "", line.strip())
    s = s.strip("*_ \t")
    # A number, an emoji or a mark before the words: `## 4. ✅ Acceptance …`.
    s = re.sub(r"^[^\w]*(?:\d{1,3}[.)])?[^\w]*", "", s)
    return s.casefold()


def _is_accept_label(line: str) -> bool:
    return _label_text(line).startswith(ACCEPT_LABELS)


def parse_acceptance_criteria(body: str) -> list[str]:
    """The issue's checkbox acceptance criteria, in order, de-duplicated.

    Read from the part of the body above the house template's preserved
    original, with fenced code and HTML comments removed. When the body has an
    `Acceptance criteria` / `Definition of done` / `Done when` section (a
    heading, a bold label or a line starting with the phrase) holding
    checkboxes, only those count; a section ends at the next heading or bold
    label. Otherwise every checkbox counts. An item's indented continuation
    lines are part of its text. Both `[ ]` and `[x]` count: a ticked box in the
    issue is not evidence that this change satisfies it.
    """
    text = (body or "").replace("\r\n", "\n")
    cut = text.find(ORIGINAL_MARKER)
    if cut >= 0:
        text = text[:cut]
    text = HTML_COMMENT_RE.sub("", FENCE_RE.sub("", text))

    in_section = False
    section: list[list[str]] = []
    every: list[list[str]] = []
    current: list[str] | None = None
    for line in text.split("\n"):
        m = CHECKBOX_RE.match(line)
        if m:
            current = [m.group("text")]
            every.append(current)
            if in_section:
                section.append(current)
            continue
        if not line.strip():
            current = None
            continue
        if HEADING_RE.match(line) or BOLD_LABEL_RE.match(line):
            in_section = _is_accept_label(line)
            current = None
            continue
        indented = line[:1] in (" ", "\t")
        if current is not None and indented and not LIST_ITEM_RE.match(line):
            current.append(line.strip())
            continue
        current = None
        if not indented and not LIST_ITEM_RE.match(line) and _is_accept_label(line):
            in_section = True

    out: list[str] = []
    seen: set[str] = set()
    for parts in (section or every):
        crit = " ".join(" ".join(parts).split())
        key = criterion_key(crit)
        if crit and key not in seen:
            seen.add(key)
            out.append(crit)
    return out


def criterion_key(text: str) -> str:
    """How a verdict's `criterion_text` is matched to a criterion: case, code
    and emphasis marks, runs of whitespace and trailing punctuation are not
    significant; the words are."""
    t = re.sub(r"[`*_]", "", str(text or ""))
    return " ".join(t.split()).casefold().rstrip(" .;:")


# --------------------------------------------------------------------------- #
# the handoff — tier 1 → tier 2
# --------------------------------------------------------------------------- #
def evidence_from_comments(comments: list[dict]) -> dict | None:
    """The LAST evidence bundle posted on the issue (tools/issue-evidence.sh's
    marker) by a trusted author, as the handoff's `evidence`: its key, when it
    was built, its URL. A stranger's marker is ignored: one naming another
    issue would otherwise get a ready issue blocked by the handoff check."""
    found = None
    for c in comments or []:
        m = EVIDENCE_MARKER_RE.search(c.get("body") or "")
        if m and is_trusted(c.get("author_association"), c.get("user_type")):
            found = {"key": m.group(1), "at": m.group(2) or None,
                     "url": c.get("html_url") or None}
    return found


def build_handoff(*, nwo: str, number: int, body: str, labels: list[str],
                  sizes: list[str], evidence: dict | None = None,
                  built_at: str | None = None, built_by: str = "issue-pipeline") -> dict:
    """The handoff document for one issue, built from the issue as it stands."""
    by_low = {s.lower(): s for s in sizes}
    size = next((by_low[lab.lower()] for lab in labels or [] if lab.lower() in by_low), None)
    ev = None
    if evidence:
        ev = {k: evidence.get(k) for k in ("key", "at", "url") if evidence.get(k)}
    return {
        "schema": HANDOFF_SCHEMA,
        "issue": issue_ref(nwo, number),
        "owner_repo": nwo,
        "acceptance_criteria": parse_acceptance_criteria(body),
        "evidence": ev or None,
        "size": size,
        "built_at": built_at or now_iso(),
        "built_by": built_by,
    }


def validate_handoff(doc, *, nwo: str, number: int, sizes: list[str], owner: str,
                     content: bool = True) -> list[str]:
    """Every way `doc` breaks the handoff contract for `nwo#number` ([] = valid).

    `content=False` checks only what binds a RECORDED handoff to this issue
    (its schema, issue reference and owner repo): its criteria may have been
    edited since tier 1 recorded it, and the content check runs on the handoff
    rebuilt from the issue as it stands.
    """
    if not isinstance(doc, dict):
        return ["the handoff is not a JSON object"]
    problems: list[str] = []
    want = issue_ref(nwo, number)
    missing = [k for k in HANDOFF_FIELDS if k not in doc]
    if content and missing:
        problems.append(f"missing field(s): {', '.join(missing)}")
    if content:
        unknown = sorted(set(doc) - set(HANDOFF_FIELDS) - set(HANDOFF_OPTIONAL))
        if unknown:
            problems.append(f"unknown field(s): {', '.join(unknown)}")
    if doc.get("schema") != HANDOFF_SCHEMA:
        problems.append(f"schema is {doc.get('schema')!r}, not {HANDOFF_SCHEMA!r}")

    ref = doc.get("issue")
    if not isinstance(ref, str) or not REF_RE.fullmatch(ref) or ref.startswith("#"):
        problems.append("issue is not an owner/repo#N reference")
    elif ref.lower() != want.lower():
        problems.append(f"issue is {ref}, but this is {want}: the handoff belongs to "
                        f"another issue (copied, or the issue was transferred)")

    repo = doc.get("owner_repo")
    if not isinstance(repo, str) or not NWO_RE.fullmatch(repo):
        problems.append("owner_repo is not an owner/repo name")
    else:
        if repo.lower() != nwo.lower():
            problems.append(f"owner_repo is {repo}, but the issue lives in {nwo}: tier 2 "
                            f"opens its pull request in the issue's own repo")
        if owner and repo.split("/", 1)[0].lower() != owner.lower():
            problems.append(f"owner_repo {repo} is outside {owner}/: the pipeline only "
                            f"opens pull requests in repos {owner} owns")
    if not content:
        return problems

    crit = doc.get("acceptance_criteria")
    if not isinstance(crit, list) or not crit:
        problems.append("no acceptance criteria: the issue needs a checkbox list "
                        "(`- [ ] …`) under an `Acceptance criteria` heading")
    elif not all(isinstance(c, str) and c.strip() for c in crit):
        problems.append("acceptance_criteria holds an empty or non-text entry")

    size = doc.get("size")
    if not size:
        problems.append(f"no size label (one of {', '.join(sizes)})")
    elif str(size).lower() not in {s.lower() for s in sizes}:
        problems.append(f"size {size!r} is not one of {', '.join(sizes)}")

    ev = doc.get("evidence")
    if ev is not None:
        if not isinstance(ev, dict):
            problems.append("evidence is neither null nor an object")
        else:
            if not (ev.get("key") or ev.get("url")):
                problems.append("evidence names neither a bundle key nor a URL")
            if ev.get("key") and str(ev["key"]).lower() != want.lower():
                problems.append(f"the evidence bundle is for {ev['key']}, not {want}")
            if ev.get("url") and not EVIDENCE_URL_RE.fullmatch(str(ev["url"])):
                problems.append("evidence.url is not an http(s) URL")
    return problems


def _fence_for(text: str) -> str:
    longest = max((len(m) for m in re.findall(r"`+", text)), default=0)
    return "`" * max(3, longest + 1)


def render_handoff_block(doc: dict) -> str:
    """The handoff as it is recorded on the issue: hidden start/end markers
    around a collapsed JSON block, so tier 2 of a later run can read it."""
    payload = json.dumps(doc, indent=2, ensure_ascii=False)
    fence = _fence_for(payload)
    return "\n".join([
        HANDOFF_START.format(key=doc.get("issue", "")),
        f"**Tier 1 → tier 2 handoff** · `{HANDOFF_SCHEMA}` · tier 2 checks it before "
        f"it implements ([contract]({HANDOFF_SCHEMA_URL})).",
        "",
        "<details><summary>handoff.json</summary>",
        "",
        f"{fence}json",
        payload,
        fence,
        "",
        "</details>",
        HANDOFF_END,
    ])


def embed_handoff(comment_body: str, block: str) -> str:
    """`comment_body` with its handoff block replaced by `block`, or with
    `block` appended when it has none."""
    body = comment_body or ""
    if HANDOFF_BLOCK_RE.search(body):
        return HANDOFF_BLOCK_RE.sub(lambda _m: block, body, count=1)
    return f"{body.rstrip()}\n\n{block}\n"


def parse_handoff(text: str) -> tuple[dict | None, str | None]:
    """The LAST handoff block in `text`: (document, None), (None, why it cannot
    be read), or (None, None) when there is no block at all."""
    blocks = list(HANDOFF_BLOCK_RE.finditer(text or ""))
    if not blocks:
        return None, None
    inner = blocks[-1].group(2)
    m = JSON_FENCE_RE.search(inner)
    if not m:
        return None, "the recorded handoff has no JSON block"
    try:
        doc = json.loads(m.group(2))
    except json.JSONDecodeError as exc:
        return None, f"the recorded handoff is not valid JSON ({exc.msg})"
    return doc, None


def recorded_handoff(comments: list[dict]) -> dict | None:
    """The handoff tier 1 recorded on the issue, from trusted authors only:
    {"doc", "error", "url"} for the last block found, or None."""
    found = None
    for c in comments or []:
        body = c.get("body") or ""
        if "issue-pipeline-handoff key=" not in body:
            continue
        if not is_trusted(c.get("author_association"), c.get("user_type")):
            continue
        doc, err = parse_handoff(body)
        if doc is not None or err:
            found = {"doc": doc, "error": err, "url": c.get("html_url")}
    return found


def plan_record(*, nwo: str, number: int, body: str, labels: list[str],
                comments: list[dict], sizes: list[str], owner: str,
                built_at: str | None = None) -> dict:
    """What recording one issue's handoff writes: the document, its problems,
    and the comment operation (patch the comment that already holds a handoff,
    else append to tier 1's marker comment, else a comment of its own)."""
    doc = build_handoff(nwo=nwo, number=number, body=body, labels=labels, sizes=sizes,
                        evidence=evidence_from_comments(comments), built_at=built_at,
                        built_by="issue-pipeline tier 1")
    problems = validate_handoff(doc, nwo=nwo, number=number, sizes=sizes, owner=owner)
    block = render_handoff_block(doc)
    key = issue_ref(nwo, number)
    host = None
    for c in comments or []:
        b = c.get("body") or ""
        if HANDOFF_BLOCK_RE.search(b) and is_trusted(c.get("author_association"), c.get("user_type")):
            host = c
    if host is None:
        for c in comments or []:
            m = TIER1_MARKER_RE.search(c.get("body") or "")
            if m and m.group(1).lower() == key.lower() \
                    and is_trusted(c.get("author_association"), c.get("user_type")):
                host = c
    op: dict = {"op": "create", "nwo": nwo, "number": number, "body": block}
    if host is not None and host.get("id"):
        new = embed_handoff(host.get("body") or "", block)
        if len(new) <= MAX_COMMENT_CHARS:
            op = {"op": "patch", "nwo": nwo, "comment_id": host["id"], "body": new,
                  "fallback": {"op": "create", "nwo": nwo, "number": number, "body": block}}
    return {"key": key, "handoff": doc, "problems": problems, "action": op}


def handoff_block_comment(key: str, problems: list[str], *, ready: str, blocked: str) -> str:
    lines = [
        HANDOFF_CHECK_MARKER.format(key=key),
        f"**Blocked by the tier-1 → tier-2 handoff contract** (`{HANDOFF_SCHEMA}`). "
        f"Tier 2 checked this issue before implementing it and found:",
        "",
        *[f"- {p}" for p in problems],
        "",
        f"Add what is missing to the issue, then replace `{blocked}` with `{ready}`; "
        f"tier 2 checks it again on its next run. The contract: "
        f"[pipeline-handoff.schema.json]({HANDOFF_SCHEMA_URL}).",
    ]
    return "\n".join(lines)


def plan_block(reject: dict, *, ready: str, blocked: str) -> list[dict]:
    """The writes that move one rejected issue to `blocked`, with the reason."""
    nwo, number = reject["nwo"], int(reject["number"])
    key = issue_ref(nwo, number)
    return [
        {"op": "add_labels", "nwo": nwo, "number": number, "labels": [blocked]},
        {"op": "remove_label", "nwo": nwo, "number": number, "label": ready},
        {"op": "comment", "nwo": nwo, "number": number,
         "body": handoff_block_comment(key, list(reject.get("problems") or []),
                                       ready=ready, blocked=blocked)},
    ]


# --------------------------------------------------------------------------- #
# the verdict — tier 3 → agent:done
# --------------------------------------------------------------------------- #
def names_test(word: str) -> bool:
    """Is `word` (a directory, a file name without its extension, or one
    segment of a qualified id) a test or spec name? `test_x`, `x_test`,
    `x.spec`, `__tests__`, `TestFoo` and `FooSpec` are; `tested`, `latest`,
    `contest` and `testament` are not."""
    parts = [p for p in re.split(r"[._-]+", word) if p]
    return any(p.lower() in TEST_WORDS or CAMEL_TEST_RE.fullmatch(p) for p in parts)


def evidence_ok(evidence) -> bool:
    """A `met` verdict's evidence: a URL, a `path#Lx-Ly` line anchor, or a test
    id. A test id names a test: the path of a file whose name, or one of whose
    directories, is a test or spec name (`tools/test_x.py`, `x.spec.ts`,
    `templates/ai-runner/tests/contract.sh`), optionally followed by a `::name`
    chain, a `[param]` and a `:line`; or a `::`-qualified id with a test or
    spec name in it (`crate::tests::it_works`). A word is not a test id
    (`tested`, `tests`, `manual-test`), and prose is not evidence."""
    if not isinstance(evidence, str):
        return False
    s = evidence.strip()
    if not s:
        return False
    if EVIDENCE_URL_RE.fullmatch(s) or EVIDENCE_ANCHOR_RE.fullmatch(s):
        return True
    m = EVIDENCE_TEST_FILE_RE.fullmatch(s)
    if m:
        dirs = [d for d in m.group("dirs").split("/") if d]
        if any(names_test(w) for w in dirs + [m.group("stem")]):
            return True
    if EVIDENCE_QUALIFIED_RE.fullmatch(s):
        segments = re.sub(r"\[[^\]]*\]$", "", s).split("::")
        return any(names_test(seg) for seg in segments)
    return False


def parse_verdicts(texts: list[str]) -> tuple[list | None, str | None]:
    """The LAST ```pipeline-verdict block across `texts` (oldest first):
    (entries, None), (None, why it cannot be read), or (None, None)."""
    last = None
    for t in texts or []:
        for m in VERDICT_FENCE_RE.finditer(t or ""):
            last = m.group(2)
    if last is None:
        return None, None
    try:
        data = json.loads(last)
    except json.JSONDecodeError as exc:
        return None, f"the pipeline-verdict block is not valid JSON ({exc.msg})"
    if not isinstance(data, list):
        return None, "the pipeline-verdict block must be a JSON array of verdicts"
    return data, None


def _verdict_shape(i: int, v, default_nwo: str) -> list[str]:
    where = f"verdict {i}"
    if not isinstance(v, dict):
        return [f"{where} is not an object"]
    probs = []
    missing = [k for k in VERDICT_FIELDS if k not in v]
    if missing:
        probs.append(f"{where} is missing {', '.join(missing)}")
    unknown = sorted(set(v) - set(VERDICT_FIELDS) - set(VERDICT_OPTIONAL))
    if unknown:
        probs.append(f"{where} has unknown field(s) {', '.join(unknown)}")
    if "issue" in v and normalize_ref(v["issue"], default_nwo) is None:
        probs.append(f"{where}: issue {v['issue']!r} is not owner/repo#N or #N")
    if "criterion_text" in v and not (isinstance(v["criterion_text"], str)
                                      and v["criterion_text"].strip()):
        probs.append(f"{where}: criterion_text is empty")
    if "status" in v and v["status"] not in VERDICT_STATUSES:
        probs.append(f"{where}: status {v['status']!r} is not one of "
                     f"{', '.join(VERDICT_STATUSES)}")
    if "evidence" in v and not isinstance(v["evidence"], str):
        probs.append(f"{where}: evidence must be a string")
    return probs


def check_verdicts(verdicts, issues: dict[str, str], *, default_nwo: str,
                   read_error: str | None = None) -> dict:
    """Judge tier 3's verdict against the issues the PR closes.

    `issues` maps `owner/repo#N` to the issue body. It passes only when every
    checkbox criterion of every issue has exactly one verdict, every verdict is
    `met`, and every `met` cites evidence. An issue with no checkboxes is
    `unverifiable` and never passes: there is nothing to check a claim against.
    """
    result: dict = {"schema": VERDICT_SCHEMA, "pass": False, "issues": [], "problems": []}
    if read_error:
        result["problems"].append(read_error)
    elif verdicts is None:
        result["problems"].append("no `pipeline-verdict` block on the pull request")
    if not issues:
        result["problems"].append("the pull request closes no issue (`Closes #N`), so "
                                  "there are no acceptance criteria to judge")

    entries = []
    for i, v in enumerate(verdicts or [], 1):
        shape = _verdict_shape(i, v, default_nwo)
        if shape:
            result["problems"].extend(shape)
            continue
        entries.append({"ref": normalize_ref(v["issue"], default_nwo),
                        "key": criterion_key(v["criterion_text"]),
                        "text": v["criterion_text"], "status": v["status"],
                        "evidence": v.get("evidence") or ""})

    known = {r.lower() for r in issues}
    for e in entries:
        if e["ref"].lower() not in known:
            result["problems"].append(f"verdict for {e['ref']}, which the pull request "
                                      f"does not close: {e['text']!r}")

    for ref, body in issues.items():
        crit = parse_acceptance_criteria(body)
        mine = [e for e in entries if e["ref"].lower() == ref.lower()]
        row = {"issue": ref, "status": "pass", "met": 0, "total": len(crit),
               "criteria": [], "problems": []}
        if not crit:
            row["status"] = "unverifiable"
            row["problems"].append("the issue has no checkbox acceptance criteria, so "
                                   "nothing can be verified against it")
        keys = set()
        for c in crit:
            k = criterion_key(c)
            keys.add(k)
            hits = [e for e in mine if e["key"] == k]
            if not hits:
                state, ev = "missing", ""
                row["problems"].append(f"no verdict for: {c}")
            elif len(hits) > 1:
                state, ev = "duplicate", ""
                row["problems"].append(f"{len(hits)} verdicts for: {c}")
            else:
                state, ev = hits[0]["status"], hits[0]["evidence"]
                if state == "met" and not evidence_ok(ev):
                    state = "met-without-evidence"
                    row["problems"].append(f"met without evidence (a test id, a run URL "
                                           f"or path#Lx-Ly): {c}")
                elif state == "met":
                    row["met"] += 1
                else:
                    row["problems"].append(f"{state}: {c}")
            row["criteria"].append({"text": c, "verdict": state, "evidence": ev})
        for e in mine:
            if e["key"] not in keys:
                row["problems"].append(f"verdict for a criterion the issue does not "
                                       f"list: {e['text']}")
        if row["problems"] and row["status"] == "pass":
            row["status"] = "fail"
        result["issues"].append(row)

    result["pass"] = (not result["problems"] and bool(result["issues"])
                      and all(r["status"] == "pass" for r in result["issues"]))
    return result


def render_verdict_report(result: dict, *, pr: str = "") -> str:
    """The check's result as Markdown: what passed, and every unmet item."""
    head = "passes" if result.get("pass") else "FAILS"
    lines = [f"**Verdict check {head}**" + (f" for {pr}" if pr else "")
             + f" (`{VERDICT_SCHEMA}`, [schema]({VERDICT_SCHEMA_URL})).", ""]
    for p in result.get("problems") or []:
        lines.append(f"- {p}")
    for row in result.get("issues") or []:
        lines.append(f"- **{row['issue']}**: {row['status']}, {row['met']}/{row['total']} "
                     f"criteria met with evidence")
        for p in row["problems"]:
            lines.append(f"  - {p}")
    return "\n".join(lines)


def render_verdict_template(issues: dict[str, str]) -> str:
    """A verdict comment to fill in: every criterion of every issue, verbatim."""
    entries = []
    for ref, body in issues.items():
        for c in parse_acceptance_criteria(body):
            entries.append({"issue": ref, "criterion_text": c,
                            "status": "unverifiable", "evidence": ""})
    payload = json.dumps(entries, indent=2, ensure_ascii=False)
    fence = _fence_for(payload)
    return "\n".join([VERDICT_MARKER, f"{fence}pipeline-verdict", payload, fence])


def asserted_this_run(target: dict, *, pr_draft: bool, issue_labels: dict[str, list[str]],
                      done: str) -> tuple[bool, list[str]]:
    """What tier 3 asserted on one PR since the scan: (marked it ready, the
    issues it marked done). A PR that was already ready, or an issue already
    `done`, at the start of the run is not tier 3's claim this run."""
    became_ready = bool(target.get("draft")) and not pr_draft
    before = {str(r).lower() for r in target.get("done_at_scan") or []}
    marked = [r for r, labs in issue_labels.items()
              if done.lower() in {lab.lower() for lab in labs} and r.lower() not in before]
    return became_ready, marked


def plan_backstop(target: dict, *, pr_draft: bool, issue_labels: dict[str, list[str]],
                  result: dict | None, done: str, pr_ref: str) -> list[dict]:
    """The writes that undo what tier 3 asserted on a PR whose verdict fails.

    Tier 3 asserted something when the PR was a draft at the start of the run
    and is ready now, or when an issue it closes carries `done` that it did not
    carry at the start (`asserted_this_run`). Only those are reverted: a PR a
    person marked ready before the run, or an earlier run's `done`, is left alone.
    """
    nwo, number = target["nwo"], int(target["number"])
    became_ready, done_refs = asserted_this_run(target, pr_draft=pr_draft,
                                                issue_labels=issue_labels, done=done)
    if not (became_ready or done_refs) or (result and result.get("pass")):
        return []
    actions: list[dict] = []
    if became_ready:
        actions.append({"op": "pr_undo_ready", "nwo": nwo, "number": number})
    for ref in done_refs:
        inwo, _, inum = ref.partition("#")
        actions.append({"op": "remove_label", "nwo": inwo, "number": int(inum), "label": done})
    reverted = []
    if became_ready:
        reverted.append("returned the pull request to draft")
    if done_refs:
        reverted.append(f"removed `{done}` from {', '.join(done_refs)}")
    body = "\n".join([
        BACKSTOP_MARKER,
        f"**Reverted by the verdict backstop:** {' and '.join(reverted)}. Tier 3 may mark a "
        f"pull request ready and its issue done only when "
        f"`tools/dash-gen issues verdict check --repo {nwo} --pr {number}` passes.",
        "",
        render_verdict_report(result or {"pass": False, "issues": [],
                                         "problems": ["the verdict could not be checked"]},
                              pr=pr_ref),
    ])
    actions.append({"op": "comment", "nwo": nwo, "number": number, "body": body})
    return actions


# --------------------------------------------------------------------------- #
# GitHub — the `gh` CLI, auth from GH_TOKEN / `gh auth login`
# --------------------------------------------------------------------------- #
class GhError(RuntimeError):
    """A `gh` call failed; the message carries gh's own error line."""


def gh(args: list[str], *, stdin: str | None = None) -> str:
    try:
        proc = subprocess.run(["gh", *args], input=stdin, capture_output=True,
                              text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GhError(f"gh {' '.join(args[:2])}: {exc}") from exc
    if proc.returncode != 0:
        msg = (proc.stderr or proc.stdout or "").strip().splitlines()
        raise GhError(f"gh {' '.join(args[:2])}: {msg[-1] if msg else 'failed'}")
    return proc.stdout


COMMENT_JQ = (".[] | {id, body, html_url, created_at, author_association, "
              "user: (.user.login // \"\"), user_type: (.user.type // \"\")}")


def fetch_issue(nwo: str, number: int) -> dict:
    data = json.loads(gh(["api", f"repos/{nwo}/issues/{int(number)}"]) or "{}")
    return {"nwo": nwo, "number": int(number), "body": data.get("body") or "",
            "title": data.get("title") or "", "state": data.get("state") or "",
            "url": data.get("html_url") or "",
            "labels": [lab.get("name", "") for lab in data.get("labels") or []
                       if isinstance(lab, dict)]}


def fetch_comments(nwo: str, number: int) -> list[dict]:
    out = gh(["api", "--paginate", f"repos/{nwo}/issues/{int(number)}/comments?per_page=100",
              "--jq", COMMENT_JQ])
    return [json.loads(line) for line in out.splitlines() if line.strip()]


def fetch_pr(nwo: str, number: int) -> dict:
    data = json.loads(gh(["api", f"repos/{nwo}/pulls/{int(number)}"]) or "{}")
    return {"nwo": nwo, "number": int(number), "body": data.get("body") or "",
            "draft": bool(data.get("draft")), "url": data.get("html_url") or "",
            "state": data.get("state") or "",
            "author_association": data.get("author_association") or "",
            "user_type": ((data.get("user") or {}).get("type")) or ""}


def linked_refs(pr_body: str, nwo: str) -> list[str]:
    """`Closes #N` / `Fixes owner/repo#N` / `Resolves #N` in a PR body, in order."""
    out: list[str] = []
    rx = re.compile(r"\b(?:clos(?:e|es|ed)|fix(?:e[sd])?|resolv(?:e|es|ed))\s+"
                    r"((?:[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)?#[1-9][0-9]*)\b", re.I)
    for m in rx.finditer(pr_body or ""):
        ref = normalize_ref(m.group(1), nwo)
        if ref and ref.lower() not in {r.lower() for r in out}:
            out.append(ref)
    return out


def verdict_inputs(nwo: str, pr_number: int, issue_args: list[str] | None = None) -> dict:
    """Everything the verdict check reads for one PR, fetched once."""
    pr = fetch_pr(nwo, pr_number)
    refs = [normalize_ref(a, nwo) for a in issue_args or []] or linked_refs(pr["body"], nwo)
    refs = [r for r in refs if r]
    bodies = {ref: fetch_issue(ref.split("#")[0], int(ref.split("#")[1]))["body"] for ref in refs}
    texts = [pr["body"]] if is_trusted(pr["author_association"], pr["user_type"]) else []
    for c in fetch_comments(nwo, pr_number):
        if is_trusted(c.get("author_association"), c.get("user_type")):
            texts.append(c.get("body") or "")
    verdicts, err = parse_verdicts(texts)
    return {"pr": pr, "issues": bodies, "verdicts": verdicts, "error": err}


def check_pr(nwo: str, pr_number: int, issue_args: list[str] | None = None) -> tuple[dict, dict]:
    inp = verdict_inputs(nwo, pr_number, issue_args)
    result = check_verdicts(inp["verdicts"], inp["issues"], default_nwo=nwo,
                            read_error=inp["error"])
    return result, inp


def apply_action(action: dict) -> None:
    """Perform one planned write."""
    op, nwo = action["op"], action["nwo"]
    if op == "comment" or op == "create":
        gh(["api", "-X", "POST", f"repos/{nwo}/issues/{action['number']}/comments",
            "--input", "-"], stdin=json.dumps({"body": action["body"]}))
    elif op == "patch":
        try:
            gh(["api", "-X", "PATCH", f"repos/{nwo}/issues/comments/{action['comment_id']}",
                "--input", "-"], stdin=json.dumps({"body": action["body"]}))
        except GhError:
            if not action.get("fallback"):
                raise
            apply_action(action["fallback"])
    elif op == "add_labels":
        gh(["api", "-X", "POST", f"repos/{nwo}/issues/{action['number']}/labels",
            "--input", "-"], stdin=json.dumps({"labels": list(action["labels"])}))
    elif op == "remove_label":
        try:
            gh(["api", "-X", "DELETE", f"repos/{nwo}/issues/{action['number']}/labels/"
                f"{quote(action['label'], safe='')}"])
        except GhError as exc:
            if "404" not in str(exc):  # not applied: already where we want it
                raise
    elif op == "pr_undo_ready":
        gh(["pr", "ready", str(action["number"]), "-R", nwo, "--undo"])
    else:
        raise ValueError(f"unknown action {op!r}")


def describe(action: dict) -> str:
    op = action["op"]
    where = f"{action['nwo']}#{action.get('number', action.get('comment_id'))}"
    if op in ("comment", "create"):
        return f"comment on {where}"
    if op == "patch":
        return f"update comment {action['comment_id']} in {action['nwo']}"
    if op == "add_labels":
        return f"label {where} {', '.join(action['labels'])}"
    if op == "remove_label":
        return f"unlabel {where} {action['label']}"
    if op == "pr_undo_ready":
        return f"return {where} to draft"
    return f"{op} {where}"
