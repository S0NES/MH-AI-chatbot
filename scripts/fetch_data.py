"""Fetch game databases from git repositories into data/<game-id>/.

    python scripts/fetch_data.py <game-id>=<git-url>[#<sub-folder>] [...]

Example:
    python scripts/fetch_data.py rise=https://github.com/Badge87/MHRiseScraperData.git#MHRiseScraperData
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data"


def fetch(game_id, source):
    url, _, subdir = source.partition("#")
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(["git", "clone", "--depth", "1", url, tmp], check=True)
        src = Path(tmp) / subdir
        if not src.is_dir():
            raise SystemExit("sub-folder %r not found in %s" % (subdir, url))
        files = list(src.glob("*.json"))
        if not files:
            raise SystemExit("no .json files in %s#%s" % (url, subdir))
        dest = DATA / game_id
        dest.mkdir(parents=True, exist_ok=True)
        for f in files:
            shutil.copy2(f, dest / f.name)
        print("%s: %d files -> %s" % (game_id, len(files), dest))


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    for spec in argv:
        game_id, sep, source = spec.partition("=")
        if not sep or not source:
            raise SystemExit("expected <game-id>=<git-url>[#sub-folder], got %r" % spec)
        fetch(game_id, source)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
