"""Unit tests for EAM QEA Analyzer core helpers and safety-critical paths.

Run without the MASC fixture (pure logic tests):
    python -m unittest discover -s tests -v

Run WITH the official MASC fixture (NAF view integration tests):
    MASC_QEA_PATH=/path/to/Musterarchitektur_MASC.qea \
        python -m unittest discover -s tests -v

Requires: pandas, networkx (same as the tool itself). stdlib unittest only.
"""

import asyncio
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import eam_qea_tool as et
from eam_qea_tool import NAF_VIEW_STEREOTYPES, QEAAnalyzer, Tools, pg_clean_str

MASC_QEA = Path(os.environ["MASC_QEA_PATH"]) if os.environ.get("MASC_QEA_PATH") else None


# ── pg_clean_str ────────────────────────────────────────────────


class TestPgCleanStr(unittest.TestCase):
    def test_none_becomes_empty(self):
        self.assertEqual(pg_clean_str(None), "")

    def test_nan_variants_become_empty(self):
        self.assertEqual(pg_clean_str("nan"), "")
        self.assertEqual(pg_clean_str("NaN"), "")
        self.assertEqual(pg_clean_str(float("nan")), "")
        self.assertEqual(pg_clean_str("NAN"), "")

    def test_html_entities_decoded(self):
        self.assertEqual(pg_clean_str("F&#228;higkeitsforderung"), "Fähigkeitsforderung")
        self.assertEqual(
            pg_clean_str('F&#228;higkeitsforderung "Aufkl&#228;rung"'),
            'Fähigkeitsforderung "Aufklärung"',
        )
        self.assertEqual(pg_clean_str("A &amp; B"), "A & B")
        self.assertEqual(pg_clean_str("&lt;b&gt;fett&lt;/b&gt;"), "<b>fett</b>")
        self.assertEqual(pg_clean_str("It&#39;s"), "It's")
        self.assertEqual(pg_clean_str("&#39; &#34; &#60;"), "' \" <")

    def test_plain_strings_pass_through(self):
        self.assertEqual(pg_clean_str("plain"), "plain")
        self.assertEqual(pg_clean_str("bereits dekodiert: äöü"), "bereits dekodiert: äöü")

    def test_non_string_values_stringified(self):
        self.assertEqual(pg_clean_str(42), "42")
        self.assertEqual(pg_clean_str(3.5), "3.5")
        self.assertEqual(pg_clean_str(True), "True")

    def test_double_escaped_entities_decoded_once(self):
        # html.unescape handles repeated entities for the same char
        self.assertEqual(pg_clean_str("&amp;#228;"), "&#228;")


# ── NAF view mapping ───────────────────────────────────────────


class TestNafViewMapping(unittest.TestCase):
    def test_all_six_views_defined(self):
        for view in ["NAF-2", "NAF-3", "NAF-4", "NAF-5", "NAF-6", "NAF-7"]:
            self.assertIn(view, NAF_VIEW_STEREOTYPES, f"{view} missing")
            self.assertTrue(NAF_VIEW_STEREOTYPES[view], f"{view} has no stereotypes")

    def test_admbw_nav4_stereotypes_present(self):
        # Regression: MASC/ADMBw model uses NAFv4 stereotypes (AAroN review)
        self.assertIn("OperationalPerformer", NAF_VIEW_STEREOTYPES["NAF-2"])
        self.assertIn("OperationalRole", NAF_VIEW_STEREOTYPES["NAF-2"])
        self.assertIn("Organization", NAF_VIEW_STEREOTYPES["NAF-4"])
        self.assertIn("OperationalPerformer", NAF_VIEW_STEREOTYPES["NAF-4"])
        self.assertIn("ResourcePort", NAF_VIEW_STEREOTYPES["NAF-6"])
        self.assertIn("OperationalActivity", NAF_VIEW_STEREOTYPES["NAF-5"])

    def test_view_lookup_is_case_insensitive_and_falls_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "fallback.qea"
            conn = sqlite3.connect(db)
            conn.execute(
                "CREATE TABLE t_object (Object_ID INTEGER, Name TEXT, Object_Type TEXT,"
                " Stereotype TEXT, ea_guid TEXT, Package_ID INTEGER, Note TEXT,"
                " Status TEXT, Phase TEXT)"
            )
            conn.execute(
                "CREATE TABLE t_package (Package_ID INTEGER, Name TEXT)"
            )
            conn.execute(
                "INSERT INTO t_object VALUES (1,'NodeA','Class','OpNode','g1',0,'','','')"
            )
            conn.execute(
                "INSERT INTO t_object VALUES (2,'Weird','Class','NonsenseView','g2',0,'','','')"
            )
            conn.commit()
            conn.close()

            analyzer = QEAAnalyzer(str(db))
            try:
                rows = analyzer.get_naf_view_elements("naf-2")
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["Name"], "NodeA")
                # unknown view falls back to the view name as stereotype
                rows = analyzer.get_naf_view_elements("NonsenseView")
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["Name"], "Weird")
            finally:
                analyzer.close()


