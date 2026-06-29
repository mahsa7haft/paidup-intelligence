"""
Tests for database.py — the DB connection is mocked, so these run without a database.
"""

from unittest.mock import MagicMock, patch

import pytest

from app import database


def _mock_conn(rows):
    """Mock connection whose cursor (a context manager) returns `rows`."""
    mock_cur = MagicMock()
    mock_cur.fetchall.return_value = rows
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__ = lambda s: mock_cur
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    return mock_conn, mock_cur


class TestValidation:
    def test_unknown_table_raises(self):
        with pytest.raises(ValueError, match="Unknown table"):
            database.similarity_search("secret_table", [0.1, 0.2], 5)

    def test_k_below_one_raises(self):
        with pytest.raises(ValueError, match="k must be"):
            database.similarity_search("interests_vectors", [0.1, 0.2], 0)

    def test_unknown_table_is_rejected_before_any_db_call(self):
        # Injection guard: a bad table name never reaches the database.
        with patch("app.database._connect") as mock_connect:
            with pytest.raises(ValueError):
                database.similarity_search("votes_vectors; DROP TABLE x", [0.1], 3)
        mock_connect.assert_not_called()


class TestQueryBuilding:
    def test_casts_vector_and_names_table(self):
        mock_conn, mock_cur = _mock_conn([])
        with patch("app.database._connect", return_value=mock_conn):
            database.similarity_search("interests_vectors", [0.1, 0.2, 0.3], 5)
        sql, params = mock_cur.execute.call_args[0]
        assert "interests_vectors" in sql
        assert "::vector" in sql            # the cast that fixes vector <=> numeric[]
        assert "embedding <=>" in sql       # cosine distance operator
        assert params[2] == 5               # k passed through

    def test_vector_passed_as_literal_string(self):
        mock_conn, mock_cur = _mock_conn([])
        with patch("app.database._connect", return_value=mock_conn):
            database.similarity_search("interests_vectors", [0.1, 0.2], 3)
        _, params = mock_cur.execute.call_args[0]
        assert params[0] == "[0.1,0.2]"     # vector literal, not a Python list
        assert params[0] == params[1]       # same literal used for SELECT and ORDER BY

    def test_connection_is_closed(self):
        mock_conn, _ = _mock_conn([])
        with patch("app.database._connect", return_value=mock_conn):
            database.similarity_search("interests_vectors", [0.1], 1)
        mock_conn.close.assert_called_once()


class TestResults:
    def test_returns_list_of_dicts(self):
        rows = [{"mp_name": "Jane", "similarity": 0.9}, {"mp_name": "John", "similarity": 0.5}]
        mock_conn, _ = _mock_conn(rows)
        with patch("app.database._connect", return_value=mock_conn):
            result = database.similarity_search("interests_vectors", [0.1], 2)
        assert result == rows
        assert all(isinstance(r, dict) for r in result)


class TestReadUrl:
    def test_prefers_readonly_url(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL_READONLY", "postgresql://ro@host/db")
        monkeypatch.setenv("DATABASE_URL", "postgresql://rw@host/db")
        assert database._read_url() == "postgresql://ro@host/db"

    def test_falls_back_to_database_url(self, monkeypatch):
        monkeypatch.delenv("DATABASE_URL_READONLY", raising=False)
        monkeypatch.setenv("DATABASE_URL", "postgresql://rw@host/db")
        assert database._read_url() == "postgresql://rw@host/db"

    def test_normalises_postgres_scheme(self, monkeypatch):
        monkeypatch.delenv("DATABASE_URL_READONLY", raising=False)
        monkeypatch.setenv("DATABASE_URL", "postgres://rw@host/db")
        assert database._read_url().startswith("postgresql://")

    def test_raises_when_no_url(self, monkeypatch):
        monkeypatch.delenv("DATABASE_URL_READONLY", raising=False)
        monkeypatch.delenv("DATABASE_URL", raising=False)
        with pytest.raises(RuntimeError):
            database._read_url()
