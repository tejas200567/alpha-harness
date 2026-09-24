"""
Re-adds cookie-based login, lost when git reset --hard wiped an earlier
session's unpushed patch. Reuses AuthService.restore/Authenticator.restore/
_save_cookies -- the same mechanism that already restores a cached session
at startup, just fed a browser-pasted cookie instead of one loaded from DB.

Run from backend/src/alpha_harness/.
"""

with open("account.py") as f:
    account_src = f.read()

ANCHOR = "    async def login(self, email: str | None = None, password: str | None = None) -> SessionInfo:"

if "login_with_cookie" in account_src:
    print("account.py: login_with_cookie already present, skipping")
else:
    if ANCHOR not in account_src:
        raise SystemExit("account.py: anchor not found, refusing to guess -- paste the file again")

    new_method = '''    async def login_with_cookie(self, cookie_value: str, *, domain: str = "api.worldquantbrain.com") -> SessionInfo:
        """Sign in by restoring a cookie pasted from an already-authenticated browser.

        Reuses Authenticator.restore, the same path startup uses to reuse a cached
        session -- a cookie from a browser that has already completed identity
        verification restores cleanly here without re-triggering that check, per
        Authenticator.restore's own docstring.
        """
        async with self._lock:
            cookies = [{"name": "t", "value": cookie_value, "domain": domain, "path": "/"}]
            restored = await self.auth.restore(cookies)
            if restored is None or not restored.authenticated:
                self._session = restored or SessionInfo.anonymous(
                    detail="That cookie is not valid or has expired."
                )
                return self._session
            self._session = restored
            await self._save_cookies(restored)
            await self.get_user_profile()
            await self._warm_operators()
            return restored

'''
    account_src = account_src.replace(ANCHOR, new_method + ANCHOR)
    with open("account.py", "w") as f:
        f.write(account_src)
    print("account.py: added login_with_cookie")

with open("api/auth.py") as f:
    api_src = f.read()

if "CookieLoginRequest" in api_src:
    print("api/auth.py: cookie route already present, skipping")
else:
    ROUTE_ANCHOR = '@router.post("/logout")'
    if ROUTE_ANCHOR not in api_src:
        raise SystemExit("api/auth.py: anchor not found, refusing to guess -- paste the file again")

    new_route = '''class CookieLoginRequest(BaseModel):
    """Restore a session from a cookie pasted out of an already-signed-in browser."""

    cookie: str = Field(min_length=1, max_length=4096)
    email: str | None = Field(default=None, description="Label only, not used for auth")


@router.post("/cookie")
async def login_cookie(payload: CookieLoginRequest, state: State) -> Session:
    """Sign in using a pasted BRAIN session cookie instead of email+password."""
    info = await state.auth.login_with_cookie(payload.cookie)

    if info.authenticated:
        state.engine.configure_from_permissions(info.permissions)
        try:
            await state.metadata.refresh_metadata()
        except Exception:
            log.warning("auth.metadata_refresh_failed", exc_info=True)

    await state.hub.broadcast(TOPIC_SESSION, info.to_dict())
    return Session.model_validate(info.to_dict())


'''
    api_src = api_src.replace(ROUTE_ANCHOR, new_route + ROUTE_ANCHOR)
    with open("api/auth.py", "w") as f:
        f.write(api_src)
    print("api/auth.py: added POST /api/auth/cookie")

print("\nDone. Restart uvicorn, then POST /api/auth/cookie with {'cookie': '<t value>'}")
