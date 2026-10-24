import argparse
import asyncio
import logging
import random
import re
import sys
import json
import hashlib
from collections import Counter
from pathlib import Path
from typing import Optional
from urllib.parse import quote_plus, unquote, urlparse

import yaml

from bs4 import BeautifulSoup
from playwright.async_api import (
    async_playwright,
    Browser,
    Page,
)

try:
    from .username_store import UsernameStore
except ImportError:
    from username_store import UsernameStore


INSPECTED_POSTS = set()
FILE_DIR = Path(__file__).resolve().parent

# Supports running from the project root or scraper directory.
if (FILE_DIR / "config.yaml").exists():
    PROJECT_DIR = FILE_DIR
elif (FILE_DIR.parent / "config.yaml").exists():
    PROJECT_DIR = FILE_DIR.parent
else:
    PROJECT_DIR = FILE_DIR.parent

CONFIG_PATH = PROJECT_DIR / "config.yaml"
DATA_DIR = PROJECT_DIR / "data" / "usernames"


def load_config() -> dict:
    """Load and validate the project's YAML configuration."""

    if not CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"Configuration file not found: {CONFIG_PATH}"
        )

    with CONFIG_PATH.open("r", encoding="utf-8") as file:
        config = yaml.safe_load(file)

    if not isinstance(config, dict):
        raise ValueError("config.yaml must contain a YAML mapping.")

    if not config.get("niches"):
        raise ValueError("No niches were defined in config.yaml.")

    if not config.get("runtime"):
        raise ValueError("The runtime section is missing from config.yaml.")

    return config


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger("instagram_discovery")


# ============================================================
# USERNAME EXTRACTION
# ============================================================

NON_PROFILE_PATHS = {
    "explore",
    "accounts",
    "direct",
    "reels",
    "reel",
    "stories",
    "about",
    "developer",
    "developers",
    "p",
    "tv",
    "legal",
    "privacy",
    "web",
    "emails",
    "session",
    "challenge",
    "checkpoint",
}

USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9._]{1,30}$")

GENERIC_HASHTAGS = {
    "viral",
    "trending",
    "explore",
    "explorepage",
    "fyp",
    "follow",
    "followforfollow",
    "like",
    "likeforlike",
    "instagood",
    "instagram",
    "reels",
    "reelitfeelit",
}


def normalize_username(value: str) -> Optional[str]:
    """
    Accept a username or a single-segment Instagram profile URL.

    Returns a normalized username, or None if the value does not
    resemble a valid Instagram username.
    """

    if not value:
        return None

    value = value.strip()

    if value.startswith("@"):
        value = value[1:]

    if "instagram.com/" in value.casefold():
        parsed = urlparse(
            value
            if value.startswith(("http://", "https://"))
            else f"https://{value}"
        )

        if parsed.hostname not in {
            "instagram.com",
            "www.instagram.com",
        }:
            return None

        parts = [
            unquote(part)
            for part in parsed.path.strip("/").split("/")
            if part
        ]

        if len(parts) != 1:
            return None

        value = parts[0]

    value = value.strip("/")

    if not USERNAME_PATTERN.fullmatch(value):
        return None

    if value.casefold() in NON_PROFILE_PATHS:
        return None

    return value


def extract_usernames(html: str) -> set[str]:
    """
    Extract profile-like usernames from links in loaded HTML.

    This function parses the current page only. It never navigates
    to any discovered profile.
    """

    soup = BeautifulSoup(html, "html.parser")
    usernames = {}

    for anchor in soup.find_all("a", href=True):
        href = anchor["href"].strip()

        if not href.startswith("/"):
            continue

        parsed = urlparse(href)

        parts = [
            unquote(part)
            for part in parsed.path.strip("/").split("/")
            if part
        ]

        # Profile-like links must have exactly one path component.
        if len(parts) != 1:
            continue

        username = normalize_username(parts[0])

        if username:
            # Case-insensitive deduplication while preserving spelling.
            usernames[username.casefold()] = username

    return set(usernames.values())

