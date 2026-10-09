from ekumidayomi.auth.rate_limits import private_identifier


def test_limit_identifiers_do_not_expose_pii() -> None:
    value = private_identifier("customer@example.com", "a dedicated test secret")
    assert len(value) == 64
    assert "customer" not in value
    assert value != private_identifier("customer@example.com", "a rotated test secret")
