"""Loads a game's JSON files using the mapping in its definition file (games/<id>.json)."""
import json
import re

MISSING = object()

# normalized field -> (required?, default when the definition omits an optional field)
FIELDS = {
    "skills": {"name": (True, None), "description": (False, ""), "levels": (False, [])},
    "armors": {"name": (True, None), "part": (True, None), "rank": (True, None), "defense": (True, None),
               "slots": (True, None), "skills": (True, None), "rarity": (False, 0), "res": (False, {}),
               "materials": (False, []), "set": (False, "")},
    "decorations": {"name": (True, None), "size": (True, None), "skills": (True, None), "materials": (False, [])},
    "weapons": {"name": (True, None), "type": (True, None), "attack": (True, None), "rank": (False, ""),
                "rarity": (False, 0), "affinity": (False, 0), "defense_bonus": (False, 0),
                "extras": (False, []), "materials": (False, [])},
    "items": {"name": (True, None), "description": (False, ""), "buy": (False, 0), "sell": (False, 0)},
}


class SchemaError(Exception):
    """The database does not match its definition file. Message says which table/field/record."""


def get_path(obj, path):
    if path in ("$", "", None):
        return obj
    for part in str(path).split("."):
        if isinstance(obj, dict) and part in obj:
            obj = obj[part]
        else:
            return MISSING
    return obj


def _to_int(raw):
    try:
        return int(float(str(raw).strip()))
    except ValueError:
        m = re.search(r"-?\d+", str(raw))
        if m:
            return int(m.group())
        raise


def _natural(key):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", key)]


def convert(spec, rec, game_def):
    """Apply one field spec to one record. Raises KeyError('path') when a required path is absent."""
    if isinstance(spec, str):
        spec = {"path": spec}
    kind = spec.get("type", "str")

    if kind == "keys_regex_list":
        rx = re.compile(spec["pattern"])
        return [str(rec[k]) for k in sorted((k for k in rec if rx.fullmatch(k)), key=_natural) if rec[k]]

    raw = get_path(rec, spec.get("path", "$"))
    if raw is MISSING:
        if "default" in spec:
            return spec["default"]
        raise KeyError(spec.get("path"))

    if kind == "str":
        return str(raw)
    if kind == "int":
        return _to_int(raw)
    if kind == "float":
        return float(raw)
    if kind == "enum":
        key = str(raw)
        if key in spec["map"]:
            return spec["map"][key]
        if "default" in spec:
            return spec["default"]
        raise ValueError("value %r not in map %s" % (raw, sorted(spec["map"])))
    if kind == "range_map":
        n = _to_int(raw)
        for rid, (lo, hi) in spec["ranges"].items():
            if lo <= n <= hi:
                return rid
        if "default" in spec:
            return spec["default"]
        raise ValueError("%d is outside every range" % n)
    if kind == "weapon_type":
        for wt in game_def["weapon_types"]:
            if str(wt["value"]) == str(raw):
                return wt["name"]
        return spec.get("default", "unknown")
    if kind == "json_int_list":
        size = spec.get("size", 3)
        vals = json.loads(raw) if isinstance(raw, str) else raw
        vals = [int(v) for v in vals][:size]
        return vals + [0] * (size - len(vals))
    if kind == "tail_int":
        m = re.search(r"(\d+)\s*$", str(raw))
        if m:
            return int(m.group(1))
        if "default" in spec:
            return spec["default"]
        raise ValueError("no trailing number in %r" % raw)
    if kind == "list_str":
        return [str(get_path(e, spec.get("each", "$"))) for e in raw]
    if kind == "name_levels":
        out = {}
        for e in raw:
            name = get_path(e, spec["name"])
            if name is MISSING:
                raise KeyError(spec["name"])
            lvl = spec.get("level", 1)
            if "level_path" in spec:
                found = get_path(e, spec["level_path"])
                lvl = _to_int(found) if found is not MISSING else lvl
            out[str(name)] = out.get(str(name), 0) + lvl
        return out
    if kind == "materials":
        out = []
        for e in raw:
            item = get_path(e, spec["item"])
            if item is MISSING:
                raise KeyError(spec["item"])
            amount = get_path(e, spec["amount"]) if "amount" in spec else 1
            link = get_path(e, spec["link"]) if "link" in spec else MISSING
            out.append((str(item), _to_int(amount) if amount is not MISSING else 1, "" if link is MISSING else str(link)))
        return out
    raise ValueError("unknown field type %r" % kind)


