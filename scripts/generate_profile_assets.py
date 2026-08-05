import datetime as dt
import json
import os
import urllib.request
from pathlib import Path

GITHUB_API = "https://api.github.com/graphql"
QUERY = """
query($login: String!) {
  user(login: $login) {
    contributionsCollection {
      contributionCalendar {
        totalContributions
        weeks {
          contributionDays {
            contributionCount
            contributionLevel
            date
          }
        }
      }
    }
  }
}
"""


def fetch_calendar(login: str, token: str) -> dict:
    """Fetch the public contribution calendar shown on the GitHub profile."""
    payload = json.dumps(
        {"query": QUERY, "variables": {"login": login}}
    ).encode("utf-8")
    request = urllib.request.Request(
        GITHUB_API,
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "wrqkkk-profile-assets-generator",
        },
        method="POST",
    )

    with urllib.request.urlopen(request, timeout=30) as response:
        result = json.loads(response.read().decode("utf-8"))

    if "errors" in result:
        raise RuntimeError(f"GitHub GraphQL errors: {result['errors']}")

    user = result.get("data", {}).get("user")
    if user is None:
        raise RuntimeError(f"GitHub user not found: {login}")

    return user["contributionsCollection"]["contributionCalendar"]


def parse_days(calendar: dict) -> list[dict]:
    days: list[dict] = []
    for week in calendar["weeks"]:
        for item in week["contributionDays"]:
            day = dict(item)
            day["date_obj"] = dt.date.fromisoformat(day["date"])
            days.append(day)
    days.sort(key=lambda item: item["date_obj"])
    return days


def compute_streaks(days: list[dict]) -> dict:
    if not days:
        return {
            "current": 0,
            "current_start": None,
            "current_end": None,
            "longest": 0,
            "longest_start": None,
            "longest_end": None,
            "last_active": None,
        }

    # The final date returned by GitHub is the authoritative calendar endpoint.
    calendar_end = max(day["date_obj"] for day in days)
    counts = {
        day["date_obj"]: day["contributionCount"]
        for day in days
        if day["date_obj"] <= calendar_end
    }
    active_dates = sorted(date for date, count in counts.items() if count > 0)
    last_active = active_dates[-1] if active_dates else None

    longest = 0
    longest_start = None
    longest_end = None
    run = 0
    run_start = None

    for date_obj in sorted(counts):
        if counts[date_obj] > 0:
            if run == 0:
                run_start = date_obj
            run += 1
            if run > longest:
                longest = run
                longest_start = run_start
                longest_end = date_obj
        else:
            run = 0
            run_start = None

    current = 0
    current_start = None
    current_end = None

    # Match common GitHub streak behavior: activity through yesterday still
    # counts as current because the present day is not yet complete.
    if last_active is not None and (calendar_end - last_active).days <= 1:
        cursor = last_active
        current_end = last_active
        while counts.get(cursor, 0) > 0:
            current += 1
            current_start = cursor
            cursor -= dt.timedelta(days=1)

    return {
        "current": current,
        "current_start": current_start,
        "current_end": current_end,
        "longest": longest,
        "longest_start": longest_start,
        "longest_end": longest_end,
        "last_active": last_active,
    }


def format_date(date_obj: dt.date | None) -> str:
    if date_obj is None:
        return "—"
    return date_obj.strftime("%b") + f" {date_obj.day}, {date_obj.year}"


def graph_theme(mode: str) -> dict:
    if mode == "dark":
        return {
            "background": "#0d1117",
            "border": "#30363d",
            "title": "#e6edf3",
            "muted": "#8b949e",
            "levels": {
                "NONE": "#161b22",
                "FIRST_QUARTILE": "#0e4429",
                "SECOND_QUARTILE": "#006d32",
                "THIRD_QUARTILE": "#26a641",
                "FOURTH_QUARTILE": "#39d353",
            },
        }

    return {
        "background": "#ffffff",
        "border": "#d0d7de",
        "title": "#24292f",
        "muted": "#57606a",
        "levels": {
            "NONE": "#ebedf0",
            "FIRST_QUARTILE": "#9be9a8",
            "SECOND_QUARTILE": "#40c463",
            "THIRD_QUARTILE": "#30a14e",
            "FOURTH_QUARTILE": "#216e39",
        },
    }


