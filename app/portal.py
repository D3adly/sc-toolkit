"""Signing in to the SC-Toolkit online service, and calling its API.

The launcher is an OAuth 2 *public* client (it's open source, so it can't keep a secret):
authorization code + PKCE (S256) through the system browser, with the code handed back on a
one-shot loopback address, as RFC 8252 describes for native apps.

- The refresh token lives in the OS keyring (Windows Credential Manager, or the Secret Service on
  Linux), never in settings.json. The access token (15 minutes) stays in memory.
- Refresh tokens rotate on every use and the service treats a reused one as stolen (it signs you out
  everywhere), so refreshes are serialized behind one lock and the new token is stored before the
  access token is used.
- A small non-secret copy of the profile (name, avatar) is cached, so the launcher can say who is
  signed in while offline.

Nothing here touches Qt; app.account_controller runs it off the UI thread.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from app import __version__, config, settings

CLIENT_ID = "sc-toolkit-launcher"
SCOPES = "profile orgs events"
KEYRING_SERVICE = "SC-Toolkit online"
PROFILE_FILE = config.USER_CONFIG_DIR / "account.json"
SIGN_IN_TIMEOUT = 300  # seconds to finish signing in in the browser
_HTTP_TIMEOUT = 15
_REFRESH_MARGIN = 60   # refresh this many seconds before the access token expires


class PortalError(Exception):
    """Something went wrong; the message is shown to the user."""


class SignedOut(PortalError):
    """The sign-in is gone (expired, revoked, or signed out elsewhere): sign in again."""


class Unreachable(PortalError):
    """The service couldn't be reached (offline, or it's down)."""


# -- the service ---------------------------------------------------------------

def service_url() -> str:
    """Base URL of the online service ('' = not configured). The SCT_PORTAL_URL environment
    variable wins over Settings, for development."""
    url = (os.environ.get("SCT_PORTAL_URL") or settings.current().portal_url).strip().rstrip("/")
    return url


def check_service_url(url: str) -> str | None:
    """None if `url` is usable, else why not. Tokens only travel over HTTPS, except to this machine."""
    if not url:
        return "Not set"
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return "Not a web address"
    if parsed.scheme == "http" and parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
        return "Must start with https:// (plain http only works for localhost)"
    return None


# -- profile cache (not secret) ------------------------------------------------

@dataclass
class Profile:
    display_name: str
    avatar_url: str | None = None
    rsi_handle: str | None = None
    service: str = ""

    @classmethod
    def from_me(cls, me: dict, service: str) -> Profile:
        rsi = me.get("rsi") or {}
        return cls(me.get("displayName") or "?", me.get("avatarUrl"), rsi.get("handle"), service)


def load_profile() -> Profile | None:
    try:
        data = json.loads(PROFILE_FILE.read_text())
        return Profile(**{k: data.get(k) for k in ("display_name", "avatar_url", "rsi_handle", "service")})
    except (OSError, ValueError, TypeError):
        return None


def save_profile(profile: Profile | None) -> None:
    if profile is None:
        PROFILE_FILE.unlink(missing_ok=True)
        return
    PROFILE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = PROFILE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(profile), indent=2))
    tmp.replace(PROFILE_FILE)


# -- keyring -------------------------------------------------------------------

def _keyring():
    try:
        import keyring
        from keyring.errors import KeyringError
    except Exception as exc:  # broken install: report, don't crash
        raise PortalError(f"The keyring library isn't available ({exc}).") from exc
    return keyring, KeyringError


def load_refresh_token(service: str) -> str | None:
    keyring, KeyringError = _keyring()
    try:
        return keyring.get_password(KEYRING_SERVICE, service)
    except KeyringError as exc:
        raise PortalError(_keyring_message(exc)) from exc


def store_refresh_token(service: str, token: str) -> None:
    keyring, KeyringError = _keyring()
    try:
        keyring.set_password(KEYRING_SERVICE, service, token)
    except KeyringError as exc:
        raise PortalError(_keyring_message(exc)) from exc


def delete_refresh_token(service: str) -> None:
    keyring, KeyringError = _keyring()
    try:
        keyring.delete_password(KEYRING_SERVICE, service)
    except KeyringError:
        pass  # nothing stored (PasswordDeleteError) or the keyring is gone: nothing to delete


def _keyring_message(exc: Exception) -> str:
    name = type(exc).__name__
    if name == "NoKeyringError":
        return ("No password store found to keep your sign-in safe. On Linux, install or enable "
                "KWallet or GNOME Keyring (Secret Service).")
    if name == "KeyringLocked":
        return "Your password store is locked. Unlock it and try again."
    return f"Your password store refused the request ({exc})."


# -- HTTP ----------------------------------------------------------------------

def _request(method: str, url: str, *, form: dict | None = None, token: str | None = None) -> tuple[int, dict]:
    headers = {
        "Accept": "application/json",
        "User-Agent": f"{config.USER_AGENT}/{__version__}",
        "X-Launcher-Version": __version__,
    }
    data = None
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
            return resp.status, _json(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, _json(exc.read())
    except (urllib.error.URLError, OSError) as exc:
        raise Unreachable(f"The online service can't be reached ({getattr(exc, 'reason', exc)}).") from exc


def _json(body: bytes) -> dict:
    try:
        data = json.loads(body or b"{}")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {"data": data}


# -- PKCE + loopback -----------------------------------------------------------

def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def pkce_pair() -> tuple[str, str]:
    """(code_verifier, S256 code_challenge)."""
    verifier = _b64url(secrets.token_bytes(48))
    return verifier, _b64url(hashlib.sha256(verifier.encode()).digest())


_DONE_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><title>SC-Toolkit</title>
<meta name="viewport" content="width=device-width, initial-scale=1"></head>
<body style="margin:0;min-height:100vh;display:grid;place-items:center;background:#0f1215;color:#f3ede2;
font:16px/1.5 Inter,'Segoe UI',system-ui,sans-serif">
<div style="max-width:420px;padding:28px;border:1px solid rgba(218,197,164,.16);border-radius:14px;
background:rgba(16,19,23,.9);text-align:center">
<h1 style="font-size:22px;margin:0 0 8px;color:{color}">{title}</h1>
<p style="margin:0;color:#cfc6b6">{text}</p></div></body></html>"""