def extract_post_urls(html: str) -> list[str]:
    """
    Extract public Instagram post, reel, and IGTV URLs
    from the currently loaded HTML.

    Does not visit individual profiles.
    """
    soup = BeautifulSoup(html, "html.parser")
    post_urls = set()

    valid_post_types = {"p", "reel", "tv"}

    for anchor in soup.find_all("a", href=True):
        href = anchor["href"]

        if not href.startswith("/"):
            continue

        parsed = urlparse(href)
        parts = [
            part
            for part in parsed.path.strip("/").split("/")
            if part
        ]

        if len(parts) != 2:
            continue

        post_type, shortcode = parts

        if post_type not in valid_post_types:
            continue

        if not shortcode:
            continue

        post_urls.add(
            f"https://www.instagram.com/{post_type}/{shortcode}/"
        )

    return sorted(post_urls)


def extract_post_author(html: str) -> str | None:
    """Extract the likely author username from a public Instagram post."""

    soup = BeautifulSoup(html, "html.parser")

    # Prefer Instagram's structured post metadata.
    for script in soup.find_all("script", type="application/ld+json"):
        raw = script.string or script.get_text()
        if not raw:
            continue

        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue

        items = data if isinstance(data, list) else [data]

        for item in items:
            if not isinstance(item, dict):
                continue

            author = item.get("author")

            if isinstance(author, dict):
                for key in ("alternateName", "name", "url"):
                    username = normalize_username(str(author.get(key, "")))
                    if username:
                        return username

            elif isinstance(author, str):
                username = normalize_username(author)
                if username:
                    return username

    # Fall back to an explicit Instagram post-owner field.
    patterns = [
        r'"owner"\s*:\s*\{[^{}]{0,1000}?"username"\s*:\s*"([^"]+)"',
        r'"user"\s*:\s*\{[^{}]{0,1000}?"username"\s*:\s*"([^"]+)"',
    ]

    for pattern in patterns:
        match = re.search(pattern, html)

        if match:
            username = normalize_username(match.group(1))
            if username:
                return username

    # Do not guess from arbitrary profile links on the page.
    return None




def extract_hashtags_from_post(
    post_html: str,
    limit: int = 6,
) -> list[str]:
    """
    Extract up to the first 'limit' hashtag links from one HTML fragment.

    Note: these are hashtag links visible in the HTML, not necessarily
    the first hashtags in the post's original caption.
    """

    soup = BeautifulSoup(post_html, "html.parser")

    hashtags = []
    seen = set()

    for anchor in soup.find_all("a", href=True):
        href = urlparse(anchor["href"]).path
        parts = [
            unquote(part)
            for part in href.strip("/").split("/")
            if part
        ]

        if len(parts) < 3:
            continue

        if parts[0] != "explore" or parts[1] != "tags":
            continue

        tag = parts[2].strip().lstrip("#").casefold()

        if not tag:
            continue

        if tag in GENERIC_HASHTAGS:
            continue

        if tag in seen:
            continue

        seen.add(tag)
        hashtags.append(f"#{tag}")

        if len(hashtags) >= limit:
            break

    return hashtags


def extract_page_hashtags(
    html: str,
    seen_articles: set[str],
    limit_per_post: int = 6,
) -> Counter:
    """
    Count hashtags from newly encountered article elements only.

    Each article is identified by a content hash to prevent the same
    visible post from being counted repeatedly during scrolling.
    """

    soup = BeautifulSoup(html, "html.parser")
    frequency = Counter()

    for article in soup.find_all("article"):
        article_html = str(article)

        fingerprint = hashlib.sha256(
            article_html.encode("utf-8")
        ).hexdigest()

        if fingerprint in seen_articles:
            continue

        seen_articles.add(fingerprint)

        hashtags = extract_hashtags_from_post(
            article_html,
            limit=limit_per_post,
        )

        for hashtag in hashtags:
            frequency[hashtag] += 1

    return frequency

# ============================================================
# PAGE ACCESS AND RETRIES
# ============================================================

