#!/usr/bin/env python3
from __future__ import annotations

import email.utils
import html
import json
import os
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

USER = os.environ.get("GITHUB_USER", "luceat-lux-vestra")
TOKEN = os.environ.get("GITHUB_TOKEN", "")
README_PATH = Path(os.environ.get("README_PATH", "README.md"))
BLOG_FEED = os.environ.get("BLOG_FEED", "https://blog.ox0.uk/rss/")
GITHUB_API = "https://api.github.com"
USER_AGENT = "luceat-lux-vestra-profile-updater/1.0"

SECTIONS = {
    "writing": ("<!-- LATEST-WRITING:START -->", "<!-- LATEST-WRITING:END -->"),
    "contrib": ("<!-- OSS-CONTRIBUTIONS:START -->", "<!-- OSS-CONTRIBUTIONS:END -->"),
    "activity": ("<!-- RECENT-ACTIVITY:START -->", "<!-- RECENT-ACTIVITY:END -->"),
}


def request_bytes(url: str, *, accept: str = "application/vnd.github+json") -> bytes:
    headers = {"User-Agent": USER_AGENT, "Accept": accept}
    if TOKEN and url.startswith(GITHUB_API):
        headers["Authorization"] = f"Bearer {TOKEN}"
        headers["X-GitHub-Api-Version"] = "2022-11-28"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.read()


def github_json(path: str, params: dict[str, str | int] | None = None) -> Any:
    url = f"{GITHUB_API}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    return json.loads(request_bytes(url).decode("utf-8"))


def markdown_text(value: str) -> str:
    value = html.unescape(value or "").replace("\n", " ").strip()
    value = re.sub(r"\s+", " ", value)
    return value.replace("[", "\\[").replace("]", "\\]")


def iso_date(value: str | None) -> str:
    if not value:
        return ""
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).date().isoformat()
    except ValueError:
        return ""


def update_section(readme: str, section: str, lines: list[str]) -> str:
    start, end = SECTIONS[section]
    if start not in readme or end not in readme:
        raise RuntimeError(f"README markers missing for {section}")
    pattern = re.compile(re.escape(start) + r".*?" + re.escape(end), re.DOTALL)
    body = "\n".join(lines).strip()
    return pattern.sub(lambda _: f"{start}\n{body}\n{end}", readme, count=1)


def latest_writing() -> list[str]:
    data = request_bytes(BLOG_FEED, accept="application/rss+xml, application/xml;q=0.9, */*;q=0.8")
    root = ET.fromstring(data)
    posts: list[tuple[datetime, str, str]] = []
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        published = (item.findtext("pubDate") or "").strip()
        if not title or not link or re.search(r"[가-힣]", title):
            continue
        try:
            dt = email.utils.parsedate_to_datetime(published)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            dt = dt.astimezone(timezone.utc)
        except (TypeError, ValueError):
            dt = datetime.min.replace(tzinfo=timezone.utc)
        posts.append((dt, markdown_text(title), link))
    posts.sort(key=lambda post: post[0], reverse=True)
    if not posts:
        raise RuntimeError("RSS feed returned no English-titled posts")
    return [f"- [{title}]({link}) — {dt.date().isoformat()}" for dt, title, link in posts[:3]]


def external_contributions() -> list[str]:
    items: list[dict[str, Any]] = []
    for kind in ("pr", "issue"):
        result = github_json(
            "/search/issues",
            {"q": f"author:{USER} is:{kind} -user:{USER}", "sort": "updated", "order": "desc", "per_page": 20},
        )
        for item in result.get("items", []):
            repo_url = item.get("repository_url", "")
            if "/repos/" not in repo_url:
                continue
            repo = repo_url.split("/repos/", 1)[1]
            if repo.lower().startswith(f"{USER.lower()}/"):
                continue
            items.append(
                {
                    "kind": "PR" if kind == "pr" else "Issue",
                    "repo": repo,
                    "number": item.get("number"),
                    "title": markdown_text(item.get("title", "")),
                    "url": item.get("html_url", ""),
                    "updated_at": item.get("updated_at", ""),
                }
            )
    items.sort(key=lambda item: item["updated_at"], reverse=True)

    chosen: list[dict[str, Any]] = []
    seen_repos: set[str] = set()
    for item in items:
        repo = item["repo"].lower()
        if repo in seen_repos:
            continue
        seen_repos.add(repo)
        chosen.append(item)
        if len(chosen) == 4:
            break

    if not chosen:
        return ["_No recent public contributions to external repositories found._"]
    return [
        f"- **{item['kind']}** · [{item['repo']}#{item['number']}: {item['title']}]({item['url']}) — {iso_date(item['updated_at'])}"
        for item in chosen
    ]


