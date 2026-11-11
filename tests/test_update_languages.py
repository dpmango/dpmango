import importlib.util
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest


spec = importlib.util.spec_from_file_location("update_languages", Path(__file__).parents[1] / "scripts/update_languages.py")
chart = importlib.util.module_from_spec(spec)
spec.loader.exec_module(chart)


class LanguageChartTests(unittest.TestCase):
    def test_missing_private_access_keeps_the_existing_chart(self):
        def fetch(route):
            return {"login": "dpmango"} if route == "/user" else [{"fork": False, "private": False, "owner": {"login": "dpmango"}}]

        with self.assertRaisesRegex(RuntimeError, "Private repositories are not visible"):
            chart.collect_languages("dpmango", "all", fetch)

    def test_a_failed_repository_does_not_become_partial_statistics(self):
        def fetch(route):
            if route == "/user":
                return {"login": "dpmango"}
            if route.startswith("/user/repos?"):
                return [{"fork": False, "private": True, "owner": {"login": "dpmango"}, "full_name": "dpmango/example", "pushed_at": "2026-11-11T00:00:00Z"}]
            raise RuntimeError("GitHub metadata request failed (HTTP 403)")

        with self.assertRaisesRegex(RuntimeError, "HTTP 403"):
            chart.collect_languages("dpmango", "all", fetch, date(2026, 11, 11))

    def test_five_year_window_includes_boundary_and_excludes_forks(self):
        base = {"fork": False, "private": True, "owner": {"login": "dpmango"}}
        repositories = [
            {**base, "full_name": "dpmango/boundary", "pushed_at": "2021-11-10T21:00:00Z"},
            {**base, "full_name": "dpmango/public", "private": False, "pushed_at": "2026-11-11T00:00:00Z"},
            {**base, "full_name": "dpmango/old", "pushed_at": "2021-11-10T20:59:59Z"},
            {**base, "full_name": "dpmango/empty", "pushed_at": None},
            {**base, "full_name": "dpmango/fork", "fork": True, "pushed_at": "2026-11-11T00:00:00Z"},
        ]
        languages = {"/repos/dpmango/boundary/languages": {"TypeScript": 3}, "/repos/dpmango/public/languages": {"Python": 1}}

        def fetch(route):
            if route == "/user":
                return {"login": "dpmango"}
            if route.startswith("/user/repos?"):
                return repositories
            return languages[route]

        result = chart.collect_languages("dpmango", "all", fetch, date(2026, 11, 11))
        self.assertEqual(result, {"scope": "all", "period_years": 5, "since": "2021-11-11", "repositories": 2, "private": 1, "public": 1, "languages": {"TypeScript": 3, "Python": 1}})
        private = chart.collect_languages("dpmango", "private", fetch, date(2026, 11, 11))
        self.assertEqual((private["repositories"], private["private"], private["public"], private["languages"]), (1, 1, 0, {"TypeScript": 3}))

    def test_leap_day_uses_five_calendar_years(self):
        def fetch(route):
            if route == "/user":
                return {"login": "dpmango"}
            if route.startswith("/user/repos?"):
                return [{"fork": False, "private": True, "owner": {"login": "dpmango"}, "full_name": "dpmango/example", "pushed_at": "2023-02-28T00:00:00Z"}]
            return {"TypeScript": 1}

        result = chart.collect_languages("dpmango", "all", fetch, date(2028, 2, 29))
        self.assertEqual(result["since"], "2023-02-28")
        self.assertEqual(result["repositories"], 1)

    def test_unchanged_data_does_not_create_daily_date_only_commits(self):
        data = {"scope": "all", "period_years": 5, "since": "2021-11-11", "repositories": 2, "private": 1, "public": 1, "languages": {"TypeScript": 3, "Python": 1}}
        with TemporaryDirectory() as directory:
            target = Path(directory) / "languages.svg"
            self.assertTrue(chart.write_chart(target, data, "2026-11-11"))
            original = target.read_text()
            self.assertFalse(chart.write_chart(target, {**data, "since": "2021-11-12"}, "2026-11-12"))
            self.assertEqual(target.read_text(), original)
            self.assertTrue(chart.write_chart(target, {**data, "languages": {"TypeScript": 4, "Python": 1}}, "2026-11-12"))


if __name__ == "__main__":
    unittest.main()