class LoopbackReceiver:
    """A one-shot HTTP listener on 127.0.0.1 (random port) that receives the authorization code.

    Only `GET /callback` with the expected `state` is accepted; anything else gets a 404 and is
    ignored, so a stray request can't end the sign-in early.
    """

    def __init__(self, state: str):
        self._state = state
        self._result: tuple[str | None, str | None] | None = None  # (code, error)
        self._done = threading.Event()
        receiver = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 (http.server API)
                parts = urllib.parse.urlsplit(self.path)
                query = urllib.parse.parse_qs(parts.query)
                if parts.path != "/callback" or query.get("state", [""])[0] != receiver._state or receiver._done.is_set():
                    self.send_error(404)
                    return
                code = query.get("code", [None])[0]
                error = query.get("error", [None])[0]
                if code:
                    page = _DONE_PAGE.format(color="#e3a33b", title="You're signed in",
                                             text="You can close this tab and go back to SC-Toolkit.")
                else:
                    page = _DONE_PAGE.format(color="#e26a55", title="Sign-in cancelled",
                                             text="Nothing was changed. You can close this tab.")
                body = page.encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
                receiver._result = (code, error or (None if code else "no_code"))
                receiver._done.set()

            def log_message(self, *_args):  # keep codes out of stderr
                pass

        self._server = HTTPServer(("127.0.0.1", 0), Handler)
        self._server.timeout = 0.5
        self.redirect_uri = f"http://127.0.0.1:{self._server.server_address[1]}/callback"

    def wait(self, timeout: float, cancelled) -> str:
        """Serves until the code arrives; returns it. Raises PortalError on denial, timeout or cancel."""
        deadline = time.monotonic() + timeout
        try:
            while not self._done.is_set():
                if cancelled():
                    raise PortalError("Sign-in cancelled.")
                if time.monotonic() > deadline:
                    raise PortalError("Sign-in timed out. Try again.")
                self._server.handle_request()
        finally:
            self._server.server_close()
        code, error = self._result or (None, "no_code")
        if error == "access_denied":
            raise PortalError("Sign-in was cancelled in the browser.")
        if not code:
            raise PortalError(f"Sign-in failed ({error}).")
        return code


# -- the session ---------------------------------------------------------------

