import json
import os
import platform
from pathlib import Path

import pathspec
import plyvel


class SymlinkManager:
    def __init__(self, repo_path, db_path=".symlinks.ldb"):
        self.repo_path = Path(repo_path).absolute()
        self.db_path = db_path
        self.db = plyvel.DB(db_path, create_if_missing=True)
        self.current_os = platform.system().lower()

        # Load translation rules from config file if exists
        self.translation_rules = self._load_translation_rules()
        self.gitignore_spec = self._load_gitignore_spec()

    def _load_gitignore_spec(self):
        """Load .gitignore patterns from repository."""
        gitignore_path = self.repo_path / ".gitignore"
        patterns = []

        if gitignore_path.exists():
            with open(gitignore_path, "r") as f:
                patterns = f.readlines()

        # Also check for .git/info/exclude
        git_exclude_path = self.repo_path / ".git" / "info" / "exclude"
        if git_exclude_path.exists():
            with open(git_exclude_path, "r") as f:
                patterns.extend(f.readlines())

        # Filter out comments and empty lines
        patterns = [p.strip() for p in patterns if p.strip() and not p.startswith("#")]

        return pathspec.PathSpec.from_lines("gitwildmatch", patterns)

    def _is_ignored(self, path):
        """Check if a path matches .gitignore patterns."""
        # Convert to relative path for matching
        try:
            rel_path = str(Path(path).relative_to(self.repo_path))
        except ValueError:
            return True  # Ignore paths outside repository

        # Check against gitignore patterns
        return self.gitignore_spec.match_file(rel_path)

    def _load_translation_rules(self):
        """Load translation rules from config file."""
        rules_file = self.repo_path / ".symlink-rules.json"
        default_rules = {
            "windows": {
                "/home/user": "C:\\Users\\user",
                "/usr/local": "C:\\Program Files",
            },
            "linux": {
                "C:\\Users\\user": "/home/user",
                "C:\\Program Files": "/usr/local",
            },
            "darwin": {
                "C:\\Users\\user": "/Users/user",
                "C:\\Program Files": "/usr/local",
            },
        }

        if rules_file.exists():
            with open(rules_file) as f:
                custom_rules = json.load(f)
                return {**default_rules, **custom_rules.get("rules", {})}
        return default_rules

    def _get_relative_path(self, path):
        """Convert absolute path to repository-relative path."""
        try:
            return str(Path(path).absolute().relative_to(self.repo_path))
        except ValueError:
            raise ValueError(f"Path {path} is not within repository {self.repo_path}")

    # CRUD Operations
    def add_symlink(self, link_path, target_path, force=False):
        """
        Add a new symlink to the repository and database.

        Args:
            link_path: Path where symlink should be created (relative or absolute)
            target_path: Target path the symlink should point to
            force: Overwrite existing symlink if True
        """
        link_path = Path(link_path)
        if not link_path.is_absolute():
            link_path = self.repo_path / link_path

        rel_path = self._get_relative_path(link_path)

        # Check if symlink already exists
        if link_path.exists():
            if not force:
                raise FileExistsError(f"Path {link_path} already exists")
            if not link_path.is_symlink():
                raise ValueError(f"Path {link_path} exists but is not a symlink")

        # Create parent directories if needed
        link_path.parent.mkdir(parents=True, exist_ok=True)

        # Create the symlink
        os.symlink(target_path, link_path)

        # Store in database
        self.db.put(
            rel_path.encode(),
            json.dumps(
                {
                    "original_target": str(target_path),
                    "translations": {
                        self.current_os: str(
                            target_path
                        )  # Store original as first translation
                    },
                }
            ).encode(),
        )

        return rel_path

    def remove_symlink(self, link_path):
        """
        Remove a symlink from both filesystem and database.

        Args:
            link_path: Path to symlink (relative or absolute)
        """
        link_path = Path(link_path)
        if not link_path.is_absolute():
            link_path = self.repo_path / link_path

        rel_path = self._get_relative_path(link_path)

        if not link_path.is_symlink():
            raise ValueError(f"Path {link_path} is not a symlink")

        # Remove from filesystem
        os.remove(link_path)

        # Remove from database
        self.db.delete(rel_path.encode())

        return rel_path

    def update_symlink_target(self, link_path, new_target):
        """
        Update a symlink's target path.

        Args:
            link_path: Path to existing symlink
            new_target: New target path
        """
        link_path = Path(link_path)
        if not link_path.is_absolute():
            link_path = self.repo_path / link_path

        rel_path = self._get_relative_path(link_path)

        if not link_path.is_symlink():
            raise ValueError(f"Path {link_path} is not a symlink")

        # Update filesystem symlink
        os.remove(link_path)
        os.symlink(new_target, link_path)

        # Update database record
        data = self.db.get(rel_path.encode())
        if data:
            record = json.loads(data.decode())
            record["original_target"] = str(new_target)
            record["translations"][self.current_os] = str(new_target)
            self.db.put(rel_path.encode(), json.dumps(record).encode())
        else:
            self.db.put(
                rel_path.encode(),
                json.dumps(
                    {
                        "original_target": str(new_target),
                        "translations": {self.current_os: str(new_target)},
                    }
                ).encode(),
            )

        return rel_path

    def list_symlinks(self):
        """Return a list of all tracked symlinks."""
        return [key.decode() for key, _ in self.db]

    def get_symlink_info(self, link_path):
        """
        Get information about a specific symlink.

        Returns:
            Dictionary with original_target and translations
        """
        link_path = Path(link_path)
        if not link_path.is_absolute():
            link_path = self.repo_path / link_path

        rel_path = self._get_relative_path(link_path)
        data = self.db.get(rel_path.encode())

        if not data:
            raise KeyError(f"No record found for symlink {rel_path}")

        return json.loads(data.decode())

    # Translation methods (from previous implementation)
    def translate_path(self, target_path):
        """Apply translation rules based on current OS."""
        for src, dest in self.translation_rules.get(self.current_os, {}).items():
            if str(target_path).startswith(src):
                return str(target_path).replace(src, dest)
        return str(target_path)

    def update_symlink(self, rel_path):
        """Update a single symlink based on DB record."""
        data = self.db.get(rel_path.encode())
        if not data:
            return False

        record = json.loads(data.decode())
        link_path = self.repo_path / rel_path

        if not link_path.exists():
            return False

        current_target = os.readlink(link_path)

        # Check if translation exists for this OS
        translated = record["translations"].get(self.current_os)
        if not translated:
            translated = self.translate_path(record["original_target"])
            record["translations"][self.current_os] = translated
            self.db.put(rel_path.encode(), json.dumps(record).encode())

        if current_target != translated:
            os.remove(link_path)
            os.symlink(translated, link_path)
            return True
        return False

    def process_all(self):
        """Process all symlinks in database."""
        updated = 0
        for key, value in self.db:
            rel_path = key.decode()
            if self.update_symlink(rel_path):
                updated += 1
        return updated

    def close(self):
        """Close the database connection."""
        self.db.close()

    def __enter__(self):
        return self

    # Scan untracked symlinks methods.
    def scan_for_untracked_symlinks(self):
        """Find symlinks in filesystem that aren't in the database.
        Respects .gitignore.
        """
        untracked = []
        db_keys = {key.decode() for key, _ in self.db}

        for root, dirs, files in os.walk(self.repo_path, topdown=True):
            # Remove ignored directories from walk
            dirs[:] = [d for d in dirs if not self._is_ignored(Path(root) / d)]

            for file in files:
                full_path = Path(root) / file
                if self._is_ignored(full_path):
                    continue

                if full_path.is_symlink():
                    try:
                        rel_path = str(full_path.relative_to(self.repo_path))
                        if rel_path not in db_keys:
                            untracked.append(rel_path)
                    except ValueError:
                        continue  # Skip symlinks pointing outside repo

        return untracked

    def add_untracked_symlinks(self):
        """Add all untracked symlinks to the database."""
        added = 0
        for rel_path in self.scan_for_untracked_symlinks():
            full_path = self.repo_path / rel_path
            target = os.readlink(full_path)
            print(rel_path, target)

            self.db.put(
                rel_path.encode(),
                json.dumps(
                    {
                        "original_target": target,
                        "translations": {self.current_os: target},
                    }
                ).encode(),
            )
            added += 1

        return added

    def full_sync(self):
        """Complete synchronization between filesystem and database."""
        # First add any untracked symlinks
        added = self.add_untracked_symlinks()

        # Then update existing symlinks for current platform
        updated = self.process_all()

        # Finally check for deleted symlinks
        deleted = self.cleanup_deleted_symlinks()

        return {"added": added, "updated": updated, "deleted": deleted}

    def cleanup_deleted_symlinks(self):
        """Remove database entries for symlinks that no longer exist."""
        deleted = 0
        to_delete = []

        for key, _ in self.db:
            rel_path = key.decode()
            full_path = self.repo_path / rel_path
            try:
                full_path.lstat()
            except FileNotFoundError:
                to_delete.append(key)

        for key in to_delete:
            self.db.delete(key)
            deleted += 1

        return deleted

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