def recent_open_source_activity() -> list[str]:
    events = github_json(f"/users/{USER}/events/public", {"per_page": 100})
    lines: list[str] = []
    push_included = False
    own_repo_prefix = f"{USER.lower()}/"

    for event in events:
        event_type = event.get("type", "")
        repo = (event.get("repo") or {}).get("name", "")
        if not repo or repo.lower().startswith(own_repo_prefix):
            continue

        payload = event.get("payload") or {}
        date = iso_date(event.get("created_at"))
        repo_url = f"https://github.com/{repo}"
        line = ""

        if event_type == "PullRequestEvent":
            pr = payload.get("pull_request") or {}
            action = payload.get("action", "updated")
            number = pr.get("number") or payload.get("number")
            title = markdown_text(pr.get("title", "pull request"))
            url = pr.get("html_url") or f"{repo_url}/pull/{number}"
            line = f"- **PR {action}** · [{repo}#{number}: {title}]({url}) — {date}"
        elif event_type == "IssuesEvent":
            issue = payload.get("issue") or {}
            action = payload.get("action", "updated")
            number = issue.get("number")
            title = markdown_text(issue.get("title", "issue"))
            url = issue.get("html_url") or f"{repo_url}/issues/{number}"
            line = f"- **Issue {action}** · [{repo}#{number}: {title}]({url}) — {date}"
        elif event_type == "IssueCommentEvent":
            issue = payload.get("issue") or {}
            number = issue.get("number")
            title = markdown_text(issue.get("title", "discussion"))
            url = (payload.get("comment") or {}).get("html_url") or issue.get("html_url") or f"{repo_url}/issues/{number}"
            label = "PR comment" if "pull_request" in issue else "Issue comment"
            line = f"- **{label}** · [{repo}#{number}: {title}]({url}) — {date}"
        elif event_type == "PullRequestReviewEvent":
            pr = payload.get("pull_request") or {}
            number = pr.get("number")
            title = markdown_text(pr.get("title", "pull request"))
            url = pr.get("html_url") or f"{repo_url}/pull/{number}"
            line = f"- **Reviewed PR** · [{repo}#{number}: {title}]({url}) — {date}"
        elif event_type == "PullRequestReviewCommentEvent":
            pr = payload.get("pull_request") or {}
            number = pr.get("number")
            title = markdown_text(pr.get("title", "pull request"))
            url = (payload.get("comment") or {}).get("html_url") or pr.get("html_url") or f"{repo_url}/pull/{number}"
            line = f"- **PR review comment** · [{repo}#{number}: {title}]({url}) — {date}"
        elif event_type == "ReleaseEvent":
            release = payload.get("release") or {}
            tag = markdown_text(release.get("tag_name", "release"))
            url = release.get("html_url") or f"{repo_url}/releases"
            line = f"- **Release** · [{repo} {tag}]({url}) — {date}"
        elif event_type == "CreateEvent":
            ref_type = payload.get("ref_type", "repository")
            ref = payload.get("ref")
            label = f"{ref_type} `{markdown_text(str(ref))}`" if ref else ref_type
            line = f"- **Created {label}** · [{repo}]({repo_url}) — {date}"
        elif event_type == "ForkEvent":
            forkee = payload.get("forkee") or {}
            full_name = forkee.get("full_name", repo)
            url = forkee.get("html_url", repo_url)
            line = f"- **Forked** · [{full_name}]({url}) — {date}"
        elif event_type == "PushEvent" and not push_included:
            size = payload.get("size")
            if size is None:
                size = len(payload.get("commits") or [])
            line = f"- **Pushed {size} commit{'s' if size != 1 else ''}** · [{repo}]({repo_url}) — {date}"
            push_included = True

        if line:
            lines.append(line)
        if len(lines) == 5:
            break

    return lines or ["_No recent public activity in external repositories found._"]


def main() -> int:
    readme = README_PATH.read_text(encoding="utf-8")
    updated = readme
    successes = 0
    for section, loader in (
        ("writing", latest_writing),
        ("contrib", external_contributions),
        ("activity", recent_open_source_activity),
    ):
        try:
            lines = loader()
            updated = update_section(updated, section, lines)
            successes += 1
            print(f"updated {section}: {len(lines)} item(s)")
        except Exception as exc:
            # Preserve last known-good content when one upstream source is temporarily unavailable.
            print(f"warning: could not update {section}: {exc}", file=sys.stderr)

    if successes == 0:
        print("warning: no dynamic source could be refreshed; README left unchanged", file=sys.stderr)
        return 0
    if updated != readme:
        README_PATH.write_text(updated, encoding="utf-8")
        print("README updated")
    else:
        print("README already current")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
