#!/usr/bin/env python3
"""pr_review — the fleet's one PR comment (constitution § 19).

Every CI failure on a pull request is summarized in one sticky comment, so a
reader learns why a check failed without opening a log. The comment is rebuilt
from the state of the PR's head commit each time a workflow finishes, so it
always says what is true now, and it is deleted when nothing is failing.

  python3 pr_review.py ci --repo OWNER/NAME --run RUN_ID            post or update
  python3 pr_review.py ci --repo OWNER/NAME --run RUN_ID --dry-run  print, write nothing

Called by .github/workflows/pr-review.yml (a `workflow_run` of every workflow).
Doc: templates/pr-review/README.md.

The logs it reads come from pull requests on public repositories and it holds a
write token, so every string that reaches the comment is treated as untrusted:
it goes through a code fence or a code span, never into a shell. Nothing here
runs anything from the pull request.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import workflow_atlas as atlas  # noqa: E402  classify_failure, the fleet's failure classes

MARKER = "<!-- fleet:pr-review -->"
STATE_RX = re.compile(r"<!-- fleet:pr-review-state (\{.*?\}) -->")
SELF_NAME = "PR review"
PR_EVENTS = ("pull_request", "pull_request_target")
FAILED = ("failure", "timed_out", "startup_failure")
HELD = ("action_required",)
MAX_RUNS = 6            # failed workflows detailed in one comment
MAX_JOBS = 4            # failed jobs detailed per workflow
MAX_EXCERPT_LINES = 14
MAX_LINE = 220
MAX_BODY = 30_000       # GitHub's limit is 65,536

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
        details.append({"job": job.get("name") or "job", "url": job.get("html_url") or "", "step": (step or {}).get("name") or "",
                        "class": found["class"], "cause": found["cause"], "reason": reason, "excerpt": excerpt})
    # A job that only reports its siblings failed says nothing the sibling doesn't.
    real = [d for d in details if not ROLLUP_RX.search(d["reason"])]
    out["jobs"] = real or details
    out["skipped_jobs"] = max(0, len(failed) - len(details))
    out["this_pr"] = baseline(gh, run, default_branch, [d["job"] for d in out["jobs"]])
    return out


# ------------------------------------------------------------------- the comment
def render(sha: str, reports: list[dict], extra: int, state: dict, signature: str) -> str:
    """The comment. Its footer always survives: without the state marker the next
    run would rewrite it, and § 19.4 requires the signature."""
    footer = f"<!-- fleet:pr-review-state {json.dumps(state, separators=(',', ':'))} -->\n{signature}"
    body = _body(sha, reports, extra, excerpts=True)
    if len(body) + len(footer) > MAX_BODY:
        body = _body(sha, reports, extra, excerpts=False) + "\nLog excerpts are left out because this comment got too long.\n"
    return body[:MAX_BODY - len(footer) - 1] + "\n" + footer


def _body(sha: str, reports: list[dict], extra: int, excerpts: bool) -> str:
    failed = sum(1 for r in reports if r["jobs"] or "No job ran" in r["note"])
    held = len(reports) - failed
    title = f"CI failed on `{sha[:7]}`" if failed else f"CI is waiting for approval on `{sha[:7]}`"
    count = [f"{failed} workflow{'' if failed == 1 else 's'} failed"] if failed else []
    count += [f"{held} held for approval"] if held else []
    parts = [MARKER, f"## {title}", "", (", ".join(count) + ".").capitalize(), ""]
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


def report(gh: Gh, run_id: str, dry_run: bool, trigger: str, self_url: str, say=print) -> str:
    """Bring the PR's comment in line with its head commit. Returns what it did."""
    run = gh.get(f"actions/runs/{run_id}") or {}
    number, head = find_pr(gh, run)
    if not number:
        return "no pull request for this run"
    if run.get("event") in PR_EVENTS and head != run.get("head_sha"):
        return "a newer commit is on the PR; its own runs will report"
    runs = latest_runs(gh, run["head_sha"])
    bad = [r for r in runs if r.get("conclusion") in FAILED + HELD]
    current = sticky(gh, number)
    if not bad:
        if not current:
            return "nothing failing and no comment"
        if not dry_run:
            gh.delete_comment(int(current["id"]))
        return f"deleted the comment on #{number}: nothing is failing"
    state = {"sha": run["head_sha"], "runs": sorted([r["id"], r.get("run_attempt") or 1] for r in bad)}
    seen = STATE_RX.search(str((current or {}).get("body") or ""))
    if seen and json.loads(seen.group(1)) == state:
        return "comment is already current"
    default_branch = gh.default_branch()
    bad.sort(key=lambda r: (r.get("conclusion") in HELD, r.get("name") or ""))
    reports = [describe_run(gh, r, default_branch) for r in bad[:MAX_RUNS]]
    signature = f"<!-- fleet:source=ci-failure trigger={trigger} run={self_url} -->"
    body = render(run["head_sha"], reports, len(bad) - len(reports), state, signature)
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
    ci = sub.add_parser("ci", help="summarize a commit's CI failures on its pull request")
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
