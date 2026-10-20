"""Builds answers as display blocks: p, h, list, table and note."""
import difflib
from urllib.parse import urlparse

from . import nlu
from .knowledge import norm
from .optimizer import optimize


def _mats(mats):
    return ", ".join("%s x%d" % (n, a) for n, a, _ in mats) or "none listed"


def _link_cell(url):
    return {"t": urlparse(url).netloc or "link", "href": url} if url else ""


def _materials_table(sources):
    """Combined material list for crafting several things. sources: [(name of the thing, materials, copies)]."""
    totals = {}
    for source, materials, copies in sources:
        for name, amount, link in materials:
            entry = totals.setdefault(name, {"amount": 0, "link": link, "for": []})
            entry["amount"] += amount * copies
            label = source if copies == 1 else "%s x%d" % (source, copies)
            if label not in entry["for"]:
                entry["for"].append(label)
    rows = [[name, "x%d" % e["amount"], ", ".join(e["for"]), _link_cell(e["link"])] for name, e in sorted(totals.items())]
    return {"table": {"head": ["Material", "Amount", "Needed for", "Link"], "rows": rows}} if rows else None


def _rank_label(game, rank_id):
    return game.rank_text(rank_id)


def _slots_text(slots):
    return " ".join("[%d]x%d" % (i + 1, c) for i, c in enumerate(slots) if c) or "no slots"


def _part_key(game):
    order = game.part_order
    return lambda p: order.index(p["part"]) if p["part"] in order else len(order)


def ask_weapon(game):
    return {"intent": "clarify", "blocks": [{"p": "Which weapon type is the build for?"}],
            "suggestions": ["Best armor set for %s" % w["name"] for w in game.weapon_types]}


def answer_build(game, parsed):
    if not parsed["weapon"]:
        return ask_weapon(game)
    blocks = []
    if parsed["rank_note"]:
        blocks.append({"note": parsed["rank_note"]})
    rank_id = parsed["rank_id"] or next((r["id"] for r in reversed(game.ranks) if game.rank_has_data(r["id"])), game.ranks[-1]["id"])
    if not parsed["rank_id"]:
        blocks.append({"note": "No rank given, so I used %s." % _rank_label(game, rank_id)})
    builds = optimize(game, parsed["weapon"], rank_id, parsed["skills"])
    if not builds:
        return {"intent": "build", "blocks": [{"p": "No armor found for %s." % _rank_label(game, rank_id)}], "suggestions": []}

    best = builds[0]
    blocks.insert(0, {"h": "Best %s armor set for %s (%s)" % (_rank_label(game, rank_id), parsed["weapon"], game.label)})
    blocks.append({"table": {"head": ["Part", "Piece", "Defense", "Slots"],
                             "rows": [[p["part"].title(), p["name"], str(p["defense"]), _slots_text(p["slots"])]
                                      for p in sorted(best["pieces"], key=_part_key(game))]}})
    if best["decorations"]:
        counts = {}
        for _, name in best["decorations"]:
            counts[name] = counts.get(name, 0) + 1
        blocks.append({"p": "Decorations: " + ", ".join("%s x%d" % (n, c) for n, c in sorted(counts.items()))})
    sources = [(p["name"], p["materials"], 1) for p in sorted(best["pieces"], key=_part_key(game))]
    by_name = {d["name"]: d for d in game.decorations}
    sources += [(n, by_name[n]["materials"], c) for n, c in sorted(counts.items())] if best["decorations"] else []
    materials = _materials_table(sources)
    if materials:
        blocks += [{"h": "Materials to craft this set"}, materials]
    prof = best["profile"]
    skill_rows = sorted(best["levels"].items(), key=lambda kv: (kv[0] not in prof, -kv[1], kv[0]))
    blocks.append({"table": {"head": ["Skill", "Level", "Max", "What it does", "Counted"],
                             "rows": [[n, str(lv), str(game.skills[n]["max_level"]), game.skills[n]["description"],
                                       "yes" if n in prof else "no"]
                                      for n, lv in skill_rows]}})
    blocks.append({"p": "Total defense %d | resistances %s" % (
        best["defense"], ", ".join("%s %+d" % kv for kv in best["res"].items()))})
    if best["unused_slots"]:
        blocks.append({"p": "Unfilled slots: " + ", ".join("[%d]" % s for s in sorted(best["unused_slots"], reverse=True))})
    if len(builds) > 1:
        blocks.append({"h": "Alternatives"})
        blocks.append({"list": ["%s (score %.1f)" % (", ".join(p["name"] for p in sorted(b["pieces"], key=_part_key(game))), b["score"])
                                for b in builds[1:]]})
    if prof:
        top = sorted(prof.items(), key=lambda kv: -kv[1]["w"] * kv[1]["cap"])[:8]
        blocks.append({"note": "How this was ranked: skills whose database description increases attack/affinity/damage"
                               " (or that name %s) - e.g. %s. Defense breaks ties." % (
                                   parsed["weapon"], ", ".join("%s (%s)" % (n, v["why"]) for n, v in top))})
    else:
        blocks.append({"note": "This game's definition has no 'scoring' rules, so sets are ranked by defense only."})
    blocks += [{"note": n} for n in game.notes]
    return {"intent": "build", "blocks": blocks, "suggestions": ["Best %s weapons" % parsed["weapon"]]}


