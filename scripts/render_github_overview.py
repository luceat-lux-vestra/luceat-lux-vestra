#!/usr/bin/env python3
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from update_profile import (
    ASSETS_DIR,
    USER,
    contribution_calendar,
    owned_public_repo_stats,
    search_total,
    write_text,
    xml_escape,
)

WIDTH = 880
HEIGHT = 376
CARD_X = 24
CARD_Y = 70
CARD_W = 158
CARD_H = 88
CARD_GAP = 12
GRID_X = 54
GRID_Y = 238
CELL = 10
GAP = 3


def icon_repo(x: int, y: int, color: str) -> str:
    return (
        f'<g transform="translate({x} {y})" fill="none" stroke="{color}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">'
        '<rect x="1" y="1" width="15" height="17" rx="2"/><path d="M5 1v17"/><path d="M8.5 5h4"/><path d="M8.5 9h4"/>'
        '</g>'
    )


def icon_star(x: int, y: int, color: str) -> str:
    return (
        f'<g transform="translate({x} {y})" fill="none" stroke="{color}" stroke-width="1.6" stroke-linejoin="round">'
        '<path d="M9 1.6l2.25 4.55 5.02.73-3.63 3.54.86 5-4.5-2.37-4.5 2.37.86-5L1.73 6.88l5.02-.73z"/>'
        '</g>'
    )


def icon_pr(x: int, y: int, color: str) -> str:
    return (
        f'<g transform="translate({x} {y})" fill="none" stroke="{color}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">'
        '<circle cx="4" cy="4" r="2.2"/><circle cx="4" cy="16" r="2.2"/><circle cx="14" cy="16" r="2.2"/>'
        '<path d="M4 6.5v7"/><path d="M10 4h2a2 2 0 0 1 2 2v7.5"/><path d="M9 1l3 3-3 3"/>'
        '</g>'
    )


def icon_issue(x: int, y: int, color: str) -> str:
    return (
        f'<g transform="translate({x} {y})" fill="none" stroke="{color}" stroke-width="1.6" stroke-linecap="round">'
        '<circle cx="9" cy="9" r="7.5"/><path d="M9 5.2v5"/>'
        f'<circle cx="9" cy="13.7" r=".8" fill="{color}" stroke="none"/>'
        '</g>'
    )


def icon_contrib(x: int, y: int, color: str) -> str:
    squares = []
    for row in range(3):
        for col in range(3):
            opacity = 0.35 + (row * 3 + col) * 0.07
            squares.append(
                f'<rect x="{col * 6}" y="{row * 6}" width="4" height="4" rx="1" fill="{color}" opacity="{opacity:.2f}"/>'
            )
    return f'<g transform="translate({x} {y})">{"".join(squares)}</g>'


ICONS = {
    "repo": icon_repo,
    "star": icon_star,
    "pr": icon_pr,
    "issue": icon_issue,
    "contrib": icon_contrib,
}


def level_for(count: int, max_count: int) -> int:
    if count <= 0 or max_count <= 0:
        return 0
    ratio = count / max_count
    if ratio <= 0.25:
        return 1
    if ratio <= 0.50:
        return 2
    if ratio <= 0.75:
        return 3
    return 4


def month_labels(parsed: list[tuple[date, int]], first_sunday: date, muted: str) -> str:
    labels: list[str] = []
    seen: set[tuple[int, int]] = set()
    for current, _ in parsed:
        key = (current.year, current.month)
        if key in seen or current.day > 7:
            continue
        seen.add(key)
        week = (current - first_sunday).days // 7
        x = GRID_X + week * (CELL + GAP)
        if x > WIDTH - 42:
            continue
        labels.append(
            f'<text x="{x}" y="225" font-size="10" fill="{muted}">{current.strftime("%b")}</text>'
        )
    return "".join(labels)


