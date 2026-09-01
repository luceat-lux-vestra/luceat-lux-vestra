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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

USER = os.environ.get("GITHUB_USER", "luceat-lux-vestra")
TOKEN = os.environ.get("GITHUB_TOKEN", "")
README_PATH = Path(os.environ.get("README_PATH", "README.md"))
ASSETS_DIR = Path(os.environ.get("ASSETS_DIR", "assets"))
BLOG_FEED = os.environ.get("BLOG_FEED", "https://blog.ox0.uk/rss/")
GITHUB_API = "https://api.github.com"
GITHUB_GRAPHQL = "https://api.github.com/graphql"
USER_AGENT = "luceat-lux-vestra-profile-updater/2.0"

SECTIONS = {
    "writing": ("<!-- LATEST-WRITING:START -->", "<!-- LATEST-WRITING:END -->"),
    "contrib": ("<!-- OSS-CONTRIBUTIONS:START -->", "<!-- OSS-CONTRIBUTIONS:END -->"),
    "activity": ("<!-- RECENT-ACTIVITY:START -->", "<!-- RECENT-ACTIVITY:END -->"),
}


def request_bytes(
    url: str,
    *,
    accept: str = "application/vnd.github+json",
    method: str = "GET",
    data: bytes | None = None,
) -> bytes:
    headers = {"User-Agent": USER_AGENT, "Accept": accept}
    if TOKEN and url.startswith(GITHUB_API):
        headers["Authorization"] = f"Bearer {TOKEN}"
        headers["X-GitHub-Api-Version"] = "2022-11-28"
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, headers=headers, method=method, data=data)
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def github_json(path: str, params: dict[str, str | int] | None = None) -> Any:
    url = f"{GITHUB_API}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    return json.loads(request_bytes(url).decode("utf-8"))


def github_graphql(query: str, variables: dict[str, Any]) -> dict[str, Any]:
    if not TOKEN:
        raise RuntimeError("GITHUB_TOKEN is required for GraphQL profile metrics")
    payload = json.dumps({"query": query, "variables": variables}).encode("utf-8")
    result = json.loads(request_bytes(GITHUB_GRAPHQL, method="POST", data=payload).decode("utf-8"))
    if result.get("errors"):
        raise RuntimeError(f"GitHub GraphQL error: {result['errors']}")
    return result["data"]


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


def owned_public_repo_stats() -> tuple[int, int]:
    repo_count = 0
    stars = 0
    page = 1
    while True:
        repos = github_json(f"/users/{USER}/repos", {"type": "owner", "sort": "full_name", "per_page": 100, "page": page})
        if not repos:
            break
        for repo in repos:
            if repo.get("fork"):
                continue
            repo_count += 1
            stars += int(repo.get("stargazers_count") or 0)
        if len(repos) < 100:
            break
        page += 1
    return repo_count, stars


def search_total(query: str) -> int:
    result = github_json("/search/issues", {"q": query, "per_page": 1})
    return int(result.get("total_count") or 0)


def contribution_calendar() -> tuple[int, list[dict[str, Any]], str, str]:
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=364)
    query = """
    query ProfileContributions($login: String!, $from: DateTime!, $to: DateTime!) {
      user(login: $login) {
        contributionsCollection(from: $from, to: $to) {
          contributionCalendar {
            totalContributions
            weeks {
              contributionDays {
                contributionCount
                date
              }
            }
          }
        }
      }
    }
    """
    data = github_graphql(
        query,
        {"login": USER, "from": start.isoformat(), "to": now.isoformat()},
    )
    calendar = data["user"]["contributionsCollection"]["contributionCalendar"]
    days: list[dict[str, Any]] = []
    for week in calendar["weeks"]:
        days.extend(week["contributionDays"])
    return int(calendar["totalContributions"]), days, start.date().isoformat(), now.date().isoformat()


def xml_escape(value: str) -> str:
    return html.escape(str(value), quote=True)


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def stats_svg(metrics: list[tuple[str, str]], *, dark: bool) -> str:
    bg = "#0d1117" if dark else "#ffffff"
    border = "#30363d" if dark else "#d0d7de"
    title = "#f0f6fc" if dark else "#1f2328"
    muted = "#8b949e" if dark else "#656d76"
    accent = "#58a6ff" if dark else "#0969da"
    width, height = 880, 176
    card_w = 164
    gap = 10
    start_x = 20

    cards = []
    for i, (label, value) in enumerate(metrics):
        x = start_x + i * (card_w + gap)
        cards.append(
            f'<rect x="{x}" y="64" width="{card_w}" height="88" rx="8" fill="{bg}" stroke="{border}"/>'
            f'<text x="{x + 14}" y="91" font-size="13" fill="{muted}">{xml_escape(label)}</text>'
            f'<text x="{x + 14}" y="128" font-size="27" font-weight="600" fill="{accent}">{xml_escape(value)}</text>'
        )

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">'
        f'<rect width="{width}" height="{height}" rx="10" fill="{bg}" stroke="{border}"/>'
        f'<style>text{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif}}</style>'
        f'<text x="20" y="34" font-size="18" font-weight="600" fill="{title}">GitHub · first-party public data</text>'
        f'<text x="20" y="53" font-size="11" fill="{muted}">Generated from GitHub REST and GraphQL APIs by this profile repository</text>'
        + "".join(cards)
        + "</svg>"
    )


