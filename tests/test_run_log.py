"""
Tests for run_log.py — DB calls are mocked.
"""

from unittest.mock import MagicMock, patch

from app import run_log


def _mock_conn(fetchone_return=None):
    """Build a mock psycopg2 connection with a cursor context manager."""
    mock_cur = MagicMock()
    mock_cur.fetchone.return_value = fetchone_return

    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__ = lambda s: mock_cur
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    return mock_conn, mock_cur


# ── start_run ──────────────────────────────────────────────────────────────────

class TestStartRun:
    def test_returns_run_id_on_success(self):
        mock_conn, mock_cur = _mock_conn(fetchone_return=(42,))
        with patch("app.run_log._connect", return_value=mock_conn):
            result = run_log.start_run("postgresql://test", "ingest_donations")
        assert result == 42

    def test_commits_and_closes_connection(self):
        mock_conn, _ = _mock_conn(fetchone_return=(1,))
        with patch("app.run_log._connect", return_value=mock_conn):
            run_log.start_run("postgresql://test", "ingest_donations")
        mock_conn.commit.assert_called_once()
        mock_conn.close.assert_called_once()

    def test_inserts_with_running_status(self):
        mock_conn, mock_cur = _mock_conn(fetchone_return=(1,))
        with patch("app.run_log._connect", return_value=mock_conn):
            run_log.start_run("postgresql://test", "ingest_votes")
        sql, args = mock_cur.execute.call_args[0]
        assert "running" in sql
        assert "ingest_votes" in args

    def test_returns_none_when_db_unavailable(self):
        with patch("app.run_log._connect", side_effect=Exception("connection refused")):
            result = run_log.start_run("postgresql://test", "ingest_donations")
        assert result is None

    def test_does_not_raise_when_db_unavailable(self):
        with patch("app.run_log._connect", side_effect=Exception("db error")):
            run_log.start_run("postgresql://test", "ingest_interests")  # must not raise


# ── finish_run ─────────────────────────────────────────────────────────────────

class TestFinishRun:
    def test_updates_row_with_correct_counts(self):
        mock_conn, mock_cur = _mock_conn()
        with patch("app.run_log._connect", return_value=mock_conn):
            run_log.finish_run("postgresql://test", 42, "success",
                               embedded=1000, skipped=500, errors=0)
        args = mock_cur.execute.call_args[0][1]
        # args: (finished_at, last_updated_at, status, embedded, skipped, errors, notes, run_id)
        assert args[2] == "success"
        assert args[3] == 1000   # embedded
        assert args[4] == 500    # skipped
        assert args[5] == 0      # errors
        assert args[7] == 42     # WHERE id = run_id

    def test_commits_and_closes_connection(self):
        mock_conn, _ = _mock_conn()
        with patch("app.run_log._connect", return_value=mock_conn):
            run_log.finish_run("postgresql://test", 1, "success")
        mock_conn.commit.assert_called_once()
        mock_conn.close.assert_called_once()

    def test_noop_when_run_id_is_none(self):
        with patch("app.run_log._connect") as mock_connect:
            run_log.finish_run("postgresql://test", None, "success")
        mock_connect.assert_not_called()

    def test_records_error_status_and_notes(self):
        mock_conn, mock_cur = _mock_conn()
        with patch("app.run_log._connect", return_value=mock_conn):
            run_log.finish_run("postgresql://test", 5, "error", notes="disk full")
        args = mock_cur.execute.call_args[0][1]
        # args: (finished_at, last_updated_at, status, embedded, skipped, errors, notes, run_id)
        assert args[2] == "error"
        assert args[6] == "disk full"

    def test_does_not_raise_when_db_unavailable(self):
        with patch("app.run_log._connect", side_effect=Exception("db error")):
            run_log.finish_run("postgresql://test", 1, "success")  # must not raise