def answer_best_weapon(game, parsed):
    blocks = []
    if parsed["rank_note"]:
        blocks.append({"note": parsed["rank_note"]})
    rank_id = parsed["rank_id"]
    rows = [w for w in game.weapons if w["type"] == parsed["weapon"] and (not rank_id or w["rank"] in ("", rank_id))]
    if not rows:
        return {"intent": "best_weapon", "blocks": [{"p": "No %s found." % parsed["weapon"]}], "suggestions": []}
    rows.sort(key=lambda w: (w["attack"], w["affinity"]), reverse=True)
    blocks.insert(0, {"h": "Top %s weapons%s" % (parsed["weapon"], " (%s)" % _rank_label(game, rank_id) if rank_id else "")})
    blocks.append({"table": {"head": ["Weapon", "Attack", "Affinity", game.extras_label],
                             "rows": [[w["name"], str(w["attack"]), "%+d%%" % w["affinity"], ", ".join(w["extras"])] for w in rows[:6]]}})
    blocks.append({"note": "Ranked by raw attack, then affinity. Weapons are bucketed into ranks by rarity (an approximation)."})
    return {"intent": "best_weapon", "blocks": blocks, "suggestions": ["Best armor set for %s" % parsed["weapon"]]}


def answer_skill_info(game, parsed):
    blocks = []
    for name in parsed["skills"][:3]:
        s = game.skills[name]
        blocks += [{"h": name}, {"p": s["description"]}, {"list": ["Lv%d: %s" % (i + 1, t) for i, t in enumerate(s["levels"])]}]
    first = parsed["skills"][0]
    return {"intent": "skill_info", "blocks": blocks,
            "suggestions": ["Which armor has %s" % first, "Which decoration gives %s" % first]}


def answer_armor_with_skill(game, parsed):
    blocks = []
    if parsed["rank_note"]:
        blocks.append({"note": parsed["rank_note"]})
    rank_id, skill = parsed["rank_id"], parsed["skills"][0]
    rows = [a for a in game.armors if skill in a["skills"] and (not rank_id or a["rank"] == rank_id)]
    rows.sort(key=lambda a: (-len(set(a["skills"]) & set(parsed["skills"])), -sum(a["slots"]), -a["defense"]))
    if not rows:
        return {"intent": "armor_with_skill", "blocks": [{"p": "No armor piece grants %s." % skill}], "suggestions": []}
    blocks.insert(0, {"h": "Armor with %s%s" % (skill, " (%s)" % _rank_label(game, rank_id) if rank_id else "")})
    blocks.append({"table": {"head": ["Piece", "Part", "Rank", "Defense", "Slots", "Skills"],
                             "rows": [[a["name"], a["part"], _rank_label(game, a["rank"]), str(a["defense"]),
                                       _slots_text(a["slots"]), ", ".join(a["skills"])] for a in rows[:15]]}})
    if len(rows) > 15:
        blocks.append({"note": "Showing 15 of %d pieces." % len(rows)})
    return {"intent": "armor_with_skill", "blocks": blocks, "suggestions": ["What does %s do" % skill]}


def answer_deco_for_skill(game, parsed):
    skill = parsed["skills"][0]
    rows = [d for d in game.decorations if skill in d["skills"]]
    if not rows:
        return {"intent": "deco_for_skill", "blocks": [{"p": "No decoration for %s." % skill}], "suggestions": []}
    return {"intent": "deco_for_skill", "suggestions": [],
            "blocks": [{"h": "Decorations for %s" % skill},
                       {"table": {"head": ["Decoration", "Slot size", "Materials"],
                                  "rows": [[d["name"], str(d["size"]), _mats(d["materials"])] for d in rows]}}]}


