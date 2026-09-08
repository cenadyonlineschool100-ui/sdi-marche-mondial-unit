import asyncio
import traceback
from pathlib import Path

from playwright.async_api import async_playwright

BASE_URL = "http://127.0.0.1:8000/"
TEST_A = "test_notification_A"
TEST_B = "test_notification_B"
TEST_PASSWORD = "TempPass123!"
LOG_PATH = Path("playwright_debug_log.txt")


def log(msg: str):
    print(msg)
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(msg + "\n")


async def safe_goto(page, url: str, step: str, timeout: int = 15000):
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=timeout)
        log(f"STEP={step} URL={url} OK")
        return True
    except Exception as e:
        log(f"STEP={step} URL={url} ERROR={type(e).__name__}: {e}")
        traceback.print_exc()
        raise


async def find_login_route(page):
    candidates = []
    try:
        hrefs = await page.locator('a[href]').evaluate_all(
            "els => els.map(el => el.getAttribute('href'))"
        )
        for href in hrefs:
            if href and any(token in href.lower() for token in ["login", "signin", "connexion", "auth"]):
                candidates.append(href)
    except Exception as e:
        log(f"STEP=find_login_route_scan ERROR={type(e).__name__}: {e}")
        traceback.print_exc()

    for href in candidates:
        log(f"LOGIN_ROUTE_CANDIDATE={href}")

    paths = [
        "/login/",
        "/accounts/login/",
        "/admin/login/",
        "/signin/",
        "/connexion/",
    ]

    for path in paths:
        url = BASE_URL.rstrip("/") + path
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=15000)
            form = page.locator('form')
            if await form.count() > 0:
                log(f"LOGIN_URL={url}")
                return url
        except Exception as e:
            log(f"STEP=probe_login_url URL={url} ERROR={type(e).__name__}: {e}")
            traceback.print_exc()

    if candidates:
        url = BASE_URL.rstrip("/") + candidates[0] if not candidates[0].startswith("http") else candidates[0]
        log(f"LOGIN_URL={url}")
        return url

    log("LOGIN_URL=NOT_FOUND")
    return None


async def ensure_auth(page, username: str, label: str):
    try:
        login_url = await find_login_route(page)
        if login_url:
            await page.goto(login_url, wait_until="domcontentloaded", timeout=15000)
        else:
            log(f"{label}_FAIL_REASON=NO_LOGIN_PAGE_FOUND")
            return False

        username_field = page.locator(
            'input[name="username"], input[name="email"], input[id*="username"], input[id*="email"], input[type="text"], input[type="email"]'
        ).first
        password_field = page.locator('input[name="password"], input[id*="password"], input[type="password"]').first
        submit = page.locator('button[type="submit"], input[type="submit"], button:has-text("Se connecter"), button:has-text("Connexion"), button:has-text("Login")').first

        log(f"LOGIN_FORM_FOUND={ 'YES' if await page.locator('form').count() > 0 else 'NO' }")
        log(f"USERNAME_FIELD_FOUND={ 'YES' if await username_field.count() > 0 else 'NO' }")
        log(f"PASSWORD_FIELD_FOUND={ 'YES' if await password_field.count() > 0 else 'NO' }")
        log(f"SUBMIT_FOUND={ 'YES' if await submit.count() > 0 else 'NO' }")

        if await username_field.count() == 0 or await password_field.count() == 0:
            log(f"{label}_FAIL_REASON=LOGIN_FORM_INCOMPLETE")
            return False

        await username_field.fill(username)
        await password_field.fill(TEST_PASSWORD)
        await submit.click()
        await page.wait_for_timeout(4000)

        final_url = page.url
        title = await page.title()
        log(f"{label}_FINAL_URL={final_url}")
        log(f"{label}_FINAL_TITLE={title}")

        session_cookie_names = await page.context.cookies()
        names = [c["name"] for c in session_cookie_names]
        log(f"{label}_COOKIE_NAMES={names}")

        if any(token in final_url.lower() for token in ["login", "signin", "connexion"]) or "error" in final_url.lower():
            log(f"{label}_FAIL_REASON=AUTH_FAILED_AFTER_SUBMIT URL={final_url}")
            return False

        # Minimal proof of a successful authenticated session: cookie or user indicator.
        if any(name.lower() in {"sessionid", "csrftoken", "auth", "django_language"} for name in names):
            log(f"{label}=OK")
            return True

        log(f"{label}_FAIL_REASON=NO_SESSION_COOKIE_AFTER_LOGIN URL={final_url}")
        return False
    except Exception as e:
        log(f"STEP={label}_AUTH_ERROR ERROR={type(e).__name__}: {e}")
        traceback.print_exc()
        return False


async def main():
    LOG_PATH.write_text("", encoding="utf-8")
    log("PLAYWRIGHT_START=OK")
    try:
        async with async_playwright() as p:
            log("BROWSER_START=OK")
            browser = await p.chromium.launch(headless=True)
            context_a = await browser.new_context()
            context_b = await browser.new_context()
            log("CONTEXT_A=OK")
            log("CONTEXT_B=OK")
            page_a = await context_a.new_page()
            page_b = await context_b.new_page()
            log("PAGE_A=OK")
            log("PAGE_B=OK")

            for page, label in [(page_a, "PAGE_A"), (page_b, "PAGE_B")]:
                await safe_goto(page, BASE_URL, label)
                log(f"{label}_URL={page.url}")
                log(f"{label}_TITLE={await page.title()}")

            if page_a.url == page_b.url and "http" in page_a.url:
                log("SESSIONS_PROBE=PAGE_LOAD_OK")

            auth_a = await ensure_auth(page_a, TEST_A, "AUTH_A")
            auth_b = await ensure_auth(page_b, TEST_B, "AUTH_B")

            cookies_a = [c["name"] for c in await context_a.cookies()]
            cookies_b = [c["name"] for c in await context_b.cookies()]
            session_independent = "YES" if set(cookies_a) != set(cookies_b) or len(cookies_a) != len(cookies_b) else "NO"
            log(f"SESSION_A_INDEPENDENT={session_independent}")
            log(f"SESSION_B_INDEPENDENT={session_independent}")

            if not auth_a:
                log("AUTH_A_FAIL_REASON=LOGIN_FAILED")
            if not auth_b:
                log("AUTH_B_FAIL_REASON=LOGIN_FAILED")

            if auth_a and auth_b:
                log("AUTHENTICATION_SUITE=OK")
            else:
                log("AUTHENTICATION_SUITE=FAIL")

            await browser.close()
            log("BROWSER_CLOSE=OK")
    except Exception as e:
        log(f"FATAL_ERROR={type(e).__name__}: {e}")
        traceback.print_exc()
        raise SystemExit(1)


asyncio.run(main())
