"""Kaufland Card login and receipt listing.

Auth is OAuth2/PKCE against account.kaufland.com. Receipts are the transaction
objects from p.crm-dynamics.schwarz; that list is the full receipt payload.
"""

import base64
from datetime import datetime, timedelta, timezone
import hashlib
import re
import string
import time
from secrets import choice, token_urlsafe
from urllib.parse import parse_qs, quote, urlencode, urlparse

import requests

from .dates import resolve_date_range

CIDAAS_BASE = "https://account.kaufland.com"
API_BASE = "https://p.crm-dynamics.schwarz"
CLIENT_ID = "fb1b425b-ab2f-4140-aef9-20263b6cfa49"
LOYALTY_CLIENT_ID = "88207bfc-780b-400d-92ee-893ae72dab40"
REDIRECT_URI = "com.kaufland.kaufland://oauth/callback"
OAUTH_VERSION = "1.5.22"
APP_VERSION = "6.17.1"
PAGE_SIZE = 50


class KauflandApi:
    def __init__(self, language, country, refresh_token="", user_id=""):
        self._country = country.upper()
        self._language = language.lower()
        self._refresh_token = refresh_token
        self._user_id = user_id
        self._token = ""
        self._expires = None
        self._code_verifier = ""
        self._oauth_state = ""
        self._basech = string.ascii_letters + string.digits + "-._~"
        self._page_size = PAGE_SIZE

    @property
    def refresh_token(self):
        return self._refresh_token

    @property
    def user_id(self):
        return self._user_id

    def _pkce(self):
        verifier = "".join(choice(self._basech) for _ in range(64))
        digest = hashlib.sha256(verifier.encode("ascii")).digest()
        challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
        return verifier, challenge

    def _authorize_url(self):
        self._code_verifier, challenge = self._pkce()
        self._oauth_state = token_urlsafe(32)
        params = {
            "client_id": CLIENT_ID,
            "response_type": "code",
            "redirect_uri": REDIRECT_URI,
            "ui_locales": f"{self._language}-{self._country}",
            "v": OAUTH_VERSION,
            "view_type": "login",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": self._oauth_state,
        }
        return f"{CIDAAS_BASE}/authz-srv/authz?{urlencode(params)}"

    def _exchange(self, payload):
        response = requests.post(
            f"{CIDAAS_BASE}/token-srv/token",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data=payload,
            timeout=30,
        )
        response.raise_for_status()
        body = response.json()
        self._expires = datetime.now(timezone.utc) + timedelta(
            seconds=body["expires_in"]
        )
        self._token = body["access_token"]
        if body.get("refresh_token"):
            self._refresh_token = body["refresh_token"]
        return body

    def _renew_token(self):
        return self._exchange(
            {
                "grant_type": "refresh_token",
                "refresh_token": self._refresh_token,
                "client_id": CLIENT_ID,
                "v": OAUTH_VERSION,
            }
        )

    def _authorization_code(self, code):
        body = self._exchange(
            {
                "grant_type": "authorization_code",
                "code": code,
                "client_id": CLIENT_ID,
                "redirect_uri": REDIRECT_URI,
                "code_verifier": self._code_verifier,
                "v": OAUTH_VERSION,
            }
        )
        info = requests.get(
            f"{CIDAAS_BASE}/users-srv/userinfo",
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self._token}",
            },
            timeout=30,
        )
        info.raise_for_status()
        user = info.json()
        subject = user.get("sub")
        if not isinstance(subject, str) or not subject:
            raise MissingLogin("Login succeeded but userinfo had no user id.")
        self._user_id = subject
        return body

    def _callback_code(self, url):
        parsed = urlparse(url)
        if parsed.scheme != "com.kaufland.kaufland" or parsed.netloc != "oauth":
            return None
        if parsed.path not in {"/callback", "callback"}:
            return None
        values = parse_qs(parsed.query)
        if values.get("state") != [self._oauth_state]:
            raise MissingLogin("Login callback state did not match. Run login again.")
        if values.get("error"):
            raise MissingLogin("Kaufland rejected the login. Run login again.")
        return values.get("code", [None])[0]

    def login(self, *, timeout=300, diagnostics=False):
        """Open Kaufland login; complete any verification in the browser yourself."""
        from playwright.sync_api import sync_playwright

        codes = []
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False)
            try:
                page = browser.new_page()

                def capture_navigation(event):
                    code = self._callback_code(event.get("url", ""))
                    if code:
                        codes.append(code)

                cdp = page.context.new_cdp_session(page)
                cdp.send("Page.enable")
                cdp.on("Page.frameRequestedNavigation", capture_navigation)

                def capture_blocked_app_launch(event):
                    message = event.get("entry", {}).get("text", "")
                    match = re.search(
                        r"Failed to launch '(com\.kaufland\.kaufland://[^']+)'",
                        message,
                    )
                    if match:
                        code = self._callback_code(match[1])
                        if code:
                            codes.append(code)

                cdp.on("Log.entryAdded", capture_blocked_app_launch)
                cdp.send("Log.enable")

                def capture(route):
                    code = self._callback_code(route.request.url)
                    if code:
                        codes.append(code)
                    route.abort()

                page.route("com.kaufland.kaufland://**", capture)

                def capture_redirect(response):
                    parsed = urlparse(response.url)
                    if parsed.hostname != "account.kaufland.com":
                        return
                    if diagnostics and (
                        response.request.resource_type == "document"
                        or response.status >= 400
                    ):
                        print(
                            f"Login diagnostic: HTTP {response.status} {parsed.path}",
                            flush=True,
                        )
                    code = self._callback_code(response.headers.get("location", ""))
                    if code:
                        codes.append(code)

                page.on("response", capture_redirect)
                page.goto(self._authorize_url())
                deadline = time.monotonic() + timeout
                while not codes:
                    if page.is_closed() or time.monotonic() >= deadline:
                        raise MissingLogin(
                            "Login was closed or timed out. Run login again."
                        )
                    page.wait_for_timeout(200)
                self._authorization_code(codes[0])
            finally:
                if browser.is_connected():
                    browser.close()

    def _headers(self):
        if (
            not self._token
            or self._expires is None
            or datetime.now(timezone.utc) >= self._expires
        ):
            if not self._refresh_token:
                raise MissingLogin("You need to login!")
            self._renew_token()
        if not self._user_id:
            raise MissingLogin("Saved login has no user id. Run login again.")
        return {
            "Accept": "application/json",
            "Authorization": f"Bearer {self._token}",
            "client-id": LOYALTY_CLIENT_ID,
            "app-platform": "Android",
            "app-version": APP_VERSION,
        }

    def transactions(self, start=0, limit=PAGE_SIZE):
        url = (
            f"{API_BASE}/api/v2/customers/{quote(self._user_id, safe='')}/transactions"
            f"?{urlencode({'start': start, 'limit': limit, 'country': self._country, 'version': 2})}"
        )
        response = requests.get(url, headers=self._headers(), timeout=30)
        if response.status_code == 401:
            self._renew_token()
            response = requests.get(url, headers=self._headers(), timeout=30)
        response.raise_for_status()
        return response.json()

    def iter_receipts(self, *, period=None, since=None, until=None):
        """Yield full transactions in an inclusive date range, following every page."""
        dates = resolve_date_range(period=period, since=since, until=until)
        seen = set()
        start = 0
        while True:
            payload = self.transactions(start=start, limit=self._page_size)
            tickets = extract_transactions(payload)
            if not tickets:
                total = _total(payload)
                if total is not None and len(seen) < total:
                    raise ValueError(
                        "Receipt listing ended before the reported total was reached."
                    )
                return
            added = 0
            for ticket in tickets:
                ticket_id = transaction_id(ticket)
                if ticket_id not in seen:
                    seen.add(ticket_id)
                    added += 1
                    if dates.matches(ticket):
                        yield ticket
            if not added:
                raise ValueError(
                    "Receipt API repeated a page; download stopped to avoid a loop."
                )
            total = _total(payload)
            if total is not None and len(seen) >= total:
                return
            if len(tickets) < self._page_size:
                return
            start += len(tickets)


def transaction_id(ticket):
    value = ticket.get("id") if isinstance(ticket, dict) else None
    if isinstance(value, bool) or value is None or not str(value).strip():
        raise ValueError("Receipt summary has no valid id.")
    return str(value).strip()


def extract_transactions(payload):
    value = payload if isinstance(payload, list) else None
    if isinstance(payload, dict):
        for key in ("transactions", "items", "receipts", "results", "data"):
            found = payload.get(key)
            if isinstance(found, list):
                value = found
                break
            if isinstance(found, dict):
                return extract_transactions(found)
    if value is None or not all(isinstance(item, dict) for item in value):
        raise ValueError("Unexpected receipt list response.")
    return value


def _total(payload):
    if not isinstance(payload, dict):
        return None
    for key in ("totalCount", "total"):
        total = payload.get(key)
        if isinstance(total, int) and not isinstance(total, bool):
            return total
    data = payload.get("data")
    if isinstance(data, dict):
        return _total(data)
    return None


class MissingLogin(RuntimeError):
    """Authentication is required before querying the API."""
