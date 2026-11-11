import argparse
import calendar
import hashlib
import html
import json
import os
import re
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


WIDTH = 960
TOP_LANGUAGES = 9
REPORT_YEARS = 5
REQUEST_TIMEOUT = 30
MAX_WORKERS = 4
STYLE = {
    "background": "#0d1117",
    "border": "#e1e4e8",
    "text": "#c9d1d9",
    "muted": "#8b949e",
    "font_size": 12,
    "title_size": 16,
    "bar_height": 8,
}
LANGUAGE_COLORS = {
    "ApacheConf": "#d12127",
    "Batchfile": "#C1F12E",
    "C": "#555555",
    "C#": "#7355dd",
    "CSS": "#663399",
    "CoffeeScript": "#244776",
    "Dockerfile": "#384d54",
    "Go": "#00ADD8",
    "HTML": "#e34c26",
    "Java": "#b07219",
    "JavaScript": "#f1e05a",
    "Less": "#1d365d",
    "Makefile": "#427819",
    "Mustache": "#724b3b",
    "Objective-C": "#438eff",
    "PHP": "#4F5D95",
    "PLSQL": "#dad8d8",
    "PLpgSQL": "#336790",
    "PowerShell": "#012456",
    "Pug": "#a86454",
    "Python": "#3572A5",
    "Roff": "#ecdebe",
    "Ruby": "#701516",
    "SCSS": "#c6538c",
    "SQLPL": "#e38c00",
    "Sass": "#a53b70",
    "Shell": "#89e051",
    "Smarty": "#f0c040",
    "Swift": "#F05138",
    "TypeScript": "#3178c6",
    "VBScript": "#15dcdc",
    "Vue": "#41b883"
}


def api_json(route, token):
    request = Request(
        "https://api.github.com" + route,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": "Bearer " + token,
            "User-Agent": "dpmango-profile-languages",
            "X-GitHub-Api-Version": "2026-03-10",
        },
    )
    for attempt in range(3):
        try:
            with urlopen(request, timeout=REQUEST_TIMEOUT) as response:
                return json.load(response)
        except HTTPError as error:
            if error.code in (429, 502, 503, 504) and attempt < 2:
                time.sleep(max(2 ** attempt, int(error.headers.get("Retry-After", "0"))))
                continue
            raise RuntimeError(f"GitHub metadata request failed (HTTP {error.code})") from None
        except (URLError, TimeoutError):
            if attempt < 2:
                time.sleep(2 ** attempt)
                continue
            raise RuntimeError("GitHub metadata request timed out") from None


def collect_languages(owner, scope, fetch, today=None):
    if fetch("/user")["login"].casefold() != owner.casefold():
        raise RuntimeError("The statistics token belongs to a different account")
    repositories = []
    page = 1
    while True:
        query = urlencode({"affiliation": "owner", "visibility": "all", "per_page": 100, "page": page})
        batch = fetch("/user/repos?" + query)
        repositories.extend(repo for repo in batch if not repo["fork"] and repo["owner"]["login"].casefold() == owner.casefold())
        if len(batch) < 100:
            break
        page += 1
    private_count = sum(repo["private"] for repo in repositories)
    if not private_count:
        raise RuntimeError("Private repositories are not visible; existing chart was kept")
    today = today or datetime.now(ZoneInfo("Europe/Moscow")).date()
    cutoff_year = today.year - REPORT_YEARS
    cutoff = today.replace(year=cutoff_year, day=min(today.day, calendar.monthrange(cutoff_year, today.month)[1]))
    selected = [repo for repo in repositories if repo["pushed_at"] and datetime.fromisoformat(repo["pushed_at"].replace("Z", "+00:00")).astimezone(ZoneInfo("Europe/Moscow")).date() >= cutoff]
    if scope == "private":
        selected = [repo for repo in selected if repo["private"]]
    private_count = sum(repo["private"] for repo in selected)

    def read_languages(repo):
        return fetch(f"/repos/{repo['full_name']}/languages")

    totals = defaultdict(int)
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        for languages in pool.map(read_languages, selected):
            for name, size in languages.items():
                totals[name] += size
    if not sum(totals.values()):
        raise RuntimeError("GitHub returned no language data; existing chart was kept")
    return {"scope": scope, "period_years": REPORT_YEARS, "since": cutoff.isoformat(), "repositories": len(selected), "private": private_count, "public": len(selected) - private_count, "languages": dict(totals)}