def overview_svg(*, dark: bool) -> str:
    repos, stars = owned_public_repo_stats()
    prs = search_total(f"author:{USER} is:pr is:public")
    issues = search_total(f"author:{USER} is:issue is:public")
    total, days, start_date, end_date = contribution_calendar()

    bg = "#0d1117" if dark else "#ffffff"
    border = "#30363d" if dark else "#d0d7de"
    card = "#161b22" if dark else "#f6f8fa"
    title = "#f0f6fc" if dark else "#1f2328"
    muted = "#8b949e" if dark else "#656d76"
    accent = "#58a6ff" if dark else "#0969da"
    empty = "#161b22" if dark else "#ebedf0"
    levels = [
        empty,
        "#0e4429" if dark else "#9be9a8",
        "#006d32" if dark else "#40c463",
        "#26a641" if dark else "#30a14e",
        "#39d353" if dark else "#216e39",
    ]

    metrics = [
        ("repo", "Public Repos", str(repos), "Owned · non-fork"),
        ("star", "Stars Earned", str(stars), "Owned public repos"),
        ("pr", "Pull Requests", str(prs), "Public · authored"),
        ("issue", "Issues", str(issues), "Public · authored"),
        ("contrib", "Contributions", f"{total:,}", "Last 365 days"),
    ]

    cards: list[str] = []
    for i, (icon_name, label, value, detail) in enumerate(metrics):
        x = CARD_X + i * (CARD_W + CARD_GAP)
        icon = ICONS[icon_name](x + 14, CARD_Y + 12, accent)
        cards.append(
            f'<rect x="{x}" y="{CARD_Y}" width="{CARD_W}" height="{CARD_H}" rx="8" fill="{card}" stroke="{border}"/>'
            + icon
            + f'<text x="{x + 42}" y="{CARD_Y + 26}" font-size="10.5" font-weight="600" fill="{muted}">{xml_escape(label)}</text>'
            + f'<text x="{x + 14}" y="{CARD_Y + 59}" font-size="25" font-weight="700" fill="{title}">{xml_escape(value)}</text>'
            + f'<text x="{x + 14}" y="{CARD_Y + 77}" font-size="9.5" fill="{muted}">{xml_escape(detail)}</text>'
        )

    parsed = [(datetime.fromisoformat(day["date"]).date(), int(day["contributionCount"])) for day in days]
    parsed.sort(key=lambda item: item[0])
    if not parsed:
        raise RuntimeError("Contribution calendar returned no days")

    first_sunday = parsed[0][0] - timedelta(days=(parsed[0][0].weekday() + 1) % 7)
    max_count = max((count for _, count in parsed), default=0)
    cells: list[str] = []
    for current, count in parsed:
        week = (current - first_sunday).days // 7
        weekday = (current.weekday() + 1) % 7
        x = GRID_X + week * (CELL + GAP)
        y = GRID_Y + weekday * (CELL + GAP)
        fill = levels[level_for(count, max_count)]
        cells.append(
            f'<rect x="{x}" y="{y}" width="{CELL}" height="{CELL}" rx="2" fill="{fill}">'
            f'<title>{xml_escape(current.isoformat())}: {count} contribution{"s" if count != 1 else ""}</title></rect>'
        )

    weekdays = "".join(
        f'<text x="20" y="{GRID_Y + weekday * (CELL + GAP) + 9}" font-size="9.5" fill="{muted}">{name}</text>'
        for weekday, name in ((1, "Mon"), (3, "Wed"), (5, "Fri"))
    )

    legend_x = 713
    legend = [f'<text x="{legend_x - 32}" y="357" font-size="9.5" fill="{muted}">Less</text>']
    for i, fill in enumerate(levels):
        legend.append(f'<rect x="{legend_x + i * 15}" y="347" width="10" height="10" rx="2" fill="{fill}"/>')
    legend.append(f'<text x="{legend_x + 80}" y="357" font-size="9.5" fill="{muted}">More</text>')

    updated = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}">'
        '<style>text{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif}</style>'
        f'<rect x="0.5" y="0.5" width="879" height="375" rx="10" fill="{bg}" stroke="{border}"/>'
        f'<text x="24" y="32" font-size="17" font-weight="700" fill="{title}">GitHub Overview</text>'
        f'<text x="24" y="51" font-size="10.5" fill="{muted}">First-party public data · GitHub REST &amp; GraphQL</text>'
        f'<text x="856" y="32" text-anchor="end" font-size="9.5" fill="{muted}">Updated {updated} UTC</text>'
        + "".join(cards)
        + f'<line x1="24" y1="178" x2="856" y2="178" stroke="{border}"/>'
        + f'<text x="24" y="202" font-size="12" font-weight="650" fill="{title}">Contributions · Last 365 Days</text>'
        + f'<text x="856" y="202" text-anchor="end" font-size="9.5" fill="{muted}">{xml_escape(start_date)} → {xml_escape(end_date)}</text>'
        + month_labels(parsed, first_sunday, muted)
        + weekdays
        + "".join(cells)
        + "".join(legend)
        + '</svg>'
    )


def main() -> None:
    write_text(ASSETS_DIR / "github-overview-light.svg", overview_svg(dark=False))
    write_text(ASSETS_DIR / "github-overview-dark.svg", overview_svg(dark=True))


if __name__ == "__main__":
    main()
