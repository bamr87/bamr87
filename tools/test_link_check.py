#!/usr/bin/env python3
"""
File: tools/test_link_check.py
Description: Offline tests for tools/link_check.py — what counts as a link
             (code, comments and placeholders do not), how a GitHub URL is
             read, the GraphQL batching against a fake API (missing repo,
             renamed repo, missing file / issue / workflow, rate limit), the
             HTTP classification (HEAD refused then GET, 404, robots, DNS),
             relative links resolved case-sensitively against tracked files,
             a live-site crawl from a sitemap against a fake fetcher, and the
             link-check.yml workflow's read-only, gated, declared shape.
Usage: python3 tools/test_link_check.py      (PyYAML only; no network)
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import link_check as lc  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CFG = {**lc.DEFAULTS, "owners": ["bamr87", "bash-365"], "hub_repo": "bamr87/bamr87"}


def urls(found):
    return [t for _, t, k in found if k == "url"]


def rels(found):
    return [t for _, t, k in found if k == "rel"]


class ExtractTests(unittest.TestCase):
    def test_code_comments_and_inline_code_are_not_links(self):
        text = "\n".join([
            "See [the docs](https://docs.example.org/a).",
            "```bash",
            "curl https://api.inside-a-fence.dev/x",
            "```",
            "Run `curl https://inline.code.dev/y` first.",
            "<!-- https://commented.out.dev/z -->",
            "~~~",
            "https://tilde.fence.dev/",
            "~~~",
            "Last: https://after.fences.dev/ok.",
        ])
        found = lc.extract(text, "md")
        self.assertEqual(urls(found), ["https://docs.example.org/a", "https://after.fences.dev/ok"])
        self.assertEqual([n for n, _, _ in found], [1, 10])

    def test_trailing_punctuation_and_balanced_parentheses(self):
        text = ("A (https://en.wikipedia.org/wiki/Foo_(bar)) and [x](https://a.dev/b), "
                "<https://c.dev/d>; https://e.dev/f. \"https://g.dev/h\" https://i.dev/j?q=1&amp;r=2")
        self.assertEqual(sorted(urls(lc.extract(text, "md"))), sorted([
            "https://en.wikipedia.org/wiki/Foo_(bar)", "https://a.dev/b", "https://c.dev/d",
            "https://e.dev/f", "https://g.dev/h", "https://i.dev/j?q=1&r=2",
        ]))

    def test_relative_file_links_only(self):
        text = "\n".join([
            "[a](docs/A.md) [b](../img/b.png \"title\") [c](#anchor) [d](/abs/path.md)",
            "[e](about/) [f](page.html) [g](https://x.dev/y.md) [h]({{ '/x.png' | relative_url }})",
            "[ref]: ./notes/ref.txt",
            '<img src="pics/c.svg"> <a href="mailto:a@b.c">m</a>',
        ])
        self.assertEqual(sorted(rels(lc.extract(text, "md"))),
                         ["../img/b.png", "./notes/ref.txt", "docs/A.md", "pics/c.svg"])

    def test_html_strips_script_and_pre(self):
        text = '<a href="https://ok.dev/">x</a>\n<script>fetch("https://api.script.dev/")</script>\n<pre>https://pre.dev/</pre>'
        self.assertEqual(urls(lc.extract(text, "html")), ["https://ok.dev/"])

    def test_yaml_reads_url_values_with_their_line(self):
        text = "- name: x\n  repo_url: https://github.com/bamr87/x\n  live_url: \"https://bamr87.github.io/x/\"  # site\n  description: see https://not.a.value.dev too\n"
        found = lc.extract(text, "yaml")
        self.assertEqual([(n, t) for n, t, _ in found],
                         [(2, "https://github.com/bamr87/x"), (3, "https://bamr87.github.io/x/")])


class SkipTests(unittest.TestCase):
    def test_placeholders_local_and_examples_are_skipped(self):
        cases = {
            "https://github.com/your-username/repo": "placeholder",
            "https://github.com/<owner>/<repo>": "placeholder",
            "https://{{ site.url }}/x": "placeholder",
            "http://localhost:4000/": "local",
            "http://127.0.0.1:8000/": "local",
            "http://192.168.1.5/": "local",
            "http://172.20.0.2/": "local",
            "http://app.test/": "local",
            "http://db/": "local",
            "https://example.com/x": "example",
            "https://api.example.org/": "example",
            "ftp://files.dev/": "not http",
        }
        for url, why in cases.items():
            self.assertEqual(lc.skip_reason(url, CFG), why, url)
        self.assertIsNone(lc.skip_reason("https://github.com/bamr87/README", CFG))
        self.assertEqual(lc.skip_reason("https://www.linkedin.com/in/x", {**CFG, "exclude_urls": [r"linkedin\.com"]}), "excluded")

    def test_url_key_folds_case_and_fragment(self):
        self.assertEqual(lc.url_key("HTTPS://Bamr87.GitHub.io/README/#top"), "https://bamr87.github.io/README/")
        self.assertEqual(lc.url_key("https://a.dev"), "https://a.dev/")


class GitHubParseTests(unittest.TestCase):
    def test_kinds(self):
        P = lc.parse_github
        self.assertEqual(P("https://github.com/bamr87"), lc.GhRef("bamr87", None))
        self.assertEqual(P("https://github.com/bamr87/zer0-demo-cookbook"), lc.GhRef("bamr87", "zer0-demo-cookbook"))
        self.assertEqual(P("https://github.com/bamr87/x.git"), lc.GhRef("bamr87", "x"))
        self.assertEqual(P("https://github.com/o/r/blob/main/docs/A.md").leaf,
                         ("obj", ("main:docs/A.md", "main/docs:A.md", "main/docs/A.md")))
        self.assertEqual(P("https://github.com/o/r/tree/main").leaf, ("obj", ("main",)))
        self.assertEqual(P("https://github.com/o/r/pull/12/files").leaf, ("issue", 12))
        self.assertEqual(P("https://github.com/o/r/issues/7").leaf, ("issue", 7))
        self.assertEqual(P("https://github.com/o/r/commit/abc123").leaf, ("obj", ("abc123",)))
        self.assertEqual(P("https://github.com/o/r/releases/tag/v1.0").leaf, ("release", "v1.0"))
        self.assertEqual(P("https://github.com/o/r/actions/workflows/ci.yml/badge.svg").leaf,
                         ("obj", ("HEAD:.github/workflows/ci.yml",)))
        self.assertEqual(P("https://github.com/o/r/blob/main/a%20b.md").leaf[1][0], "main:a b.md")
        self.assertIsNone(P("https://github.com/o/r/issues").leaf)
        self.assertIsNone(P("https://github.com/o/r/actions/runs/123").leaf)
        self.assertIsNone(P("https://github.com/sponsors/bamr87"))
        self.assertIsNone(P("https://github.com/user-attachments/assets/abc"))
        self.assertIsNone(P("https://gist.github.com/x/y"))
        self.assertIsNone(P("https://bamr87.github.io/README/"))
        raw = P("https://raw.githubusercontent.com/o/r/refs/heads/main/README.md")
        self.assertEqual((raw.owner, raw.repo, raw.leaf[1][0]), ("o", "r", "main:README.md"))


class FakeGitHub:
    """A GraphQL endpoint over a tiny world: which repos exist, with which
    files, issues and releases; renamed repos answer only over REST."""

    def __init__(self):
        self.repos = {
            "bamr87/readme": {"files": {"main:README.md", "HEAD:.github/workflows/ci.yml", "feature/x:a.md"},
                              "issues": {1, 2}, "releases": {"v1"}},
        }
        self.renamed = {"bamr87/old-name": "bamr87/new-name"}
        self.owners = {"bamr87"}
        self.queries = []
        self.limited = False

    def call(self, query):
        import re
        self.queries.append(query)
        data, errors = {}, []
        if self.limited:
            return {"data": None, "errors": [{"type": "RATE_LIMITED"}]}
        for alias, owner, name, body in re.findall(r'(r\d+): repository\(owner: "([^"]+)", name: "([^"]+)"\) \{ (.*?) \}(?= r\d+:| \}$)', query):
            repo = self.repos.get(f"{owner}/{name}".lower())
            if repo is None:
                data[alias] = None
                errors.append({"type": "NOT_FOUND", "path": [alias]})
                continue
            node = {"nameWithOwner": f"{owner}/{name}"}
            for leaf, expr in re.findall(r'(l\d+_\d+): object\(expression: "([^"]+)"\)', body):
                node[leaf] = {"__typename": "Blob"} if expr in repo["files"] else None
            for leaf, n in re.findall(r'(l\d+_\d+): issueOrPullRequest\(number: (\d+)\)', body):
                node[leaf] = {"__typename": "Issue"} if int(n) in repo["issues"] else None
            for leaf, tag in re.findall(r'(l\d+_\d+): release\(tagName: "([^"]+)"\)', body):
                node[leaf] = {"id": "R"} if tag in repo["releases"] else None
            data[alias] = node
        for alias, login in re.findall(r'(o\d+): repositoryOwner\(login: "([^"]+)"\)', query):
            data[alias] = {"login": login} if login in self.owners else None
        return {"data": data, "errors": errors}

    def rest(self, nwo):
        if nwo in self.renamed:
            return 200, self.renamed[nwo]
        return (200, nwo) if nwo in self.repos else (404, None)


class GitHubCheckerTests(unittest.TestCase):
    URLS = {
        "https://github.com/bamr87/README": "ok",
        "https://github.com/bamr87/README/blob/main/README.md": "ok",
        "https://github.com/bamr87/README/blob/main/NOPE.md": "broken",
        "https://github.com/bamr87/README/blob/feature/x/a.md": "ok",
        "https://github.com/bamr87/README/issues/2": "ok",
        "https://github.com/bamr87/README/pull/9": "broken",
        "https://github.com/bamr87/README/releases/tag/v1": "ok",
        "https://github.com/bamr87/README/releases/tag/v9": "broken",
        "https://github.com/bamr87/README/actions/workflows/ci.yml/badge.svg": "ok",
        "https://github.com/bamr87/README/actions/workflows/gone.yml": "broken",
        "https://github.com/bamr87/README/actions/runs/1": "ok",
        "https://github.com/bamr87/zer0-demo-cookbook": "broken",
        "https://github.com/bamr87/zer0-demo-cookbook/blob/main/x.md": "broken",
        "https://github.com/bamr87/old-name/blob/main/x.md": "moved",
        "https://github.com/bamr87": "ok",
        "https://github.com/nobody-zz9": "broken",
    }

    def run_checker(self, fake, batch=80):
        refs = {u: lc.parse_github(u) for u in self.URLS}
        return lc.GitHubChecker(fake.call, fake.rest, batch=batch).check(refs)

    def test_answers(self):
        out = self.run_checker(FakeGitHub())
        self.assertEqual({u: r.status for u, r in out.items()}, self.URLS)
        self.assertIn("not found", out["https://github.com/bamr87/zer0-demo-cookbook"].detail)
        self.assertIn("new-name", out["https://github.com/bamr87/old-name/blob/main/x.md"].detail)
        self.assertIn("gone.yml", out["https://github.com/bamr87/README/actions/workflows/gone.yml"].detail)

    def test_small_batches_give_the_same_answers(self):
        fake = FakeGitHub()
        out = self.run_checker(fake, batch=2)
        self.assertEqual({u: r.status for u, r in out.items()}, self.URLS)
        self.assertGreater(len(fake.queries), 3)

    def test_rate_limit_is_unverified_not_broken(self):
        fake = FakeGitHub()
        fake.limited = True
        fake.rest = lambda nwo: (403, None)
        out = self.run_checker(fake)
        self.assertEqual({r.status for r in out.values()}, {"unverified"})


class HttpTests(unittest.TestCase):
    def fetcher(self, table):
        calls = []

        def f(url, method, timeout, read=0):
            calls.append((method, url))
            return table[(method, url)] if (method, url) in table else table[url]
        return f, calls

    def test_head_refused_then_get(self):
        f, calls = self.fetcher({("HEAD", "https://a.dev/"): lc.Fetched(405), ("GET", "https://a.dev/"): lc.Fetched(200)})
        self.assertEqual(lc.check_http("https://a.dev/", lc.HostGate(2), 5, f).status, "ok")
        self.assertEqual([m for m, _ in calls], ["HEAD", "GET"])

    def test_classification(self):
        cases = [
            (lc.Fetched(404), "broken"), (lc.Fetched(410), "broken"), (lc.Fetched(999), "unverified"),
            (lc.Fetched(403), "unverified"), (lc.Fetched(429), "unverified"), (lc.Fetched(301), "ok"),
            (lc.Fetched(None, error="DNS: nx", dns=True), "broken"), (lc.Fetched(None, error="timeout"), "error"),
            (lc.Fetched(400), "error"), (lc.Fetched(503), "error"),
        ]
        for fetched, status in cases:
            self.assertEqual(lc.classify(fetched).status, status, fetched)

    def test_dns_failure_is_not_retried(self):
        f, calls = self.fetcher({"https://gone.dev/": lc.Fetched(None, error="DNS", dns=True)})
        self.assertEqual(lc.check_http("https://gone.dev/", lc.HostGate(2), 5, f).status, "broken")
        self.assertEqual(len(calls), 1)

    def test_interleave_spreads_hosts(self):
        urls = [f"https://big.dev/{i}" for i in range(4)] + ["https://a.dev/", "https://b.dev/"]
        order = [u.split("/")[2] for u in lc.interleave(urls)]
        self.assertEqual(order[:3], ["big.dev", "a.dev", "b.dev"])
        self.assertEqual(sorted(lc.interleave(urls)), sorted(urls))

    def test_host_limits_match_suffixes(self):
        gate = lc.HostGate(4, lc.HOST_LIMITS)
        self.assertEqual(gate.limit_for("bamr87.github.io"), 8)
        self.assertEqual(gate.limit_for("github.com"), 2)
        self.assertEqual(gate.limit_for("lifehacker.dev"), 4)


def git_repo(path: Path, files: dict[str, str]) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    for rel, body in files.items():
        (path / rel).parent.mkdir(parents=True, exist_ok=True)
        (path / rel).write_text(body)
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "add", "-A"], check=True)
    return path


class RepoScanTests(unittest.TestCase):
    def test_relative_links_resolve_case_sensitively_against_tracked_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = git_repo(Path(tmp) / "hub", {
                "README.md": "[ok](docs/Guide.md) [case](docs/guide.md) [gone](docs/Missing.md) [up](../out.md)\n"
                             "https://github.com/bamr87/x\n",
                "docs/Guide.md": "[back](../README.md) [img](img/a.png)\n",
                "docs/img/a.png": "x",
                "_reports/old.md": "https://expired.dev/run/1\n",
                "_data/portfolio.yml": "extra:\n  - repo_url: https://github.com/bamr87/gone\n",
            })
            cfg = {**CFG, "exclude_paths": ["bamr87:_reports/**"]}
            scan = lc.Scan()
            lc.scan_repos(scan, [lc.Repo("bamr87", "bamr87/bamr87", root)], cfg, lc.TrackedIndex())
            files = {k: r.status for k, r in scan.results.items() if k.startswith("file:")}
            self.assertEqual(files, {
                "file:bamr87:docs/Guide.md": "ok",
                "file:bamr87:docs/guide.md": "broken",
                "file:bamr87:docs/Missing.md": "broken",
                "file:bamr87:../out.md": "broken",
                "file:bamr87:README.md": "ok",
                "file:bamr87:docs/img/a.png": "ok",
            })
            self.assertIn("https://github.com/bamr87/x", scan.occurrences)
            self.assertIn("https://github.com/bamr87/gone", scan.occurrences)
            self.assertEqual(scan.occurrences["https://github.com/bamr87/gone"][0].label(), "_data/portfolio.yml:2")
            self.assertNotIn("https://expired.dev/run/1", scan.occurrences)

    def test_scoped_and_global_excludes(self):
        self.assertTrue(lc._excluded("README", "context/x/y.md", ["README:context/**"]))
        self.assertFalse(lc._excluded("it-journey", "context/x/y.md", ["README:context/**"]))
        self.assertTrue(lc._excluded("any", "a/node_modules/b.md", ["**/node_modules/**"]))
        self.assertTrue(lc._excluded("README", "docs/it-journey/a.md", ["README:docs/*/**"]))
        self.assertFalse(lc._excluded("README", "docs/index.md", ["README:docs/*/**"]))


class TargetTests(unittest.TestCase):
    def test_owned_checked_out_repos_and_live_sites(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = git_repo(Path(tmp) / "hub", {"README.md": "x\n"})
            git_repo(root / "projects" / "a", {"README.md": "a\n"})
            git_repo(root / "projects" / "ext", {"README.md": "e\n"})
            (root / "_data").mkdir()
            (root / "_data" / "projects.yml").write_text(yaml.safe_dump([
                {"name": "a", "repo_url": "https://github.com/bamr87/a", "submodule_path": "projects/a",
                 "live_url": "https://bamr87.github.io/a", "status": "active"},
                {"name": "ext", "repo_url": "https://github.com/microsoft/ext", "submodule_path": "projects/ext",
                 "live_url": "https://ext.dev/", "status": "active"},
                {"name": "old", "repo_url": "https://github.com/bamr87/old", "live_url": "https://old.dev/", "status": "archived"},
                {"name": "unchecked", "repo_url": "https://github.com/bamr87/unchecked", "submodule_path": "projects/unchecked",
                 "status": "active", "live_url": None},
            ]))
            (root / "_data" / "portfolio.yml").write_text(yaml.safe_dump({"extra": [
                {"name": "demo", "live_url": "https://bamr87.github.io/demo/"}]}))
            repos, sites = lc.targets(root, CFG)
            self.assertEqual([r.name for r in repos], ["bamr87", "a"])
            self.assertEqual([s.url for s in sites], ["https://bamr87.github.io/a", "https://bamr87.github.io/demo/"])
            repos, sites = lc.targets(root, CFG, ["demo"])
            self.assertEqual(([r.name for r in repos], [s.label for s in sites]), ([], ["demo"]))


class CrawlTests(unittest.TestCase):
    def test_sitemap_pages_and_their_links(self):
        site = "https://bamr87.github.io/demo/"
        pages = {
            site: '<a href="about/">About</a><img src="/demo/img/a.png"><a href="https://ext.dev/x">x</a>',
            site + "about/": '<a href="../missing/">gone</a><a href="mailto:a@b.c">m</a>',
        }
        sitemap = ("<urlset><url><loc>%s</loc></url><url><loc>%sabout/</loc></url>"
                   "<url><loc>https://other.host/p/</loc></url></urlset>" % (site, site)).encode()

        def fetcher(url, method, timeout, read=0):
            if url == site + "sitemap.xml":
                return lc.Fetched(200, url, sitemap, "application/xml")
            if url in pages:
                return lc.Fetched(200, url, pages[url].encode(), "text/html")
            return lc.Fetched(404, url)

        scan = lc.Scan()
        lc.crawl_site(scan, lc.Site(site, "demo"), {**CFG, "workers": 2}, lc.HostGate(2), fetcher)
        self.assertEqual(scan.pages, 2)
        self.assertEqual(scan.results[lc.url_key(site)].status, "ok")
        self.assertIn("https://bamr87.github.io/demo/missing/", scan.occurrences)
        self.assertIn("https://bamr87.github.io/demo/img/a.png", scan.occurrences)
        self.assertIn("https://ext.dev/x", scan.occurrences)
        occ = scan.occurrences["https://bamr87.github.io/demo/missing/"][0]
        self.assertEqual((occ.repo, occ.where), ("site bamr87.github.io/demo", site + "about/"))
        self.assertNotIn("https://other.host/p/", scan.occurrences)

    def test_a_dead_site_is_one_broken_link(self):
        scan = lc.Scan()
        lc.crawl_site(scan, lc.Site("https://bamr87.github.io/gone/", "gone"), CFG, lc.HostGate(2),
                      lambda url, method, timeout, read=0: lc.Fetched(404, url))
        self.assertEqual(scan.results["https://bamr87.github.io/gone/"].status, "broken")
        self.assertEqual(scan.pages, 0)


class ReportTests(unittest.TestCase):
    def test_problems_group_by_the_repo_that_publishes_them(self):
        scan = lc.Scan(repos=["bamr87", "README"])
        u = "https://github.com/bamr87/zer0-demo-cookbook"
        scan.occurrences[u] += [lc.Occurrence("bamr87", "README.md", 68), lc.Occurrence("bamr87", "_data/portfolio.yml", 130),
                                lc.Occurrence("README", "docs/index.md", 3)]
        scan.occurrences["https://ok.dev/"].append(lc.Occurrence("bamr87", "README.md", 1))
        scan.results[u] = lc.Result("broken", detail="repository bamr87/zer0-demo-cookbook not found", how="github")
        scan.results["https://ok.dev/"] = lc.Result("ok", 200)
        report = lc.summarize(scan)
        self.assertEqual(report["counts"]["broken"], 1)
        self.assertEqual(report["counts"]["ok"], 1)
        self.assertEqual(report["problems"]["bamr87"][0]["sources"], ["README.md:68", "_data/portfolio.yml:130"])
        text = lc.render_text(report)
        self.assertIn("✗ https://github.com/bamr87/zer0-demo-cookbook — repository bamr87/zer0-demo-cookbook not found", text)
        self.assertIn("README.md:68 · _data/portfolio.yml:130", text)
        md = lc.render_markdown(report)
        self.assertIn("### bamr87 (1)", md)


class ContractTests(unittest.TestCase):
    """The hub's own configuration and workflow follow the house rules."""

    def test_fleet_yml_links_block_loads(self):
        cfg = lc.load_config(ROOT)
        self.assertIn("bamr87:_reports/**", cfg["exclude_paths"])
        self.assertIn("_data/portfolio.yml", cfg["data_files"])
        for key in ("workers", "per_host", "timeout", "max_pages", "cache_hours", "github_batch"):
            self.assertIsInstance(cfg[key], int, key)

    def test_workflow_is_read_only_gated_and_declared(self):
        wf = ROOT / ".github" / "workflows" / "link-check.yml"
        doc = yaml.safe_load(wf.read_text())
        on = doc.get("on") or doc.get(True)
        cron = on["schedule"][0]["cron"]
        fleet = yaml.safe_load((ROOT / "_data" / "fleet.yml").read_text())
        self.assertEqual(fleet["schedule"]["link_check"], cron)
        self.assertNotEqual(cron.split()[0], "0")
        self.assertEqual(doc["permissions"], {"contents": "read"})
        text = wf.read_text()
        self.assertIn("vars.LINK_CHECK_ENABLED", text)
        self.assertIn("github.event_name != 'schedule'", text)
        self.assertNotIn("git push", text)
        self.assertIn("LINK_CHECK_ENABLED", yaml.safe_dump(fleet["switches"]))


if __name__ == "__main__":
    unittest.main(verbosity=1)
