from pathlib import Path
from typing import Iterable


class UsernameStore:
    """Store discovered Instagram usernames by niche and in a master file."""

    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.master_file = self.data_dir / "all_usernames.txt"
        self.master_file.touch(exist_ok=True)

    def _niche_file(self, niche: str) -> Path:
        """Return the filename for a niche."""
        return self.data_dir / f"{niche}.txt"

    @staticmethod
    def normalize(username: str) -> str | None:
        """Validate and normalize a username without its @ prefix."""

        if not username:
            return None

        username = username.strip()

        if username.startswith("@"):
            username = username[1:]

        if not username:
            return None

        if len(username) > 30:
            return None

        if not all(
            char.isalnum() or char in "._"
            for char in username
        ):
            return None

        return username

    def get_niche_usernames(self, niche: str) -> set[str]:
        """Load unique usernames belonging to one niche."""

        file_path = self._niche_file(niche)

        if not file_path.exists():
            return set()

        usernames = {}

        for line in file_path.read_text(
            encoding="utf-8"
        ).splitlines():
            username = self.normalize(line)

            if username:
                usernames[username.casefold()] = username

        return set(usernames.values())

    def get_master_associations(self) -> set[tuple[str, str]]:
        """
        Read all username-niche associations.

        The master file format is:
            username | niche

        A username can legitimately belong to multiple niches.
        """

        associations = set()

        if not self.master_file.exists():
            return associations

        for line in self.master_file.read_text(
            encoding="utf-8"
        ).splitlines():

            if "|" not in line:
                continue

            raw_username, raw_niche = line.split("|", 1)

            username = self.normalize(raw_username)
            niche = raw_niche.strip()

            if username and niche:
                associations.add(
                    (username.casefold(), niche.casefold())
                )

        return associations

    
    def add_usernames(
        self,
        niche: str,
        usernames: Iterable[str],
    ) -> int:
        """Save usernames and repair missing master associations."""

        file_path = self._niche_file(niche)
        file_path.touch(exist_ok=True)

        existing = {
            username.casefold()
            for username in self.get_niche_usernames(niche)
        }

        new_usernames = {}

        for raw_username in usernames:
            username = self.normalize(raw_username)

            if not username:
                continue

            key = username.casefold()

            if key not in existing:
                new_usernames[key] = username

        # Save only usernames not already present in this niche.
        if new_usernames:
            with file_path.open("a", encoding="utf-8") as file:
                for username in new_usernames.values():
                    file.write(username + "\n")

        # Repair the master file even if no new niche usernames were added.
        master_associations = self.get_master_associations()

        niche_key = niche.casefold()
        all_niche_usernames = self.get_niche_usernames(niche)

        with self.master_file.open("a", encoding="utf-8") as file:
            for username in all_niche_usernames:
                association = (username.casefold(), niche_key)

                if association not in master_associations:
                    file.write(f"{username} | {niche}\n")
                    master_associations.add(association)

        return len(new_usernames)

    def count(self, niche: str) -> int:
        """Return the number of unique usernames for a niche."""
        return len(self.get_niche_usernames(niche))

    def total_unique_usernames(self) -> int:
        """Return the unique username count across the master file."""

        usernames = set()

        for username, _ in self.get_master_associations():
            usernames.add(username)

        return len(usernames)