def render_contribution_graph(calendar: dict, login: str, mode: str) -> str:
    theme = graph_theme(mode)
    weeks = calendar["weeks"]
    total = calendar["totalContributions"]

    width = 910
    height = 180
    cell = 11
    gap = 3
    grid_x = 62
    grid_y = 52

    month_labels: list[tuple[int, str]] = []
    seen_months: set[tuple[int, int]] = set()

    for week_index, week in enumerate(weeks):
        dates = [
            dt.date.fromisoformat(day["date"])
            for day in week["contributionDays"]
        ]
        for date_obj in dates:
            key = (date_obj.year, date_obj.month)
            if key not in seen_months and (week_index == 0 or date_obj.day == 1):
                month_labels.append((week_index, date_obj.strftime("%b")))
                seen_months.add(key)

    month_svg = []
    for week_index, label in month_labels:
        x = grid_x + week_index * (cell + gap)
        month_svg.append(
            f'<text x="{x}" y="35" font-size="12" fill="{theme["muted"]}" '
            'font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif">'
            f"{label}</text>"
        )

    # GitHub contribution calendars use Sunday as row zero.
    day_labels = [(1, "Mon"), (3, "Wed"), (5, "Fri")]
    day_svg = []
    for row, label in day_labels:
        y = grid_y + row * (cell + gap) + 9
        day_svg.append(
            f'<text x="22" y="{y}" font-size="11" fill="{theme["muted"]}" '
            'font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif">'
            f"{label}</text>"
        )

    cells = []
    for week_index, week in enumerate(weeks):
        for day in week["contributionDays"]:
            date_obj = dt.date.fromisoformat(day["date"])
            row = (date_obj.weekday() + 1) % 7
            x = grid_x + week_index * (cell + gap)
            y = grid_y + row * (cell + gap)
            fill = theme["levels"].get(
                day["contributionLevel"], theme["levels"]["NONE"]
            )
            cells.append(
                f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" '
                f'rx="2" fill="{fill}"><title>{day["date"]}: '
                f'{day["contributionCount"]} contributions</title></rect>'
            )

    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="GitHub contribution graph for {login}">
  <rect x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" rx="12" fill="{theme['background']}" stroke="{theme['border']}"/>
  <text x="20" y="25" font-size="15" font-weight="600" fill="{theme['title']}" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif">{total} contributions in the last year</text>
  {''.join(month_svg)}
  {''.join(day_svg)}
  {''.join(cells)}
  <text x="20" y="165" font-size="11" fill="{theme['muted']}" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif">Generated daily from the same public contribution calendar used by GitHub.</text>
</svg>'''


def streak_theme(mode: str) -> dict:
    if mode == "dark":
        return {
            "background": "#0d1117",
            "border": "#30363d",
            "text": "#c9d1d9",
            "muted": "#8b949e",
            "accent": "#a78bfa",
            "green": "#39d353",
        }

    return {
        "background": "#ffffff",
        "border": "#9be9a8",
        "text": "#24292f",
        "muted": "#57606a",
        "accent": "#800080",
        "green": "#30a14e",
    }


def metric_block(
    x: int,
    value: str,
    label: str,
    detail: str,
    theme: dict,
    value_color: str,
) -> str:
    return f'''
  <g transform="translate({x}, 0)">
    <text x="0" y="60" font-size="34" font-weight="700" fill="{value_color}" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif">{value}</text>
    <text x="0" y="85" font-size="14" font-weight="600" fill="{theme['text']}" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif">{label}</text>
    <text x="0" y="107" font-size="12" fill="{theme['muted']}" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif">{detail}</text>
  </g>'''


def render_streak_card(
    calendar: dict,
    streaks: dict,
    login: str,
    mode: str,
) -> str:
    theme = streak_theme(mode)
    total = calendar["totalContributions"]
    width = 910
    height = 135

    if streaks["current"] > 0:
        current_detail = (
            f"{format_date(streaks['current_start'])} – "
            f"{format_date(streaks['current_end'])}"
        )
    elif streaks["last_active"] is not None:
        current_detail = f"Last active {format_date(streaks['last_active'])}"
    else:
        current_detail = "No contributions yet"

    if streaks["longest"] > 0:
        longest_detail = (
            f"{format_date(streaks['longest_start'])} – "
            f"{format_date(streaks['longest_end'])}"
        )
    else:
        longest_detail = "No completed streak"

    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="GitHub streak statistics for {login}">
  <rect x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" rx="12" fill="{theme['background']}" stroke="{theme['border']}"/>
  <line x1="303" y1="20" x2="303" y2="115" stroke="{theme['border']}"/>
  <line x1="606" y1="20" x2="606" y2="115" stroke="{theme['border']}"/>
  {metric_block(40, str(streaks['current']), 'Current streak', current_detail, theme, theme['accent'])}
  {metric_block(343, str(streaks['longest']), 'Longest streak', longest_detail, theme, theme['accent'])}
  {metric_block(646, str(total), 'Total contributions', f'Profile: @{login}', theme, theme['green'])}
</svg>'''


def main() -> None:
    login = os.environ["GITHUB_USER"]
    token = os.environ["GITHUB_TOKEN"]

    calendar = fetch_calendar(login, token)
    streaks = compute_streaks(parse_days(calendar))

    output_dir = Path("dist")
    output_dir.mkdir(parents=True, exist_ok=True)

    assets = {
        "contribution-graph-light.svg": render_contribution_graph(
            calendar, login, "light"
        ),
        "contribution-graph-dark.svg": render_contribution_graph(
            calendar, login, "dark"
        ),
        "streak-stats-light.svg": render_streak_card(
            calendar, streaks, login, "light"
        ),
        "streak-stats-dark.svg": render_streak_card(
            calendar, streaks, login, "dark"
        ),
    }

    for filename, content in assets.items():
        (output_dir / filename).write_text(content, encoding="utf-8")

    summary = {
        "login": login,
        "totalContributions": calendar["totalContributions"],
        "currentStreak": streaks["current"],
        "longestStreak": streaks["longest"],
        "lastActive": (
            streaks["last_active"].isoformat()
            if streaks["last_active"] is not None
            else None
        ),
    }
    (output_dir / "profile-stats.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
