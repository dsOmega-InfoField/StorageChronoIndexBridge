import json
import os
import platform
from pathlib import Path
from types import UnionType
from typing import Literal

import pathspec
import plyvel

from symlink_manager.date_utils import postfix_created_file_with_utc


class ChronoIndexPaths:
    root: Path
    year: Path
    current: Path


class ChronoIndex:
    # "global" is reserved as a keyword.
    main: ChronoIndexPaths
    local: ChronoIndexPaths


def init_chrono_index(cwd: Path) -> ChronoIndex:
    # REFACTOR: Change to class. Root should be just chrono_index.global or
    # chrono_index.local
    chrono_index: ChronoIndex = {
        # REFACTOR: Duplicating
        # ~/.bookmarks/shared-scripts/InfoField__ChronoIndex/info_field_coonoIndex/info_field_consts.py
        "main": {
            "root": "/home/ds13/.bookmarks/ChronoIndex",
            "current": "/home/ds13/.bookmarks/ChronoIndex/Current",
        },
        "local": {
            "root": cwd / ".ChronoIndex",
        },
    }

    chrono_index['local']['root'].mkdir(exist_ok=True)

    # TODO: Get current year
    year = "2025"
    chrono_index['local']['year'] = chrono_index['local']['root'] / year
    chrono_index['local']['year'].mkdir(exist_ok=True)

    chrono_index['local']['current'] = chrono_index['local']['root'] / "Current"

    year_local_chrono_index = None
    try:
        year_local_chrono_index = os.readlink(chrono_index['local']['current'])
    except FileNotFoundError:
        os.symlink(
            chrono_index['local']['year'],
            chrono_index['local']['current'],
            target_is_directory=True
        )
        return chrono_index

    if year_local_chrono_index != chrono_index['local']['year']:
        update_fs_symlink(
            chrono_index['local']['current'],
            chrono_index['local']['year'],
            target_is_directory=True
        )

    return chrono_index


def update_fs_symlink(link_path: str | Path, new_link_path: str | Path, **symlink_kwargs):
    os.remove(link_path)
    os.symlink(new_link_path, link_path, **symlink_kwargs)


def is_git_repo(path: Path):
    git_dir = path / ".git"
    return git_dir.is_dir()


def find_repo_root(path):
    """Find repository root from the path"""

    if is_git_repo(path):
        return path

    for parent in Path(path).parents:
        if is_git_repo(parent):
            return parent


type TargetOsName = Literal["windows", "linux", "darwin"]
# Result of `platform.system().lower()`. Can be "java", for instance.
type OsName = UnionType[TargetOsName, str]


class Symlink:
    original_target: str
    translations: dict[OsName, str]


