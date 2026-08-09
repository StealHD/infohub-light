from src.auth import AuthSettings, hash_password, verify_password_hash


def test_auth_password_hash_verification() -> None:
    stored_hash = hash_password("correct horse battery staple")

    assert verify_password_hash("correct horse battery staple", stored_hash)
    assert not verify_password_hash("wrong", stored_hash)
    assert not verify_password_hash(
        "correct horse battery staple",
        "not-a-valid-hash",
    )


def test_auth_settings_use_bounded_database_session_environment(monkeypatch) -> None:
    monkeypatch.setenv("HORIZON_AUTH_SECURE_COOKIE", "true")
    monkeypatch.setenv("HORIZON_AUTH_SESSION_TTL_SECONDS", "120")

    settings = AuthSettings.from_env()

    assert settings.cookie_secure is True
    assert settings.session_ttl_seconds == 300


def test_auth_settings_ignore_invalid_session_ttl(monkeypatch) -> None:
    monkeypatch.setenv("HORIZON_AUTH_SESSION_TTL_SECONDS", "invalid")

    settings = AuthSettings.from_env()

    assert settings.session_ttl_seconds == 7 * 24 * 60 * 60
