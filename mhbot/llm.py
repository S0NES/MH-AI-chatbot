"""Optional client for an OpenAI-compatible chat server. Maps free-form questions onto the same structured query as nlu.parse."""
import json
import os
import re
import urllib.request

from . import nlu
from .knowledge import norm

INTENTS = ["build", "best_weapon", "skill_info", "armor_with_skill", "deco_for_skill", "recipe", "entity_info", "unknown"]


class LLM:
    def __init__(self, base_url=None, model=None, api_key=None, timeout=None, narrate=None):
        self.base_url = (base_url or os.environ.get("LLM_BASE_URL", "")).rstrip("/")
        self.model = model or os.environ.get("LLM_MODEL", "local")
        self.api_key = api_key or os.environ.get("LLM_API_KEY", "none")
        self.timeout = float(timeout or os.environ.get("LLM_TIMEOUT", 60))
        self.narrate_enabled = (os.environ.get("LLM_NARRATE", "0") == "1") if narrate is None else narrate

    @property
    def enabled(self):
        return bool(self.base_url)

    def _chat(self, messages, max_tokens, json_mode=False):
        body = {"model": self.model, "messages": messages, "max_tokens": max_tokens, "temperature": 0.1}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        req = urllib.request.Request(
            self.base_url + "/chat/completions", data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + self.api_key})
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.load(resp)["choices"][0]["message"]["content"]

    def understand(self, game, question):
        """Returns a parsed-question dict (same shape as nlu.parse) or None if the LLM couldn't help."""
        system = (
            "You convert a question about %s into JSON. Reply with JSON only, keys: "
            "intent (one of %s), weapon (one of %s or null), rank (one of %s or null; a number N means the Nth rank), "
            "skills (list of skill names mentioned), name (an armor/weapon/decoration/item name mentioned, or null). "
            "intents: build = best armor set for a weapon; best_weapon = strongest weapons of a type; skill_info = what a skill does; "
            "armor_with_skill = which armor has a skill; deco_for_skill = which decoration gives a skill; "
            "recipe = materials to craft something; entity_info = details about a named piece of gear or item; "
            "unknown = anything not about this game's data."
            % (game.label, INTENTS, [w["name"] for w in game.weapon_types], [r["id"] for r in game.ranks]))
        try:
            data = json.loads(self._chat([{"role": "system", "content": system}, {"role": "user", "content": question}],
                                         max_tokens=200, json_mode=True))
        except Exception:
            return None
        if not isinstance(data, dict) or data.get("intent") not in INTENTS:
            return None

        base = nlu.parse(game, question)
        weapon = base["weapon"] or nlu.find_weapon(game, norm(str(data.get("weapon") or "")))
        rank_id, rank_note = base["rank_id"], base["rank_note"]
        raw_rank = str(data.get("rank") or "")
        if not rank_id and raw_rank:
            rank_id, rank_note = nlu.find_rank(game, norm("rank " + raw_rank if raw_rank.isdigit() else raw_rank))
        skills = list(base["skills"])
        if not skills:
            for s in data.get("skills") or []:
                skills += nlu.find_skills(game, norm(str(s)))
        skills = list(dict.fromkeys(skills))
        entity = base["entity"]
        if not entity and data.get("name"):
            entity = nlu.find_entity(game, norm(str(data["name"])))
        intent = base["intent"] if base["intent"] != "unknown" else data["intent"]
        return {"q": base["q"], "intent": intent, "weapon": weapon, "rank_id": rank_id,
                "rank_note": rank_note, "skills": skills, "entity": entity}

    def narrate(self, game, question, response):
        """One or two sentences summarising the already-computed answer. Returns text or ''."""
        facts = []
        for b in response["blocks"]:
            if "h" in b or "p" in b:
                facts.append(b.get("h") or b.get("p"))
            elif "list" in b:
                facts += b["list"][:6]
            elif "table" in b:
                facts += [" | ".join(r) for r in b["table"]["rows"][:6]]
        fact_text = "\n".join(facts)[:3000]
        prompt = ("Question: %s\n\nFacts from the %s database:\n%s\n\n"
                  "Write 1-2 short sentences that answer the question using ONLY these facts. "
                  "Every name and number you write must appear in the facts. If the facts do not answer the question, reply exactly: NONE"
                  % (question, game.label, fact_text))
        try:
            text = self._chat([{"role": "system", "content": "You restate database facts. You never add outside knowledge."},
                               {"role": "user", "content": prompt}], max_tokens=120).strip()
        except Exception:
            return ""
        return text if grounded(text, fact_text) else ""


def grounded(text, facts):
    """True if every number and proper name in text also appears in facts."""
    if not text or text.upper().startswith("NONE") or re.search(r"https?://|www\.|[|`#]", text):
        return False
    haystack = facts.lower()
    known_numbers = re.findall(r"\d+(?:\.\d+)?", haystack)
    if any(n not in known_numbers for n in re.findall(r"\d+(?:\.\d+)?", text)):
        return False
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        for w in re.findall(r"[A-Za-z][A-Za-z'\-]*", sentence)[1:]:
            if w[0].isupper() and w.lower() not in haystack:
                return False
    return True
