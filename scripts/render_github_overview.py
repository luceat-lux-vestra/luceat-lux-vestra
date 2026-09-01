#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

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
HEIGHT = 352
CARD_X = 24
CARD_Y = 72
CARD_W = 158
CARD_H = 76
CARD_GAP = 12
GRID_X = 54
GRID_Y = 210
CELL = 10
GAP = 3


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


def month_labels(parsed: list[tuple[datetime.date, int]], first_sunday) -> str:
    labels: list[str] = []
    seen: set[tuple[int, int]] = set()
    for date, _ in parsed:
        key = (date.year, date.month)
        if key in seen or date.day > 7:
            continue
        seen.add(key)
        week = (date - first_sunday).days // 7
        x = GRID_X + week * (CELL + GAP)
        if x > WIDTH - 38:
            continue
        labels.append(
            f'<text x="{x}" y="194" font-size="10" fill="var(--muted)">{date.strftime("%b")}</text>'
        )
    return "".join(labels)


def overview_svg(*, dark: bool) -> str:
    repos, stars = owned_public_repo_stats()
    prs = search_total(f"author:{USER} is:pr is:public")
    issues = search_total(f"author:{USER} is:issue is:public")
    total, days, start_date, end_date = contribution_calendar()

    theme = {
        "bg": "#0d1117" if dark else "#ffffff",
        "border": "#30363d" if dark else "#d0d7de",
        "card": "#161b22" if dark else "#ffffff",
        "title": "#f0f6fc" if dark else "#1f2328",
        "muted": "#8b949e" if dark else "#656d76",
        "accent": "#58a6ff" if dark else "#0969da",
        "empty": "#161b22" if dark else "#ebedf0",
        "l1": "#0e4429" if dark else "#9be9a8",
        "l2": "#006d32" if dark else "#40c463",
        "l3": "#26a641" if dark else "#30a14e",
        "l4": "#39d353" if dark else "#216e39",
    }

    metrics = [
        ("Public Repos", str(repos), "Owned · non-fork"),
        ("Stars Earned", str(stars), "Owned public repos"),
        ("Pull Requests", str(prs), "Public · authored"),
        ("Issues", str(issues), "Public · authored"),
        ("Contributions", f"{total:,}", "Last 365 days"),
    ]

    cards: list[str] = []
    for i, (label, value, detail) in enumerate(metrics):
        x = CARD_X + i * (CARD_W + CARD_GAP)
        cards.append(
            f'<rect x="{x}" y="{CARD_Y}" width="{CARD_W}" height="{CARD_H}" rx="7" '
            f'fill="var(--card)" stroke="var(--border)"/>'
            f'<text x="{x + 14}" y="{CARD_Y + 22}" font-size="11" font-weight="500" fill="var(--muted)">{xml_escape(label)}</text>'
            f'<text x="{x + 14}" y="{CARD_Y + 49}" font-size="24" font-weight="650" fill="var(--title)">{xml_escape(value)}</text>'
            f'<text x="{x + 14}" y="{CARD_Y + 66}" font-size="9.5" fill="var(--muted)">{xml_escape(detail)}</text>'
        )

    parsed = [(datetime.fromisoformat(day["date"]).date(), int(day["contributionCount"])) for day in days]
    parsed.sort(key=lambda item: item[0])
    if not parsed:
        raise RuntimeError("Contribution calendar returned no days")

    first_sunday = parsed[0][0] - timedelta(days=(parsed[0][0].weekday() + 1) % 7)
    max_count = max((count for _, count in parsed), default=0)
    cells: list[str] = []
    for date, count in parsed:
        week = (date - first_sunday).days // 7
        weekday = (date.weekday() + 1) % 7
        x = GRID_X + week * (CELL + GAP)
        y = GRID_Y + weekday * (CELL + GAP)
        level = level_for(count, max_count)
        cells.append(
            f'<rect x="{x}" y="{y}" width="{CELL}" height="{CELL}" rx="2" fill="var(--l{level})">'
            f'<title>{xml_escape(date.isoformat())}: {count} contribution{"s" if count != 1 else ""}</title></rect>'
        )

    weekdays = "".join(
        f'<text x="20" y="{GRID_Y + weekday * (CELL + GAP) + 9}" font-size="9.5" fill="var(--muted)">{name}</text>'
        for weekday, name in ((1, "Mon"), (3, "Wed"), (5, "Fri"))
    )

    legend_x = 715
    legend = [f'<text x="{legend_x - 30}" y="329" font-size="9.5" fill="var(--muted)">Less</text>']
    for i in range(5):
        legend.append(
            f'<rect x="{legend_x + i * 15}" y="319" width="10" height="10" rx="2" fill="var(--l{i})"/>'
        )
    legend.append(f'<text x="{legend_x + 80}" y="329" font-size="9.5" fill="var(--muted)">More</text>')

    updated = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}">'
        '<style>'
        f':root{{--bg:{theme["bg"]};--border:{theme["border"]};--card:{theme["card"]};--title:{theme["title"]};--muted:{theme["muted"]};--accent:{theme["accent"]};'
        f'--l0:{theme["empty"]};--l1:{theme["l1"]};--l2:{theme["l2"]};--l3:{theme["l3"]};--l4:{theme["l4"]};}}'
        'text{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif}'
        '</style>'
        f'<rect x="0.5" y="0.5" width="879" height="351" rx="10" fill="var(--bg)" stroke="var(--border)"/>'
        '<text x="24" y="34" font-size="17" font-weight="650" fill="var(--title)">GitHub Overview</text>'
        '<text x="24" y="53" font-size="10.5" fill="var(--muted)">First-party public data · GitHub REST &amp; GraphQL</text>'
        f'<text x="856" y="34" text-anchor="end" font-size="9.5" fill="var(--muted)">Updated {updated} UTC</text>'
        + "".join(cards)
        + '<line x1="24" y1="169" x2="856" y2="169" stroke="var(--border)"/>'
        + '<text x="24" y="190" font-size="12" font-weight="600" fill="var(--title)">Contributions · Last 365 Days</text>'
        + f'<text x="856" y="190" text-anchor="end" font-size="9.5" fill="var(--muted)">{xml_escape(start_date)} → {xml_escape(end_date)}</text>'
        + month_labels(parsed, first_sunday)
        + weekdays
        + "".join(cells)
        + "".join(legend)
        + '</svg>'
    )


def main() -> None:
    write_text(ASSETS_DIR / "github-overview-light.svg", overview_svg(dark=False))
    write_text(ASSETS_DIR / "github-overview-dark.svg", overview_svg(dark=True))

    # Retire the previous two-card renderer once the unified overview exists.
    for legacy in (
        "github-stats-light.svg",
        "github-stats-dark.svg",
        "github-contributions-light.svg",
        "github-contributions-dark.svg",
    ):
        path = Path(ASSETS_DIR) / legacy
        if path.exists():
            path.unlink()


if __name__ == "__main__":
    main()
