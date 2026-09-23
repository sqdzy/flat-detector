# Avito read-only browser probe

**Status:** experimental, owner-invoked, disabled by default. It is a technical feasibility probe, not a claim that Avito authorizes automated extraction.

The probe uses a normal Playwright Chromium session with a persistent profile. It deliberately does **not** modify browser fingerprints, solve CAPTCHA, rotate proxies/IPs, import third-party cookies or bypass access controls. A 403, 429, CAPTCHA/challenge, transport error, or unexpected page structure produces a non-zero exit and **no database write**.

## Why this is a separate container

The browser image is separate from the API/Telegram image. It has no PostgreSQL secret, no Telegram token, no internal application network, and no Docker socket. Its root filesystem is read-only, while a dedicated named volume stores only the Chromium profile. The service is limited to 768 MiB RAM and 256 MiB shared memory.

This keeps a compromised rendering process away from subscriber data and bot credentials.

## First operator test

1. In a normal browser, create the exact Avito search you want: sale / apartment / one room / Khimki / max 9,000,000 RUB. Copy the resulting public `https://www.avito.ru/...` search URL. Do not copy cookies or authorization data.
2. On the VPS update the branch and build only the isolated scraper image:

```bash
cd /opt/flat-detector
git status --short
git pull --ff-only origin feat/mvp-v0.2
docker compose --env-file .env --profile scraper build avito_probe
```

3. Run the completely offline Chromium smoke test first:

```bash
docker compose --env-file .env --profile scraper \
  run --rm --no-deps -T avito_probe --smoke
```

Expected: `Avito Chromium smoke: OK (offline fixture, zero external requests)`.

4. Then perform **one** live, read-only probe:

```bash
read -r -p "Avito search URL: " AVITO_URL
docker compose --env-file .env --profile scraper \
  run --rm --no-deps -T \
  -e FD_AVITO_SEARCH_URL="$AVITO_URL" \
  avito_probe --limit 20
unset AVITO_URL
```

On success it prints `AVITO_PROBE_OK` followed by normalized JSON lines containing only listing id/title/price/address/public URL. It does not create/update Source, Listing, Evidence, subscribers, or outbox rows.

## Exit states

- `20 / SourceChallenged`: 403 or challenge/CAPTCHA text detected. Stop automation and inspect manually.
- `21 / SourceRateLimited`: 429. Back off; do not retry in a tight loop.
- `22 / SourceUnavailable`: timeout/browser/server failure.
- `23 / StructureChanged`: HTTP response succeeded but expected public listing cards were not found. Review the rendered page/selectors before changing code.

None of these states means an apartment was removed.

## Selector evidence and maintenance

Current extraction prefers Avito's public `data-marker="item"` cards, `data-marker="item-title"`, `itemprop="price"` / `data-marker="item-price"`, and `data-marker="item-address"`. These hooks are corroborated by current open-source Avito parser implementations but are not a public compatibility contract, so the live probe must be tested before any DB integration.

The next gate, only after a successful live probe, is to snapshot a **small owner-observed HTML fixture or normalized JSON output**, write a dedicated Avito adapter into the existing evidence model, then run at a conservative interval. Do not wire the live browser directly to Telegram before that.