# ── NAF views against the official MASC fixture ────────────────


@unittest.skipUnless(
    MASC_QEA is not None and MASC_QEA.exists(),
    "MASC_QEA_PATH not set or fixture missing — set it to Musterarchitektur_MASC.qea",
)
class TestNafViewsWithMascFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.analyzer = QEAAnalyzer(str(MASC_QEA))

    @classmethod
    def tearDownClass(cls):
        cls.analyzer.close()

    def test_naf2_returns_elements(self):
        rows = self.analyzer.get_naf_view_elements("NAF-2")
        self.assertGreater(len(rows), 0, "NAF-2 must return elements")
        stereotypes = {r["Stereotype"] for r in rows}
        self.assertTrue(
            stereotypes & {"OperationalPerformer", "OperationalRole", "OperationalPort"},
            f"NAF-2 should hit ADMBw stereotypes, got {stereotypes}",
        )

    def test_naf4_returns_elements(self):
        rows = self.analyzer.get_naf_view_elements("NAF-4")
        self.assertGreater(len(rows), 0, "NAF-4 must return elements")
        stereotypes = {r["Stereotype"] for r in rows}
        self.assertTrue(
            stereotypes & {"Organization", "OperationalPerformer", "Post"},
            f"NAF-4 should hit ADMBw stereotypes, got {stereotypes}",
        )

    def test_naf6_returns_elements(self):
        rows = self.analyzer.get_naf_view_elements("NAF-6")
        self.assertGreater(len(rows), 0, "NAF-6 must return elements")
        stereotypes = {r["Stereotype"] for r in rows}
        self.assertTrue(
            stereotypes & {"ResourcePort", "ResourceExchange", "SystemPort"},
            f"NAF-6 should hit ADMBw stereotypes, got {stereotypes}",
        )

    def test_naf2357_still_work(self):
        # no regression for the originally working views
        for view in ("NAF-3", "NAF-5", "NAF-7"):
            rows = self.analyzer.get_naf_view_elements(view)
            self.assertGreater(len(rows), 0, f"{view} must return elements")


# ── execute_query limit & blocking ─────────────────────────────