def grouped_languages(data):
    rows = sorted(data["languages"].items(), key=lambda row: (-row[1], row[0]))
    shown = rows[:TOP_LANGUAGES]
    remainder = sum(size for _, size in rows[TOP_LANGUAGES:])
    if remainder:
        shown.append(("Other", remainder))
    return sorted(shown, key=lambda row: (-row[1], row[0]))


def text_width(value):
    return sum(3.6 if char in "ilI.,: !" else 9.5 if char in "MW@" else 7.6 if char.isupper() else 6.8 for char in value)


def data_digest(data):
    # Advancing the cutoff alone must not create daily commits when the selected code is unchanged.
    content = {key: value for key, value in data.items() if key != "since"}
    return hashlib.sha256(json.dumps({"data": content, "style": STYLE, "width": WIDTH, "top": TOP_LANGUAGES}, sort_keys=True).encode()).hexdigest()


def render_svg(data, updated):
    rows = grouped_languages(data)
    total = sum(size for _, size in rows)
    x, y = 21, 91
    segments, labels = [], []
    bar_x = 21
    for name, size in rows:
        percentage = size / total * 100
        color = LANGUAGE_COLORS.get(name, "#8b949e")
        width = size / total * 918
        segments.append(f'<rect x="{bar_x:.4f}" y="53" width="{width:.4f}" height="{STYLE["bar_height"]}" fill="{color}" stroke="#393f47" stroke-width="2"/>')
        bar_x += width
        value = f"{percentage:.2f}%"
        name_width = text_width(name) + 8
        item_width = 20 + name_width + 10 + text_width(value) + 14
        if x + item_width > 939:
            x, y = 21, y + 23
        labels.append(f'<circle cx="{x + 8}" cy="{y - 4}" r="4" fill="{color}"/><text x="{x + 20}" y="{y}" font-weight="600" fill="{STYLE["text"]}">{html.escape(name)}</text><text x="{x + 30 + name_width:.2f}" y="{y}" fill="{STYLE["muted"]}">{value}</text>')
        x += item_width
    height = max(150, y + 36)
    title = f'Languages Used · Last {data["period_years"]} Years · {data["repositories"]} ' + ("Public + Private Repositories" if data["scope"] == "all" else "Private Repositories")
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{height}" viewBox="0 0 {WIDTH} {height}" data-language-digest="{data_digest(data)}"><title>{html.escape(title)}</title><rect x="5" y="5" width="950" height="{height - 10}" rx="6" fill="{STYLE["background"]}" stroke="{STYLE["border"]}" stroke-width="0.5"/><g font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif" font-size="{STYLE["font_size"]}"><text x="21" y="37" font-size="{STYLE["title_size"]}" font-weight="600" fill="{STYLE["text"]}">{html.escape(title)}</text><defs><clipPath id="rounded-progress"><rect x="21" y="53" width="918" height="{STYLE["bar_height"]}" rx="6"/></clipPath></defs><g clip-path="url(#rounded-progress)">{"".join(segments)}</g>{"".join(labels)}<text x="21" y="{height - 12}" font-size="10" fill="{STYLE["muted"]}">Updated {updated} · Current default-branch code · Repositories pushed to in the last {data["period_years"]} years</text></g></svg>\n'''


def write_chart(target, data, updated):
    if target.exists():
        current = target.read_text()
        digest = re.search(r'data-language-digest="([a-f0-9]+)"', current)
        if digest and digest[1] == data_digest(data):
            return False
    content = render_svg(data, updated)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(content)
    temporary.replace(target)
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--owner", default="dpmango")
    parser.add_argument("--scope", choices=("all", "private"), default="all")
    parser.add_argument("--output", type=Path, default=Path("profile/languages.svg"))
    args = parser.parse_args()
    token = os.environ.get("LANGUAGES_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("PROFILE_LANGUAGES_TOKEN secret is required")
    today = datetime.now(ZoneInfo("Europe/Moscow")).date()
    data = collect_languages(args.owner, args.scope, lambda route: api_json(route, token), today)
    changed = write_chart(args.output, data, today.isoformat())
    print(f'Repositories: {data["repositories"]}; private: {data["private"]}; public: {data["public"]}; pushed since: {data["since"]}; chart {"updated" if changed else "unchanged"}')


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
