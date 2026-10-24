#!/usr/bin/env python3
"""
One-time step: log in to Instagram in a real (visible) browser window and
save the session so the collection script can reuse it headlessly.

Run:  python playwright_login.py
      (a browser window opens -> log in normally -> switch back to the
       terminal and press Enter)

Produces: playwright_session.json  (cookies + storage; keep this private,
it grants full access to the account, same as a password)
"""
from playwright.sync_api import sync_playwright

OUT = "playwright_session.json"


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto("https://www.instagram.com/accounts/login/")
        print("Log in to Instagram in the window that opened.")
        print("Once you see your home feed (no checkpoint, no prompts), come back here and press Enter.")
        input()
        context.storage_state(path=OUT)
        browser.close()
    print("Saved session to %s" % OUT)
    print("Now run:  python collect_playwright.py --input niche_file.txt --storage-state %s" % OUT)


if __name__ == "__main__":
    main()
