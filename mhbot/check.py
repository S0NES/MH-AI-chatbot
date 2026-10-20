"""Validate a game definition against its data: python -m mhbot.check <game-id>"""
import json
import sys

from .knowledge import DATA, ROOT, _read_json, load_games, resolve_data_dir


def main(argv):
    games, catalog = load_games()
    if not argv:
        for c in catalog:
            print("%-10s %-24s %s" % (c["id"], c["label"], "ready" if c["available"] else "unavailable: " + c["reason"]))
        return 0
    gid = argv[0]
    entry = next((c for c in catalog if c["id"] == gid), None)
    if entry is None:
        print("no definition with id %r in %s (found: %s)" % (gid, ROOT / "games", [c["id"] for c in catalog]))
        return 2
    if not entry["available"]:
        print("NOT LOADABLE:", entry["reason"])
        return 1
    g = games[gid]
    cfg = next(c for c in (_read_json(p, {}) for p in sorted((ROOT / "games").glob("*.json"))) if c.get("id") == gid)
    print("OK  %s  (data: %s)" % (g.label, resolve_data_dir(cfg, DATA)))
    for table in ("skills", "armors", "decorations", "weapons", "items"):
        rows = getattr(g, table)
        sample = next(iter(rows.items()), None) if isinstance(rows, dict) else (rows[0] if rows else None)
        print("  %-12s %5d rows   %s" % (table, len(rows), json.dumps(sample, ensure_ascii=False)[:150] if sample else "(not defined)"))
    print("  weapon types:", [w["name"] for w in g.weapon_types] or "none defined")
    print("  scored skills for a bow:", len(g.weapon_profile("bow")) if g.scoring else "no 'scoring' block - builds rank by defense only")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
