#!/usr/bin/env python3
"""pr_review — the fleet's one PR comment (constitution § 19).

Every CI failure on a pull request is summarized in one sticky comment, so a
reader learns why a check failed without opening a log. The comment is rebuilt
from the state of the PR's head commit each time a workflow finishes, so it
always says what is true now, and it is deleted when nothing is failing.

A repo check reports findings by uploading a `fleet-findings` artifact (JSON
lines: path, line, rule, severity, message, kind) instead of commenting itself.
Each finding on a line the PR adds is posted once as an inline review comment
with its severity, keyed by (path, line, rule) so a later push never reposts
it; content and docs findings are dropped on Dependabot and release PRs (§ 19.3,
§ 19.6). The contract is in templates/pr-review/README.md.

  python3 pr_review.py ci --repo OWNER/NAME --run RUN_ID            post or update
  python3 pr_review.py ci --repo OWNER/NAME --run RUN_ID --dry-run  print, write nothing

Called by .github/workflows/pr-review.yml (a `workflow_run` of every workflow).
Doc: templates/pr-review/README.md.

The logs and artifacts it reads come from pull requests on public repositories
and it holds a write token, so every string that reaches a comment is treated as
untrusted: it goes through a code fence, a code span or markdown escaping, never
into a shell. An artifact is read in memory and validated line by line; one bad
line rejects the whole artifact. Nothing here runs anything from the pull request.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import lzma
import os
import re
import subprocess
import sys
import zipfile
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import workflow_atlas as atlas  # noqa: E402  classify_failure, the fleet's failure classes

MARKER = "<!-- fleet:pr-review -->"
STATE_RX = re.compile(r"<!-- fleet:pr-review-state (\{.*?\}) -->")
SELF_NAME = "PR review"
AI_REVIEW_WORKFLOW = ".github/workflows/pr-ai-review.yml"   # § 19.7: its review is posted from here (ai_review_of)
QA_LEAD_WORKFLOW = ".github/workflows/qa-lead.yml"          # § 15.5: QA Lead's review is posted from here (qa_lead_of)
PR_EVENTS = ("pull_request", "pull_request_target")
FAILED = ("failure", "timed_out", "startup_failure")
HELD = ("action_required",)
MAX_RUNS = 6            # failed workflows detailed in one comment
MAX_JOBS = 4            # failed jobs detailed per workflow
MAX_EXCERPT_LINES = 14
MAX_LINE = 220
MAX_BODY = 30_000       # GitHub's limit is 65,536; the AI region (MAX_AI_REGION) comes on top
LOG_TAIL_LINES = 160    # what the AI analysis reads of a failed step

# The findings channel (§ 19.3). The artifact is data from the PR's own code.
FINDINGS_ARTIFACT = "fleet-findings"
FINDING_KEYS = frozenset({"path", "line", "rule", "severity", "message", "kind"})
FINDING_SEVERITIES = ("error", "warning", "note")
FINDING_KINDS = ("code", "content", "docs")
SCOPED_KINDS = ("content", "docs")   # § 19.6: skipped on Dependabot and release PRs
DEPENDABOT = "dependabot[bot]"
RELEASE_REF = "release-please--"
MAX_ARTIFACTS = 10          # findings artifacts read per review
MAX_ARTIFACT_BYTES = 1 << 20    # the zip, as GitHub reports it
MAX_JSONL_BYTES = 2 << 20       # every .jsonl in it, uncompressed
MAX_FINDINGS = 500          # per artifact
MAX_MESSAGE = 1000
MAX_INLINE = 20             # new inline comments per review; the rest wait for the next one
MAX_REFUSED = 5             # refusals in a row before a review stops posting; the rest wait
MAX_PAGES = 30              # GitHub lists at most 3,000 files of a PR
RULE_ID_RX = re.compile(r"[A-Za-z0-9][\w.:/-]{0,79}")
FINDING_KEY_RX = re.compile(r"<!-- fleet:finding key=([0-9a-f]{40}) -->")
HUNK_RX = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")
SEVERITY_LABEL = {"error": "Error", "warning": "Warning", "note": "Note"}

CLASS_LABEL = {
    "defect": "Code or test failure",
    "config": "A setting or credential",
    "transient": "Temporary: likely to pass on a re-run",
    "dependency": "An upstream dependency",
    "capacity": "A shared limit was spent",
}
NEXT_STEP = {
    "defect": "Fix the failure shown here.",
    "config": "Check the repo setting or secret this names. A re-run won't help until that changes.",
    "transient": "Re-run the failed jobs.",
    "dependency": "Check the upstream package or Dependabot's own log, then re-run.",
    "capacity": "It clears by itself when the limit resets. Re-run after that.",
}

TS_RX = re.compile(r"^\ufeff?(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.\d+)?Z ?")
ANSI_RX = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
SCRIPT_ECHO_RX = re.compile(r"\[36;1m|^shell: |^env:$")
GENERIC_RX = re.compile(r"^(?:##\[error\])?(?:Process completed with exit code \d+\.?|The operation was canceled\.?|"
                        r"The process '[^']*' failed with exit code \d+)$")
ROLLUP_RX = re.compile(r"(?i)\b(?:shards?|jobs?|needs?)\b.*\b(?:ended|failed|failure|result)\b")
ERROR_RX = re.compile(r"^##\[error\](.*)$")
TRACE_RX = re.compile(r"^Traceback \(most recent call last\):")
EXC_RX = re.compile(r"^(?:[A-Za-z_][\w.]*\.)?[A-Z]\w*(?:Error|Exception|Failure|Exit|Interrupt|Warning)\b.*")
DETAIL_RX = re.compile(r"(?i)\b(?:found|expected|but|got|duplicate|missing|invalid|unknown|cannot|can't|not found|no such)\b")
SIGNAL_RX = re.compile(r"(?i)(?:^\s*(?:✗|✖|×|FAIL\b|FAILED\b|FAILURE\b|ERROR\b|E\s{2,}\S|npm (?:ERR!|error)\b|fatal:)"
                       r"|\b(?:error|failure|failed|denied|refused|exceeded|timed out)\b\s*[:!-]"
                       r"|:\d+(?::\d+)?:?\s+(?:error|fatal)\b|\bcommand not found\b|\bis too (?:long|short|large)\b)")
NOISE_RX = re.compile(r"^(?:Post job cleanup|Cleaning up orphan processes|Temporarily overriding HOME|Adding repository "
                      r"directory|Removing (?:SSH|HTTP|includeIf|credentials)|\[command\]|##\[(?:start|end)-action|Evaluate and set)")
SECRET_RX = re.compile(r"(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-ant-[A-Za-z0-9_-]{20,}"
                       r"|AKIA[0-9A-Z]{16}|(?i:bearer)\s+[A-Za-z0-9._-]{20,})")

# The AI analysis (§ 19.11, pr_ai_analysis.py) lives in this same comment: one block per
# failed run, keyed by (run id, attempt), inside one region under the summary. A rebuild
# carries the blocks of the runs that are still failing at the same attempt, so a run is
# analysed once; a fixed or re-run workflow drops its block.
AI_REGION_OPEN = "<!-- fleet:ai-analyses -->"
AI_REGION_CLOSE = "<!-- /fleet:ai-analyses -->"
AI_BLOCK_OPEN = "<!-- fleet:ai-analysis {} -->"
AI_BLOCK_CLOSE = "<!-- /fleet:ai-analysis -->"
AI_BLOCK_RX = re.compile(r"<!-- fleet:ai-analysis (\{[^\n]*?\}) -->\n.*?<!-- /fleet:ai-analysis -->", re.S)
MAX_AI_REGION = 18_000


class Gh:
    """`gh api`, as a list of arguments and never through a shell."""

    def __init__(self, repo: str):
        self.repo, self.calls = repo, 0

    def _run(self, *args: str, stdin: str | None = None) -> str:
        self.calls += 1
        p = subprocess.run(["gh", "api", *args], capture_output=True, text=True, input=stdin, errors="replace")
        if p.returncode:
            raise RuntimeError(f"gh api {args[0]}: {p.stderr.strip()[:200]}")
        return p.stdout

    def get(self, path: str):
        return json.loads(self._run(f"repos/{self.repo}/{path}") or "null")

    def text(self, path: str) -> str:
        """A job log. Logs carry colour codes, and `gh` refuses to print those
        without this flag, so a plain call returns nothing at all."""
        try:
            return self._run("--allow-escape-sequences", f"repos/{self.repo}/{path}")
        except RuntimeError as e:
            if "unknown flag" not in str(e):
                raise
            return self._run(f"repos/{self.repo}/{path}")

    def default_branch(self) -> str:
        return (json.loads(self._run(f"repos/{self.repo}") or "{}") or {}).get("default_branch") or "main"

    def post_comment(self, number: int, body: str) -> None:
        self._run("-X", "POST", f"repos/{self.repo}/issues/{number}/comments", "--input", "-", stdin=json.dumps({"body": body}))

    def edit_comment(self, cid: int, body: str) -> None:
        self._run("-X", "PATCH", f"repos/{self.repo}/issues/comments/{cid}", "--input", "-", stdin=json.dumps({"body": body}))

    def delete_comment(self, cid: int) -> None:
        self._run("-X", "DELETE", f"repos/{self.repo}/issues/comments/{cid}")

    def blob(self, path: str) -> bytes:
        """A binary download (an artifact's zip), held in memory, never written out."""
        self.calls += 1
        p = subprocess.run(["gh", "api", f"repos/{self.repo}/{path}"], capture_output=True)
        if p.returncode:
            raise RuntimeError(f"gh api {path}: {p.stderr.decode('utf-8', 'replace').strip()[:200]}")
        return p.stdout

    def post_review_comment(self, number: int, payload: dict) -> None:
        """One inline comment on the PR's diff. Never a review, so never an approval (§ 19.5)."""
        self._run("-X", "POST", f"repos/{self.repo}/pulls/{number}/comments", "--input", "-", stdin=json.dumps(payload))


# ------------------------------------------------------------------- untrusted text
def scrub(text: str) -> str:
    return SECRET_RX.sub("***", ANSI_RX.sub("", text))


def code_span(text: str, limit: int = MAX_LINE) -> str:
    """One line of untrusted text as inline code: no backtick can end the span."""
    one = " ".join(scrub(text).split()).replace("`", "'")
    return f"`{one[:limit]}`" if one else "`(no message)`"


def plain(text: str, limit: int = 120) -> str:
    """A workflow or job name: the PR can set it, so nothing in it renders."""
    out = " ".join(scrub(text).split())[:limit]
    return re.sub(r"([\\`*_{}\[\]<>()#|!~@])", r"\\\1", out)


def fence(lines: list[str]) -> str:
    body = "\n".join(scrub(line).replace("~~~", "~ ~ ~")[:MAX_LINE] for line in lines)
    return f"~~~text\n{body}\n~~~"


# ------------------------------------------------------------------- reading a log
def step_lines(log: str, step: dict | None) -> list[str]:
    """The log lines of the failed step, without timestamps or the script's echo."""
    start = str((step or {}).get("started_at") or "")[:19]
    end = str((step or {}).get("completed_at") or "")[:19]
    out = []
    for raw in log.splitlines():
        m = TS_RX.match(raw)
        stamp = m.group(1) if m else ""
        if stamp and start and end and not start <= stamp <= end:
            continue
        line = ANSI_RX.sub("", raw[m.end():] if m else raw).rstrip()
        # Timestamps only narrow to the second, and post-job steps start in the
        # same second the step failed. Nothing after this line is the step's.
        if out and line.startswith("Post job cleanup"):
            break
        if line and not SCRIPT_ECHO_RX.search(raw) and not NOISE_RX.match(line):
            out.append(line)
    return out


def _is_group_edge(line: str) -> bool:
    return line.startswith(("##[group]", "##[endgroup]"))


def focus(lines: list[str]) -> list[str]:
    """Narrow a long step to what failed. A runner that prints `##[error]X failed`
    right after a log group means that group is X's output, and the fixture
    output of the passing groups before it is noise."""
    for i, line in enumerate(lines):
        m = ERROR_RX.match(line)
        if not m or GENERIC_RX.match(line):
            continue
        j = i - 1
        while j >= 0 and lines[j].startswith("##[endgroup]"):
            j -= 1
        k = j
        while k >= 0 and not lines[k].startswith("##[group]"):
            k -= 1
        if j < i - 1 and k >= 0:
            return lines[k + 1:j + 1] + [line]
    return lines


def _traceback_block(lines: list[str]) -> list[str]:
    """The exception that ended the last traceback, with its message."""
    start = max((i for i, line in enumerate(lines) if TRACE_RX.match(line)), default=-1)
    if start < 0:
        return []
    i = start + 1
    while i < len(lines) and (lines[i].startswith((" ", "\t")) or not lines[i].strip()):
        i += 1
    block = []
    for line in lines[i:]:
        if block and (line.startswith(("✓", "✗", "##[", "To suppress")) or re.match(r"^\s*(ok|FAIL|PASS)\b", line)):
            break
        block.append(line)
        if len(block) >= MAX_EXCERPT_LINES:
            break
    return block


def explain(log: str, step: dict | None, annotations: list[str]) -> tuple[str, list[str]]:
    """(the reason in one line, the lines that show it). Never generic if the log
    says more: the exit code is the last resort."""
    lines = focus(step_lines(log, step))
    specific = [a for a in annotations if a.strip() and not GENERIC_RX.match(a.strip())]
    block = _traceback_block(lines)
    if block:
        detail = next((line for line in block[1:] if DETAIL_RX.search(line)), "")
        head = block[0]
        return (f"{head} {detail.strip()}".strip() if detail else head), block
    hits = [i for i, line in enumerate(lines) if SIGNAL_RX.search(line) and not GENERIC_RX.match(line)]
    if hits:
        first = hits[-1]
        while first > 0 and first - 1 in hits and hits[-1] - first < MAX_EXCERPT_LINES - 1:
            first -= 1
        excerpt = [line for line in lines[max(0, first - 2):hits[-1] + 3] if not _is_group_edge(line)]
        # The first line of the last run of errors: tools end a failure with a
        # pointer to a log file, and the cause is above it.
        reason = next((a for a in specific), None) or ERROR_RX.sub(r"\1", lines[first]).strip()
        return reason, excerpt[-MAX_EXCERPT_LINES:]
    if specific:
        return specific[0], [line for line in lines if not _is_group_edge(line)][-MAX_EXCERPT_LINES:]
    tail = [line for line in lines if not _is_group_edge(line) and not GENERIC_RX.match(line)]
    # Say so rather than dress up the last line as a cause.
    return ("The step printed no clear error. Its last output: " + tail[-1] if tail
            else "The step failed without printing anything."), tail[-MAX_EXCERPT_LINES:]


# ------------------------------------------------------------------- reading GitHub
def latest_runs(gh: Gh, sha: str) -> list[dict]:
    """The newest run of each workflow on a commit, leaving out this one."""
    runs = (gh.get(f"actions/runs?head_sha={sha}&per_page=100") or {}).get("workflow_runs") or []
    newest: dict = {}
    for r in sorted(runs, key=lambda r: (r.get("created_at") or "", r.get("run_attempt") or 0)):
        if r.get("event") == "dynamic" or r.get("name") == SELF_NAME:
            continue
        newest[r.get("workflow_id")] = r
    return list(newest.values())


def find_pr(gh: Gh, run: dict) -> tuple[int | None, str]:
    """(pull request number, the head that decides what is current). A push to a
    default branch maps to the PR that merged it, whose head is that commit."""
    sha = run["head_sha"]
    for ref in run.get("pull_requests") or []:
        if ref.get("number"):
            pr = gh.get(f"pulls/{ref['number']}") or {}
            return int(ref["number"]), str(((pr.get("head") or {}).get("sha")) or sha)
    pulls = gh.get(f"commits/{sha}/pulls") or []
    pulls = sorted(pulls, key=lambda p: (p.get("state") != "open", -int(p.get("number") or 0)))
    if pulls:
        p = pulls[0]
        return int(p["number"]), (str((p.get("head") or {}).get("sha") or sha) if p.get("state") == "open" else sha)
    return None, sha


def baseline(gh: Gh, run: dict, default_branch: str, jobs: list[str]) -> str:
    """Did this workflow also fail on the default branch? The answer to the first
    question anyone asks: is this my change?"""
    if run.get("event") not in PR_EVENTS or run.get("head_branch") == default_branch and not run.get("pull_requests"):
        return ""
    found = (gh.get(f"actions/workflows/{run['workflow_id']}/runs?branch={default_branch}&status=completed&per_page=20") or {})
    # `branch=main` also matches a PR whose head branch is named main, so read the event.
    last = next((r for r in found.get("workflow_runs") or []
                 if r.get("event") in ("push", "schedule") and r.get("conclusion") in ("success", *FAILED)), None)
    if not last:
        return f"Unknown: this workflow has no recent run on `{default_branch}` to compare."
    sha = str(last.get("head_sha") or "")[:7]
    if last.get("conclusion") == "success":
        return f"Probably yes: it passed on `{default_branch}` at `{sha}`."
    failed = {j.get("name") for j in (gh.get(f"actions/runs/{last['id']}/jobs?per_page=100") or {}).get("jobs") or []
              if j.get("conclusion") in FAILED}
    if failed & set(jobs):
        return f"Probably not: the same job also failed on `{default_branch}` at `{sha}`."
    return f"Unclear: this workflow also failed on `{default_branch}` at `{sha}`, but in a different job."


def describe_run(gh: Gh, run: dict, default_branch: str) -> dict:
    """One failed or held workflow run, as what the comment needs to say."""
    out = {"name": run.get("name") or "workflow", "url": run.get("html_url") or "", "jobs": [], "note": "", "this_pr": ""}
    if run.get("conclusion") in HELD:
        out["note"] = ("Held for approval. GitHub won't run workflows on a PR from `github-actions[bot]` until someone "
                       "with write access approves them. Approve the run, or open these PRs with a token so CI runs by itself.")
        return out
    jobs = (gh.get(f"actions/runs/{run['id']}/jobs?per_page=100") or {}).get("jobs") or []
    if not jobs:
        actor = (run.get("actor") or {}).get("login") or ""
        out["note"] = ("No job ran. GitHub held this run for a PR from `github-actions[bot]`, and it expired. Open these PRs "
                       "with a token so CI runs by itself." if actor == "github-actions[bot]" else
                       "No job ran, so GitHub refused the workflow before it started. The usual cause is a `uses:` reference "
                       "that doesn't exist at that ref, or invalid YAML. Open the run to see GitHub's message.")
        return out
    failed = [j for j in jobs if j.get("conclusion") in FAILED]
    details = []
    for job in failed[:MAX_JOBS]:
        step = next((s for s in job.get("steps") or [] if s.get("conclusion") in FAILED), None)
        notes = gh.get(f"check-runs/{job['id']}/annotations") or []
        messages = [str(n.get("message") or "") for n in notes if isinstance(n, dict) and n.get("annotation_level") == "failure"]
        try:
            log = gh.text(f"actions/jobs/{job['id']}/logs")
        except RuntimeError:
            log = ""
        reason, excerpt = explain(log, step, messages)
        found = atlas.classify_failure(["\n".join(f"##[error]{m}" for m in messages) + "\n" + log[-20000:]],
                                       run.get("conclusion"), (step or {}).get("name"))
        # `log_tail` is never rendered: pr_ai_analysis.py hands it to the model, so a log is downloaded once.
        details.append({"job": job.get("name") or "job", "url": job.get("html_url") or "", "step": (step or {}).get("name") or "",
                        "class": found["class"], "cause": found["cause"], "reason": reason, "excerpt": excerpt,
                        "log_tail": step_lines(log, step)[-LOG_TAIL_LINES:]})
    # A job that only reports its siblings failed says nothing the sibling doesn't.
    real = [d for d in details if not ROLLUP_RX.search(d["reason"])]
    out["jobs"] = real or details
    out["skipped_jobs"] = max(0, len(failed) - len(details))
    out["this_pr"] = baseline(gh, run, default_branch, [d["job"] for d in out["jobs"]])
    return out


# ------------------------------------------------------------------- findings (§ 19.3)
class BadArtifact(ValueError):
    """A findings artifact that breaks the contract. Nothing from it is posted."""


def finding_key(path: str, line: int, rule: str) -> str:
    """The dedupe key: the same (path, line, rule) is one finding on every push."""
    return hashlib.sha1(f"{path}:{line}:{rule}".encode("utf-8"), usedforsecurity=False).hexdigest()


def _utf8(text: str) -> bool:
    """False for a string UTF-8 cannot hold. JSON's `\\ud800` escape decodes to a
    lone surrogate, which would crash the job summary's UTF-8 write."""
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _valid_path(path) -> bool:
    if (not isinstance(path, str) or not 0 < len(path) <= 512 or not _utf8(path)
            or re.search(r"[\x00-\x1f\x7f\\]", path)):
        return False
    return not path.startswith("/") and all(part not in ("", ".", "..") for part in path.split("/"))


def validate_finding(item, where: str) -> dict:
    """One JSON line of the artifact, or BadArtifact. Exactly the contract's six
    keys: an unknown key is a contract this reader does not know."""
    if not isinstance(item, dict):
        raise BadArtifact(f"{where}: not a JSON object")
    if set(item) != FINDING_KEYS:
        raise BadArtifact(f"{where}: keys must be exactly {', '.join(sorted(FINDING_KEYS))}")
    line, message = item["line"], item["message"]
    if not _valid_path(item["path"]):
        raise BadArtifact(f"{where}: `path` must be a relative path inside the repository")
    if type(line) is not int or not 1 <= line <= 10_000_000:
        raise BadArtifact(f"{where}: `line` must be a positive integer")
    if not isinstance(item["rule"], str) or not _utf8(item["rule"]) or not RULE_ID_RX.fullmatch(item["rule"]):
        raise BadArtifact(f"{where}: `rule` must be an id of letters, digits and . _ : / -")
    if item["severity"] not in FINDING_SEVERITIES:
        raise BadArtifact(f"{where}: `severity` must be one of {', '.join(FINDING_SEVERITIES)}")
    if item["kind"] not in FINDING_KINDS:
        raise BadArtifact(f"{where}: `kind` must be one of {', '.join(FINDING_KINDS)}")
    if (not isinstance(message, str) or not message.strip() or len(message) > MAX_MESSAGE or "\x00" in message
            or not _utf8(message)):
        raise BadArtifact(f"{where}: `message` must be UTF-8 text of 1 to {MAX_MESSAGE} characters")
    return {k: item[k] for k in ("path", "line", "rule", "severity", "kind", "message")}


def parse_findings(data: bytes) -> list[dict]:
    """The findings in an artifact's zip, read in memory. Every `.jsonl` member is
    read; blank lines are allowed, anything else that is not a valid finding
    rejects the whole artifact."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
        members = [i for i in archive.infolist() if not i.is_dir() and i.filename.endswith(".jsonl")]
        if not members:
            raise BadArtifact("it holds no .jsonl file")
        if sum(i.file_size for i in members) > MAX_JSONL_BYTES:
            raise BadArtifact(f"its .jsonl files are over {MAX_JSONL_BYTES >> 20} MiB")
        out, total = [], 0
        for info in members:
            with archive.open(info) as fh:
                raw = fh.read(MAX_JSONL_BYTES + 1 - total)
            total += len(raw)
            if total > MAX_JSONL_BYTES:  # a header can lie about its size
                raise BadArtifact(f"its .jsonl files are over {MAX_JSONL_BYTES >> 20} MiB")
            name = Path(info.filename).name
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError as e:
                raise BadArtifact(f"{name} is not UTF-8") from e
            # Only "\n" ends a JSON line. str.splitlines() also splits on \x0c,
            # \x85 and U+2028, which may sit raw inside a JSON string.
            for n, line in enumerate(text.split("\n"), 1):
                if not line.strip():
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError as e:
                    raise BadArtifact(f"{name}:{n}: not JSON") from e
                except (ValueError, RecursionError) as e:
                    # An integer past Python's 4,300-digit limit, or nesting past the recursion limit.
                    raise BadArtifact(f"{name}:{n}: JSON this reader cannot hold ({type(e).__name__})") from e
                out.append(validate_finding(item, f"{name}:{n}"))
                if len(out) > MAX_FINDINGS:
                    raise BadArtifact(f"it holds more than {MAX_FINDINGS} findings")
        return out
    except BadArtifact:
        raise
    except (zipfile.BadZipFile, zipfile.LargeZipFile, NotImplementedError, RuntimeError, EOFError, OSError,
            ValueError, zlib.error, lzma.LZMAError) as e:
        # An encrypted member raises RuntimeError, an unknown compression
        # NotImplementedError, a truncated stream EOFError or zlib.error, and a
        # member name flagged UTF-8 that is not valid UTF-8 UnicodeDecodeError, a
        # ValueError. BadArtifact is a ValueError too, so it is re-raised above.
        raise BadArtifact(f"not a readable zip archive ({type(e).__name__})") from e


def added_lines(patch: str) -> set[int]:
    """The new-file line numbers a unified-diff patch adds."""
    out: set[int] = set()
    n = None
    # Git ends a diff line with "\n" only; str.splitlines() would also split an
    # added line holding a form feed, \x85 or U+2028 and shift every later number.
    for line in patch.split("\n"):
        m = HUNK_RX.match(line)
        if m:
            n = int(m.group(1))
        elif n is None or line.startswith(("-", "\\")):
            continue
        elif line.startswith("+"):
            out.add(n)
            n += 1
        else:
            n += 1
    return out


def _pages(gh: Gh, path: str) -> list:
    rows: list = []
    for page in range(1, MAX_PAGES + 1):
        got = gh.get(f"{path}{'&' if '?' in path else '?'}per_page=100&page={page}") or []
        rows += [r for r in got if isinstance(r, dict)] if isinstance(got, list) else []
        if not isinstance(got, list) or len(got) < 100:
            break
    return rows


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(name or "").lower()).strip("-")[:40] or "findings"


def finding_body(f: dict, trigger: str, self_url: str) -> str:
    """An inline comment: severity first, the message escaped, the dedupe key, and
    the § 19.4 signature last."""
    return "\n".join([
        f"**{SEVERITY_LABEL[f['severity']]}** · {code_span(f['rule'], 80)}", "",
        plain(f["message"], MAX_MESSAGE), "",
        f"<!-- fleet:finding key={finding_key(f['path'], f['line'], f['rule'])} -->",
        f"<!-- fleet:source={f['source']} trigger={trigger} run={self_url} -->"])


def findings_table(rows: list[dict], rejected: list[str]) -> str:
    """The job summary: every finding and what happened to it, so nothing a check
    reported is lost even when it is not posted."""
    parts = ["## Findings", ""]
    parts += [f"- Rejected: {r}. Nothing from it was posted." for r in rejected]
    if rows:
        parts += ["", "| Severity | Where | Rule | Source | What happened |", "| --- | --- | --- | --- | --- |"]
        for f in rows[:300]:
            # A pipe ends a table cell even inside a code span.
            where = code_span(f"{f['path']}:{f['line']}", 120).replace("|", "\\|")
            status = f["status"].replace("|", "\\|")
            parts.append(f"| {f['severity']} | {where} | {code_span(f['rule'], 80)} | {f['source']} | {status} |")
        if len(rows) > 300:
            parts.append(f"\n{len(rows) - 300} more finding(s) are not listed.")
    return "\n".join(parts) + "\n"


def review_findings(gh: Gh, number: int, head_sha: str, runs: list[dict], dry_run: bool,
                    trigger: str, self_url: str) -> dict:
    """Post the head commit's findings inline, once each. Every run's artifact is
    re-read on every review, because a queued review can be cancelled by a newer
    one in the same concurrency group; the keys make that idempotent. Returns
    the counts per severity of findings on the diff, and what it did."""
    names = {r.get("id"): r.get("name") or "workflow" for r in runs}
    listing = gh.get(f"actions/artifacts?name={FINDINGS_ARTIFACT}&per_page=100") or {}
    newest: dict = {}
    for a in (listing.get("artifacts") if isinstance(listing, dict) else None) or []:
        wr = (a.get("workflow_run") or {}) if isinstance(a, dict) else {}
        if (not isinstance(a, dict) or a.get("expired") or wr.get("head_sha") != head_sha
                or wr.get("id") not in names or a.get("name") != FINDINGS_ARTIFACT):
            continue
        if str(a.get("created_at") or "") >= str((newest.get(wr["id"]) or {}).get("created_at") or ""):
            newest[wr["id"]] = a
    if not newest:
        return {"counts": {}, "result": ""}
    rejected: list[str] = []
    found: dict[str, dict] = {}
    for rid, art in sorted(newest.items(), key=lambda kv: str(names[kv[0]]))[:MAX_ARTIFACTS]:
        source = _slug(names[rid])
        label = f"`{FINDINGS_ARTIFACT}` from {plain(names[rid])}"
        if int(art.get("size_in_bytes") or 0) > MAX_ARTIFACT_BYTES:
            rejected.append(f"{label} is over {MAX_ARTIFACT_BYTES >> 20} MiB")
            continue
        try:
            items = parse_findings(gh.blob(f"actions/artifacts/{int(art['id'])}/zip"))
        except BadArtifact as e:
            rejected.append(f"{label}: {code_span(str(e), 200)}")
            continue
        except RuntimeError as e:
            rejected.append(f"{label} could not be downloaded: {code_span(str(e), 200)}")
            continue
        for f in items:
            found.setdefault(finding_key(f["path"], f["line"], f["rule"]), {**f, "source": source})
    pr = gh.get(f"pulls/{number}") or {}
    author = str((pr.get("user") or {}).get("login") or "")
    skip = ("a Dependabot PR" if author == DEPENDABOT
            else "a release PR" if str((pr.get("head") or {}).get("ref") or "").startswith(RELEASE_REF) else "")
    rows = sorted(found.values(), key=lambda f: (FINDING_SEVERITIES.index(f["severity"]), f["path"], f["line"], f["rule"]))
    for f in rows:
        f["status"] = f"skipped: {f['kind']} check on {skip}" if skip and f["kind"] in SCOPED_KINDS else ""
    live = [f for f in rows if not f["status"]]
    diff: dict[str, set[int]] = {}
    if live:
        for row in _pages(gh, f"pulls/{number}/files"):
            diff[str(row.get("filename"))] = added_lines(str(row.get("patch") or ""))
    on_diff = []
    for f in live:
        if f["line"] in diff.get(f["path"], ()):
            on_diff.append(f)
        else:
            f["status"] = "not on a line this PR adds"
    posted_keys = set()
    if on_diff:
        for c in _pages(gh, f"pulls/{number}/comments"):
            if (c.get("user") or {}).get("type") == "Bot":
                posted_keys.update(FINDING_KEY_RX.findall(str(c.get("body") or "")))
    new = refused = 0   # refused: in a row, so one bad line never blocks the rest
    for f in on_diff:
        if finding_key(f["path"], f["line"], f["rule"]) in posted_keys:
            f["status"] = "already on the PR"
        elif new >= MAX_INLINE:
            f["status"] = f"waiting: over {MAX_INLINE} new comments in one review"
        elif refused >= MAX_REFUSED:
            # A locked conversation or a 403 refuses every comment: stop asking.
            f["status"] = f"waiting: GitHub refused {MAX_REFUSED} comments in a row"
        elif dry_run:
            new += 1
            f["status"] = "would post"
        else:
            payload = {"body": finding_body(f, trigger, self_url), "commit_id": head_sha,
                       "path": f["path"], "line": f["line"], "side": "RIGHT"}
            try:
                gh.post_review_comment(number, payload)
                new, refused = new + 1, 0
                f["status"] = "posted"
            except RuntimeError as e:
                refused += 1
                f["status"] = f"GitHub refused it: {code_span(str(e), 120)}"
    counts: dict[str, int] = {}
    for f in on_diff:
        counts[f["severity"]] = counts.get(f["severity"], 0) + 1
    table = findings_table(rows, rejected)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(table)
    verb = "would post" if dry_run else "posted"
    return {"counts": counts, "result": (f"findings: {len(rows)} read, {verb} {new} inline on #{number}, "
                                         f"{len(on_diff)} on the diff, {len(rejected)} artifact(s) rejected")}


def count_text(counts: dict) -> str:
    return ", ".join(f"{counts[s]} {s if counts[s] == 1 else s + 's'}" for s in FINDING_SEVERITIES if counts.get(s))


# ------------------------------------------------------------------- the AI region
def ai_blocks(comment: dict | None) -> dict[int, tuple[dict, str]]:
    """{run id: (its block's header, the block)} from the sticky. Only a comment a bot
    wrote is read: a person can post text that starts with the marker, and nothing they
    write may pass for an analysis or stop one from running."""
    if not comment or (comment.get("user") or {}).get("type") != "Bot":
        return {}
    out: dict[int, tuple[dict, str]] = {}
    for m in AI_BLOCK_RX.finditer(str(comment.get("body") or "")):
        try:
            head = json.loads(m.group(1))
            out[int(head["run"])] = (head, m.group(0))
        except (ValueError, KeyError, TypeError):
            continue
    return out


def carried(comment: dict | None, runs: list[dict]) -> list[str]:
    """The blocks a rebuild keeps: those of runs still failing, at the same attempt."""
    blocks = ai_blocks(comment)
    keep = []
    for r in runs:
        head, block = blocks.get(int(r.get("id") or 0), ({}, ""))
        if block and int(head.get("attempt") or 0) == int(r.get("run_attempt") or 1):
            keep.append(block)
    return keep


def ai_region(blocks: list[str], limit: int = MAX_AI_REGION) -> str:
    """The region, present (empty) whenever a run failed, so a later analysis has its
    place. A block that does not fit keeps its header, so its run is not analysed again."""
    if not blocks:
        return f"{AI_REGION_OPEN}\n{AI_REGION_CLOSE}"
    parts, used = [], 0
    for block in sorted(blocks, key=lambda b: b.split("\n", 2)[1] if b.count("\n") >= 1 else b):
        if used + len(block) > limit:
            lines = block.split("\n")
            block = "\n".join([lines[0], lines[1] if len(lines) > 2 else "", "",
                               "_This run's analysis did not fit in the comment: the analysis run's job summary has it._",
                               AI_BLOCK_CLOSE])
        parts.append(block)
        used += len(block)
    return "\n".join([AI_REGION_OPEN, "## AI analysis", "", "\n\n".join(parts), AI_REGION_CLOSE])


# ------------------------------------------------------------------- the comment
def render(sha: str, reports: list[dict], extra: int, state: dict, signature: str, findings: dict | None = None,
           ai: str = "") -> str:
    """The comment. Its footer always survives: without the state marker the next
    run would rewrite it, and § 19.4 requires the signature. The AI region sits
    between the summary and the footer, outside the summary's own size budget."""
    footer = f"<!-- fleet:pr-review-state {json.dumps(state, separators=(',', ':'))} -->\n{signature}"
    body = _body(sha, reports, extra, excerpts=True, findings=findings)
    if len(body) + len(footer) > MAX_BODY:
        body = (_body(sha, reports, extra, excerpts=False, findings=findings)
                + "\nLog excerpts are left out because this comment got too long.\n")
    region = (ai or ai_region([])) + "\n" if reports else ""
    return body[:MAX_BODY - len(footer) - 1] + "\n" + region + footer


def _body(sha: str, reports: list[dict], extra: int, excerpts: bool, findings: dict | None = None) -> str:
    failed = sum(1 for r in reports if r["jobs"] or "No job ran" in r["note"])
    held = len(reports) - failed
    title = f"CI failed on `{sha[:7]}`" if failed else f"CI is waiting for approval on `{sha[:7]}`"
    count = [f"{failed} workflow{'' if failed == 1 else 's'} failed"] if failed else []
    count += [f"{held} held for approval"] if held else []
    parts = [MARKER, f"## {title}", "", (", ".join(count) + ".").capitalize(), ""]
    if findings:
        parts += [f"**Findings on this commit's diff:** {count_text(findings)}, posted inline on the lines they name.", ""]
    for r in reports:
        name = f"[{plain(r['name'])}]({r['url']})" if r["url"] else plain(r["name"])
        if r["note"]:
            parts += [f"### {name}", "", r["note"], ""]
            continue
        for d in r["jobs"]:
            job = f"[{plain(d['job'])}]({d['url']})" if d["url"] else plain(d["job"])
            parts += [f"### {name} · {job}", "", f"**Why:** {code_span(d['reason'])}", ""]
            if d["step"]:
                parts += [f"- **Failed step:** {plain(d['step'])}"]
            parts += [f"- **Kind:** {CLASS_LABEL.get(d['class'], d['class'])}"]
            if r["this_pr"]:
                parts += [f"- **Caused by this PR?** {r['this_pr']}"]
            parts += [f"- **Next:** {NEXT_STEP.get(d['class'], 'Open the job log.')}", ""]
            if excerpts and d["excerpt"]:
                parts += ["<details><summary>Log excerpt</summary>", "", fence(d["excerpt"]), "", "</details>", ""]
        if r.get("skipped_jobs"):
            parts += [f"{r['skipped_jobs']} more failed job(s) in this workflow aren't shown here.", ""]
    if extra:
        parts += [f"{extra} more failed workflow(s) aren't shown here.", ""]
    return "\n".join(parts)


def sticky(gh: Gh, number: int) -> dict | None:
    page = 1
    while True:
        rows = gh.get(f"issues/{number}/comments?per_page=100&page={page}") or []
        for c in rows:
            if str(c.get("body") or "").startswith(MARKER):
                return c
        if len(rows) < 100:
            return None
        page += 1


def ai_review_of(gh: Gh, run: dict, dry_run: bool, trigger: str, self_url: str, say=print) -> str:
    """When the workflow that finished is the AI review (§ 19.7, pr-ai-review.yml), post the
    review it left as an artifact. It is posted from here because this pass is the one thing
    that writes on a pull request (§ 19.1), and after it so the review's findings are already
    on the diff. Any other run costs nothing: the test is on the run this pass already read."""
    if str(run.get("path") or "").split("@")[0] != AI_REVIEW_WORKFLOW or run.get("conclusion") != "success":
        return ""
    import pr_ai_review  # noqa: PLC0415 — it imports this module
    try:
        return pr_ai_review.post(gh, run, dry_run, trigger, self_url, say)
    except RuntimeError as e:
        # An API error: the CI-failure comment above is already written, and the review's
        # marker keeps a re-run of this pass from posting it twice.
        return f"AI review not posted: {scrub(str(e))[:160]}"


def qa_lead_of(gh: Gh, run: dict, dry_run: bool, trigger: str, self_url: str, say=print) -> str:
    """When the workflow that finished is QA Lead (§ 15.5, qa-lead.yml), post its review. QA Lead
    recomputes the review here from live GitHub with this branch's rules (qa_lead.post), so a pull
    request that edits its own copy of QA Lead cannot grade itself. Any other run costs nothing."""
    if str(run.get("path") or "").split("@")[0] != QA_LEAD_WORKFLOW:
        return ""
    import qa_lead  # noqa: PLC0415 — it imports this module
    try:
        return qa_lead.post(gh, run, dry_run, trigger, self_url, say)
    except RuntimeError as e:
        # An API error: the marker keeps a re-run of this pass from posting it twice.
        return f"QA Lead review not posted: {scrub(str(e))[:160]}"


def report(gh: Gh, run_id: str, dry_run: bool, trigger: str, self_url: str, say=print) -> str:
    """Bring the PR's comment in line with its head commit. Returns what it did."""
    run = gh.get(f"actions/runs/{run_id}") or {}
    return "; ".join(x for x in (_report(gh, run, dry_run, trigger, self_url, say),
                                 ai_review_of(gh, run, dry_run, trigger, self_url, say),
                                 qa_lead_of(gh, run, dry_run, trigger, self_url, say)) if x)


def _report(gh: Gh, run: dict, dry_run: bool, trigger: str, self_url: str, say) -> str:
    number, head = find_pr(gh, run)
    if not number:
        return "no pull request for this run"
    if run.get("event") in PR_EVENTS and head != run.get("head_sha"):
        return "a newer commit is on the PR; its own runs will report"
    runs = latest_runs(gh, run["head_sha"])
    # Findings belong to an open PR's diff; a push has no diff left to comment on.
    seen_findings = {"counts": {}, "result": ""}
    if run.get("event") in PR_EVENTS:
        try:
            seen_findings = review_findings(gh, number, run["head_sha"], runs, dry_run, trigger, self_url)
        except RuntimeError as e:
            # An API error here must not cost the PR its CI-failure summary; the
            # next review retries, and the keys keep a retry from double-posting.
            seen_findings = {"counts": {}, "result": f"findings not read: {str(e)[:160]}"}
    sticky_result = _sticky(gh, number, run, runs, dry_run, trigger, self_url, say, seen_findings["counts"])
    return "; ".join(x for x in (sticky_result, seen_findings["result"]) if x)


def _sticky(gh: Gh, number: int, run: dict, runs: list[dict], dry_run: bool, trigger: str, self_url: str,
            say, findings: dict) -> str:
    """The one summary comment: present while something fails, gone when nothing does."""
    bad = [r for r in runs if r.get("conclusion") in FAILED + HELD]
    current = sticky(gh, number)
    if not bad:
        if not current:
            return "nothing failing and no comment"
        if not dry_run:
            gh.delete_comment(int(current["id"]))
        return f"deleted the comment on #{number}: nothing is failing"
    state = {"sha": run["head_sha"], "runs": sorted([r["id"], r.get("run_attempt") or 1] for r in bad)}
    if findings:
        state["findings"] = {s: findings[s] for s in FINDING_SEVERITIES if findings.get(s)}
    seen = STATE_RX.search(str((current or {}).get("body") or ""))
    if seen and json.loads(seen.group(1)) == state:
        return "comment is already current"
    default_branch = gh.default_branch()
    bad.sort(key=lambda r: (r.get("conclusion") in HELD, r.get("name") or ""))
    reports = [describe_run(gh, r, default_branch) for r in bad[:MAX_RUNS]]
    signature = f"<!-- fleet:source=ci-failure trigger={trigger} run={self_url} -->"
    body = render(run["head_sha"], reports, len(bad) - len(reports), state, signature, findings,
                  ai=ai_region(carried(current, bad)))
    say(body)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(body + "\n")
    if dry_run:
        return f"dry run: would write to #{number} ({gh.calls} API calls)"
    if current:
        gh.edit_comment(int(current["id"]), body)
        return f"updated the comment on #{number} ({gh.calls} API calls)"
    gh.post_comment(number, body)
    return f"posted a comment on #{number} ({gh.calls} API calls)"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="The fleet's one PR comment (constitution § 19).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    ci = sub.add_parser("ci", help="summarize a commit's CI failures on its pull request and post its findings inline")
    ci.add_argument("--repo", required=True)
    ci.add_argument("--run", required=True, help="the workflow run that just finished")
    ci.add_argument("--dry-run", action="store_true", help="print the comment, write nothing")
    args = ap.parse_args(argv)
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", args.repo) or not args.run.isdigit():
        ap.error("--repo must be OWNER/NAME and --run a run id")
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    self_url = f"{server}/{args.repo}/actions/runs/{os.environ.get('GITHUB_RUN_ID', args.run)}"
    print(report(Gh(args.repo), args.run, args.dry_run, os.environ.get("GITHUB_EVENT_NAME", "manual"), self_url))
    return 0


if __name__ == "__main__":
    sys.exit(main())
