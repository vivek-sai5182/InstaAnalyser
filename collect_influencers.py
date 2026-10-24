
import argparse
import csv
import math
import os
import random
import re
import statistics
import sys
import time
from collections import Counter
from datetime import datetime, timezone

try:
    import instaloader
    from instaloader import exceptions as igex
except ImportError:  # allows offline testing of the pure functions
    instaloader = None
    igex = None

# ----------------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------------

MAX_FOLLOWERS = 1_000_000
POSTS_FOR_ENGAGEMENT = 6     # fewer posts = fewer requests per profile = faster, but noisier numbers
POSTS_TO_FETCH = 7           # fetch one extra so a pinned (old) post can be ignored
MIN_FOLLOWERS = 100          # ignore near-empty accounts

COLUMNS = [
    "Name", "Followers", "Category", "Engagement Rate (%)", "Contact",
    "Posting Frequency (per month)", "Hashtags", "Notes",
]

CATEGORY_KEYWORDS = {
    "Tech": ["tech", "technology", "coding", "developer", "programming", "software", "gadget",
             "ai", "startup", "app", "data", "cyber", "gaming", "gamer", "pc", "mobile review"],
    "Fashion": ["fashion", "style", "outfit", "ootd", "streetwear", "designer", "clothing",
                "makeup", "beauty", "skincare", "model", "jewellery", "jewelry", "saree"],
    "Fitness": ["fitness", "gym", "workout", "yoga", "bodybuilding", "trainer", "health",
                "nutrition", "diet", "crossfit", "athlete", "running", "wellness"],
    "Travel": ["travel", "traveller", "traveler", "wanderlust", "trip", "tourism", "explore",
               "vlog", "backpacker", "adventure", "nomad", "destination"],
    "Food": ["food", "foodie", "recipe", "chef", "cooking", "restaurant", "bakery", "cafe",
             "baking", "biryani", "street food"],
    "Lifestyle": ["lifestyle", "daily", "mom", "mother", "family", "home", "decor", "blogger",
                  "creator", "influencer", "motivation", "couple", "life"],
}

AUTOMATION_STRONG = [
    "manychat", "chatfuel", "mobilemonkey", "instamentions", "autopost", "auto-post",
    "auto post", "automated dm", "auto dm", "autodm", "hootsuite", "buffer.com",
]
AUTOMATION_WEAK_TOOLS = ["linktr.ee", "beacons.ai", "stan.store", "taplink", "later.com",
                         "planoly", "campsite.bio", "bio.link"]
COMMENT_TO_DM_RE = re.compile(r"comment\b.{0,40}\b(dm|send you|sent to you|link)\b", re.I | re.S)

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
    """Read usernames from .txt or .csv. Accepts @handles and profile URLs."""
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
            u = clean_username(r[col])
            if u and u not in seen:
                seen.add(u)
                names.append(u)
    return names


# ----------------------------------------------------------------------------
# Feature computation (pure functions, no network)
# ----------------------------------------------------------------------------

def classify_category(text, ig_category):
    text = " " + re.sub(r"[^a-z0-9 ]", " ", (text or "").lower()) + " "
    scores = {}
    for cat, words in CATEGORY_KEYWORDS.items():
        scores[cat] = sum(text.count(" " + w + " ") for w in words)
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
    """Average posts per month, estimated from the span of the recent posts."""
    if len(dates) < 2:
        return None
    dates = sorted(dates, reverse=True)
    span_days = (dates[0] - dates[-1]).total_seconds() / 86400
    if span_days < 1:
        span_days = 1
    return round((len(dates) - 1) / span_days * 30, 1)


def automation_label(bio, captions, post_times, avg_hashtags, external_url):
    text = " ".join([bio or "", external_url or ""] + list(captions)).lower()
    strong, weak = [], []
    for kw in AUTOMATION_STRONG:
        if kw in text:
            strong.append(kw)
    if COMMENT_TO_DM_RE.search(text):
        strong.append("comment-to-DM funnel")
    for kw in AUTOMATION_WEAK_TOOLS:
        if kw in text:
            weak.append(kw)
    if len(post_times) >= 8:
        hours = [t.hour + t.minute / 60 for t in post_times]
        if statistics.pstdev(hours) <= 1.0:
            weak.append("near-identical posting time")
    if avg_hashtags >= 25:
        weak.append("hashtag stuffing")
    score = 2 * len(strong) + len(weak)
    label = "Yes" if score >= 2 and strong else ("Likely" if score >= 1 else "No")
    if score >= 2 and not strong:
        label = "Likely"
    reasons = strong + weak
    return label, reasons