class Session:
    """A signed-in session with one service. Thread-safe; one refresh at a time."""

    def __init__(self, service: str, refresh_token: str):
        self.service = service
        self._refresh_token = refresh_token
        self._access_token: str | None = None
        self._expires_at = 0.0
        self._lock = threading.Lock()

    # -- signing in ------------------------------------------------------------
    @staticmethod
    def authorization_url(service: str, redirect_uri: str, challenge: str, state: str) -> str:
        return f"{service}/oauth/authorize?" + urllib.parse.urlencode({
            "response_type": "code",
            "client_id": CLIENT_ID,
            "redirect_uri": redirect_uri,
            "scope": SCOPES,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        })

    @classmethod
    def from_code(cls, service: str, code: str, verifier: str, redirect_uri: str) -> Session:
        status, data = _request("POST", f"{service}/oauth/token", form={
            "grant_type": "authorization_code",
            "client_id": CLIENT_ID,
            "code": code,
            "code_verifier": verifier,
            "redirect_uri": redirect_uri,
        })
        if status != 200 or "refresh_token" not in data:
            raise PortalError(f"Sign-in failed ({data.get('error_description') or data.get('error') or status}).")
        session = cls(service, data["refresh_token"])
        session._accept(data)
        store_refresh_token(service, session._refresh_token)
        return session

    @classmethod
    def restore(cls, service: str) -> Session | None:
        token = load_refresh_token(service)
        return cls(service, token) if token else None

    # -- tokens ------------------------------------------------------------------
    def _accept(self, data: dict) -> None:
        self._access_token = data["access_token"]
        self._expires_at = time.monotonic() + int(data.get("expires_in", 900))
        if data.get("refresh_token"):
            self._refresh_token = data["refresh_token"]

    def access_token(self) -> str:
        with self._lock:
            if self._access_token is None or time.monotonic() > self._expires_at - _REFRESH_MARGIN:
                self._refresh_locked()
            return self._access_token  # type: ignore[return-value]

    def _refresh_locked(self) -> None:
        status, data = _request("POST", f"{self.service}/oauth/token", form={
            "grant_type": "refresh_token",
            "client_id": CLIENT_ID,
            "refresh_token": self._refresh_token,
        })
        if status in (400, 401):
            # Expired, revoked, or rotated by someone else: this sign-in is over.
            self._access_token = None
            delete_refresh_token(self.service)
            raise SignedOut("Your sign-in has expired. Sign in again.")
        if status != 200 or "access_token" not in data:
            raise PortalError(f"The online service answered unexpectedly ({status}).")
        self._accept(data)
        # Stored before the new access token is used: the old refresh token is now spent.
        store_refresh_token(self.service, self._refresh_token)

    # -- API -----------------------------------------------------------------------
    def api(self, method: str, path: str) -> dict:
        """Calls /api/v1{path}. A 401 means the token was revoked meanwhile: refresh once and retry."""
        for attempt in (0, 1):
            status, data = _request(method, f"{self.service}/api/v1{path}", token=self.access_token())
            if status == 401 and attempt == 0:
                with self._lock:
                    self._access_token = None
                continue
            if status == 401:
                raise SignedOut("Your sign-in has expired. Sign in again.")
            if status >= 400:
                raise PortalError(data.get("detail") or data.get("error") or f"Request failed ({status}).")
            return data
        raise PortalError("Request failed.")

    def me(self) -> Profile:
        return Profile.from_me(self.api("GET", "/me"), self.service)

    def sign_out(self) -> None:
        """Revokes the refresh token on the service (best effort) and forgets it here."""
        token, self._refresh_token = self._refresh_token, ""
        self._access_token = None
        try:
            _request("POST", f"{self.service}/oauth/revoke", form={
                "client_id": CLIENT_ID, "token": token, "token_type_hint": "refresh_token",
            })
        except Unreachable:
            pass  # offline: the token still expires on its own; it's deleted here either way
        finally:
            delete_refresh_token(self.service)


def sign_in(service: str, open_browser, cancelled) -> tuple[Session, Profile]:
    """The whole browser sign-in. `open_browser(url)` must open the system browser; runs off the UI
    thread otherwise (it blocks until the user finishes or `cancelled()` turns true)."""
    verifier, challenge = pkce_pair()
    state = secrets.token_urlsafe(24)
    receiver = LoopbackReceiver(state)
    open_browser(Session.authorization_url(service, receiver.redirect_uri, challenge, state))
    code = receiver.wait(SIGN_IN_TIMEOUT, cancelled)
    session = Session.from_code(service, code, verifier, receiver.redirect_uri)
    profile = session.me()
    save_profile(profile)
    return session, profile
