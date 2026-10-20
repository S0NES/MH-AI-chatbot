"""Armor set optimizer: beam search over the armor parts, then greedy decoration filling."""
BEAM_WIDTH = 300
PER_PART = 40
DEFENSE_WEIGHT = 0.01


def _score(levels, prof):
    return sum(v["w"] * min(levels.get(n, 0), v["cap"]) for n, v in prof.items())


def _add(a, b):
    out = dict(a)
    for k, v in b.items():
        out[k] = out.get(k, 0) + v
    return out


def _gain(levels, deco_skills, prof):
    g = 0.0
    for n, lv in deco_skills.items():
        v = prof.get(n)
        if v:
            cur = levels.get(n, 0)
            g += v["w"] * (min(cur + lv, v["cap"]) - min(cur, v["cap"]))
    return g


def fill_decorations(levels, slots, decos, prof):
    """Fill slots largest first with the decoration of highest marginal gain."""
    levels = dict(levels)
    placed, unused = [], []
    for size in sorted(slots, reverse=True):
        best, best_key = None, (0.0, 0)
        for d in decos:
            if d["size"] <= size:
                key = (_gain(levels, d["skills"], prof), d["size"])
                if key > best_key:
                    best, best_key = d, key
        if best is None:
            unused.append(size)
        else:
            levels = _add(levels, best["skills"])
            placed.append((size, best["name"]))
    return levels, placed, unused


def _slot_list(slots):
    return [1] * slots[0] + [2] * slots[1] + [3] * slots[2]


def _prune(pieces, prof, slot_value):
    """Drop dominated pieces, keep the strongest PER_PART by stand-alone value."""
    def vec(p):
        return {n: p["skills"].get(n, 0) for n in prof}

    def value(p):
        s = _score(vec(p), prof)
        s += sum(slot_value[i + 1] * c for i, c in enumerate(p["slots"]))
        return s + DEFENSE_WEIGHT * p["defense"]

    keep = []
    for p in sorted(pieces, key=value, reverse=True):
        pv = vec(p)
        dominated = any(
            all(qv >= pv[n] for n, qv in vec(q).items())
            and all(qs >= ps for qs, ps in zip(q["slots"], p["slots"]))
            and q["defense"] >= p["defense"]
            for q in keep
        )
        if not dominated:
            keep.append(p)
        if len(keep) >= PER_PART:
            break
    return keep


def optimize(game, weapon_type, rank_id, extra_skills=None, top_n=3):
    """Best armor sets (one piece per part) for a weapon type at a rank. Returns a list of build dicts."""
    prof = dict(game.weapon_profile(weapon_type))
    for name in extra_skills or []:
        prof[name] = {"w": 6.0, "cap": game.skills[name]["max_level"]}

    decos = [d for d in game.decorations if any(n in prof for n in d["skills"])]
    slot_value = {}
    for size in (1, 2, 3):
        slot_value[size] = 0.7 * max([_gain({}, d["skills"], prof) for d in decos if d["size"] <= size] or [0.0])

    by_part = {}
    for a in game.armors:
        if a["rank"] == rank_id:
            by_part.setdefault(a["part"], []).append(a)
    if not by_part:
        return []
    parts = [_prune(by_part[p], prof, slot_value) for p in sorted(by_part)]

    def proxy(levels, slots, defense):
        return _score(levels, prof) + sum(slot_value[s] for s in _slot_list(slots)) + DEFENSE_WEIGHT * defense

    beam = [(0.0, {}, [0, 0, 0], 0, ())]
    for candidates in parts:
        nxt = []
        for _, levels, slots, defense, chosen in beam:
            for p in candidates:
                lv = _add(levels, p["skills"])
                sl = [x + y for x, y in zip(slots, p["slots"])]
                df = defense + p["defense"]
                nxt.append((proxy(lv, sl, df), lv, sl, df, chosen + (p,)))
        nxt.sort(key=lambda s: s[0], reverse=True)
        beam = nxt[:BEAM_WIDTH]

    builds = []
    for _, levels, slots, defense, chosen in beam:
        final_levels, placed, unused = fill_decorations(levels, _slot_list(slots), decos, prof)
        builds.append({
            "score": _score(final_levels, prof) + DEFENSE_WEIGHT * defense,
            "pieces": list(chosen), "levels": final_levels, "decorations": placed,
            "unused_slots": unused, "defense": defense,
            "res": {e: sum(p["res"][e] for p in chosen) for e in chosen[0]["res"]},
            "profile": prof,
        })
    builds.sort(key=lambda b: b["score"], reverse=True)

    out, seen = [], set()
    for b in builds:
        key = tuple(p["name"] for p in b["pieces"])
        if key not in seen:
            seen.add(key)
            out.append(b)
        if len(out) >= top_n:
            break
    return out