def is_access_restricted(url: str, body_text: str = "") -> bool:
    """Identify common login, challenge, or restriction pages."""

    url = url.casefold()
    body_text = body_text.casefold()

    restricted_url_markers = (
        "/accounts/login",
        "/challenge/",
        "/checkpoint/",
    )

    restricted_text_markers = (
        "please wait a few minutes before you try again",
        "try again later",
        "confirm it's you",
    )

    if any(marker in url for marker in restricted_url_markers):
        return True

    if any(
        marker in body_text
        for marker in restricted_text_markers
    ):
        return True

    return False


async def navigate_with_retries(
    page: Page,
    url: str,
    runtime: dict,
) -> bool:
    """
    Navigate to a public page with retries.

    Does not attempt to bypass login requirements, CAPTCHAs,
    challenges, rate limits, or other access restrictions.
    """

    browser_settings = runtime["browser"]

    timeout = browser_settings.get("timeout", 30000)
    max_retries = runtime.get("max_retries", 3)
    retry_delay = runtime.get("retry_delay", 5)

    for attempt in range(max_retries + 1):
        try:
            response = await page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=timeout,
            )

            if response and response.status in (401, 403, 429):
                logger.warning(
                    "Access restricted: HTTP %s",
                    response.status,
                )
                return False

            # Allow the page time to render.
            await page.wait_for_timeout(2000)

            body_text = ""

            try:
                body_text = await page.locator("body").inner_text(
                    timeout=3000
                )
            except Exception:
                pass

            if is_access_restricted(page.url, body_text):
                logger.warning(
                    "Login/challenge/restriction detected. "
                    "Skipping this page."
                )
                return False

            return True

        except Exception as exc:
            logger.warning(
                "Navigation attempt %d/%d failed: %s",
                attempt + 1,
                max_retries + 1,
                exc,
            )

            if attempt < max_retries:
                await asyncio.sleep(retry_delay)

    return False


async def wait_between_requests(runtime: dict) -> None:
    """Wait for a random duration within the configured range."""

    delays = runtime.get("delays", {})

    minimum = float(delays.get("min", 1))
    maximum = float(delays.get("max", 3))

    if maximum < minimum:
        maximum = minimum

    await asyncio.sleep(random.uniform(minimum, maximum))


async def collect_from_hashtag(
    page: Page,
    hashtag: str,
    runtime: dict,
) -> tuple[set[str], Counter]:
    """Discover post authors and related hashtags from public hashtag pages."""

    tag = hashtag.strip().lstrip("#")
    if not tag:
        return set(), Counter()

    hashtag_url = (
        "https://www.instagram.com/explore/tags/"
        f"{quote_plus(tag)}/"
    )

    logger.info("[HASHTAG] %s", hashtag)

    success = await navigate_with_retries(page, hashtag_url, runtime)
    if not success:
        return set(), Counter()

    post_urls = set()
    max_scrolls = runtime.get("max_scrolls_per_page", 5)
    max_posts = runtime.get("max_posts_to_inspect_per_hashtag", 20)

    for scroll_number in range(max_scrolls + 1):
        post_urls.update(extract_post_urls(await page.content()))

        if len(post_urls) >= max_posts or scroll_number >= max_scrolls:
            break

        try:
            await page.evaluate(
                "() => window.scrollTo(0, document.body.scrollHeight)"
            )
        except Exception as exc:
            logger.warning(
                "Could not scroll hashtag page %s: %s", hashtag, exc
            )
            break

        await wait_between_requests(runtime)

    selected_posts = sorted(post_urls)[:max_posts]
    usernames = {}
    hashtag_frequency = Counter()

    for post_url in selected_posts:
        if post_url in INSPECTED_POSTS:
            continue

        success = await navigate_with_retries(page, post_url, runtime)
        if not success:
            continue

        INSPECTED_POSTS.add(post_url)

        try:
            post_html = await page.content()

            author = extract_post_author(post_html)
            if author:
                usernames[author.casefold()] = author

            hashtags = extract_hashtags_from_post(post_html, limit=6)
            hashtag_frequency.update(hashtags)

        except Exception as exc:
            logger.warning("Could not process post %s: %s", post_url, exc)

        await wait_between_requests(runtime)

    logger.info(
        "[FOUND] %d candidate authors from #%s", len(usernames), tag
    )

    if hashtag_frequency:
        logger.info("[TOP HASHTAGS] %s", hashtag_frequency.most_common(4))

    return set(usernames.values()), hashtag_frequency



