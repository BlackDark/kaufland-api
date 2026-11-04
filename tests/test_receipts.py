import json
import stat
from datetime import date, datetime
from unittest.mock import MagicMock, Mock
from zoneinfo import ZoneInfo

import pytest

from kaufland_api import KauflandApi
from kaufland_api.api import MissingLogin
from kaufland_api.archive import download_receipts, receipt_destination
from kaufland_api.cli import save_auth
from kaufland_api.dates import DateRange, receipt_date, resolve_date_range
from kaufland_api.html import receipt_html


def test_missing_login_has_useful_error():
    with pytest.raises(MissingLogin, match="login"):
        KauflandApi("de", "DE")._headers()


def test_pagination_and_overlapping_results():
    api = KauflandApi("de", "DE", "refresh", "user")
    api._page_size = 2
    api.transactions = Mock(
        side_effect=[
            {
                "transactions": [
                    {"id": "a", "timestamp": "2026-10-01"},
                    {"id": "b", "timestamp": "2026-10-02"},
                ],
                "totalCount": 3,
            },
            {
                "transactions": [
                    {"id": "b", "timestamp": "2026-10-02"},
                    {"id": "c", "timestamp": "2026-10-03"},
                ],
                "totalCount": 3,
            },
        ]
    )
    assert [ticket["id"] for ticket in api.iter_receipts()] == ["a", "b", "c"]
    assert api.transactions.call_args.kwargs == {"start": 2, "limit": 2}


def test_repeated_page_does_not_loop_forever():
    api = KauflandApi("de", "DE", "refresh", "user")
    api._page_size = 1
    api.transactions = Mock(
        return_value={
            "transactions": [{"id": "a", "timestamp": "2026-10-01"}],
            "totalCount": 10,
        }
    )
    with pytest.raises(ValueError, match="repeated"):
        list(api.iter_receipts())


def test_truncated_listing_is_reported():
    api = KauflandApi("de", "DE", "refresh", "user")
    api.transactions = Mock(return_value={"transactions": [], "totalCount": 4})
    with pytest.raises(ValueError, match="total"):
        list(api.iter_receipts())


def test_auth_file_is_private_and_replaced(tmp_path):
    api = KauflandApi("de", "DE", "first", "user-1")
    path = tmp_path / "auth.json"
    save_auth(path, api)
    api._refresh_token = "rotated"
    save_auth(path, api)
    saved = json.loads(path.read_text())
    assert saved["refresh_token"] == "rotated"
    assert saved["user_id"] == "user-1"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_originals_survive_render_failure_and_resume(tmp_path, monkeypatch):
    api = Mock()
    api.iter_receipts.return_value = [
        {
            "id": "../../escape",
            "timestamp": "2026-10-24T10:00:00+02:00",
            "positions": [{"name": "Milch", "total": 99}],
            "sum": 99,
        },
        {
            "id": "good",
            "timestamp": "2026-10-24T11:00:00+02:00",
            "positions": [],
            "sum": 0,
        },
    ]
    monkeypatch.setattr("kaufland_api.archive.renderer", MagicMock())
    render = Mock(side_effect=[ValueError("bad render"), None])
    monkeypatch.setattr("kaufland_api.archive.render_receipt", render)
    count, failures = download_receipts(api, tmp_path, progress=lambda _: None)
    assert count == 1
    assert failures[0]["id"] == "../../escape"
    assert (
        receipt_destination(tmp_path, {"id": "../../escape", "date": "2026-10-24"})
        .with_suffix(".json")
        .exists()
    )
    render.side_effect = None
    count, failures = download_receipts(api, tmp_path, progress=lambda _: None)
    assert (count, failures) == (2, [])


def test_calendar_presets():
    assert resolve_date_range(
        period="last-month", today=date(2026, 1, 10)
    ) == DateRange(date(2025, 12, 1), date(2025, 12, 31))


def test_inclusive_dates_and_epoch():
    dates = resolve_date_range(since="2026-10-01", until="2026-10-31")
    assert dates.matches({"timestamp": "2026-10-01T00:00:00+02:00"})
    assert dates.matches({"date": "2026-10-31"})
    assert not dates.matches({"timestamp": "2026-11-01"})
    epoch = datetime(2026, 10, 24, 12, tzinfo=ZoneInfo("Europe/Berlin")).timestamp()
    assert receipt_date({"timestamp": epoch}) == date(2026, 10, 24)


def test_cli_rejects_invalid_filters_before_login(monkeypatch, capsys):
    from kaufland_api.cli import main

    monkeypatch.setattr(
        "sys.argv",
        ["kaufland", "download", "--period", "this-month", "--since", "2026-01-01"],
    )
    assert main() == 1
    assert "either period or since/until" in capsys.readouterr().err


def test_oauth_callback_checks_state():
    api = KauflandApi("de", "DE")
    api._oauth_state = "expected"
    assert (
        api._callback_code(
            "com.kaufland.kaufland://oauth/callback?state=expected&code=a%2Bb"
        )
        == "a+b"
    )
    with pytest.raises(MissingLogin, match="state"):
        api._callback_code(
            "com.kaufland.kaufland://oauth/callback?state=wrong&code=bad"
        )
    assert (
        api._callback_code("https://account.kaufland.com/?state=expected&code=bad")
        is None
    )


def test_refresh_http_errors_do_not_replace_token(monkeypatch):
    import requests

    response = Mock()
    response.raise_for_status.side_effect = requests.HTTPError("unauthorized")
    monkeypatch.setattr("kaufland_api.api.requests.post", Mock(return_value=response))
    api = KauflandApi("de", "DE", "existing", "user")
    with pytest.raises(requests.HTTPError):
        api._renew_token()
    assert api.refresh_token == "existing"


def test_html_escapes_item_names_and_formats_cents():
    document = receipt_html(
        {
            "id": "r1",
            "timestamp": "2026-10-24T10:00:00+02:00",
            "currency": "EUR",
            "sum": 199,
            "positions": [{"name": "<b>Äpfel</b>", "quantity": 2, "total": 199}],
            "refundPositions": [{"name": "Pfand", "total": -25}],
        }
    )
    assert "&lt;b&gt;Äpfel&lt;/b&gt;" in document
    assert "1,99" in document
    assert "<script>" not in document


def test_download_filters_and_writes_summary(tmp_path, monkeypatch):
    api = KauflandApi("de", "DE", "refresh", "user")
    api.transactions = Mock(
        return_value={
            "totalCount": 2,
            "transactions": [
                {
                    "id": "outside",
                    "timestamp": "2026-09-30",
                    "positions": [],
                    "sum": 10,
                },
                {
                    "id": "selected",
                    "timestamp": "2026-10-01T08:00:00+02:00",
                    "positions": [{"name": "Brot", "total": 250}],
                    "sum": 250,
                    "currency": "EUR",
                },
            ],
        }
    )
    monkeypatch.setattr("kaufland_api.archive.renderer", MagicMock())
    render = Mock()
    monkeypatch.setattr("kaufland_api.archive.render_receipt", render)
    assert download_receipts(
        api, tmp_path, since="2026-10-01", until="2026-10-31", progress=lambda _: None
    ) == (1, [])
    render.assert_called_once()
    saved = json.loads(
        (tmp_path / "2026-10/2026-10-01/2026-10-01_selected.json").read_text()
    )
    summary = json.loads(
        (tmp_path / "2026-10/2026-10-01/2026-10-01_selected_summary.json").read_text()
    )
    assert saved["positions"][0]["name"] == "Brot"
    assert summary["date"] == "2026-10-01"
    assert summary["items"] == 1
