#!/usr/bin/env python3
"""
Generates a plain-language release-notes markdown file from a dbt platform
manifest diff and the PRs merged since the previous production release.

Adapted to fit the client's actual deploy pipeline (EDS-SNOWFLAKE-ACTIONS):
  - Their `_dbt-cd.yml` triggers on push to `main` and on the `uat`/`prd`
    tags, which are mutable (force-moved onto a versioned release tag by
    `_move-environment.yml`). There's no growing series of immutable release
    tags to diff against, so "current" and "previous" production releases
    are identified by run/commit, not by git tag ordering.
  - Their CD pipeline requests `contents: read` only and never commits
    anything back to the repo, so there's no committed manifest snapshot to
    diff against either. Both manifests are always fetched fresh from the
    Admin API.

Flow:
  1. Fetch the manifest for CURRENT_RUN_ID (the run that `dbt_cloud_deploy`
     just completed — pinned explicitly so this never re-queries "latest"
     and risks a race with a run that started after it).
  2. Find the most recent other successful run of the same job and fetch
     its manifest as the "previous release" baseline.
  3. Diff the two manifests for added/removed/modified models, seeds, and
     snapshots.
  4. For each changed node, walk child_map to find downstream exposures.
  5. Pull merged PR titles/descriptions between the two runs' git_sha
     values (GitHub compare API) for the "why".
  6. Render plain-language markdown with format_digest() — no LLM call.

Delivery (where this markdown actually ends up — a GitHub Release, a repo
file, somewhere else entirely) hasn't been decided yet, so write_output()
is a placeholder that writes to a local `release-notes/` folder pending
that decision.
"""

import os
import sys
from pathlib import Path

import requests

DBT_HOST_URL = os.environ["DBT_HOST_URL"].rstrip("/")
DBT_API_KEY = os.environ["DBT_API_KEY"]
DBT_ACCOUNT_ID = os.environ["DBT_ACCOUNT_ID"]
DBT_PROD_JOB_ID = os.environ["DBT_PROD_JOB_ID"]
CURRENT_RUN_ID = os.environ["CURRENT_RUN_ID"]  # run_id output of the dbt_cloud_deploy job that just ran

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

DBT_HEADERS = {"Authorization": f"Bearer {DBT_API_KEY}"}


def get_run(run_id) -> dict:
    url = f"{DBT_HOST_URL}/api/v2/accounts/{DBT_ACCOUNT_ID}/runs/{run_id}/"
    resp = requests.get(url, headers=DBT_HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.json()["data"]


def get_previous_successful_run(exclude_run_id) -> dict | None:
    """Most recent successful run of DBT_PROD_JOB_ID other than exclude_run_id."""
    url = f"{DBT_HOST_URL}/api/v2/accounts/{DBT_ACCOUNT_ID}/runs/"
    resp = requests.get(
        url,
        headers=DBT_HEADERS,
        params={"job_definition_id": DBT_PROD_JOB_ID, "status": 10, "order_by": "-id", "limit": 5},
        timeout=30,
    )
    resp.raise_for_status()
    for run in resp.json()["data"]:
        if str(run["id"]) != str(exclude_run_id):
            return run
    return None


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
    """Titles/descriptions of PRs associated with commits between two production git_sha values."""
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

    lines = [f"# What Changed — {digest['release_label']}", ""]
    if digest.get("previous_release_label"):
        lines.append(f"_Comparing against the previous production release, `{digest['previous_release_label']}`._")
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
    """Placeholder delivery: writes locally pending a decision on where this actually needs to land."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"{label}.md"
    out_path.write_text(markdown)
    return out_path


def main() -> None:
    current_run = get_run(CURRENT_RUN_ID)
    current_manifest = download_manifest(current_run["id"])
    current_sha = current_run.get("git_sha")
    current_label = current_sha[:7] if current_sha else f"run-{current_run['id']}"

    previous_run = get_previous_successful_run(exclude_run_id=current_run["id"])

    if previous_run is None:
        write_output(
            current_label,
            f"# What Changed — {current_label}\n\n"
            "_This is the first tracked production release — there's no "
            "prior run to compare against. Future releases will include a "
            "full summary of what changed._\n",
        )
        return

    previous_manifest = download_manifest(previous_run["id"])
    previous_sha = previous_run.get("git_sha")
    previous_label = previous_sha[:7] if previous_sha else f"run-{previous_run['id']}"

    changes = diff_manifests(previous_manifest, current_manifest)

    if not (changes["added"] or changes["removed"] or changes["modified"]):
        write_output(
            current_label,
            f"# What Changed — {current_label}\n\n_No data-affecting changes since the last release._\n",
        )
        return

    pull_requests = get_merged_prs(previous_sha, current_sha)

    digest = {
        "release_label": current_label,
        "previous_release_label": previous_label,
        "changes": changes,
        "pull_requests": pull_requests,
    }

    markdown = format_digest(digest)
    if not current_manifest.get("exposures"):
        markdown += NO_EXPOSURES_NOTE

    out_path = write_output(current_label, markdown)
    print(f"Wrote {out_path} (placeholder location pending delivery decision)", file=sys.stderr)


if __name__ == "__main__":
    main()