async def collect_from_search(
    page: Page,
    query: str,
    runtime: dict,
) -> set[str]:
    """
    Search Instagram for a configured query and extract usernames
    from the loaded search-results HTML.

    Does not navigate to individual profiles.
    """

    url = (
        "https://www.instagram.com/explore/search/keyword/"
        f"?q={quote_plus(query)}"
    )

    logger.info("[SEARCH] %s", query)

    success = await navigate_with_retries(
        page,
        url,
        runtime,
    )

    if not success:
        return set()

    usernames = {}

    max_per_search = runtime.get(
        "max_usernames_per_search",
        100,
    )

    max_scrolls = runtime.get("max_scrolls_per_page", 5)

    for scroll_number in range(max_scrolls + 1):
        html = await page.content()

        for username in extract_usernames(html):
            usernames[username.casefold()] = username

        if len(usernames) >= max_per_search:
            break

        if scroll_number >= max_scrolls:
            break

        try:
            await page.evaluate(
                "() => window.scrollTo(0, document.body.scrollHeight)"
            )
        except Exception as exc:
            logger.warning("Could not scroll search page: %s", exc)
            break

        await wait_between_requests(runtime)

    logger.info(
        "[FOUND] %d candidate usernames from search",
        len(usernames),
    )

    return set(usernames.values())


# ============================================================
# CORE NICHE COLLECTION
# ============================================================

