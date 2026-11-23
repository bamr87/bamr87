#!/usr/bin/env python3
"""pr_readiness — what is left before a pull request merges, in the fleet's one PR comment (ADR 0012).

pr_review.py keeps one sticky comment per pull request that explains its failed CI runs
(constitution § 19). This adds merge readiness to that same comment, and it is the entry
point `pr-review.yml` uses when `vars.PR_READINESS_ENABLED` is 'true':

  python3 pr_readiness.py ci --repo OWNER/NAME --run RUN_ID [--dry-run]    after a workflow finishes
  python3 pr_readiness.py ready --repo OWNER/NAME --pr N [--dry-run]       for a pull-request event

Under the failed runs the comment lists what is left: the PR queue's own reading of that
one pull request (tools/console/pr_queue.py `live_row`: checks, base, draft state, the
review gate and its label, the governance trace, the task list, review threads). The
comment stays while anything is left. When nothing is, it goes (§ 19.2) and one review per
head commit says the pull request is ready and who merges it. That review is a `COMMENT`:
it never approves (§ 19.5).

Everything about a failed run (which runs count, how one is explained, the sticky comment,
its state marker, how untrusted text is made safe) is pr_review.py's and is called here,
never copied. When the readiness read fails, this behaves exactly as pr_review.py does.
It holds a write token and reads text a pull request controls, so every item goes through
`pr_review.plain`. Nothing here runs anything from the pull request.

Doc: templates/pr-review/README.md, docs/adr/0012-merge-readiness.md.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pr_review as P  # noqa: E402

READY_MARKER = "<!-- fleet:pr-ready sha={sha} -->"
READY_RX = re.compile(r"<!-- fleet:pr-ready sha=([0-9a-f]{40}) -->")
VERDICT_TITLE = {"ready": "Ready to merge", "waiting": "Waiting", "not-ready": "Not ready to merge"}
ITEM_TITLE = {"todo": "To do", "wait": "Waiting", "held": "Held", "note": "Note", "done": "Done"}
WHO_TITLE = {"amr": "The maintainer", "agent": "An agent", "loop": "A loop", "author": "The author"}
MERGE_LINE = {"maintainer": "The maintainer merges it.", "agent": "An agent may merge it (§ 12.2)."}


class Gh(P.Gh):
    def reviews(self, number: int) -> list[dict]:
        rows = self.get(f"pulls/{number}/reviews?per_page=100")
        return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []

    def post_review(self, number: int, sha: str, body: str) -> None:
        """A review that comments and never approves (§ 19.5)."""
        self._run("-X", "POST", f"repos/{self.repo}/pulls/{number}/reviews", "--input", "-",
                  stdin=json.dumps({"event": "COMMENT", "commit_id": sha, "body": body}))


def live_readiness(repo: str, number: int) -> dict:
    """The PR queue's row for one pull request, read live. Imported here and not at the top: the queue
    lives in the hub's tools/, which a checkout of this directory alone does not hold."""
    hub = Path(__file__).resolve().parents[3]
    for extra in (hub, hub / "tools", hub / "tools" / "console"):
        if str(extra) not in sys.path:
            sys.path.insert(0, str(extra))
    import pr_queue  # noqa: PLC0415
    return pr_queue.live_row(repo, number, root=hub)


def _items(rd: dict, states: tuple[str, ...]) -> list[str]:
    """Item text comes from the pull request (a task's words, a file's path, a check's name): it is
    untrusted, so each cell goes through `plain`, which also keeps a `|` from ending the cell."""
    rows = [i for i in rd.get("items") or [] if i.get("state") in states]
    out = ["| | What | Who moves it |", "| --- | --- | --- |"] if rows else []
    for i in rows:
        who = WHO_TITLE.get(str(i.get("who")), "") if i["state"] in ("todo", "held") else ""
        out.append(f"| {ITEM_TITLE[i['state']]} | {P.plain(str(i.get('text') or ''), 300)} | {who} |")
    return out


