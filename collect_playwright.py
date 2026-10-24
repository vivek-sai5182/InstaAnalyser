import argparse
import csv
import os
import random
import re
import statistics
import sys
import time
from datetime import datetime, timezone
from collections import Counter

from playwright.sync_api import sync_playwright

APP_ID = "936619743392459"  # Instagram's public web client app id
PROFILE_URL = "https://www.instagram.com/api/v1/users/web_profile_info/?username={}"

MAX_FOLLOWERS = 1_000_000
MIN_FOLLOWERS = 100
POSTS_FOR_ENGAGEMENT = 10

COLUMNS = [
    "Name", "Followers", "Category", "Engagement Rate (%)", "Contact",
    "Posting Frequency (per month)", "Hashtags", "Notes",
]
CATEGORY_KEYWORDS = {
    "Tech": ["tech", "technology", "coding", "developer", "programming", "software", "gadget",
             "ai", "startup", "app", "data", "cyber", "gaming", "gamer"],
    "Fashion": ["fashion", "style", "outfit", "ootd", "streetwear", "designer", "clothing",
                "makeup", "beauty", "skincare", "model"],
    "Fitness": ["fitness", "gym", "workout", "yoga", "bodybuilding", "trainer", "health",
                "nutrition", "diet", "crossfit", "athlete"],
    "Travel": ["travel", "traveller", "traveler", "wanderlust", "trip", "tourism", "explore",
               "backpacker", "adventure", "nomad"],
    "Food": ["food", "foodie", "recipe", "chef", "cooking", "restaurant", "bakery", "cafe"],
    "Business": ["business", "entrepreneur", "startup", "founder", "ceo", "marketing"],
    "Education": ["education", "learning", "teach", "student", "tutor"],
    "Gaming": ["gaming", "gamer", "esports", "streamer", "twitch"],
    "Music": ["music", "singer", "musician", "band", "producer", "dj"],
    "Lifestyle": ["lifestyle", "daily", "mom", "family", "home", "decor", "blogger", "creator"],
}

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"(?<!\d)(?:\+?\d{1,3}[\s\-]?)?(?:\d[\s\-]?){9,11}(?!\d)")
USERNAME_RE = re.compile(r"^[a-z0-9._]{1,30}$")


# ----------------------------------------------------------------------------
# Input handling
# ----------------------------------------------------------------------------

def clean_username(raw):
    s = (raw or "").strip().lower()
    if not s:
        return None
    s = re.sub(r"^https?://(www\.)?instagram\.com/", "", s)
    s = s.split("?")[0].strip("/ @")
    s = s.split("/")[0]
    return s if USERNAME_RE.match(s) else None


