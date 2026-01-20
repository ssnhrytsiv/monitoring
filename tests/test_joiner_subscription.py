import sys
import types

import pytest

# Підміняємо queue_worker, щоб уникнути циклічного імпорту у subscription_worker під час тестів.
dummy_qw = types.SimpleNamespace(process_batch=None)
sys.modules.setdefault("app.admin_bot.services.subscription.subscription_worker", dummy_qw)

from app.services import joiner  # noqa: E402

try:
    from app.admin_bot.services.subscription import subscription_worker as sw
except ImportError:  # pragma: no cover - якщо модуль не зібрався через цикли, пропустимо тести sw
    sw = None


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://t.me/+abcdEFGH12345678", "abcdEFGH12345678"),
        (" https://t.me/joinchat/abcdEFGH12345678 ", "abcdEFGH12345678"),
        ("t.me/+abcdEFGH12345678", "abcdEFGH12345678"),
        ("https://t.me/username", None),
        ("", None),
    ],
)
def test_joiner_extract_invite_hash(url, expected):
    assert joiner._extract_invite_hash(url) == expected


@pytest.mark.parametrize(
    "h,expected",
    [
        ("abcdEFGH12345678", True),
        ("short", False),
        ("a" * 70, False),
        ("bad space", False),
        ("bad#", False),
    ],
)
def test_joiner_plausible_invite_hash(h, expected):
    assert joiner._plausible_invite_hash(h) is expected


@pytest.mark.parametrize(
    "url,should_match",
    [
        ("https://t.me/", False),
        ("https://t.me/+", True),
        ("https://t.me/joinchat/", True),
        ("https://t.me/joinchat/+ ", True),
    ],
)
def test_subscription_invite_stub_regex(url, should_match):
    if sw is None:
        pytest.skip("subscription_worker not importable in test env")
    m = sw._INVITE_STUB_RE.match(url)
    assert (m is not None) is should_match
