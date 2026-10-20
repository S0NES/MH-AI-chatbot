"""Rule-based question parsing against the selected game's data."""
import difflib
import re

from .knowledge import norm

ARMOR_WORDS = {"armor", "armour", "set", "build", "gear", "equipment", "loadout", "armors", "armours", "sets", "builds"}
DECO_WORDS = {"jewel", "jewels", "decoration", "decorations", "deco", "decos", "gem", "gems"}
RECIPE_WORDS = {"craft", "forge", "recipe", "materials", "material", "ingredients", "upgrade"}
BEST_WORDS = {"best", "good", "top", "strongest", "optimal", "recommend", "recommended", "ideal", "highest"}
SKILL_Q_WORDS = {"what", "does", "do", "explain", "effect", "effects", "work", "works", "mean", "info", "about", "describe"}
FIND_WORDS = {"which", "what", "has", "have", "with", "gives", "give", "list", "show", "find", "contains", "providing", "grants"}
PART_WORDS = {"piece", "pieces", "head", "chest", "arms", "waist", "legs", "helmet", "helmets", "helm", "helms", "gloves", "boots", "greaves", "vambraces"}
RANK_ORDINAL = re.compile(r"\brank\s*(\d+)\b|\b(\d+)(?:st|nd|rd|th)?\s*rank\b")


def find_weapon(game, q):
    padded = " %s " % q
    best = None
    for wt in game.weapon_types:
        for alias in [wt["name"]] + wt["aliases"]:
            a = norm(alias)
            if " %s " % a in padded and (best is None or len(a) > best[0]):
                best = (len(a), wt["name"])
    return best[1] if best else None


def find_rank(game, q):
    """Returns (rank_id or None, note or None). 'rank 3' means the 3rd rank of the game."""
    padded = " %s " % q
    m = RANK_ORDINAL.search(q)
    if m:
        n = int(m.group(1) or m.group(2))
        if 1 <= n <= len(game.ranks):
            return game.ranks[n - 1]["id"], None
        top = game.ranks[-1]
        return top["id"], "%s only has %d rank(s) in this dataset (up to %s), so I used %s." % (
            game.label, len(game.ranks), top["label"], top["label"])
    for r in reversed(game.ranks):
        for alias in [r["label"]] + r["aliases"]:
            if " %s " % norm(alias) in padded:
                return r["id"], None
    if re.search(r"\bmaster\b|\bmr\b", q):
        top = game.ranks[-1]
        return top["id"], "No Master Rank data for %s here, so I used %s." % (game.label, top["label"])
    return None, None


def find_skills(game, q):
    words = q.split()
    found, padded = [], " %s " % q
    for n, name in game.skill_by_norm.items():
        if " %s " % n not in padded:
            continue
        if n in game.ambiguous_skills:
            first = n.split()[0]
            i = words.index(first) if first in words else -1
            before = words[i - 1] if i > 0 else ""
            after = words[i + 1] if 0 <= i + 1 < len(words) else ""
            ok = after in ("skill", "jewel") or before in ("with", "has", "have", "gives", "for", "include", "including", "and")
            if not ok or after in ("on", "your", "the"):
                continue
        found.append((len(n), name))
    if not found:
        words_ = q.split()
        for size in (3, 2, 1):
            for i in range(len(words_) - size + 1):
                chunk = " ".join(words_[i:i + size])
                if len(chunk) < 6:
                    continue
                hit = difflib.get_close_matches(chunk, game.skill_by_norm, n=1, cutoff=0.86)
                if hit:
                    found.append((len(hit[0]), game.skill_by_norm[hit[0]]))
    names = []
    for _, name in sorted(found, reverse=True):
        if not any(name != o and norm(name) in norm(o) for o in names):
            names.append(name)
    return names


def find_entity(game, q):
    padded = " %s " % q
    best = None
    for n, (kind, row) in game.named.items():
        if len(n) >= 4 and " %s " % n in padded and (best is None or len(n) > len(best[0])):
            best = (n, kind, row)
    if best:
        return {"kind": best[1], "row": best[2]}
    hit = difflib.get_close_matches(q, game.named, n=1, cutoff=0.82) if len(q) >= 5 else []
    if hit:
        kind, row = game.named[hit[0]]
        return {"kind": kind, "row": row}
    return None


def parse(game, question):
    q = norm(question)
    words = set(q.split())
    weapon = find_weapon(game, q)
    rank_id, rank_note = find_rank(game, q)
    skills = find_skills(game, q)
    entity = find_entity(game, q)
    out = {"q": q, "weapon": weapon, "rank_id": rank_id, "rank_note": rank_note, "skills": skills, "entity": entity}

    if skills and words & DECO_WORDS:
        intent = "deco_for_skill"
    elif entity and words & RECIPE_WORDS:
        intent = "recipe"
    elif words & ARMOR_WORDS and (weapon or words & BEST_WORDS or "build" in words) and not (skills and words & FIND_WORDS and not weapon):
        intent = "build"
    elif skills and words & (ARMOR_WORDS | PART_WORDS):
        intent = "armor_with_skill"
    elif weapon and (words & BEST_WORDS or "weapon" in words or "weapons" in words):
        intent = "best_weapon"
    elif skills and (words & SKILL_Q_WORDS or len(words) <= 3 or "skill" in words):
        intent = "skill_info"
    elif entity:
        intent = "entity_info"
    elif weapon:
        intent = "best_weapon"
    elif skills:
        intent = "skill_info"
    else:
        intent = "unknown"
    out["intent"] = intent
    return out
