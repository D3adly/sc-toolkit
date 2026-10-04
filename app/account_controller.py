"""The signed-in SC-Toolkit online account, for the UI: restores the sign-in at startup, runs the
browser sign-in and sign-out off the UI thread (app.portal does the work), and reports the state
through `changed`.

One controller for the whole app (`controller()`), like the data hub: Settings shows it, and
features that need the service will call `session` through it.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtGui import QDesktopServices

from app import portal


@dataclass(frozen=True)
class AccountState:
    status: str                         # "off" | "signed_out" | "signing_in" | "signed_in"
    profile: portal.Profile | None = None
    message: str = ""                   # last error / note, shown under the status
    offline: bool = False               # signed in, but the service couldn't be reached just now


class AccountController(QObject):
    changed = Signal(object)            # AccountState
    _open_url = Signal(str)             # worker thread -> UI thread

    def __init__(self, parent=None):
        super().__init__(parent)
        self.session: portal.Session | None = None
        self._cancel = False
        self._busy = False
        self._open_url.connect(lambda url: QDesktopServices.openUrl(QUrl(url)))
        self.state = AccountState("off")

    def _set(self, state: AccountState) -> None:
        self.state = state
        self.changed.emit(state)

    def _service(self) -> str | None:
        url = portal.service_url()
        return url if url and portal.check_service_url(url) is None else None

    # -- startup -----------------------------------------------------------------
    def restore(self) -> None:
        """Picks up a sign-in kept in the keyring. Shows the cached profile straight away, then
        checks it with the service in the background."""
        service = self._service()
        self.session = None
        if service is None:
            self._set(AccountState("off"))
            return
        cached = portal.load_profile()
        cached = cached if cached and cached.service == service else None
        self._set(AccountState("signed_in" if cached else "signed_out", cached))
        threading.Thread(target=self._restore, args=(service, cached), daemon=True).start()

    def _restore(self, service: str, cached: portal.Profile | None) -> None:
        try:
            session = portal.Session.restore(service)
            if session is None:
                portal.save_profile(None)
                self._set(AccountState("signed_out"))
                return
            self.session = session
            profile = session.me()
            portal.save_profile(profile)
            self._set(AccountState("signed_in", profile))
        except portal.SignedOut as exc:
            self.session = None
            portal.save_profile(None)
            self._set(AccountState("signed_out", message=str(exc)))
        except portal.Unreachable:
            self._set(AccountState("signed_in" if self.session else "signed_out", cached, offline=self.session is not None))
        except portal.PortalError as exc:
            self._set(AccountState("signed_in" if self.session else "signed_out", cached, message=str(exc)))

    # -- sign in / out -------------------------------------------------------------
    def sign_in(self) -> None:
        service = self._service()
        if service is None or self._busy:
            return
        self._busy = True
        self._cancel = False
        self._set(AccountState("signing_in", message="Finish signing in in your browser…"))
        threading.Thread(target=self._sign_in, args=(service,), daemon=True).start()

    def cancel_sign_in(self) -> None:
        self._cancel = True

    def _sign_in(self, service: str) -> None:
        try:
            self.session, profile = portal.sign_in(service, self._open_url.emit, lambda: self._cancel)
            self._set(AccountState("signed_in", profile))
        except portal.PortalError as exc:
            self._set(AccountState("signed_out", message=str(exc)))
        finally:
            self._busy = False

    def sign_out(self) -> None:
        session, self.session = self.session, None
        portal.save_profile(None)
        self._set(AccountState("signed_out" if self._service() else "off", message="Signed out."))

        def work():
            try:
                if session is not None:
                    session.sign_out()
                else:
                    service = self._service()
                    if service:
                        portal.delete_refresh_token(service)
            except portal.PortalError:
                pass  # signed out locally either way
        threading.Thread(target=work, daemon=True).start()


_controller: AccountController | None = None


def controller() -> AccountController:
    global _controller
    if _controller is None:
        _controller = AccountController()
    return _controller
