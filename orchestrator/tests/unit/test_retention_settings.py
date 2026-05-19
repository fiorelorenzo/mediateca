from orchestrator.core.retention.settings import RetentionSettings, load_retention_settings


def test_defaults_match_spec() -> None:
    s = RetentionSettings()
    assert s.retention_enabled is False
    assert s.retention_dry_run is True
    assert s.movie_ttl_days == 10
    assert s.movie_grace_days == 3
    assert s.series_ttl_days == 7
    assert s.series_grace_days == 3
    assert s.series_bait_first_n == 3
    assert s.series_lookahead_n == 3
    assert s.series_engagement_window_days == 30
    assert s.disk_pressure_target_free_pct == 20
    assert s.disk_pressure_critical_free_pct == 10
    assert s.disk_pressure_grace_days == 0
    assert s.retention_user_ids_include == []
    assert s.retention_user_ids_exclude == []
    assert s.retention_arr_keep_tag == "keep"
    assert s.retention_respect_jellyfin_favorites is True
    assert s.retention_max_deletes_per_day == 50
    assert s.retention_max_deletes_per_tick == 20
    assert s.retention_stale_watch_max_hours == 6
    assert s.retention_refetch_max_attempts == 5
    assert s.retention_refetch_min_interval_hours == 12


def test_load_from_db_settings_table(monkeypatch) -> None:
    fake = {
        "retention_enabled": "true",
        "movie_ttl_days": "20",
    }
    monkeypatch.setattr(
        "orchestrator.core.retention.settings._read_all_settings",
        lambda: fake,
    )
    s = load_retention_settings()
    assert s.retention_enabled is True
    assert s.movie_ttl_days == 20
    # Untouched defaults still apply
    assert s.series_ttl_days == 7