class SymlinkManager:
    def __init__(
        self,
        # Returns already resolved path if we're in a symlinked directory.
        cwd=os.getcwd(),
        db_path=".symlinks.ldb",
    ):
    
        self.cwd = Path(cwd).absolute()
        # INFO: Currently all rules and .gitignores we get from root - we don't
        # support potential extends and overrides.
        self.repo_path = find_repo_root(self.cwd)
        self.db_path = db_path
        self.db = plyvel.DB(db_path, create_if_missing=True)
        self.current_os = platform.system().lower()
        self.chrono_index = init_chrono_index(self.cwd)

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

        # Also check for user local gitignore: .git/info/exclude
        git_exclude_path = self.repo_path / ".git" / "info" / "exclude"
        if git_exclude_path.exists():
            with open(git_exclude_path, "r") as f:
                patterns.extend(f.readlines())

        # Filter out comments and empty lines
        patterns = [p.strip() for p in patterns if p.strip() and not p.startswith("#")]

        return pathspec.PathSpec.from_lines("gitwildmatch", patterns)

    def _is_ignored(self, path):
        """Check if a path matches .gitignore patterns."""
        # Convert to relative path for matching.
        try:
            rel_path = str(Path(path).relative_to(self.repo_path))
        except ValueError:
            return True  # Ignore paths outside repository

        # Check against gitignore patterns.
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
    def add_symlink(self, target_path, link_path, force=False):
        """
        Add a new symlink to the repository and database.

        Args:
            link_path: Path where symlink should be created (relative or absolute)
            target_path: Target path the symlink should point to
            force: Overwrite existing symlink if True
        """
        link_path = Path(link_path)
        if not link_path.is_absolute():
            link_path = self.cwd / link_path

        rel_path = self._get_relative_path(link_path)

        # Check if symlink already exists
        if link_path.exists():
            if not force:
                raise FileExistsError(f"Path {link_path} already exists")
            if not link_path.is_symlink():
                raise ValueError(f"Path {link_path} exists but is not a symlink")

        target_path = Path(target_path)
        if not target_path.exists():
            raise FileNotFoundError(f"Path {target_path} doesn't exist")

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
            link_path = self.cwd / link_path

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
            link_path = self.cwd / link_path

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
            link_path = self.cwd / link_path

        rel_path = self._get_relative_path(link_path)
        data = self.db.get(rel_path.encode())

        if not data:
            raise KeyError(f"No record found for symlink {rel_path}")

        return json.loads(data.decode())

    def add_to_chrono_index(self, file_path):
        """
        Add a file to the ChronoIndex.

        Args:
            file: Path to a file that will be added to ChronoIndex
        Returns:
            chrono_index_id: identifier of the file after it was added to ChronoIndex
        """
        file_path = Path(file_path)

        if not file_path.exists():
            raise FileNotFoundError(f"Path {file_path} doesn't exist")

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

    # def add_to_view(self, file, view_path):
    #     """
    #     Add a file to the view.

    #     Args:
    #         file: Path to a file that will be added to ChronoIndex and linked to the view
    #         view_path: Path of the view
    #     """
    #     pass

    # def add_view(self, files, view_name):
    #     """
    #     Add a view of the specified files.

    #     Args:
    #         files: Paths where symlink should be created (relative or absolute)
    #         target_path: Target path the symlink should point to
    #         force: Overwrite existing symlink if True
    #     """
    #     link_path = Path(link_path)
    #     if not link_path.is_absolute():
    #         link_path = self.repo_path / link_path

    #     rel_path = self._get_relative_path(link_path)

    #     # Check if symlink already exists
    #     if link_path.exists():
    #         if not force:
    #             raise FileExistsError(f"Path {link_path} already exists")
    #         if not link_path.is_symlink():
    #             raise ValueError(f"Path {link_path} exists but is not a symlink")

    #     target_path = Path(target_path)
    #     if not target_path.exists():
    #         raise FileNotFoundError(f"Path {target_path} doesn't exist")

    #     # Create parent directories if needed
    #     link_path.parent.mkdir(parents=True, exist_ok=True)

    #     # Create the symlink
    #     os.symlink(target_path, link_path)

    #     # Store in database
    #     self.db.put(
    #         rel_path.encode(),
    #         json.dumps(
    #             {
    #                 "original_target": str(target_path),
    #                 "translations": {
    #                     self.current_os: str(
    #                         target_path
    #                     )  # Store original as first translation
    #                 },
    #             }
    #         ).encode(),
    #     )

    #     return rel_path

    # Translation methods.
    def translate_path(self, target_path):
        """Apply translation rules based on current OS."""
        for src, dest in self.translation_rules.get(self.current_os, {}).items():
            if str(target_path).startswith(src):
                return str(target_path).replace(src, dest)
        return str(target_path)

    def extract_value_for_current_translation(self, record: Symlink):
        """
        Get from record a translation for current os or if doesn't exist
        translate path from original_target.

        Args:
            record(Symlink) from db
        Return:
            [boolean, translated_path] - indicator if translation for current os exists and a translated path.
        """
        translated_path = record["translations"].get(self.current_os)
        if translated_path:
            return [True, translated_path]

        # We haven't yet translated this symlink for current os.
        translated_path = self.translate_path(record["original_target"])
        record["translations"][self.current_os] = translated_path

        return [False, translated_path]

    def get_value_for_current_translation_from_db(self, key: str) -> Path:
        """
        Get from db a translation for current os. If translation doesn't exist -
        translate path from original_target and update db.
        If record doesn't exist at all, throws error.

        Args:
            key - to the record in db.
        Return:
            translated_path - a translated path.
        Throws:
            KeyError - if entry by `key` doesn't exist in db.
        """
        data = self.db.get(key.encode())
        if not data:
            # QUESTION: Maybe db already throws better error?
            raise KeyError(f"Entry by the key: {key} doesn't exist in db")

        record = json.loads(data.decode())

        [was_already_translated, translated_path] = (
            self.extract_value_for_current_translation(record)
        )

        if not was_already_translated:
            self.db.put(key.encode(), json.dumps(record).encode())

        return translated_path

    def update_symlink(self, rel_path):
        """
        Update a single symlink based on DB record.

        Returns:
            True if symlink was added.
            False is symlink already existed or failed to be added.
        """
        link_path = self.cwd / rel_path

        if not link_path.exists():
            return False

        translated_path = None

        try:
            translated_path = self.get_value_for_current_translation_from_db(rel_path)
        except KeyError:
            return False

        current_target = os.readlink(link_path)

        if current_target != translated_path:
            update_fs_symlink(link_path, translated_path)
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

    # Scan untracked symlinks.
    def scan_for_untracked_symlinks(self):
        """Find symlinks in filesystem that aren't in the database.
        Respects .gitignore.
        """
        untracked = []
        db_keys = {key.decode() for key, _ in self.db}

        for root, dirs, files in os.walk(self.cwd, topdown=True):
            # Iterate over both dirs and files.
            # PERF: Doesn't it iterate same files twice?
            paths = [Path(root) / path for path in files + dirs]
            # Remove ignored paths from walk.
            relevant_paths = [path for path in paths if not self._is_ignored(path)]

            for path in relevant_paths:
                if path.is_symlink():
                    try:
                        rel_path = str(path.relative_to(self.cwd))
                        if rel_path not in db_keys:
                            untracked.append(rel_path)
                    except ValueError:
                        continue  # Skip symlinks pointing outside repo

        return untracked

    def add_untracked_symlinks(self):
        """Add all untracked symlinks to the database."""
        added = 0
        for rel_path in self.scan_for_untracked_symlinks():
            full_path = self.cwd / rel_path
            target = os.readlink(full_path)

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

    def cleanup_deleted_symlinks(self):
        """Remove database entries for symlinks that no longer exist."""
        deleted = 0
        to_delete = []

        for key, _ in self.db:
            rel_path = key.decode()
            full_path = self.cwd / rel_path
            try:
                full_path.lstat()
            except FileNotFoundError:
                to_delete.append(key)

        for key in to_delete:
            self.db.delete(key)
            deleted += 1

        return deleted

    # PERF: All three methods are loops, usually over the same values.
    def push(self):
        """Update data in database from filesystem (push from fs -> db)."""
        # First add any untracked symlinks.
        added = self.add_untracked_symlinks()

        # Then update existing symlinks for current platform.
        updated = self.process_all()

        # Finally check for deleted symlinks.
        deleted = self.cleanup_deleted_symlinks()

        return {"added": added, "updated": updated, "deleted": deleted}

    # TODO: Add hub.
    def link(self, source: Path, target: Path):
        """Transiently add link to local ChronoIndex and link it to the target location.

        :param source: 
        :param target: 
        """
        name_in_chrono_index = postfix_created_file_with_utc(self.chrono_index['local']['current'] / target.name)
        os.link(source, name_in_chrono_index)
        os.symlink(name_in_chrono_index, target)

    def add_tracked_symlink(self, rel_path):
        """
        Add a single symlink based on DB record.

        Returns:
            True if symlink was added.
            False is symlink failed to be added.
        """
        link_path = self.cwd / rel_path

        translated_path = None

        try:
            translated_path = self.get_value_for_current_translation_from_db(rel_path)
        except KeyError:
            return False

        current_target = None
        try:
            current_target = os.readlink(link_path)
        except FileNotFoundError:
            self.link(translated_path, link_path)
            return True

        if current_target != translated_path:
            update_fs_symlink(link_path, translated_path)
            return True

        return False

    def add_tracked_symlinks(self):
        """Add all tracked in the database symlinks to filesystem."""
        values = [self.add_tracked_symlink(key.decode()) for key, _ in self.db]

        # Number of True's (newly added items).
        return len(list(filter(bool, values)))

    def cleanup_untracked_symlinks(self):
        """Remove entities for symlinks that are not tracked inside database"""
        deleted = 0
        to_delete = []

        for rel_path in self.scan_for_untracked_symlinks():
            full_path = self.cwd / rel_path
            to_delete.append(full_path)

        for path in to_delete:
            os.remove(path)
            deleted += 1

        return deleted

    # PERF: All three methods are loops, usually over the same values.
    def pull(self):
        """Pull data from database to filesystem (pull from db -> fs)."""
        # First ensure symlinks are tracked.
        added = self.add_tracked_symlinks()

        # Then update existing symlinks for current platform.
        updated = self.process_all()

        # Finally check for deleted symlinks.
        deleted = self.cleanup_untracked_symlinks()

        return {"added": added, "updated": updated, "deleted": deleted}

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
    add_parser.add_argument(
        "target_path", help="Target path the symlink should point to"
    )
    add_parser.add_argument("link_path", help="Path to create symlink at")
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

    # Sync commands.
    scan_parser = subparsers.add_parser("scan", help="Scan for untracked symlinks")

    push_parser = subparsers.add_parser("push", help="Sync data from filesystem to DB")

    pull_parser = subparsers.add_parser("pull", help="Sync data from DB to filesystem")

    args = parser.parse_args()

    with SymlinkManager() as manager:
        if args.command == "add":
            print(
                f"Added symlink: {manager.add_symlink(args.target_path, args.link_path, args.force)}"
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
            if not untracked:
                print("There's no untracked symlinks")
            else:
                print("Untracked symlinks:")
                for symlink in untracked:
                    print(f" - {symlink}")
        elif args.command == "push":
            result = manager.push()
            print(
                f"Push to DB completed: {result['added']} added, {result['updated']} updated, {result['deleted']} deleted"
            )
        elif args.command == "pull":
            result = manager.pull()
            print(
                f"Pull to filesystem completed: {result['added']} added, {result['updated']} updated, {result['deleted']} deleted"
            )