def load_names(path):
    """Reads .txt/.csv; accepts @handles, URLs, and 'name | niche' lines."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    if not rows:
        return []
    col = 0
    header_words = {"username", "handle", "user", "name", "instagram_handle", "instagram handle", "account"}
    first = [c.strip().lower() for c in rows[0]]
    if any(c in header_words for c in first):
        for pref in ("username", "handle", "instagram_handle", "instagram handle", "user", "account", "name"):
            if pref in first:
                col = first.index(pref)
                break
        rows = rows[1:]
    seen, names = set(), []
    for r in rows:
        if col < len(r):
            u = clean_username(r[col].split("|")[0])
            if u and u not in seen:
                seen.add(u)
                names.append(u)
    return names


# ----------------------------------------------------------------------------
# Feature computation (pure functions, no network — testable offline)
# ----------------------------------------------------------------------------

def classify_category(text, ig_category):
    text = " " + re.sub(r"[^a-z0-9 ]", " ", (text or "").lower()) + " "
    scores = {cat: sum(text.count(" " + w + " ") for w in words) for cat, words in CATEGORY_KEYWORDS.items()}
    best = max(scores, key=scores.get)
    if scores[best] > 0:
        return best
    return ig_category.strip() if ig_category else "Other"


def extract_contact(bio, public_email=None):
    parts = []
    emails = EMAIL_RE.findall(bio or "")
    if public_email:
        emails.append(public_email)
    for e in dict.fromkeys(emails):
        parts.append(e)
    phones = [p.strip() for p in PHONE_RE.findall(bio or "")]
    for p in dict.fromkeys(phones):
        if len(re.sub(r"\D", "", p)) >= 10:
            parts.append(p)
    return "; ".join(parts) if parts else "Not public"


def posting_frequency(dates):
    if len(dates) < 2:
        return None
    dates = sorted(dates, reverse=True)
    span_days = (dates[0] - dates[-1]).total_seconds() / 86400
    if span_days < 1:
        span_days = 1
    return round((len(dates) - 1) / span_days * 30, 1)


def parse_profile_json(data, username):
    """
    data: parsed JSON from web_profile_info.
    Returns (row_dict, None) or (None, skip_reason).
    """
    user = (data or {}).get("data", {}).get("user")
    if not user:
        return None, "no user data in response"
    if user.get("is_private"):
        return None, "private account"

    followers = (user.get("edge_followed_by") or {}).get("count", 0)
    if followers >= MAX_FOLLOWERS:
        return None, "followers >= 1M"
    if followers < MIN_FOLLOWERS:
        return None, "followers < %d" % MIN_FOLLOWERS

    edges = (user.get("edge_owner_to_timeline_media") or {}).get("edges", [])
    posts = [e["node"] for e in edges][:POSTS_FOR_ENGAGEMENT]

    notes = []
    ers, hidden = [], 0
    dates, captions, tag_counter = [], [], Counter()
    for node in posts:
        likes = node.get("edge_liked_by") or node.get("edge_media_preview_like") or {}
        likes = likes.get("count")
        comments = (node.get("edge_media_to_comment") or {}).get("count", 0)
        if likes is None or likes < 0:
            hidden += 1
        else:
            ers.append((likes + (comments or 0)) / followers if followers else 0)
        ts = node.get("taken_at_timestamp")
        if ts:
            dates.append(datetime.fromtimestamp(ts, tz=timezone.utc))
        cap_edges = (node.get("edge_media_to_caption") or {}).get("edges", [])
        cap = cap_edges[0]["node"]["text"] if cap_edges else ""
        captions.append(cap)
        tag_counter.update(t.lower() for t in re.findall(r"#(\w+)", cap))

    if not posts:
        return None, "no posts"
    if not ers:
        return None, "likes hidden on all recent posts"
    if hidden:
        notes.append("likes hidden on %d post(s)" % hidden)
    engagement = round(statistics.mean(ers) * 100, 2)

    bio = (user.get("biography") or "").replace("\n", " ").strip()
    tag_counter.update(t.lower() for t in re.findall(r"#(\w+)", bio))
    top_tags = " ".join("#" + t for t, _ in tag_counter.most_common(5))

    freq = posting_frequency(dates)
    if dates:
        now = datetime.now(timezone.utc)
        if (now - max(dates)).days > 90:
            notes.append("inactive: last post %d days ago" % (now - max(dates)).days)

    category = classify_category(
        " ".join([bio, user.get("category_name") or user.get("business_category_name") or ""]),
        user.get("category_name") or user.get("business_category_name"),
    )

    row = {
        "Name": user.get("full_name") or username,
        "Followers": followers,
        "Category": category,
        "Engagement Rate (%)": engagement,
        "Contact": extract_contact(bio, user.get("business_email")),
        "Posting Frequency (per month)": freq if freq is not None else "",
        "Hashtags": top_tags,
        "Notes" : ";".join(notes + [
            "Engagement measured from up to 10 recent posts; "
            "posting frequency derived from post timestamps; "
            "hashtags extracted from captions and bio"
        ]),
    }
    return row, None


# ----------------------------------------------------------------------------
# Output handling
# ----------------------------------------------------------------------------

def append_row(path, columns, row):
    new = not os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=columns)
        if new:
            w.writeheader()
        w.writerow(row)
        f.flush()


def load_done_usernames(path):
    if not os.path.exists(path):
        return set()
    with open(path, encoding="utf-8") as f:
        return {l.strip() for l in f if l.strip()}


# ----------------------------------------------------------------------------
# Fetching
# ----------------------------------------------------------------------------

class StopRun(Exception):
    pass


def fetch_json(request_ctx, username, backoff_tries=3):
    wait = 300
    headers = {"x-ig-app-id": APP_ID, "accept": "*/*", "x-requested-with": "XMLHttpRequest"}
    for attempt in range(backoff_tries + 1):
        resp = request_ctx.get(PROFILE_URL.format(username), headers=headers)
        status = resp.status
        if status == 200:
            return resp.json()
        if status == 404:
            return None  # profile not found
        if status in (401, 403, 429) or status >= 500:
            if attempt >= backoff_tries:
                raise StopRun("Blocked or rate limited (HTTP %d). Wait a few hours, then re-run." % status)
            print("  HTTP %d. sleeping %d s ..." % (status, wait))
            time.sleep(wait)
            wait *= 2
            continue
        return None  # some other unexpected status; treat as not found


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", required=True, help="niche file with usernames (txt or csv)")
    ap.add_argument("--output", default=None, help="default: <input>_results.csv")
    ap.add_argument("--skipped", default=None, help="default: <input>_skipped.csv")
    ap.add_argument("--target", type=int, default=250)
    ap.add_argument("--max-per-run", type=int, default=250)
    ap.add_argument("--storage-state", default="playwright_session.json")
    ap.add_argument("--delay-min", type=float, default=6)
    ap.add_argument("--delay-max", type=float, default=12)
    ap.add_argument("--headless", action="store_true", default=True)
    args = ap.parse_args()

    base = os.path.splitext(args.input)[0]
    out_path = args.output or (base + "_results.csv")
    skip_path = args.skipped or (base + "_skipped.csv")
    done_file = out_path + ".done_usernames.txt"

    if not os.path.exists(args.storage_state):
        sys.exit("No saved session. Run playwright_login.py first.")

    names = load_names(args.input)
    print("Loaded %d usernames from %s" % (len(names), args.input))

    done_usernames = load_done_usernames(done_file)
    skipped_usernames = load_done_usernames(skip_path + ".names.txt")
    valid_count = sum(1 for _ in open(out_path, encoding="utf-8-sig")) - 1 if os.path.exists(out_path) else 0
    valid_count = max(valid_count, 0)
    todo = [n for n in names if n not in done_usernames]
    print("Valid so far: %d / %d | remaining to try: %d" % (valid_count, args.target, len(todo)))

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=args.headless)
        context = browser.new_context(storage_state=args.storage_state)
        request_ctx = context.request

        attempted = 0
        try:
            for username in todo:
                if valid_count >= args.target:
                    break
                if attempted >= args.max_per_run:
                    print("Reached --max-per-run. Re-run later to continue.")
                    break
                attempted += 1
                try:
                    data = fetch_json(request_ctx, username)
                    if data is None:
                        row, reason = None, "not found / no data"
                    else:
                        row, reason = parse_profile_json(data, username)
                except StopRun:
                    raise
                except Exception as e:
                    print("[%d] %s: error %s: %s (will retry next run)" % (attempted, username, type(e).__name__, e))
                    time.sleep(random.uniform(args.delay_min, args.delay_max))
                    continue

                with open(done_file, "a", encoding="utf-8") as f:
                    f.write(username + "\n")

                if row:
                    append_row(out_path, COLUMNS, row)
                    valid_count += 1
                    print("[%d] %s OK (%d/%d) followers=%s ER=%s%%"
                          % (attempted, username, valid_count, args.target, row["Followers"], row["Engagement Rate (%)"]))
                else:
                    append_row(skip_path, ["Username", "Reason"], {"Username": username, "Reason": reason})
                    print("[%d] %s skipped: %s" % (attempted, username, reason))

                time.sleep(random.uniform(args.delay_min, args.delay_max))
                if attempted % 25 == 0:
                    pause = random.uniform(60, 120)
                    print("  short break (%d s)" % pause)
                    time.sleep(pause)
        except StopRun as e:
            print("\nSTOPPED: %s" % e)
        except KeyboardInterrupt:
            print("\nInterrupted. Progress is saved; re-run to continue.")
        finally:
            browser.close()

    print("\nValid influencers collected: %d / %d" % (valid_count, args.target))


if __name__ == "__main__":
    main()
