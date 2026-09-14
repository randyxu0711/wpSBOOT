from wpsboot.config import Settings
from wpsboot.services import hash_ip


def test_ipv6_clients_are_grouped_by_64_prefix(settings: Settings) -> None:
    assert hash_ip(settings, "2001:db8:1:2::1") == hash_ip(settings, "2001:db8:1:2:ffff::9")
    assert hash_ip(settings, "2001:db8:1:2::1") != hash_ip(settings, "2001:db8:1:3::1")


def test_ipv4_clients_are_kept_apart(settings: Settings) -> None:
    assert hash_ip(settings, "203.0.113.7") != hash_ip(settings, "203.0.113.8")
    assert hash_ip(settings, "::ffff:203.0.113.7") == hash_ip(settings, "203.0.113.7")


def test_unparseable_client_address(settings: Settings) -> None:
    assert hash_ip(settings, "unknown") == hash_ip(settings, "unknown")