def readiness_section(sha: str, rd: dict, after_failures: bool) -> str:
    """What is left, for the sticky comment. Shown only while something is left."""
    left = int(rd.get("left") or 0)
    title = VERDICT_TITLE.get(str(rd.get("verdict")), "Not ready to merge")
    head = "### Before this merges" if after_failures else f"## {title} on `{sha[:7]}`"
    count = f"{left} thing{'' if left == 1 else 's'} left." if left else "Nothing is left to do here; something is still running."
    parts = [head, "", count, ""] + _items(rd, ("todo", "wait", "held", "note"))
    done = _items(rd, ("done",))
    if done:
        parts += ["", f"<details><summary>Done ({len(done) - 2})</summary>", ""] + done + ["", "</details>"]
    merge = MERGE_LINE.get(str(rd.get("merge")))
    if merge:
        parts += ["", f"Once this is clear: {merge[0].lower() + merge[1:]}"]
    return "\n".join(parts) + "\n"


def ready_body(sha: str, rd: dict, signature: str) -> str:
    """The review a pull request gets once, on the head commit where nothing is left."""
    parts = [READY_MARKER.format(sha=sha), f"**Ready to merge at `{sha[:7]}`.** Everything the fleet checks before a merge is done. "
             "This is an automated readiness check: no code was reviewed.", ""]
    parts += _items(rd, ("held", "note", "done"))
    merge = MERGE_LINE.get(str(rd.get("merge")))
    if merge:
        parts += ["", f"**Merge:** {merge}"]
    return "\n".join(parts) + "\n" + signature


def ready_review(gh: Gh, number: int, sha: str, rd: dict, dry_run: bool, signature: str, say=print) -> str:
    for rv in gh.reviews(number):
        m = READY_RX.search(str(rv.get("body") or ""))
        if m and m.group(1) == sha:
            return f"#{number} already carries its readiness review for {sha[:7]}"
    body = ready_body(sha, rd, signature)
    say(body)
    if dry_run:
        return f"dry run: would post the readiness review on #{number}"
    gh.post_review(number, sha, body)
    return f"posted the readiness review on #{number}"


def _digest(rd: dict) -> str:
    seen = [[i.get("key"), i.get("state"), i.get("text")] for i in rd.get("items") or []]
    return hashlib.sha256(json.dumps([rd.get("verdict"), seen], sort_keys=True).encode()).hexdigest()[:12]


def render(sha: str, reports: list[dict], extra: int, state: dict, signature: str, section: str, ai: str = "") -> str:
    """pr_review's comment with the readiness section under it; with no failed run the section is the
    whole comment. The footer always survives, as in pr_review.render, and the AI region (§ 19.11)
    sits between the failed runs and the readiness section, outside their size budget."""
    footer = f"<!-- fleet:pr-review-state {json.dumps(state, separators=(',', ':'))} -->\n{signature}"
    tail = ("\n" + section) if section else ""
    if not reports:
        return (P.MARKER + tail)[:P.MAX_BODY - len(footer) - 1] + "\n" + footer
    region = ai or P.ai_region([])
    body = P._body(sha, reports, extra, excerpts=True) + tail
    if len(body) + len(footer) > P.MAX_BODY:
        body = P._body(sha, reports, extra, excerpts=False) + "\nLog excerpts are left out because this comment got too long.\n" + tail
    body = body[:P.MAX_BODY - len(footer) - 1]
    if tail and body.endswith(tail):
        return body[:-len(tail)] + "\n" + region + "\n\n" + tail.lstrip("\n") + "\n" + footer
    # No readiness section: exactly pr_review.render's comment.
    return body + "\n" + region + "\n" + footer