def _set_nested(out, dotted, value):
    parts = dotted.split(".")
    for p in parts[:-1]:
        out = out.setdefault(p, {})
    out[parts[-1]] = value


def load_table(data_dir, table_name, tdef, game_def):
    path = data_dir / tdef["file"]
    try:
        with open(path, encoding=tdef.get("encoding", "utf-8")) as fh:
            doc = json.load(fh)
    except OSError:
        raise SchemaError("%s: file '%s' not found in %s" % (table_name, tdef["file"], data_dir))
    except ValueError as exc:
        raise SchemaError("%s: '%s' is not valid JSON (%s)" % (table_name, tdef["file"], exc))
    records = get_path(doc, tdef.get("records", "$"))
    if records is MISSING or not isinstance(records, list):
        raise SchemaError("%s: 'records' path %r is not a list in '%s'" % (table_name, tdef.get("records", "$"), tdef["file"]))

    fields = tdef.get("fields", {})
    known = FIELDS[table_name]
    for f, (required, _) in known.items():
        if required and f not in fields:
            raise SchemaError("%s: definition has no mapping for required field '%s'" % (table_name, f))
    bad = [f for f in fields if f.split(".")[0] not in known]
    if bad:
        raise SchemaError("%s: unknown field(s) %s (allowed: %s)" % (table_name, bad, sorted(known)))

    rows = []
    for i, rec in enumerate(records):
        row = {}
        for f, spec in fields.items():
            try:
                _set_nested(row, f, convert(spec, rec, game_def))
            except KeyError as exc:
                raise SchemaError("%s.%s: path %s missing in record #%d of '%s'" % (table_name, f, exc, i, tdef["file"]))
            except (ValueError, TypeError) as exc:
                raise SchemaError("%s.%s: bad value in record #%d of '%s': %s" % (table_name, f, i, tdef["file"], exc))
        for f, (_, default) in known.items():
            if f not in row:
                row[f] = json.loads(json.dumps(default))
        rows.append(row)

    key = tdef.get("dedupe_by")
    if key:
        pick = tdef.get("prefer_longest")
        seen = {}
        for r in rows:
            cur = seen.get(r[key])
            if cur is None or (pick and len(r[pick]) > len(cur[pick])):
                seen[r[key]] = r
        rows = list(seen.values())
    return rows


def load(data_dir, game_def):
    tables = game_def.get("tables", {})
    unknown = [t for t in tables if t not in FIELDS]
    if unknown:
        raise SchemaError("unknown table(s) %s (allowed: %s)" % (unknown, sorted(FIELDS)))
    model = {k: load_table(data_dir, k, tables[k], game_def) if k in tables else [] for k in FIELDS}

    skills = {}
    for s in model.pop("skills"):
        skills[s["name"]] = {"description": s["description"], "levels": s["levels"], "max_level": max(len(s["levels"]), 1)}
    for rows in (model["armors"], model["decorations"]):
        for r in rows:
            for name, lvl in r["skills"].items():
                skills.setdefault(name, {"description": "", "levels": [], "max_level": 1})
                skills[name]["max_level"] = max(skills[name]["max_level"], lvl)
    model["skills"] = skills

    rank_ids = {r["id"] for r in game_def["ranks"]}
    for a in model["armors"]:
        if a["rank"] not in rank_ids:
            raise SchemaError("armors.rank: value %r (piece %s) is not one of the ranks defined in the definition file %s"
                              % (a["rank"], a["name"], sorted(rank_ids)))

    model.update({
        "ranks": game_def["ranks"],
        "weapon_types": [{"id": w["name"], "name": w["name"], "aliases": w.get("aliases", []),
                          "text_hints": w.get("text_hints", []),
                          "lacks": w.get("lacks", [])} for w in game_def["weapon_types"]],
        "part_order": game_def.get("part_order", []),
        "extras_label": game_def.get("extras_label", "Extras"),
        "notes": list(game_def.get("notes", [])),
        "scoring": game_def.get("scoring", {}),
        "ambiguous_skills": set(game_def.get("ambiguous_skill_names", [])),
    })
    return model