def build_row(profile, posts):
    """
    profile: object with username, full_name, followers, followees, mediacount,
             biography, business_category_name, external_url, is_verified,
             is_business_account
    posts:   list of objects with date_utc, likes, comments, caption,
             caption_hashtags, is_video
    Returns (row_dict, None) or (None, skip_reason).
    """
    followers = profile.followers
    if followers >= MAX_FOLLOWERS:
        return None, "followers >= 1M"
    if followers < MIN_FOLLOWERS:
        return None, "followers < %d" % MIN_FOLLOWERS

    posts = sorted(posts, key=lambda p: p.date_utc, reverse=True)[:POSTS_FOR_ENGAGEMENT]
    if not posts:
        return None, "no posts"

    notes = []
    ers, hidden = [], 0
    for p in posts:
        likes = p.likes if p.likes is not None else -1
        if likes < 0:
            hidden += 1
            continue
        ers.append((likes + (p.comments or 0)) / followers)
    if not ers:
        return None, "likes hidden on all recent posts"
    if hidden:
        notes.append("likes hidden on %d post(s)" % hidden)
    engagement = round(statistics.mean(ers) * 100, 2)

    if len(posts) < POSTS_FOR_ENGAGEMENT:
        notes.append("only %d posts available" % len(posts))

    captions = [(p.caption or "").replace("\n", " ").strip() for p in posts]
    tag_counter = Counter()
    tag_counts = []
    for p in posts:
        tags = [t.lower() for t in (p.caption_hashtags or [])]
        tag_counts.append(len(tags))
        tag_counter.update(tags)
    bio_tags = [t.lower() for t in re.findall(r"#(\w+)", profile.biography or "")]
    tag_counter.update(bio_tags)
    top_tags = " ".join("#" + t for t, _ in tag_counter.most_common(5))
    avg_tags = round(sum(tag_counts) / len(tag_counts), 1)

    dates = [p.date_utc for p in posts]
    freq = posting_frequency(dates)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    latest = max(dates).replace(tzinfo=None)
    if (now - latest).days > 90:
        notes.append("inactive: last post %d days ago" % (now - latest).days)

    bio = (profile.biography or "").replace("\n", " ").strip()
    category = classify_category(
        " ".join([bio, profile.business_category_name or "", " ".join(t for t, _ in tag_counter.most_common(15))]),
        profile.business_category_name,
    )

    auto_label, auto_reasons = automation_label(bio, captions, dates, avg_tags, profile.external_url)
    if auto_reasons:
        notes.append("automation signals: " + ", ".join(auto_reasons))
    if profile.is_business_account:
        notes.append("business/creator account")

    row = {
        "Name": profile.full_name or profile.username,
        "Followers": followers,
        "Category": category,
        "Engagement Rate (%)": engagement,
        "Contact": extract_contact(bio, getattr(profile, "business_email", None)),
        "Posting Frequency (per month)": freq if freq is not None else "",
        "Hashtags": top_tags,
        "Notes": "; ".join(notes + [
            "Engagement measured from up to 10 recent posts; "
            "posting frequency derived from post timestamps; "
            "hashtags extracted from captions and bio"
        ]),
    }
    return row, None


# ----------------------------------------------------------------------------
# Output handling
# ----------------------------------------------------------------------------

def read_done(path, col="Username"):
    if not os.path.exists(path):
        return set(), 0
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    return {r[col] for r in rows if r.get(col)}, len(rows)


def append_row(path, columns, row):
    new = not os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=columns)
        if new:
            w.writeheader()
        w.writerow(row)
        f.flush()


# ----------------------------------------------------------------------------
# Fetching
# ----------------------------------------------------------------------------

class StopRun(Exception):
    """Raised when Instagram is blocking us; the run ends so it can be resumed later."""


