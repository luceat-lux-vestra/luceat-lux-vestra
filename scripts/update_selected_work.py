#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

USER = os.environ.get("GITHUB_USER", "luceat-lux-vestra")
TOKEN = os.environ.get("GITHUB_TOKEN", "")
README_PATH = Path(os.environ.get("README_PATH", "README.md"))
STRICT_UPSTREAM = os.environ.get("STRICT_UPSTREAM", "") == "1"
GITHUB_API = "https://api.github.com"
USER_AGENT = "luceat-lux-vestra-profile-selected-work-updater/1.0"

START_MARKER = "<!-- SELECTED-WORK:START -->"
END_MARKER = "<!-- SELECTED-WORK:END -->"

REPO_LINK_PATTERN = re.compile(
    r"(?P<prefix><!--\s*repo-id:(?P<repo_id>\d+)\s*-->\s*\n"
    r"### \[[^\]\n]+\]\()"
    r"(?P<url>https://github\.com/[^)\s]+)"
    r"(?P<suffix>\))"
)
SELECTED_HEADING_PATTERN = re.compile(
    r"^### \[[^\]\n]+\]\(https://github\.com/[^)\s]+\)$",
    re.MULTILINE,
)


class TemporaryGitHubError(RuntimeError):
    """A retryable GitHub API failure that must not destroy last-known-good content."""


def request_repo(repo_id: int) -> dict[str, Any]:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    request = urllib.request.Request(
        f"{GITHUB_API}/repositories/{repo_id}",
        headers=headers,
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code in {403, 429} or exc.code >= 500:
            raise TemporaryGitHubError(
                f"temporary GitHub API HTTP {exc.code} for repository id {repo_id}"
            ) from exc
        raise
    except (OSError, json.JSONDecodeError) as exc:
        raise TemporaryGitHubError(
            f"temporary GitHub API failure for repository id {repo_id}: {exc}"
        ) from exc


def resolve_repo_url(repo_id: int) -> str:
    repo = request_repo(repo_id)
    owner = (repo.get("owner") or {}).get("login", "")
    if owner.lower() != USER.lower():
        raise RuntimeError(
            f"repository id {repo_id} resolved to unexpected owner {owner!r}"
        )
    if repo.get("private"):
        raise RuntimeError(f"repository id {repo_id} resolved to a private repository")
    url = repo.get("html_url", "")
    if not isinstance(url, str) or not url.startswith("https://github.com/"):
        raise RuntimeError(f"repository id {repo_id} returned an invalid html_url")
    return url.rstrip("/")


def selected_work_bounds(readme: str) -> tuple[int, int]:
    if readme.count(START_MARKER) != 1 or readme.count(END_MARKER) != 1:
        raise RuntimeError("README must contain exactly one selected-work marker pair")
    start = readme.index(START_MARKER) + len(START_MARKER)
    end = readme.index(END_MARKER, start)
    return start, end


def collect_repo_ids(block: str) -> list[int]:
    matches = list(REPO_LINK_PATTERN.finditer(block))
    heading_count = len(SELECTED_HEADING_PATTERN.findall(block))
    if not matches or len(matches) != heading_count:
        raise RuntimeError(
            "every Selected Work GitHub heading must have one adjacent repo-id marker"
        )
    repo_ids = [int(match.group("repo_id")) for match in matches]
    if len(repo_ids) != len(set(repo_ids)):
        raise RuntimeError("Selected Work repo-id markers must be unique")
    return repo_ids


def rewrite_repo_links(
    block: str,
    resolved_urls: dict[int, str],
) -> str:
    def replace(match: re.Match[str]) -> str:
        repo_id = int(match.group("repo_id"))
        try:
            url = resolved_urls[repo_id]
        except KeyError as exc:
            raise RuntimeError(f"missing resolved URL for repository id {repo_id}") from exc
        return f"{match.group('prefix')}{url}{match.group('suffix')}"

    return REPO_LINK_PATTERN.sub(replace, block)


def update_selected_work(
    readme: str,
    resolver: Callable[[int], str] | None = None,
) -> str:
    if resolver is None:
        resolver = resolve_repo_url
    start, end = selected_work_bounds(readme)
    block = readme[start:end]
    repo_ids = collect_repo_ids(block)
    resolved_urls = {repo_id: resolver(repo_id) for repo_id in repo_ids}
    updated_block = rewrite_repo_links(block, resolved_urls)
    return f"{readme[:start]}{updated_block}{readme[end:]}"


def main() -> int:
    readme = README_PATH.read_text(encoding="utf-8")
    try:
        updated = update_selected_work(readme)
    except TemporaryGitHubError as exc:
        if STRICT_UPSTREAM:
            raise
        # Preserve last-known-good content on scheduled refreshes when GitHub is
        # temporarily unavailable. PR validation opts into strict upstream checks.
        print(f"warning: could not refresh selected work: {exc}", file=sys.stderr)
        return 0

    if updated != readme:
        README_PATH.write_text(updated, encoding="utf-8")
        print("updated selected work")
    else:
        print("selected work already current")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
