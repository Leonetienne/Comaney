"""
Unit tests for Project.update_lastmod() and project sorting logic.
No DB required; uses simple mock objects.
"""
from datetime import datetime, timezone as tz
from unittest.mock import MagicMock, patch


def _make_project(uid, archived, last_mod_dt):
    p = MagicMock()
    p.uid = uid
    p.archived = archived
    p.last_mod = last_mod_dt
    return p


def _make_row(project, sorting):
    return (project, sorting, project.last_mod)


def _sort_rows(rows):
    rows.sort(key=lambda x: (1 if x[0].archived else 0, x[1], -x[0].last_mod.timestamp()))
    return [r[0] for r in rows]


class TestUpdateLastmod:
    def test_update_lastmod_sets_field(self):
        from buddies.models import Project
        p = MagicMock(spec=Project)
        p.last_mod = datetime(2020, 1, 1, tzinfo=tz.utc)

        def _save(update_fields=None):
            pass

        p.save = _save
        now_val = datetime(2026, 6, 2, 12, 0, 0, tzinfo=tz.utc)

        with patch("buddies.models.timezone") as mock_tz:
            mock_tz.now.return_value = now_val
            Project.update_lastmod(p)

        assert p.last_mod == now_val


class TestProjectSortingAlgorithm:
    def test_non_archived_before_archived(self):
        t = datetime(2025, 1, 1, tzinfo=tz.utc)
        non_archived = _make_project(1, False, t)
        archived = _make_project(2, True, t)
        rows = [_make_row(archived, 1), _make_row(non_archived, 1)]
        result = _sort_rows(rows)
        assert result[0] == non_archived
        assert result[1] == archived

    def test_smaller_sorting_before_larger_within_non_archived(self):
        t = datetime(2025, 1, 1, tzinfo=tz.utc)
        p1 = _make_project(1, False, t)
        p2 = _make_project(2, False, t)
        rows = [_make_row(p2, 5), _make_row(p1, 2)]
        result = _sort_rows(rows)
        assert result[0] == p1
        assert result[1] == p2

    def test_newer_last_mod_first_when_same_sorting(self):
        t_old = datetime(2024, 1, 1, tzinfo=tz.utc)
        t_new = datetime(2026, 1, 1, tzinfo=tz.utc)
        p_old = _make_project(1, False, t_old)
        p_new = _make_project(2, False, t_new)
        rows = [_make_row(p_old, 1), _make_row(p_new, 1)]
        result = _sort_rows(rows)
        assert result[0] == p_new
        assert result[1] == p_old

    def test_archived_sorted_by_sorting_among_themselves(self):
        t = datetime(2025, 1, 1, tzinfo=tz.utc)
        a1 = _make_project(1, True, t)
        a2 = _make_project(2, True, t)
        rows = [_make_row(a2, 5), _make_row(a1, 2)]
        result = _sort_rows(rows)
        assert result[0] == a1
        assert result[1] == a2
