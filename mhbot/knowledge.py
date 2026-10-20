"""Loads every configured game through its adapter and builds lookup indexes."""
import json
import os
import re
from pathlib import Path

from .declarative import SchemaError, load as load_declared

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


def norm(text):
    """Lowercase, drop apostrophes/punctuation, collapse whitespace: "Master's Touch" -> "masters touch"."""
    text = text.lower().replace("'", "").replace("’", "")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9+/ ]", " ", text)).strip()


class Game:
    def __init__(self, cfg, model):
        self.id = cfg["id"]
        self.label = cfg["label"]
        self.__dict__.update(model)
        self.skill_by_norm = {norm(n): n for n in self.skills}
        self.named = {}
        for kind, rows in (("armor", self.armors), ("weapon", self.weapons),
                           ("decoration", self.decorations), ("item", self.items)):
            for row in rows:
                self.named.setdefault(norm(row["name"]), (kind, row))
        self.part_order = list(model.get("part_order") or [])
        self.parts = sorted({a["part"] for a in self.armors})

    def rank_by_id(self, rank_id):
        return next((r for r in self.ranks if r["id"] == rank_id), None)

    def rank_for_number(self, number):
        """The rank whose `hunter_rank` range [min, max] contains the number (max null means no upper limit)."""
        for r in self.ranks:
            bounds = r.get("hunter_rank")
            if bounds and number >= bounds[0] and (bounds[1] is None or number <= bounds[1]):
                return r
        return None

    def rank_has_data(self, rank_id):
        return any(a["rank"] == rank_id for a in self.armors) or any(w["rank"] == rank_id for w in self.weapons)

    def rank_text(self, rank_id):
        r = self.rank_by_id(rank_id)
        if r is None:
            return rank_id
        bounds = r.get("hunter_rank")
        if not bounds:
            return r["label"]
        span = "HR %d+" % bounds[0] if bounds[1] is None else "HR %d-%d" % (bounds[0], bounds[1])
        return "%s (%s)" % (r["label"], span)

    def _weapon_mentions(self, text):
        """Weapon types named in a text, by name, alias, shared last word or text_hints."""
        found = set()
        for wt in self.weapon_types:
            tokens = {norm(wt["name"])} | {norm(a) for a in wt["aliases"] if len(a) >= 3} | {norm(h) for h in wt.get("text_hints", [])}
            words = norm(wt["name"]).split()
            if len(words) > 1 and len(words[-1]) >= 6:
                tokens.add(words[-1])
            if any(re.search(r"\b%s(?:s|es)?\b" % re.escape(t), text) for t in tokens):
                found.add(wt["name"])
        return found

    def weapon_profile(self, weapon_type):
        """Skill weights for a weapon type, read from the skill descriptions in the data and the scoring block of the definition."""
        cfg = self.scoring
        keywords = {k.lower(): v for k, v in cfg.get("keywords", {}).items()}
        verbs = re.compile(r"\b(?:%s)" % "|".join(re.escape(v) for v in cfg.get("positive_verbs", ["increase", "improve", "boost"])))
        ignore = [i.lower() for i in cfg.get("ignore_if_contains", [])]
        prof = {}
        for name, s in self.skills.items():
            desc = s["description"].lower()
            all_text = desc + " " + " ".join(s["levels"]).lower()
            if any(i in all_text for i in ignore):
                continue
            named = self._weapon_mentions(norm(all_text))
            if named and weapon_type not in named:
                continue
            hits = {}
            for sentence in re.split(r"[.;]", desc):
                if verbs.search(sentence):
                    for k, v in keywords.items():
                        if re.search(r"\b%s" % re.escape(k), sentence):
                            hits[k] = v
            weight = max(hits.values(), default=0.0)
            why = max(hits, key=hits.get) if hits else ""
            if named:
                specific = cfg.get("weapon_specific_weight", 0.0)
                if specific > weight:
                    weight, why = specific, "mentions " + weapon_type
            if weight > 0:
                prof[name] = {"w": weight, "cap": s["max_level"], "why": why}
        return prof


def _read_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def resolve_data_dir(cfg, repo):
    """Where the game's JSON lives: env MH_DATA_DIR_<ID> wins, then 'data_dir' (absolute, or relative to MH_DATA_ROOT / ./data)."""
    override = os.environ.get("MH_DATA_DIR_" + cfg["id"].upper())
    base = Path(os.environ.get("MH_DATA_ROOT") or repo)
    return Path(override) if override else base / cfg.get("data_dir", cfg["id"])


def load_games(games_dir=None, repo=None):
    """Load every definition in games/ (files starting with '_' are skipped). Returns (games, catalog)."""
    games_dir = Path(games_dir or ROOT / "games")
    repo = Path(repo or DATA)
    games, catalog = {}, []
    for def_path in sorted(games_dir.glob("*.json")):
        if def_path.name.startswith("_"):
            continue
        cfg = _read_json(def_path, None)
        if not isinstance(cfg, dict) or "id" not in cfg:
            catalog.append({"id": def_path.stem, "label": def_path.stem, "available": False,
                            "reason": "definition file is not valid JSON or has no 'id'"})
            continue
        entry = {"id": cfg["id"], "label": cfg.get("label", cfg["id"]), "available": False, "reason": "",
                 "examples": cfg.get("examples", [])}
        catalog.append(entry)
        data_dir = resolve_data_dir(cfg, repo)
        if not cfg.get("tables"):
            entry["reason"] = cfg.get("status") or "definition file has no table mappings yet"
        elif not data_dir.is_dir():
            entry["reason"] = "data folder not found: %s" % data_dir
        else:
            try:
                model = load_declared(data_dir, cfg)
            except (SchemaError, KeyError, ValueError) as exc:
                entry["reason"] = "definition does not match the data: %s" % exc
                continue
            games[cfg["id"]] = Game(cfg, model)
            entry["available"] = True
    return games, catalog
