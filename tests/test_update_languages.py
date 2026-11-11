import importlib.util
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
                return [{"fork": False, "private": True, "owner": {"login": "dpmango"}, "full_name": "dpmango/example"}]
            raise RuntimeError("GitHub metadata request failed (HTTP 403)")

        with self.assertRaisesRegex(RuntimeError, "HTTP 403"):
            chart.collect_languages("dpmango", "all", fetch)

    def test_unchanged_data_does_not_create_daily_date_only_commits(self):
        data = {"scope": "all", "repositories": 2, "private": 1, "public": 1, "languages": {"TypeScript": 3, "Python": 1}}
        with TemporaryDirectory() as directory:
            target = Path(directory) / "languages.svg"
            self.assertTrue(chart.write_chart(target, data, "2026-11-11"))
            original = target.read_text()
            self.assertFalse(chart.write_chart(target, data, "2026-11-12"))
            self.assertEqual(target.read_text(), original)
            self.assertTrue(chart.write_chart(target, {**data, "languages": {"TypeScript": 4, "Python": 1}}, "2026-11-12"))


if __name__ == "__main__":
    unittest.main()
