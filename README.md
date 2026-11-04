# kaufland-api

A Python client and command-line receipt archive for the Kaufland Card. The
archive layout matches [lidlplus-api](https://github.com/Andre0512/lidl-plus):
JSON, a summary, HTML, a full-length JPG and an A4 PDF, grouped by month and
purchase date.

Kaufland does not return printable HTML. The transaction JSON from the card
API is stored untouched, then rendered locally. Login follows the same browser
flow as Lidl Plus: you sign in yourself, and only a refresh token is saved.

Receipt listing uses the endpoints documented by
[shinzo13/kaufland-cli](https://github.com/shinzo13/kaufland-cli) and
[Naxter/bonfire](https://github.com/Naxter/bonfire).
[receipt-radar](https://github.com/andrecedik/receipt-radar) parses PDFs you
export by hand and does not call the account API. This tool does.

## Setup with uv

```sh
uv sync --locked
uv run kaufland install-browser
```

Python 3.15. Chromium is stored in `.kaufland/browsers/`.

## Log in

```sh
uv run kaufland login --country DE --language de
```

A browser opens. Enter your email, password and any verification there.
Complete the flow within five minutes. The command stores a refresh token and
your account id in `.kaufland/auth.json` with owner-only permissions. Keep
that file private. Log in again if Kaufland expires or revokes the token.

## Download every available receipt

```sh
uv run kaufland download
```

```text
receipts/
  2026-10/
    2026-10-24/
      2026-10-24_<receipt-id>.json
      2026-10-24_<receipt-id>_summary.json
      2026-10-24_<receipt-id>.html
      2026-10-24_<receipt-id>.jpg
      2026-10-24_<receipt-id>.pdf
```

The plain JSON is the transaction returned by Kaufland. Amounts in that JSON
are minor units (cents). HTML, JPG and PDF show euros. Refund lines are a
second file with `-return-1` before the extension. Only purchases where the
Kaufland Card was scanned are available.

Run the same command again after an interruption. Existing JSON is reused and
JPG/PDF files are rebuilt. Use `--overwrite` to replace saved JSON with a
fresh listing.

```sh
uv run kaufland download --output receipts --overwrite
uv run kaufland convert --output receipts
```

`convert` rebuilds HTML, JPG and PDF from local JSON without logging in.
Individual receipt failures are recorded in `receipts/failures.json`; the
download continues and exits with status 1.

```sh
uv run kaufland download --period this-month
uv run kaufland download --period last-month
uv run kaufland download --since 2026-10-01 --until 2026-10-31
uv run kaufland convert --period this-year
```

Both endpoints are inclusive. Presets use your computer's local date. Epoch
timestamps are read as Europe/Berlin calendar dates. ISO timestamps keep the
date in the timestamp itself.

```sh
uv run kaufland --auth-file /private/path/auth.json download --output /private/path/receipts
```

## Python API

```python
from kaufland_api import KauflandApi, download_receipts

api = KauflandApi(
    "de", "DE", refresh_token="YOUR_REFRESH_TOKEN", user_id="YOUR_USER_ID"
)
for transaction in api.iter_receipts(period="last-month"):
    print(transaction["id"], transaction.get("sum"))

download_receipts(api, "receipts", since="2026-10-01", until="2026-10-31")
```

## Development

```sh
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

## Legal Notice

This application is an open source project written in Python. It uses
interfaces of the Kaufland Card application, owned by **Kaufland**. The
application was created solely for educational purposes and is not affiliated
with Kaufland. The creator of the application is not affiliated with Kaufland
in any way and does not derive any financial benefits from this project. All
trademarks, trade names, and logos are the property of their respective
owners. Users use the application at their own risk.