# Command-line Interface
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Manage symlinks with LevelDB tracking"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Add command
    add_parser = subparsers.add_parser("add", help="Add a new symlink")
    add_parser.add_argument("link_path", help="Path to create symlink at")
    add_parser.add_argument(
        "target_path", help="Target path the symlink should point to"
    )
    add_parser.add_argument(
        "--force", action="store_true", help="Overwrite existing symlink"
    )

    # Remove command
    remove_parser = subparsers.add_parser("remove", help="Remove a symlink")
    remove_parser.add_argument("link_path", help="Path to symlink to remove")

    # Update command
    update_parser = subparsers.add_parser("update", help="Update symlink target")
    update_parser.add_argument("link_path", help="Path to existing symlink")
    update_parser.add_argument("new_target", help="New target path")

    # List command
    subparsers.add_parser("list", help="List all tracked symlinks")

    # Info command
    info_parser = subparsers.add_parser("info", help="Get info about a symlink")
    info_parser.add_argument("link_path", help="Path to symlink")

    # Add new commands
    scan_parser = subparsers.add_parser("scan", help="Scan for untracked symlinks")
    fullsync_parser = subparsers.add_parser(
        "fullsync", help="Complete sync between filesystem and DB"
    )

    args = parser.parse_args()

    with SymlinkManager(os.getcwd()) as manager:
        if args.command == "add":
            print(
                f"Added symlink: {manager.add_symlink(args.link_path, args.target_path, args.force)}"
            )
        elif args.command == "remove":
            print(f"Removed symlink: {manager.remove_symlink(args.link_path)}")
        elif args.command == "update":
            print(
                f"Updated symlink: {manager.update_symlink_target(args.link_path, args.new_target)}"
            )
        elif args.command == "list":
            print("Tracked symlinks:")
            for symlink in manager.list_symlinks():
                print(f" - {symlink}")
        elif args.command == "info":
            info = manager.get_symlink_info(args.link_path)
            print("Symlink info:")
            print(f"Original target: {info['original_target']}")
            print("Translations:")
            for os_name, path in info["translations"].items():
                print(f"  {os_name}: {path}")
        elif args.command == "sync":
            updated = manager.process_all()
            print(f"Updated {updated} symlinks")
        elif args.command == "scan":
            untracked = manager.scan_for_untracked_symlinks()
            print("Untracked symlinks:")
            for symlink in untracked:
                print(f" - {symlink}")
        elif args.command == "fullsync":
            result = manager.full_sync()
            print(
                f"Sync complete: {result['added']} added, {result['updated']} updated, {result['deleted']} deleted"
            )
