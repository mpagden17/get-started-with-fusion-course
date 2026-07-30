#!/usr/bin/env python3
"""
Generates a plain-language release-notes markdown file from a dbt platform
manifest diff and the PRs merged since the previous release tag.

Flow:
  1. Fetch manifest.json from the latest successful run of the production
     dbt platform job (Admin API).
  2. Diff it against the manifest committed at the previous release tag.
  3. For each changed node, walk child_map to find downstream exposures.
  4. Pull merged PR titles/descriptions between the two tags (GitHub API).
  5. Send the digest to Claude with prompt_template.md and write the result
     to release-notes/, committed back to the repo by the Action.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import requests

DBT_HOST_URL = os.environ["DBT_HOST_URL"].rstrip("/")
DBT_API_KEY = os.environ["DBT_API_KEY"]
DBT_ACCOUNT_ID = os.environ["DBT_ACCOUNT_ID"]
DBT_PROD_JOB_ID = os.environ["DBT_PROD_JOB_ID"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]

GITHUB_REPOSITORY = os.environ.get("GITHUB_REPOSITORY")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
RELEASE_TAG = os.environ.get("RELEASE_TAG", "untagged")
PREVIOUS_TAG = os.environ.get("PREVIOUS_TAG") or None

CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5")

MANIFEST_PATH = Path("dbt_artifacts/manifest_latest.json")
OUTPUT_DIR = Path("release-notes")
PROMPT_TEMPLATE_PATH = Path(__file__).parent / "prompt_template.md"

TRACKED_RESOURCE_TYPES = {"model", "seed", "snapshot"}

NO_EXPOSURES_NOTE = (
    "\n\n---\n\n_Note: this summary lists what changed but not which "
    "dashboards it affects — your dbt project doesn't have exposures "
    "declared yet. Adding them would let future releases group changes by "
    "the dashboard or report they impact._\n"
)

DBT_HEADERS = {"Authorization": f"Bearer {DBT_API_KEY}"}


def get_latest_successful_run_id() -> int:
    url = f"{DBT_HOST_URL}/api/v2/accounts/{DBT_ACCOUNT_ID}/jobs/{DBT_PROD_JOB_ID}/runs/"
    resp = requests.get(
        url, headers=DBT_HEADERS, params={"status": 10, "order_by": "-id", "limit": 1}, timeout=30
    )
    resp.raise_for_status()
    runs = resp.json()["data"]
    if not runs:
        raise RuntimeError(f"No successful runs found for job {DBT_PROD_JOB_ID}")
    return runs[0]["id"]


def download_manifest(run_id: int) -> dict:
    url = f"{DBT_HOST_URL}/api/v2/accounts/{DBT_ACCOUNT_ID}/runs/{run_id}/artifacts/manifest.json"
    resp = requests.get(url, headers=DBT_HEADERS, timeout=60)
    resp.raise_for_status()
    return resp.json()


def load_previous_manifest() -> dict | None:
    """Read the manifest as committed at the previous release, before this run overwrites it."""
    if not MANIFEST_PATH.exists():
        return None
    try:
        raw = subprocess.check_output(
            ["git", "show", f"HEAD:{MANIFEST_PATH}"], stderr=subprocess.DEVNULL
        )
        return json.loads(raw)
    except subprocess.CalledProcessError:
        return None


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


def get_merged_prs(previous_tag: str | None, current_tag: str) -> list[dict]:
    """Titles/descriptions of PRs associated with commits between two tags."""
    if not (GITHUB_REPOSITORY and GITHUB_TOKEN and previous_tag):
        return []

    headers = {"Authorization": f"Bearer {GITHUB_TOKEN}", "Accept": "application/vnd.github+json"}
    compare_url = f"https://api.github.com/repos/{GITHUB_REPOSITORY}/compare/{previous_tag}...{current_tag}"
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


def call_claude(digest: dict) -> str:
    prompt = PROMPT_TEMPLATE_PATH.read_text()
    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": CLAUDE_MODEL,
            "max_tokens": 4096,
            "system": prompt,
            "messages": [{"role": "user", "content": json.dumps(digest, indent=2)}],
        },
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()["content"][0]["text"]


def write_output(markdown: str) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"{RELEASE_TAG}.md"
    out_path.write_text(markdown)
    return out_path


def main() -> None:
    previous_manifest = load_previous_manifest()

    if previous_manifest is None:
        print("No previous manifest found — this is the first tracked release.", file=sys.stderr)

    run_id = get_latest_successful_run_id()
    current_manifest = download_manifest(run_id)

    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(current_manifest))

    if previous_manifest is None:
        write_output(
            f"# What Changed — {RELEASE_TAG}\n\n"
            "_This is the first release tracked by this automation — "
            "there's no prior baseline to compare against. Future releases "
            "will include a full summary of what changed._\n"
        )
        return

    changes = diff_manifests(previous_manifest, current_manifest)
    pull_requests = get_merged_prs(PREVIOUS_TAG, RELEASE_TAG)

    if not (changes["added"] or changes["removed"] or changes["modified"]):
        write_output(
            f"# What Changed — {RELEASE_TAG}\n\n"
            "_No data-affecting changes since the last release._\n"
        )
        return

    digest = {
        "release_tag": RELEASE_TAG,
        "previous_release_tag": PREVIOUS_TAG,
        "changes": changes,
        "pull_requests": pull_requests,
    }

    markdown = call_claude(digest)
    if not current_manifest.get("exposures"):
        markdown += NO_EXPOSURES_NOTE

    out_path = write_output(markdown)
    print(f"Wrote {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
