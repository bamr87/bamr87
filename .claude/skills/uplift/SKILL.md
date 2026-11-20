---
name: uplift
description: Find what one fleet repo improved that the others still lack, judge whether each change is general, and preview the hub issues that carry it to the rest of the fleet. Use when asked "what did the repos do that the hub should pick up", "what fixes should spread to the other repos", "capture improvements from <repo>", "which rollouts have not landed", or to run the uplift review.
---

# uplift

The hub's inbound arc ([docs/UPLIFT.md](../../../docs/UPLIFT.md)). `tools/dash uplift` does the observing with a byte comparison of file contents across the local checkouts: it reads no GitHub and calls no model. This skill is the judgment the comparison cannot make. You propose; the maintainer files.

## Steps

1. **Scan.** `tools/dash uplift scan` (add `--days N` for another window, `--repo <name>` for one repo's changes). Read the whole output, including NOT READ and STALE: a repo listed there is unknown, not quiet. Say so in your report.
2. **Read the work order.** `tools/dash uplift brief --top 5` (or `brief <key> …` for named candidates). It holds each candidate's origin, the repos behind, the route the contents imply, and the diff.
3. **Judge each candidate, in this order.**
   - *Is it general?* State the improvement without naming the repo it came from. If you cannot, it is specific to that repo (a tailored issue form, a filled-in placeholder): say so and stop. A specific change can still point at a kit defect, such as a seed that ships a placeholder; name that separately.
   - *Where does it belong?* Route `kit` means the hub seeded the file: the change is made once in `templates/<kit>/` and fanned out. Never patch the copies. Route `patch` means the hub owns no source: the same patch goes to each repo behind, or the file is adopted into a kit when three or more repos hold identical copies.
   - *Who gets it?* Start from the repos listed as behind. Drop or add one only with a reason you state.
   - *What proves it landed?* The next scan no longer lists the key.
4. **Read the features section.** For each feature a repo declared or shipped, ask whether a sibling of the same kind would want it. If so it is a roadmap entry, not a patch: propose it with `/future-features`.
5. **Read the rollouts in flight.** These are not candidates. Report each as deployment progress: which kit version, how many repos hold it, who is behind, and the fan-out that carries it (`fanout.yml` with that kit and `upgrade`, or `tools/fanout.sh --kit <kit> --target <name> --upgrade`, a dry run until `--apply`).
6. **Preview.** For the candidates you judged general: `tools/dash uplift file <key>` (at most three keys a run). It writes `.fleet/uplift/previews/<key>.md` and calls nothing. Show the maintainer each preview's path and your one-line judgment.
7. **Stop there.** `tools/dash uplift file <key> --apply` files the previewed bytes as a hub issue and is typed by the maintainer. Do not run it unless they tell you to in this session, for the keys they name.

## Report

For each candidate: the key, the file, the origin, how many repos are behind, your verdict (general, or specific and why), the route, and the preview path if you made one. Then the rollouts still in flight, then the features worth a roadmap entry, then what was not read.

## Rules

- Counts come from the scan. Do not estimate who is behind; the comparison is exact, so quote it.
- A private origin is never filed to the public hub; `file --apply` withholds it. Do not paste its diff into an issue, a pull request or a comment yourself.
- An issue for route `kit` has no `applies_to:` line. Do not add one: a kit change deploys through the kit.