def answer_entity(game, parsed, recipe=False):
    kind, row = parsed["entity"]["kind"], parsed["entity"]["row"]
    blocks = [{"h": "%s (%s)" % (row["name"], kind)}]
    if kind == "armor":
        blocks.append({"list": ["%s, %s" % (row["part"].title(), _rank_label(game, row["rank"])),
                                "Defense %d | slots: %s" % (row["defense"], _slots_text(row["slots"])),
                                "Skills: %s" % (", ".join(row["skills"]) or "none"),
                                "Resistances: " + ", ".join("%s %+d" % kv for kv in row["res"].items())]})
    elif kind == "weapon":
        blocks.append({"list": ["%s, %s" % (row["type"].title(), _rank_label(game, row["rank"])),
                                "Attack %d | affinity %+d%%" % (row["attack"], row["affinity"]),
                                "%s: %s" % (game.extras_label, ", ".join(row["extras"]) or "none")]})
    elif kind == "decoration":
        blocks.append({"list": ["Slot size %d" % row["size"], "Skills: %s" % ", ".join(row["skills"])]})
    else:
        blocks += [{"p": row["description"]}, {"p": "Buy %d z | sell %d z" % (row["buy"], row["sell"])}]
    if kind != "item":
        table = _materials_table([(row["name"], row["materials"], 1)])
        blocks += [{"h": "Materials"}, table] if table else [{"p": "No materials are listed for this in the dataset."}]
    return {"intent": "recipe" if recipe else "entity_info", "blocks": blocks, "suggestions": []}


def answer_material_source(game, parsed):
    names = list(parsed.get("materials") or [])[:5]
    if not names and parsed["entity"]:
        names = [parsed["entity"]["row"]["name"]]
    rows, notes, uses_blocks = [], [], []
    for name in names:
        item = game.named.get(norm(name))
        description = item[1]["description"] if item and item[0] == "item" else ""
        link = game.material_links.get(norm(name), ("", ""))[1]
        rows.append([name, description, _link_cell(link) or "no link in the dataset"])
        if not link:
            notes.append("The dataset has no page link for %s." % name)
        uses = game.material_uses.get(name, [])
        if uses:
            shown = ", ".join(gear for _, gear in uses[:8])
            more = " and %d more" % (len(uses) - 8) if len(uses) > 8 else ""
            uses_blocks.append({"p": "%s is used to craft %d item%s: %s%s." % (name, len(uses), "" if len(uses) == 1 else "s", shown, more)})
    blocks = [{"h": "Where to get " + ", ".join(names)},
              {"table": {"head": ["Material", "What it is", "Link"], "rows": rows}}] + uses_blocks
    if len(notes) < len(names):
        blocks.append({"note": "The dataset does not record where materials drop. Open the link for where it comes from."})
    blocks += [{"note": n} for n in notes]
    return {"intent": "material_source", "blocks": blocks, "suggestions": []}


def answer_unknown(game, q):
    near = difflib.get_close_matches(q, list(game.named) + list(game.skill_by_norm), n=4, cutoff=0.75)
    blocks = [{"p": "I couldn't tell what you're asking. I can answer questions about %s's armor, weapons, skills, decorations and items." % game.label}]
    if near:
        blocks.append({"p": "Did you mean: " + ", ".join(game.skill_by_norm.get(n) or game.named[n][1]["name"] for n in near)})
    return {"intent": "unknown", "blocks": blocks, "suggestions": [
        "Best armor set for bow", "What does Critical Eye do", "Which armor has Attack Boost", "Best great sword"]}


def answer_parsed(game, parsed):
    """Dispatch an already-parsed question (from nlu.parse or from the LLM) to its answer builder."""
    intent = parsed["intent"]
    if intent == "build":
        resp = answer_build(game, parsed)
    elif intent == "best_weapon" and parsed["weapon"]:
        resp = answer_best_weapon(game, parsed)
    elif intent == "skill_info" and parsed["skills"]:
        resp = answer_skill_info(game, parsed)
    elif intent == "armor_with_skill" and parsed["skills"]:
        resp = answer_armor_with_skill(game, parsed)
    elif intent == "deco_for_skill" and parsed["skills"]:
        resp = answer_deco_for_skill(game, parsed)
    elif intent == "material_source" and (parsed.get("materials") or parsed["entity"]):
        resp = answer_material_source(game, parsed)
    elif intent in ("recipe", "entity_info") and parsed["entity"]:
        resp = answer_entity(game, parsed, recipe=intent == "recipe")
    else:
        resp = answer_unknown(game, parsed["q"])
    resp["parsed"] = {k: parsed[k] for k in ("intent", "weapon", "rank_id", "skills")}
    resp["context"] = None if resp["intent"] == "unknown" else {
        "intent": parsed["intent"], "weapon": parsed["weapon"], "rank_id": parsed["rank_id"],
        "skills": parsed["skills"], "entity": parsed["entity"]["row"]["name"] if parsed["entity"] else None}
    return resp


def answer(game, question, context=None):
    return answer_parsed(game, nlu.parse(game, question, context))
