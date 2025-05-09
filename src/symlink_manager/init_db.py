import os
import json
import plyvel
from pathlib import Path

def init_db(repo_path, db_path='.symlinks.ldb'):
    """Initialize LevelDB with all symlinks in repository."""
    db = plyvel.DB(db_path, create_if_missing=True)
    
    for root, _, files in os.walk(repo_path):
        for file in files:
            full_path = Path(root) / file
            if full_path.is_symlink():
                rel_path = str(full_path.relative_to(repo_path))
                target = os.readlink(full_path)
                
                # Store original mapping
                db.put(rel_path.encode(), json.dumps({
                    'original_target': target,
                    'translations': {}
                }).encode())
    
    db.close()

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: init-symlink-db.py <repo-path> [db-path]")
        sys.exit(1)
    
    repo_path = sys.argv[1]
    db_path = sys.argv[2] if len(sys.argv) > 2 else '.symlinks.ldb'
    init_db(repo_path, db_path)
