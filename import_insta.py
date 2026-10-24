#!/usr/bin/env python3
"""
Create an Instaloader session file from cookies of a browser where you are
already logged in to Instagram (avoids the terminal login checkpoint).

How to get the cookie values (Brave / Chrome):
  1. Open instagram.com while logged in.
  2. Press F12 -> "Application" tab -> Storage -> Cookies -> https://www.instagram.com
  3. Copy the Value of:  sessionid   (required)
                         csrftoken   (recommended)
                         ds_user_id  (optional)

Treat sessionid like a password: never share it or paste it into any chat.
Run:  python import_session.py
Then: python collect_influencers.py --session-user YOUR_USERNAME
"""
import getpass
import sys

import instaloader


def main():
    user = input("Instagram username: ").strip()
    sessionid = getpass.getpass("sessionid value (hidden): ").strip()
    csrftoken = getpass.getpass("csrftoken value (hidden, Enter to skip): ").strip()
    ds_user_id = input("ds_user_id value (Enter to skip): ").strip()

    L = instaloader.Instaloader(quiet=True)
    jar = L.context._session.cookies
    jar.set("sessionid", sessionid, domain=".instagram.com")
    if csrftoken:
        jar.set("csrftoken", csrftoken, domain=".instagram.com")
        L.context._session.headers.update({"X-CSRFToken": csrftoken})
    if ds_user_id:
        jar.set("ds_user_id", ds_user_id, domain=".instagram.com")

    logged_in_as = L.test_login()
    if not logged_in_as:
        sys.exit("Login test failed. The sessionid may be wrong or expired; copy it again.")
    if logged_in_as.lower() != user.lower():
        print("Warning: session belongs to '%s', not '%s'. Using '%s'." % (logged_in_as, user, logged_in_as))
    L.context.username = logged_in_as
    L.save_session_to_file()
    print("Session saved for %s. Now run:" % logged_in_as)
    print("  python collect_influencers.py --input names.txt --session-user %s" % logged_in_as)


if __name__ == "__main__":
    main()