def fetch(L, username, backoff_tries=3):
    """Returns (profile, posts) or raises a skip/stop signal."""
    wait = 300
    for attempt in range(backoff_tries + 1):
        try:
            profile = instaloader.Profile.from_username(L.context, username)
            if profile.is_private:
                return profile, None
            if profile.followers >= MAX_FOLLOWERS or profile.followers < MIN_FOLLOWERS:
                return profile, []
            posts = []
            for i, post in enumerate(profile.get_posts()):
                posts.append(post)
                if i + 1 >= POSTS_TO_FETCH:
                    break
            return profile, posts
        except igex.ProfileNotExistsException:
            raise
        except (igex.TooManyRequestsException, igex.LoginRequiredException,
                igex.QueryReturnedForbiddenException, igex.ConnectionException) as e:
            if attempt >= backoff_tries:
                raise StopRun("Blocked or rate limited (%s). Wait a few hours, then re-run." % type(e).__name__)
            print("  rate limited / blocked (%s). sleeping %d s ..." % (type(e).__name__, wait))
            time.sleep(wait)
            wait *= 2


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", default="names.txt", help="file with usernames (txt or csv)")
    ap.add_argument("--output", default="instagram_influencers.csv")
    ap.add_argument("--skipped", default="skipped_accounts.csv")
    ap.add_argument("--target", type=int, default=2000, help="number of valid influencers wanted")
    ap.add_argument("--max-per-run", type=int, default=250, help="profiles to attempt in one run")
    ap.add_argument("--session-user", default=None, help="throwaway account with a saved instaloader session")
    ap.add_argument("--delay-min", type=float, default=6)
    ap.add_argument("--delay-max", type=float, default=12)
    args = ap.parse_args()

    if instaloader is None:
        sys.exit("Install instaloader first: pip install instaloader")

    names = load_names(args.input)
    print("Loaded %d usernames from %s" % (len(names), args.input))

    done, valid_count = read_done(args.output)
    skipped, _ = read_done(args.skipped)
    todo = [n for n in names if n not in done and n not in skipped]
    print("Valid so far: %d / %d | skipped: %d | remaining to try: %d"
          % (valid_count, args.target, len(skipped), len(todo)))

    L = instaloader.Instaloader(
        download_pictures=False, download_videos=False, download_video_thumbnails=False,
        download_geotags=False, download_comments=False, save_metadata=False,
        compress_json=False, quiet=True, max_connection_attempts=1,
    )
    if args.session_user:
        try:
            L.load_session_from_file(args.session_user)
            print("Using saved session for %s" % args.session_user)
        except FileNotFoundError:
            sys.exit("No saved session. Run first:  instaloader --login=%s" % args.session_user)
    else:
        print("Running anonymously (expect lower limits; a saved session is recommended).")

    attempted = 0
    try:
        for username in todo:
            if valid_count >= args.target:
                break
            if attempted >= args.max_per_run:
                print("Reached --max-per-run. Re-run later (e.g. tomorrow) to continue.")
                break
            attempted += 1
            try:
                profile, posts = fetch(L, username)
                if posts is None:
                    row, reason = None, "private account"
                elif profile.followers >= MAX_FOLLOWERS or profile.followers < MIN_FOLLOWERS:
                    row, reason = None, "followers out of range (%d)" % profile.followers
                else:
                    row, reason = build_row(profile, posts)
            except igex.ProfileNotExistsException:
                row, reason = None, "profile not found"
            except StopRun:
                raise
            except Exception as e:  # unknown error: do not mark as skipped, retry next run
                print("[%d] %s: error %s: %s (will retry next run)" % (attempted, username, type(e).__name__, e))
                time.sleep(random.uniform(args.delay_min, args.delay_max))
                continue

            if row:
                append_row(args.output, COLUMNS, row)
                valid_count += 1
                print("[%d] %s OK (%d/%d) followers=%s ER=%s%%"
                      % (attempted, username, valid_count, args.target, row["Followers"], row["Engagement Rate (%)"]))
            else:
                append_row(args.skipped, ["Username", "Reason"], {"Username": username, "Reason": reason})
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

    print("\nValid influencers collected: %d / %d" % (valid_count, args.target))
    if valid_count >= args.target:
        print("Target reached. Next step: Phase 1 Week 2 cleaning.")


if __name__ == "__main__":
    main()
