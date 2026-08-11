#!/usr/bin/env python3
"""
Generates a plain-language release-notes markdown file from a dbt platform
manifest diff and the PRs merged between two commits.

Built around two explicit git SHAs — TARGET_SHA and BASELINE_SHA — rather
than "the latest run" or git tag ordering, to serve two real use cases:

  1. Environment promotion (the primary use case): when moving `uat` or
     `prd` onto a versioned release tag, diff that target commit against
     whatever commit is *currently* live in production. This answers "what
     will change from what's live today" for a uat move, and doubles as the
     official release notes when the same diff is run for the prd move onto
     that same commit later — no separate logic needed for either case.
  2. Ad hoc historical diffing: pass any two arbitrary commits (e.g. a
     January 1st release and today) to get a full summary of everything
     that changed between them — a "what did we ship this year" report.

Both cases reduce to the same operation: given two commit SHAs, find the
most recent successful dbt Cloud run that built each one (searched across
whichever job IDs are provided, since either commit may have first been
proven out via a UAT run, a PROD run, or another job entirely), diff their
manifests, and pull PR context between the two SHAs.

Flow:
  1. Resolve TARGET_SHA and BASELINE_SHA to their respective most recent
     successful dbt Cloud runs (search by git_sha, not by run id).
  2. Diff the two manifests for added / removed / modified models, seeds,
     and snapshots.
  3. For each changed node, walk child_map to find downstream exposures.
  4. Pull merged PR titles/descriptions between the two SHAs (GitHub API).
  5. Render plain-language markdown with format_digest() — no LLM call, no
     external AI vendor account required.

Delivery (where this markdown/PDF actually ends up for non-technical
readers) hasn't been decided yet, so write_output() writes to a local
`release-notes/` folder and the calling workflow uploads it as a
downloadable Action artifact (Markdown + PDF) pending that decision.
"""

import os
import sys
from pathlib import Path

import requests

DBT_HOST_URL = os.environ["DBT_HOST_URL"].rstrip("/")
DBT_API_TOKEN = os.environ["DBT_API_KEY"]
DBT_ACCOUNT_ID = os.environ["DBT_ACCOUNT_ID"]
DBT_JOB_IDS = [j.strip() for j in os.environ["DBT_JOB_IDS"].split(",") if j.strip()]

TARGET_SHA = os.environ["TARGET_SHA"]
BASELINE_SHA = os.environ.get("BASELINE_SHA") or None  # optional: omit for a first-release doc

GITHUB_REPOSITORY = os.environ.get("GITHUB_REPOSITORY")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")

OUTPUT_DIR = Path("release-notes")  # placeholder destination pending delivery decision

TRACKED_RESOURCE_TYPES = {"model", "seed", "snapshot"}

NO_EXPOSURES_NOTE = (
    "\n\n---\n\n_Note: this summary lists what changed but not which "
    "dashboards it affects — your dbt project doesn't have exposures "
    "declared yet. Adding them would let future releases group changes by "
    "the dashboard or report they impact._\n"
)

DBT_HEADERS = {"Authorization": f"Bearer {DBT_API_TOKEN}"}

RUN_SEARCH_PAGE_SIZE = 100
RUN_SEARCH_MAX_PAGES = 10  # up to ~1,000 runs per job — generous enough for a year+ of history


def find_run_by_sha(sha: str, job_ids: list[str]) -> dict:
    """Most recent successful run whose git_sha matches `sha`, searched across job_ids."""
    for job_id in job_ids:
        for page in range(RUN_SEARCH_MAX_PAGES):
            resp = requests.get(
                f"{DBT_HOST_URL}/api/v2/accounts/{DBT_ACCOUNT_ID}/runs/",
                headers=DBT_HEADERS,
                params={
                    "job_definition_id": job_id,
                    "status": 10,
                    "order_by": "-id",
                    "limit": RUN_SEARCH_PAGE_SIZE,
                    "offset": page * RUN_SEARCH_PAGE_SIZE,
                },
                timeout=30,
            )
            resp.raise_for_status()
            runs = resp.json()["data"]
            for run in runs:
                if run.get("git_sha") == sha:
                    return run
            if len(runs) < RUN_SEARCH_PAGE_SIZE:
                break
    raise RuntimeError(f"No successful run found for commit {sha} across job(s) {job_ids}")