class TestExecuteQuery(unittest.TestCase):
    ROWS = 1100

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "query_test.qea"
        conn = sqlite3.connect(self.db)
        conn.execute("CREATE TABLE t (id INTEGER, name TEXT)")
        conn.executemany(
            "INSERT INTO t VALUES (?, ?)",
            [(i, f"name-{i}") for i in range(self.ROWS)],
        )
        conn.commit()
        conn.close()
        self.analyzer = QEAAnalyzer(str(self.db))

    def tearDown(self):
        self.analyzer.close()
        self.tmp.cleanup()

    def test_select_allowed(self):
        rows = self.analyzer.execute_query("SELECT * FROM t")
        self.assertEqual(len(rows), 200)  # default cap

    def test_non_select_blocked(self):
        for sql in (
            "DROP TABLE t",
            "DELETE FROM t",
            "UPDATE t SET name='x'",
            "ATTACH DATABASE '/tmp/x' AS x",
            "PRAGMA journal_mode=WAL",
            "INSERT INTO t VALUES (1,'x')",
        ):
            result = self.analyzer.execute_query(sql)
            self.assertEqual(len(result), 1, sql)
            self.assertIn("error", result[0], sql)
            self.assertIn("Only SELECT queries allowed", result[0]["error"], sql)
        # table untouched
        self.assertEqual(
            self.analyzer.execute_query("SELECT COUNT(*) as c FROM t")[0]["c"], self.ROWS
        )

    def test_multi_statement_blocked(self):
        result = self.analyzer.execute_query("SELECT * FROM t; DROP TABLE t")
        self.assertEqual(len(result), 1)
        self.assertIn("Multiple statements are not allowed", result[0]["error"])
        self.assertEqual(
            self.analyzer.execute_query("SELECT COUNT(*) as c FROM t")[0]["c"], self.ROWS
        )

    def test_trailing_semicolon_allowed(self):
        rows = self.analyzer.execute_query("SELECT COUNT(*) as c FROM t;")
        self.assertEqual(rows[0]["c"], self.ROWS)

    def test_limit_clamped_to_minimum(self):
        self.assertEqual(len(self.analyzer.execute_query("SELECT * FROM t", limit=-1)), 1)
        self.assertEqual(len(self.analyzer.execute_query("SELECT * FROM t", limit=0)), 1)

    def test_limit_clamped_to_maximum(self):
        self.assertEqual(
            len(self.analyzer.execute_query("SELECT * FROM t", limit=999999)), 1000
        )

    def test_limit_none_uses_default(self):
        self.assertEqual(
            len(self.analyzer.execute_query("SELECT * FROM t", limit=None)), 200
        )

    def test_limit_string_literal_trick_is_capped(self):
        # regression: WHERE 'LIMIT'='LIMIT' used to bypass the cap
        rows = self.analyzer.execute_query(
            "SELECT id FROM t WHERE 'LIMIT'='LIMIT'", limit=5
        )
        self.assertEqual(len(rows), 5)

    def test_existing_trailing_limit_is_replaced(self):
        rows = self.analyzer.execute_query("SELECT id FROM t ORDER BY id LIMIT 2", limit=500)
        self.assertEqual(len(rows), 500)

    def test_existing_offset_limit_is_replaced(self):
        rows = self.analyzer.execute_query("SELECT id FROM t ORDER BY id LIMIT 3, 5", limit=500)
        self.assertEqual(len(rows), 500)

    def test_writefile_blocked(self):
        target = str(self.db) + ".evil"
        result = self.analyzer.execute_query(f"SELECT writefile('{target}','x')")
        self.assertEqual(len(result), 1)
        self.assertIn("error", result[0])
        self.assertFalse(Path(target).exists())

    def test_load_extension_blocked(self):
        result = self.analyzer.execute_query("SELECT load_extension('/tmp/x')")
        self.assertEqual(len(result), 1)
        self.assertIn("error", result[0])

    def test_sql_error_returned_not_raised(self):
        result = self.analyzer.execute_query("SELECT FROM WHERE")
        self.assertEqual(len(result), 1)
        self.assertIn("error", result[0])


# ── Newest-file selection ──────────────────────────────────────


class TestNewestFileSelection(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        tmpdir = Path(self.tmp.name)

        def make_db(path: Path, rows: int) -> None:
            conn = sqlite3.connect(path)
            conn.execute(
                "CREATE TABLE t_object (Object_ID INTEGER, Name TEXT,"
                " Object_Type TEXT, Stereotype TEXT)"
            )
            conn.executemany(
                "INSERT INTO t_object VALUES (?, ?, 'Class', '')",
                [(i, f"obj-{i}") for i in range(rows)],
            )
            conn.commit()
            conn.close()

        # old-but-big file: more rows -> bigger file, but older mtime
        self.old_big = tmpdir / "gross_alt.qea"
        make_db(self.old_big, 500)
        # new-but-small file: fewer rows -> smaller file, newer mtime
        self.new_small = tmpdir / "klein_neu.qea"
        make_db(self.new_small, 7)

        old_mtime = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc).timestamp()
        new_mtime = datetime(2026, 10, 18, 12, 0, 0, tzinfo=timezone.utc).timestamp()
        os.utime(self.old_big, (old_mtime, old_mtime))
        os.utime(self.new_small, (new_mtime, new_mtime))

        self.assertTrue(
            self.old_big.stat().st_size > self.new_small.stat().st_size,
            "fixture must make the older file the bigger one",
        )

        self.tools = Tools()
        self.tools.valves.qea_search_dirs = str(tmpdir)

    def tearDown(self):
        self.tmp.cleanup()

    def test_discover_orders_by_mtime_not_size(self):
        files = self.tools._discover_qea_files()
        self.assertEqual([f["name"] for f in files], ["klein_neu.qea", "gross_alt.qea"])
        self.assertIn("mtime", files[0])
        self.assertIn("mtime_iso", files[0])
        self.assertIn("size_mb", files[0])

    def test_resolve_path_picks_newest(self):
        self.assertEqual(
            self.tools._resolve_qea_path(None), str(self.new_small)
        )

    def test_statistics_use_newest_file(self):
        out = asyncio.run(self.tools.analyze_qea_statistics())
        stats = json.loads(out)
        self.assertEqual(stats["Elements"], 7)

    def test_listing_mentions_newest_first(self):
        out = asyncio.run(self.tools.list_available_qea_files())
        listing = json.loads(out)
        self.assertEqual(
            [f["name"] for f in listing["files"]],
            ["klein_neu.qea", "gross_alt.qea"],
        )


if __name__ == "__main__":
    unittest.main()
