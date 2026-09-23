"""Read-only Avito search probe using a normal Playwright Chromium session.

This module intentionally does not modify browser fingerprints, solve CAPTCHA, rotate
proxies, or bypass access controls. The live probe is operator-invoked and read-only:
it prints normalized public search-card fields and never writes to the database.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit

MAX_ITEMS = 50
ALLOWED_HOSTS = {"avito.ru", "www.avito.ru"}
CHALLENGE_MARKERS = (
    "captcha",
    "капча",
    "подтвердите, что вы человек",
    "доступ временно ограничен",
    "доступ ограничен",
    "проверка браузера",
)


@dataclass(frozen=True)
class AvitoCandidate:
    external_id: str
    title: str
    price_rub: int | None
    address: str | None
    url: str


class ProbeError(RuntimeError):
    exit_code = 1


class SourceChallenged(ProbeError):
    exit_code = 20


class SourceRateLimited(ProbeError):
    exit_code = 21


class SourceUnavailable(ProbeError):
    exit_code = 22


class StructureChanged(ProbeError):
    exit_code = 23


def validate_search_url(raw: str) -> str:
    """Allow only ordinary HTTPS Avito URLs with no embedded credentials."""
    if not raw or len(raw) > 2000:
        raise ValueError("FD_AVITO_SEARCH_URL is required and must be <= 2000 characters")
    p = urlsplit(raw)
    if p.scheme != "https" or (p.hostname or "").lower() not in ALLOWED_HOSTS:
        raise ValueError("Search URL must use https://avito.ru or https://www.avito.ru")
    if p.username or p.password or p.port not in (None, 443):
        raise ValueError("Search URL cannot contain credentials or a non-HTTPS port")
    if not p.path.startswith("/"):
        raise ValueError("Invalid Avito search path")
    return raw


def canonical_listing_url(raw: str, base: str = "https://www.avito.ru") -> str:
    absolute = urljoin(base, raw)
    p = urlsplit(absolute)
    if p.scheme != "https" or (p.hostname or "").lower() not in ALLOWED_HOSTS:
        raise ValueError("Listing link left the Avito origin")
    if p.username or p.password or p.port not in (None, 443):
        raise ValueError("Unsafe listing URL")
    return urlunsplit(("https", p.netloc.lower(), p.path, "", ""))


def external_id_from_url(url: str) -> str:
    path = urlsplit(url).path
    match = re.search(r"_(\d{5,})(?:/)?$", path)
    if match:
        return match.group(1)
    return "url-" + hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]


def parse_price(raw: str | None) -> int | None:
    if raw is None:
        return None
    digits = "".join(ch for ch in raw if ch.isdigit())
    if not digits:
        return None
    value = int(digits)
    return value if 0 < value <= 1_000_000_000 else None


def classify_page(status: int | None, body_text: str, card_count: int) -> str:
    """Classify transport/challenge state without treating denial as listing removal."""
    if status == 429:
        return "RATE_LIMITED"
    if status == 403:
        return "CHALLENGED"
    if status is not None and status >= 500:
        return "UNAVAILABLE"
    lower = body_text.lower()
    if any(marker in lower for marker in CHALLENGE_MARKERS):
        return "CHALLENGED"
    if card_count == 0:
        return "STRUCTURE_CHANGED"
    return "OK"


def _first_text(root, selectors: tuple[str, ...]) -> str | None:
    for selector in selectors:
        loc = root.locator(selector).first
        try:
            if loc.count():
                value = loc.inner_text(timeout=1200).strip()
                if value:
                    return value
        except Exception:
            continue
    return None


def _first_attr(root, selectors: tuple[str, ...], name: str) -> str | None:
    for selector in selectors:
        loc = root.locator(selector).first
        try:
            if loc.count():
                value = loc.get_attribute(name, timeout=1200)
                if value:
                    return value.strip()
        except Exception:
            continue
    return None


def extract_candidates(page, *, limit: int = MAX_ITEMS) -> list[AvitoCandidate]:
    """Extract only fields visible in search cards using current public data-marker hooks."""
    cards = page.locator('[data-marker="item"]')
    count = min(cards.count(), limit)
    result: list[AvitoCandidate] = []
    seen: set[str] = set()

    for index in range(count):
        card = cards.nth(index)
        href = _first_attr(
            card,
            (
                'a[data-marker="item-title"]',
                '[data-marker="item-title"] a',
                'a[href*="/kvartiry/"]',
            ),
            "href",
        )
        if not href:
            continue
        try:
            url = canonical_listing_url(href)
        except ValueError:
            continue
        if url in seen:
            continue

        title = _first_text(
            card,
            (
                '[data-marker="item-title"]',
                'h3[itemprop="name"]',
            ),
        )
        if not title:
            continue

        price_raw = _first_attr(card, ('meta[itemprop="price"]',), "content")
        if not price_raw:
            price_raw = _first_text(
                card,
                (
                    '[data-marker="item-price"]',
                    '[itemprop="price"]',
                ),
            )
        address = _first_text(
            card,
            (
                '[data-marker="item-address"]',
                '[data-marker="item-location"]',
            ),
        )

        seen.add(url)
        result.append(
            AvitoCandidate(
                external_id=external_id_from_url(url),
                title=title[:240],
                price_rub=parse_price(price_raw),
                address=address[:250] if address else None,
                url=url,
            )
        )
    return result


def _launch_context(playwright, profile_dir: Path, *, headless: bool = True):
    profile_dir.mkdir(parents=True, exist_ok=True)
    return playwright.chromium.launch_persistent_context(
        user_data_dir=str(profile_dir),
        headless=headless,
        locale="ru-RU",
        viewport={"width": 1365, "height": 900},
        accept_downloads=False,
    )


def run_live_probe(search_url: str, profile_dir: Path) -> list[AvitoCandidate]:
    """Open exactly one operator-provided Avito search URL and inspect the rendered page."""
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright

    search_url = validate_search_url(search_url)

    try:
        with sync_playwright() as pw:
            context = _launch_context(pw, profile_dir)
            try:
                page = context.pages[0] if context.pages else context.new_page()
                response = page.goto(search_url, wait_until="domcontentloaded", timeout=45_000)
                page.wait_for_timeout(1800)

                final = urlsplit(page.url)
                if final.scheme != "https" or (final.hostname or "").lower() not in ALLOWED_HOSTS:
                    raise SourceChallenged("Navigation left the approved Avito origin; manual review required")

                body = page.locator("body").inner_text(timeout=5000)[:30_000]
                candidates = extract_candidates(page)
                state = classify_page(response.status if response else None, body, len(candidates))

                if state == "RATE_LIMITED":
                    raise SourceRateLimited("Avito returned 429; stop and retry later")
                if state == "CHALLENGED":
                    raise SourceChallenged("Avito returned a challenge/denial; manual review required")
                if state == "UNAVAILABLE":
                    raise SourceUnavailable("Avito returned a server error; no data was accepted")
                if state == "STRUCTURE_CHANGED":
                    raise StructureChanged("No listing cards found; page layout or search response needs review")
                return candidates
            finally:
                context.close()
    except PlaywrightTimeoutError:
        raise SourceUnavailable("Browser navigation timed out; no data was accepted") from None
    except PlaywrightError:
        raise SourceUnavailable("Browser automation failed; no data was accepted") from None


def browser_smoke() -> int:
    """Offline CI smoke: launch Chromium and parse a deterministic local DOM fixture."""
    from playwright.sync_api import sync_playwright

    html = """
    <main data-marker="catalog-serp">
      <div data-marker="item">
        <a data-marker="item-title" href="/himki/kvartiry/1-k._kvartira_33_m_123456789">1-к. квартира, 33 м²</a>
        <meta itemprop="price" content="7990000">
        <div data-marker="item-address">Химки, Тестовая улица</div>
      </div>
      <div data-marker="item">
        <a data-marker="item-title" href="/himki/kvartiry/1-k._kvartira_42_m_987654321">1-к. квартира, 42 м²</a>
        <div data-marker="item-price">8 750 000 ₽</div>
        <div data-marker="item-address">Химки, Тестовый проспект</div>
      </div>
    </main>
    """
    with tempfile.TemporaryDirectory(prefix="fd-avito-smoke-") as td:
        with sync_playwright() as pw:
            context = _launch_context(pw, Path(td))
            try:
                page = context.pages[0] if context.pages else context.new_page()
                page.set_content(html)
                rows = extract_candidates(page)
            finally:
                context.close()

    assert len(rows) == 2
    assert rows[0].external_id == "123456789"
    assert rows[0].price_rub == 7_990_000
    assert rows[1].price_rub == 8_750_000
    print("Avito Chromium smoke: OK (offline fixture, zero external requests)")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read-only Avito search probe")
    parser.add_argument("--smoke", action="store_true", help="offline browser+DOM smoke test")
    parser.add_argument(
        "--url",
        default=os.getenv("FD_AVITO_SEARCH_URL", ""),
        help="operator-provided public Avito search URL (or FD_AVITO_SEARCH_URL)",
    )
    parser.add_argument(
        "--profile-dir",
        default=os.getenv("FD_AVITO_PROFILE_DIR", "/browser-profile"),
        help="persistent Chromium profile directory",
    )
    parser.add_argument("--limit", type=int, default=20, help="maximum cards printed, 1..50")
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.smoke:
        return browser_smoke()
    if not 1 <= args.limit <= MAX_ITEMS:
        print("ERROR: --limit must be from 1 to 50", file=sys.stderr)
        return 2

    try:
        candidates = run_live_probe(args.url, Path(args.profile_dir))
    except ValueError as exc:
        print(f"CONFIG_ERROR: {exc}", file=sys.stderr)
        return 2
    except ProbeError as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return exc.exit_code

    print(f"AVITO_PROBE_OK cards={len(candidates)} mode=READ_ONLY no_database_write=true")
    for item in candidates[: args.limit]:
        print(json.dumps(asdict(item), ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