def sync(gh: Gh, number: int, sha: str, dry_run: bool, trigger: str, self_url: str, say=print, row_of=live_readiness) -> str:
    """One comment for one head commit: the failed runs explained, then what is left before the merge."""
    runs = P.latest_runs(gh, sha)
    bad = [r for r in runs if r.get("conclusion") in P.FAILED + P.HELD]
    current = P.sticky(gh, number)
    rd = None
    try:
        row = row_of(gh.repo, number)
        if row.get("head_sha") in (None, sha):
            rd = row.get("readiness")
    except Exception as exc:  # noqa: BLE001 — the failure summary must not depend on the readiness read
        say(f"::warning::merge readiness was not computed: {type(exc).__name__}: {P.scrub(str(exc))[:200]}")
    left = bool(rd and rd.get("verdict") != "ready")
    if not bad and not left:
        did = []
        if current:
            if not dry_run:
                gh.delete_comment(int(current["id"]))
            did.append(f"deleted the comment on #{number}: nothing is failing")
        if rd:
            did.append(ready_review(gh, number, sha, rd, dry_run,
                                    f"<!-- fleet:source=merge-readiness trigger={trigger} run={self_url} -->", say))
        return "; ".join(did) if did else "nothing failing and no comment"
    state = {"sha": sha, "runs": sorted([r["id"], r.get("run_attempt") or 1] for r in bad)}
    if rd:
        state["ready"] = _digest(rd)
    seen = P.STATE_RX.search(str((current or {}).get("body") or ""))
    if seen and json.loads(seen.group(1)) == state:
        return "comment is already current"
    default_branch = gh.default_branch() if bad else ""
    bad.sort(key=lambda r: (r.get("conclusion") in P.HELD, r.get("name") or ""))
    reports = [P.describe_run(gh, r, default_branch) for r in bad[:P.MAX_RUNS]]
    signature = f"<!-- fleet:source={'ci-failure' if bad else 'merge-readiness'} trigger={trigger} run={self_url} -->"
    body = render(sha, reports, len(bad) - len(reports), state, signature, readiness_section(sha, rd, bool(bad)) if left else "",
                  ai=P.ai_region(P.carried(current, bad)))
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


def report(gh: Gh, run_id: str, dry_run: bool, trigger: str, self_url: str, say=print, row_of=live_readiness) -> str:
    """After a workflow finishes: the pull request of that run, by pr_review's own rules for which run speaks."""
    run = gh.get(f"actions/runs/{run_id}") or {}
    number, head = P.find_pr(gh, run)
    if not number:
        return "no pull request for this run"
    if run.get("event") in P.PR_EVENTS and head != run.get("head_sha"):
        return "a newer commit is on the PR; its own runs will report"
    return sync(gh, number, run["head_sha"], dry_run, trigger, self_url, say, row_of)


def report_pr(gh: Gh, number: int, dry_run: bool, trigger: str, self_url: str, say=print, row_of=live_readiness) -> str:
    """For a pull-request event that starts no workflow of its own (marked ready, labelled, edited)."""
    pr = gh.get(f"pulls/{number}") or {}
    sha = str((pr.get("head") or {}).get("sha") or "")
    if pr.get("state") != "open" or not sha:
        return f"#{number} is not an open pull request"
    return sync(gh, number, sha, dry_run, trigger, self_url, say, row_of)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Merge readiness in the fleet's one PR comment (ADR 0012).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    ci = sub.add_parser("ci", help="a commit's CI failures and what is left before its pull request merges")
    ci.add_argument("--repo", required=True)
    ci.add_argument("--run", required=True, help="the workflow run that just finished")
    ci.add_argument("--dry-run", action="store_true", help="print the comment or the review, write nothing")
    rd = sub.add_parser("ready", help="the same for a pull-request event, by the pull request's number")
    rd.add_argument("--repo", required=True)
    rd.add_argument("--pr", required=True, help="the pull request's number")
    rd.add_argument("--dry-run", action="store_true", help="print the comment or the review, write nothing")
    args = ap.parse_args(argv)
    ident = args.run if args.cmd == "ci" else args.pr
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", args.repo) or not ident.isdigit():
        ap.error("--repo must be OWNER/NAME, and --run or --pr a number")
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    self_url = f"{server}/{args.repo}/actions/runs/{os.environ.get('GITHUB_RUN_ID', ident)}"
    trigger = os.environ.get("GITHUB_EVENT_NAME", "manual")
    gh = Gh(args.repo)
    print(report_pr(gh, int(args.pr), args.dry_run, trigger, self_url) if args.cmd == "ready"
          else report(gh, args.run, args.dry_run, trigger, self_url))
    return 0


if __name__ == "__main__":
    sys.exit(main())
