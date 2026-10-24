import asyncio
import sys
from pathlib import Path


# Ensure the project root is available for imports.
PROJECT_DIR = Path(__file__).resolve().parent

if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))


from scraper.instagram_discovery import main as discovery_main


def main():
    """Launch the Instagram username discovery scraper."""

    try:
        asyncio.run(discovery_main())
    except KeyboardInterrupt:
        print("\nScraping interrupted. Previously saved usernames are preserved.")


if __name__ == "__main__":
    main()