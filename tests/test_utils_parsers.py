from __future__ import annotations

from app.utils import link_parser as lp
from app.utils import html_normalize as hn


def test_normalize_and_sanitize():
    assert lp.normalize("@user") == "https://t.me/user"
    assert lp.normalize("t.me/foo") == "https://t.me/foo"
    assert lp.normalize("https://t.me/bar") == "https://t.me/bar"
    assert lp.sanitize_link("htps://t.me/foo") == "https://t.me/foo"
    assert lp.sanitize_link("tg://resolve?domain=FooBot") == "https://t.me/FooBot"
    assert lp.sanitize_link("https://https://t.me/dup") == "https://t.me/dup"


def test_extract_links_regex_and_markups():
    text = (
        "md [link](https://t.me/test1) "
        '<a href="https://t.me/test2">t2</a> '
        "raw t.me/test3 and @user4"
    )
    urls = lp.extract_links(text)
    assert urls == [
        "https://t.me/test1",
        "https://t.me/test2",
        "https://t.me/test3",
        "https://t.me/user4",
    ]


def test_extract_links_norm_and_html():
    plain = "see https://t.me/a, https://t.me/a (dup), and @name"
    assert lp.extract_links_norm(plain) == ["https://t.me/a", "https://t.me/name"]

    html = '<b>Hi</b> <a href="https://t.me/x">https://t.me/x</a> t.me/y'
    assert lp.extract_links_from_html(html) == ["https://t.me/x", "https://t.me/y"]


def test_extract_bot_username_and_invite():
    assert lp.extract_bot_username("https://t.me/echoBot") == "echoBot"
    assert lp.extract_bot_username("@foo_bot") == "foo_bot"
    assert lp.extract_bot_username("https://t.me/channel") is None
    assert lp.is_invite("https://t.me/+Abcd") is True
    assert lp.is_invite("https://t.me/joinchat/abcd") is True
    assert lp.is_invite("https://t.me/channel") is False


def test_html_strip_and_normalize_links():
    assert hn.strip_simple_tags("<b>x</b><i>y</i>") == "xy"
    html = '<a href="https://t.me/x"><b>https://t.me/x</b></a>'
    # link body equals href -> unwrap to plain href
    assert hn.normalize_html_links(html) == "https://t.me/x"


def test_normalize_html_full_and_edit():
    src = "Hi&nbsp;<br>there <p>world</p>\u200b"
    norm = hn.normalize_html_full(src)
    assert norm == "Hi there world"

    strict = hn.normalize_html_for_edit(" A <br>  B ")
    assert strict == "A\nB"


def test_strip_tags_to_text():
    html = "<b>Hello</b> <i>world</i> &amp; all"
    assert hn.strip_tags_to_text(html) == "Hello world & all"
