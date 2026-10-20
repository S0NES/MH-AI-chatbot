"""Run from the project root:  python -m unittest discover -s tests   (stdlib only)."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mhbot.answers import answer                      # noqa: E402
from mhbot.declarative import SchemaError, load       # noqa: E402
from mhbot.knowledge import Game, load_games          # noqa: E402
from mhbot.llm import grounded                        # noqa: E402

RISE_AVAILABLE = (Path(__file__).resolve().parents[1] / "data" / "rise" / "Armors.json").exists()


def text_of(resp):
    out = []
    for b in resp["blocks"]:
        for v in b.values():
            if isinstance(v, str):
                out.append(v)
            elif isinstance(v, list):
                out += [str(x) for x in v]
            elif isinstance(v, dict):
                out += [c for r in v["rows"] for c in r]
    return " | ".join(out).lower()


@unittest.skipUnless(RISE_AVAILABLE, "Rise data folder not present")
class RiseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        games, cls.catalog = load_games()
        cls.g = games["rise"]

    def test_example_question_build_for_bow(self):
        r = answer(self.g, "what is the best armor set i can make for bow weapon for rank 3")
        self.assertEqual(r["intent"], "build")
        table = next(b["table"] for b in r["blocks"] if "table" in b and b["table"]["head"][0] == "Part")
        pieces = [row[1] for row in table["rows"]]
        self.assertEqual(len(pieces), 5)
        self.assertTrue(set(pieces) <= {a["name"] for a in self.g.armors})
        self.assertIn("only has 2 rank", text_of(r))

    def test_common_questions_are_understood(self):
        for q in ("best armor set for heavy bowgun low rank", "which armor has critical eye", "best long sword"):
            self.assertNotEqual(answer(self.g, q)["intent"], "unknown", q)

    def test_weapon_criteria_come_from_skill_texts(self):
        bow, gs = self.g.weapon_profile("bow"), self.g.weapon_profile("great sword")
        self.assertIn("Attack Boost", gs)
        self.assertIn("Bow Charge Plus", bow)
        self.assertNotIn("Bow Charge Plus", gs)
        self.assertNotIn("Pierce Up", gs)
        self.assertNotIn("Defense Boost", bow)

    def test_unrelated_question_is_not_answered(self):
        self.assertEqual(answer(self.g, "who won the world cup")["intent"], "unknown")

    def test_catalog_lists_rise_as_available(self):
        self.assertEqual([(c["id"], c["available"]) for c in self.catalog], [("rise", True)])


class OtherFormatTests(unittest.TestCase):
    """A database shaped nothing like Rise's loads with only a definition file - no code changes."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        (d / "gear.json").write_text(json.dumps({"armour": [
            {"title": "Alpha Helm", "slot": "HEAD", "tier": "LR", "stats": {"def": 10}, "gems": [2, 0, 0],
             "perks": [{"id": {"label": "Might"}, "lv": 2}]},
            {"title": "Alpha Mail", "slot": "CHEST", "tier": "LR", "stats": {"def": 20}, "gems": [1, 0, 0],
             "perks": [{"id": {"label": "Might"}, "lv": 1}]}]}))
        (d / "perks.json").write_text(json.dumps([{"label": "Might", "text": "Increases damage.", "steps": ["+5", "+10", "+15"]}]))
        self.d = d
        self.defn = {
            "ranks": [{"id": "low", "label": "Low", "aliases": ["lr"]}],
            "weapon_types": [{"value": "BOW", "name": "bow", "aliases": []}],
            "tables": {
                "skills": {"file": "perks.json", "fields": {
                    "name": "label", "description": "text", "levels": {"path": "steps", "type": "list_str"}}},
                "armors": {"file": "gear.json", "records": "armour", "fields": {
                    "name": "title", "part": {"path": "slot", "type": "enum", "map": {"HEAD": "head", "CHEST": "chest"}},
                    "rank": {"path": "tier", "type": "enum", "map": {"LR": "low"}},
                    "defense": {"path": "stats.def", "type": "int"},
                    "slots": {"path": "gems", "type": "json_int_list", "size": 3},
                    "skills": {"path": "perks", "type": "name_levels", "name": "id.label", "level_path": "lv"}}}}}

    def tearDown(self):
        self.tmp.cleanup()

    def test_loads_and_normalizes(self):
        m = load(self.d, self.defn)
        self.assertEqual(len(m["armors"]), 2)
        self.assertEqual(m["armors"][0]["skills"], {"Might": 2})
        self.assertEqual(m["skills"]["Might"]["max_level"], 3)
        game = Game({"id": "x", "label": "X"}, {**m, "scoring": {"keywords": {"damage": 1}}})
        self.assertEqual(game.parts, ["chest", "head"])
        self.assertEqual(set(game.weapon_profile("bow")), {"Might"})

    def test_wrong_definition_names_the_field(self):
        self.defn["tables"]["armors"]["fields"]["defense"] = "stats.missing"
        with self.assertRaises(SchemaError) as ctx:
            load(self.d, self.defn)
        self.assertIn("armors.defense", str(ctx.exception))


class GroundingTests(unittest.TestCase):
    def test_guard(self):
        facts = "Valstrax Helm | 80 | Attack Boost 7"
        self.assertTrue(grounded("The Valstrax Helm gives 80 defense.", facts))
        self.assertFalse(grounded("Try the Rathalos Helm.", facts))
        self.assertFalse(grounded("It gives 95 defense.", facts))
        self.assertFalse(grounded("See https://example.com", facts))


if __name__ == "__main__":
    unittest.main()