def download_manifest(run_id) -> dict:
    url = f"{DBT_HOST_URL}/api/v2/accounts/{DBT_ACCOUNT_ID}/runs/{run_id}/artifacts/manifest.json"
    resp = requests.get(url, headers=DBT_HEADERS, timeout=60)
    resp.raise_for_status()
    return resp.json()


def downstream_exposures(unique_id: str, manifest: dict) -> list[dict]:
    """BFS from a node through child_map to find every exposure downstream of it."""
    child_map = manifest.get("child_map", {})
    exposures_by_id = manifest.get("exposures", {})
    found = []
    seen = set()
    queue = [unique_id]
    while queue:
        current = queue.pop(0)
        if current in seen:
            continue
        seen.add(current)
        for child in child_map.get(current, []):
            if child.startswith("exposure."):
                exp = exposures_by_id.get(child)
                if exp:
                    found.append(
                        {
                            "name": exp.get("name"),
                            "label": exp.get("label") or exp.get("name"),
                            "owner": (exp.get("owner") or {}).get("name"),
                            "url": exp.get("url"),
                        }
                    )
            else:
                queue.append(child)
    return found


def summarize_node(uid: str, node: dict, manifest: dict, prev_node: dict | None = None) -> dict:
    prev_cols = set((prev_node or {}).get("columns", {}))
    curr_cols = set(node.get("columns", {}))
    return {
        "unique_id": uid,
        "name": node.get("name"),
        "resource_type": node.get("resource_type"),
        "description": node.get("description") or "",
        "columns_added": sorted(curr_cols - prev_cols),
        "columns_removed": sorted(prev_cols - curr_cols),
        "downstream_exposures": downstream_exposures(uid, manifest),
    }


def node_changed(prev_node: dict, curr_node: dict) -> bool:
    if prev_node.get("raw_code") != curr_node.get("raw_code"):
        return True
    if prev_node.get("description") != curr_node.get("description"):
        return True
    prev_cols = {c: v.get("description") for c, v in prev_node.get("columns", {}).items()}
    curr_cols = {c: v.get("description") for c, v in curr_node.get("columns", {}).items()}
    return prev_cols != curr_cols


def diff_manifests(previous: dict | None, current: dict) -> dict:
    prev_nodes = (previous or {}).get("nodes", {})
    curr_nodes = current.get("nodes", {})

    prev_ids = {uid for uid, n in prev_nodes.items() if n["resource_type"] in TRACKED_RESOURCE_TYPES}
    curr_ids = {uid for uid, n in curr_nodes.items() if n["resource_type"] in TRACKED_RESOURCE_TYPES}

    changes = {"added": [], "removed": [], "modified": []}

    for uid in curr_ids - prev_ids:
        changes["added"].append(summarize_node(uid, curr_nodes[uid], current))

    for uid in prev_ids - curr_ids:
        changes["removed"].append(summarize_node(uid, prev_nodes[uid], previous))

    for uid in curr_ids & prev_ids:
        if node_changed(prev_nodes[uid], curr_nodes[uid]):
            changes["modified"].append(
                summarize_node(uid, curr_nodes[uid], current, prev_node=prev_nodes[uid])
            )

    return changes


def get_merged_prs(previous_sha: str | None, current_sha: str | None) -> list[dict]:
    """Titles/descriptions of PRs associated with commits between two git_sha values."""
    if not (GITHUB_REPOSITORY and GITHUB_TOKEN and previous_sha and current_sha):
        return []

    headers = {"Authorization": f"Bearer {GITHUB_TOKEN}", "Accept": "application/vnd.github+json"}
    compare_url = f"https://api.github.com/repos/{GITHUB_REPOSITORY}/compare/{previous_sha}...{current_sha}"
    resp = requests.get(compare_url, headers=headers, timeout=30)
    resp.raise_for_status()
    commits = resp.json().get("commits", [])

    prs_by_number = {}
    for commit in commits:
        pr_url = f"https://api.github.com/repos/{GITHUB_REPOSITORY}/commits/{commit['sha']}/pulls"
        pr_resp = requests.get(pr_url, headers=headers, timeout=30)
        if pr_resp.status_code != 200:
            continue
        for pr in pr_resp.json():
            prs_by_number[pr["number"]] = {"title": pr["title"], "body": pr.get("body") or ""}

    return list(prs_by_number.values())