def heatmap_svg(total: int, days: list[dict[str, Any]], start_date: str, end_date: str, *, dark: bool) -> str:
    bg = "#0d1117" if dark else "#ffffff"
    border = "#30363d" if dark else "#d0d7de"
    title = "#f0f6fc" if dark else "#1f2328"
    muted = "#8b949e" if dark else "#656d76"
    empty = "#161b22" if dark else "#ebedf0"
    levels = [
        empty,
        "#0e4429" if dark else "#9be9a8",
        "#006d32" if dark else "#40c463",
        "#26a641" if dark else "#30a14e",
        "#39d353" if dark else "#216e39",
    ]
    width, height = 880, 190
    cell, gap = 10, 3
    grid_x, grid_y = 56, 72

    parsed = [(datetime.fromisoformat(day["date"]).date(), int(day["contributionCount"])) for day in days]
    parsed.sort(key=lambda item: item[0])
    if not parsed:
        raise RuntimeError("Contribution calendar returned no days")

    first_sunday = parsed[0][0] - timedelta(days=(parsed[0][0].weekday() + 1) % 7)
    max_count = max((count for _, count in parsed), default=0)

    def level(count: int) -> int:
        if count <= 0 or max_count <= 0:
            return 0
        ratio = count / max_count
        if ratio <= 0.25:
            return 1
        if ratio <= 0.5:
            return 2
        if ratio <= 0.75:
            return 3
        return 4

    cells = []
    for date, count in parsed:
        week = (date - first_sunday).days // 7
        weekday = (date.weekday() + 1) % 7
        x = grid_x + week * (cell + gap)
        y = grid_y + weekday * (cell + gap)
        cells.append(
            f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" rx="2" fill="{levels[level(count)]}">'
            f'<title>{xml_escape(date.isoformat())}: {count} contribution{"s" if count != 1 else ""}</title></rect>'
        )

    labels = []
    for weekday, name in ((1, "Mon"), (3, "Wed"), (5, "Fri")):
        y = grid_y + weekday * (cell + gap) + 9
        labels.append(f'<text x="20" y="{y}" font-size="10" fill="{muted}">{name}</text>')

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">'
        f'<rect width="{width}" height="{height}" rx="10" fill="{bg}" stroke="{border}"/>'
        f'<style>text{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif}}</style>'
        f'<text x="20" y="32" font-size="18" font-weight="600" fill="{title}">Public contributions · last 365 days</text>'
        f'<text x="20" y="52" font-size="12" fill="{muted}">{total:,} contributions · {xml_escape(start_date)} → {xml_escape(end_date)} · GitHub contributionCalendar</text>'
        + "".join(labels)
        + "".join(cells)
        + "</svg>"
    )


def generate_github_assets() -> None:
    repos, stars = owned_public_repo_stats()
    prs = search_total(f"author:{USER} is:pr is:public")
    issues = search_total(f"author:{USER} is:issue is:public")
    contributions, days, start_date, end_date = contribution_calendar()

    metrics = [
        ("Owned public repos", str(repos)),
        ("Stars earned", str(stars)),
        ("Public PRs authored", str(prs)),
        ("Public issues authored", str(issues)),
        ("365d contributions", f"{contributions:,}"),
    ]

    write_text(ASSETS_DIR / "github-stats-light.svg", stats_svg(metrics, dark=False))
    write_text(ASSETS_DIR / "github-stats-dark.svg", stats_svg(metrics, dark=True))
    write_text(
        ASSETS_DIR / "github-contributions-light.svg",
        heatmap_svg(contributions, days, start_date, end_date, dark=False),
    )
    write_text(
        ASSETS_DIR / "github-contributions-dark.svg",
        heatmap_svg(contributions, days, start_date, end_date, dark=True),
    )
    print(
        "github metrics: "
        f"repos={repos}, stars={stars}, public_prs={prs}, public_issues={issues}, 365d_contributions={contributions}"
    )


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

    try:
        generate_github_assets()
        successes += 1
    except Exception as exc:
        # Preserve the last generated SVGs when GitHub is temporarily unavailable.
        print(f"warning: could not refresh GitHub metric assets: {exc}", file=sys.stderr)

    if successes == 0:
        print("warning: no dynamic source could be refreshed; profile left unchanged", file=sys.stderr)
        return 0
    if updated != readme:
        README_PATH.write_text(updated, encoding="utf-8")
        print("README updated")
    else:
        print("README already current")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