async def run_for_niche(
    niche: str,
    config: dict,
    store: UsernameStore,
    limit: Optional[int] = None,
) -> None:
    """
    Collect usernames for one niche.

    Existing usernames are retained. The run resumes until the target
    is reached or the configured discovery sources are exhausted.
    """

    niches = config["niches"]

    if niche not in niches:
        raise ValueError(
            f"Unknown niche '{niche}'. "
            f"Available niches: {', '.join(niches)}"
        )

    niche_cfg = niches[niche]
    runtime = config["runtime"]

    target = (
        niche_cfg["target"]
        if limit is None
        else max(0, limit)
    )

    initial_usernames = store.get_niche_usernames(niche)

    existing_casefold = {
        username.casefold()
        for username in initial_usernames
    }

    def current_count() -> int:
        return len({
            username.casefold()
            for username in store.get_niche_usernames(niche)
        })

    logger.info("=" * 55)
    logger.info("[NICHE] %s", niche)
    logger.info("[TARGET] %d", target)
    logger.info("[EXISTING] %d usernames", current_count())

    if current_count() >= target:
        logger.info("[DONE] Target already reached for %s", niche)
        return

    pending_hashtags = list(niche_cfg.get("initial_hashtags", []))
    processed_hashtags = set()
    hashtag_frequency = Counter()

    delay_settings = runtime.get("delays", {})
    minimum_delay = float(delay_settings.get("min", 1))
    maximum_delay = float(delay_settings.get("max", 3))

    if maximum_delay < minimum_delay:
        maximum_delay = minimum_delay

    async with async_playwright() as playwright:
        browser: Optional[Browser] = None
        context = None

        try:
            browser = await playwright.chromium.launch(
                headless=runtime["browser"].get("headless", True),
                args=runtime["browser"].get("args", []),
            )

            context = await browser.new_context()
            page = await context.new_page()

            # ----------------------------------------------------
            # PHASE 1: HASHTAG DISCOVERY
            # ----------------------------------------------------

            while (
                pending_hashtags
                and current_count() < target
            ):
                hashtag = pending_hashtags.pop(0)
                normalized_tag = hashtag.strip().casefold()

                if normalized_tag in processed_hashtags:
                    continue

                processed_hashtags.add(normalized_tag)

                discovered, frequencies = await collect_from_hashtag(
                    page,
                    hashtag,
                    runtime,
                )

                hashtag_frequency.update(frequencies)

                current = current_count()
                remaining = target - current

                existing_casefold = {
                    username.casefold()
                    for username in store.get_niche_usernames(niche)
                }

                candidates = sorted(
                    (
                        username
                        for username in discovered
                        if username.casefold() not in existing_casefold
                    ),
                    key=str.casefold,
                )

                max_per_search = runtime.get(
                    "max_usernames_per_search",
                    100,
                )

                candidates = candidates[
                    :min(remaining, max_per_search)
                ]

                if candidates:
                    added = store.add_usernames(
                        niche,
                        candidates,
                    )

                    logger.info(
                        "[SAVED] %d new usernames",
                        added,
                    )

                logger.info(
                    "[TOTAL] %d/%d for %s",
                    current_count(),
                    target,
                    niche,
                )

                pending_tags = {
                    item.strip().lstrip("#").casefold()
                    for item in pending_hashtags
                }

                top_hashtags = [
                    tag
                    for tag, count in hashtag_frequency.most_common()
                    if count >= 2
                    and tag.strip().lstrip("#").casefold() not in processed_hashtags
                    and tag.strip().lstrip("#").casefold() not in pending_tags
                ][:4]

                for tag in top_hashtags:
                    pending_hashtags.append(tag)

                if top_hashtags:
                    logger.info(
                        "[DISCOVERED HASHTAGS] %s",
                        ", ".join(top_hashtags),
                    )

                await wait_between_requests(runtime)

            # ----------------------------------------------------
            # PHASE 2: CONFIGURED SEARCH QUERIES
            # ----------------------------------------------------

            if current_count() < target:
                for query in niche_cfg.get("search_queries", []):
                    if current_count() >= target:
                        break

                    discovered = await collect_from_search(
                        page,
                        query,
                        runtime,
                    )

                    current = current_count()
                    remaining = target - current

                    existing_casefold = {
                        username.casefold()
                        for username in store.get_niche_usernames(niche)
                    }

                    candidates = sorted(
                        (
                            username
                            for username in discovered
                            if username.casefold() not in existing_casefold
                        ),
                        key=str.casefold,
                    )

                    max_per_search = runtime.get(
                        "max_usernames_per_search",
                        100,
                    )

                    candidates = candidates[
                        :min(remaining, max_per_search)
                    ]

                    if candidates:
                        added = store.add_usernames(
                            niche,
                            candidates,
                        )

                        logger.info(
                            "[SAVED] %d new usernames from search",
                            added,
                        )

                    logger.info(
                        "[TOTAL] %d/%d for %s",
                        current_count(),
                        target,
                        niche,
                    )

                    await wait_between_requests(runtime)

            logger.info(
                "[DONE] %s: collected %d/%d usernames",
                niche,
                current_count(),
                target,
            )

            logger.info(
                "[HASHTAG SUMMARY] %s",
                hashtag_frequency.most_common(10),
            )

        finally:
            if context is not None:
                await context.close()

            if browser is not None:
                await browser.close()



async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Instagram username discovery."
    )

    parser.add_argument(
        "--niche",
        type=str,
        help="Collect usernames for one configured niche.",
    )

    parser.add_argument(
        "--limit",
        type=int,
        help="Override the target count for this run.",
    )

    parser.add_argument(
        "--all",
        action="store_true",
        help="Process every niche in config.yaml.",
    )

    args = parser.parse_args()

    config = load_config()

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    store = UsernameStore(DATA_DIR)

    if args.all:
        niches_to_run = list(config["niches"].keys())

    elif args.niche:
        if args.niche not in config["niches"]:
            parser.error(
                f"Unknown niche '{args.niche}'. "
                f"Choose from: {', '.join(config['niches'])}"
            )

        niches_to_run = [args.niche]

    else:
        parser.error(
            "Specify --niche NAME or --all."
        )

    for niche in niches_to_run:
        await run_for_niche(
            niche=niche,
            config=config,
            store=store,
            limit=args.limit,
        )


if __name__ == "__main__":
    asyncio.run(main())