CHANGE_VERBS = {"added": "New", "removed": "Removed", "modified": "Updated"}


def describe_change_line(item: dict, change_type: str) -> str:
    name = item.get("name", "unknown")
    description = (item.get("description") or "").strip()
    line = f"- **{CHANGE_VERBS[change_type]}: `{name}`**"
    if description:
        line += f" — {description}"
    for cols, label in ((item.get("columns_added"), "New columns"), (item.get("columns_removed"), "Removed columns")):
        if cols:
            line += f"\n  - {label}: {', '.join(cols)}"
    return line


def format_digest(digest: dict) -> str:
    """Turn the manifest-diff digest into plain-language markdown without calling an LLM."""
    entries = [
        (item, change_type)
        for change_type in ("added", "removed", "modified")
        for item in digest["changes"].get(change_type, [])
    ]

    by_exposure: dict[str, list[tuple[dict, str, dict]]] = {}
    no_exposure: list[tuple[dict, str]] = []
    for item, change_type in entries:
        exposures = item.get("downstream_exposures") or []
        if exposures:
            for exp in exposures:
                label = exp.get("label") or exp.get("name") or "Unnamed report"
                by_exposure.setdefault(label, []).append((item, change_type, exp))
        else:
            no_exposure.append((item, change_type))

    lines = [f"# What Changed — {digest['target_label']}", ""]
    if digest.get("baseline_label"):
        lines.append(f"_Comparing against baseline `{digest['baseline_label']}`._")
        lines.append("")

    if by_exposure:
        lines.append("## Dashboards & reports affected")
        lines.append("")
        for label in sorted(by_exposure):
            group = by_exposure[label]
            lines.append(f"### {label}")
            owner = group[0][2].get("owner")
            if owner:
                lines.append(f"_Owner: {owner}_")
            lines.append("")
            for item, change_type, _exp in group:
                lines.append(describe_change_line(item, change_type))
            lines.append("")

    if no_exposure:
        lines.append("## Behind the scenes")
        lines.append("_These changes aren't linked to a tracked dashboard or report._")
        lines.append("")
        for item, change_type in no_exposure:
            lines.append(describe_change_line(item, change_type))
        lines.append("")

    if digest.get("pull_requests"):
        lines.append("## Why these changes were made")
        lines.append("")
        for pr in digest["pull_requests"]:
            title = pr.get("title", "").strip()
            first_line = (pr.get("body") or "").strip().splitlines()
            first_line = first_line[0].strip() if first_line else ""
            lines.append(f"- **{title}** — {first_line}" if first_line else f"- **{title}**")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def write_output(label: str, markdown: str) -> Path:
    """Placeholder delivery: writes locally; the calling workflow uploads this as an Action artifact."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"{label}.md"
    out_path.write_text(markdown)
    return out_path


def main() -> None:
    target_run = find_run_by_sha(TARGET_SHA, DBT_JOB_IDS)
    target_manifest = download_manifest(target_run["id"])
    target_label = TARGET_SHA[:7]

    if not BASELINE_SHA:
        write_output(
            target_label,
            f"# What Changed — {target_label}\n\n"
            "_This is the first tracked release — there's no baseline to "
            "compare against. Future releases will include a full summary "
            "of what changed._\n",
        )
        return

    baseline_run = find_run_by_sha(BASELINE_SHA, DBT_JOB_IDS)
    baseline_manifest = download_manifest(baseline_run["id"])
    baseline_label = BASELINE_SHA[:7]

    changes = diff_manifests(baseline_manifest, target_manifest)

    if not (changes["added"] or changes["removed"] or changes["modified"]):
        write_output(
            target_label,
            f"# What Changed — {target_label}\n\n_No data-affecting changes since `{baseline_label}`._\n",
        )
        return

    pull_requests = get_merged_prs(BASELINE_SHA, TARGET_SHA)

    digest = {
        "target_label": target_label,
        "baseline_label": baseline_label,
        "changes": changes,
        "pull_requests": pull_requests,
    }

    markdown = format_digest(digest)
    if not target_manifest.get("exposures"):
        markdown += NO_EXPOSURES_NOTE

    out_path = write_output(target_label, markdown)
    print(f"Wrote {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
