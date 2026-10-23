"""ensure_table and the create_agol_logins.sql file it runs."""
import fnmatch
import re
import tomllib
from pathlib import Path

from agol_analytics.update_agol_logins import ensure_table
from sample_data import load_pr_fis
from test_process_logins import OUTPUT_COLUMNS

REPO_ROOT = Path(__file__).resolve().parent.parent
SQL_FILE = REPO_ROOT / "agol_analytics" / "sql" / "create_agol_logins.sql"


class SqlFileRecorder:
    def __init__(self):
        self.sql_files_run: list[Path] = []

    def execute_sql_file(self, sql_path, format_strings=None):
        self.sql_files_run.append(Path(sql_path).resolve())


def table_columns() -> list[str]:
    return re.findall(r"^\s*(\w+)\s+(?:varchar|char|date|bigint)", SQL_FILE.read_text(), re.I | re.M)


def test_ensure_table_runs_the_create_sql_next_to_the_module():
    db = SqlFileRecorder()
    ensure_table(db)
    assert db.sql_files_run == [SQL_FILE]


def test_the_table_has_a_column_for_everything_process_logins_returns():
    assert set(OUTPUT_COLUMNS) <= set(table_columns())


def test_pr_identity_prid_fits_a_pr_id():
    width = int(re.search(r"pr_identity_prid\s+CHAR\((\d+)\)", SQL_FILE.read_text(), re.I).group(1))
    assert load_pr_fis().pr_identity_prid.str.len().max() <= width  # PR IDs are 18 digits


def test_request_id_is_the_primary_key():
    assert re.search(r"PRIMARY KEY \(request_id\)", SQL_FILE.read_text())


def test_the_create_sql_is_packaged():
    package_data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text()).get(
        "tool", {}).get("setuptools", {}).get("package-data", {}).get("agol_analytics", [])
    assert any(fnmatch.fnmatch("sql/create_agol_logins.sql", pattern) for pattern in package_data)
