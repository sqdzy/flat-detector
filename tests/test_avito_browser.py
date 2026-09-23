from flat_detector.avito_browser import (
    canonical_listing_url,
    classify_page,
    external_id_from_url,
    parse_price,
    validate_search_url,
)
import pytest


def test_validate_avito_search_url_accepts_only_exact_https_hosts():
    assert validate_search_url("https://www.avito.ru/himki/kvartiry/prodam") == "https://www.avito.ru/himki/kvartiry/prodam"
    assert validate_search_url("https://avito.ru/himki/kvartiry") == "https://avito.ru/himki/kvartiry"
    for bad in (
        "http://www.avito.ru/himki",
        "https://evil-avito.ru/himki",
        "https://www.avito.ru.evil.example/himki",
        "https://user:pass@www.avito.ru/himki",
        "https://www.avito.ru:8443/himki",
    ):
        with pytest.raises(ValueError):
            validate_search_url(bad)


def test_listing_url_is_canonical_and_same_origin():
    assert canonical_listing_url("/himki/kvartiry/test_123456789?utm_source=x#part") == (
        "https://www.avito.ru/himki/kvartiry/test_123456789"
    )
    with pytest.raises(ValueError):
        canonical_listing_url("https://example.org/listing/1")


def test_external_id_prefers_numeric_avito_suffix_and_has_stable_fallback():
    assert external_id_from_url("https://www.avito.ru/himki/kvartiry/test_123456789") == "123456789"
    value = external_id_from_url("https://www.avito.ru/himki/kvartiry/no_numeric_id")
    assert value.startswith("url-") and len(value) == 28
    assert value == external_id_from_url("https://www.avito.ru/himki/kvartiry/no_numeric_id")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("8 500 000 ₽", 8_500_000),
        ("7990000", 7_990_000),
        ("цена не указана", None),
        (None, None),
    ],
)
def test_parse_price(raw, expected):
    assert parse_price(raw) == expected


def test_page_state_never_treats_403_or_429_as_listing_removal():
    assert classify_page(403, "", 0) == "CHALLENGED"
    assert classify_page(429, "", 0) == "RATE_LIMITED"
    assert classify_page(200, "Подтвердите, что вы человек", 0) == "CHALLENGED"
    assert classify_page(503, "", 0) == "UNAVAILABLE"
    assert classify_page(200, "Обычная страница", 0) == "STRUCTURE_CHANGED"
    assert classify_page(200, "Обычная страница", 2) == "OK"

def test_cli_exposes_local_headed_browser_options():
    from flat_detector.avito_browser import _parser
    args = _parser().parse_args([
        "--url", "https://www.avito.ru/himki/kvartiry",
        "--headed", "--manual-wait", "--channel", "msedge",
    ])
    assert args.headed is True
    assert args.manual_wait is True
    assert args.channel == "msedge"
