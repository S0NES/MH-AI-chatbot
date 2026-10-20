"""HTTP server for the web UI and the JSON API (standard library only)."""
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .answers import answer, answer_parsed
from .knowledge import load_games
from .llm import LLM

WEB = Path(__file__).resolve().parents[1] / "web"
MAX_QUESTION = 400
TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8"}


class App:
    def __init__(self):
        self.games, self.catalog = load_games()
        self.llm = LLM()
        self.gate = threading.Semaphore(int(os.environ.get("LLM_CONCURRENCY", 1)))

    def ask(self, game_id, question):
        game = self.games.get(game_id)
        if game is None:
            return 400, {"error": "Pick an available game first."}
        question = (question or "").strip()[:MAX_QUESTION]
        if not question:
            return 400, {"error": "Ask a question."}
        resp, engine = None, "rules"
        if self.llm.enabled and self.gate.acquire(timeout=30):
            try:
                parsed = self.llm.understand(game, question)
                if parsed:
                    resp, engine = answer_parsed(game, parsed), "llm+rules"
                    if resp["intent"] == "unknown":
                        alt = answer(game, question)
                        if alt["intent"] != "unknown":
                            resp, engine = alt, "rules"
                if resp is None:
                    resp = answer(game, question)
                if self.llm.narrate_enabled and resp["intent"] not in ("unknown", "clarify"):
                    resp["ai"] = self.llm.narrate(game, question, resp)
            finally:
                self.gate.release()
        if resp is None:
            resp = answer(game, question)
        resp["engine"] = engine
        return 200, resp


class Handler(BaseHTTPRequestHandler):
    app = None

    def _json(self, code, payload):
        data = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/api/games":
            return self._json(200, {"games": self.app.catalog, "llm": self.app.llm.enabled})
        name = "index.html" if path == "/" else path.lstrip("/")
        target = (WEB / name).resolve()
        if WEB.resolve() not in target.parents or not target.is_file():
            return self._json(404, {"error": "not found"})
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", TYPES.get(target.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        if self.path != "/api/ask":
            return self._json(404, {"error": "not found"})
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(min(length, 8192)) or b"{}")
        except (ValueError, TypeError):
            return self._json(400, {"error": "bad request"})
        code, payload = self.app.ask(body.get("game"), body.get("question"))
        self._json(code, payload)

    def log_message(self, fmt, *args):
        pass


def main():
    Handler.app = App()
    host, port = os.environ.get("HOST", "0.0.0.0"), int(os.environ.get("PORT", 8000))
    print("games:", [c["id"] for c in Handler.app.catalog if c["available"]], "| llm:", Handler.app.llm.base_url or "off")
    print("listening on http://%s:%d" % (host, port))
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    main()
