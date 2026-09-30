"""Local HTTP server for the reviewer panel (standard library only).

    python -m reviewer_panel [--port 8765] [--config minaret.yaml]

Serves the single-page UI from static/ and a small JSON API under /api/. Bound to 127.0.0.1: the
panel is a local tool with no authentication.
"""
from __future__ import annotations

import argparse
import json
import os
import mimetypes
import socketserver
import threading
import traceback
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from minaret import config as config_mod
from reviewer_panel.replay import ActionRunner, plan
from reviewer_panel.services import Services, Unavailable
from reviewer_panel.session import FLAG_ISSUES, ReviewError, SessionKey, SessionStore
from reviewer_panel.settings import Settings

STATIC = Path(__file__).resolve().parent / "static"


class Panel:
    """Application state shared by all request threads."""

    def __init__(self, cfg: config_mod.Config):
        self.services = Services(cfg)
        self.settings = Settings(cfg)
        self.store = SessionStore(self.services.runs_dir, self.services.roots)
        self.sessions: dict[tuple, object] = {}  # one live Session per recording, shared by replay
        self.replays: dict[tuple, dict] = {}  # key -> {"actions", "runner", "next"}
        self.lock = threading.RLock()

    def reload_config(self) -> None:
        """Re-read minaret.yaml + minaret.local.yaml + .env after Settings changed them."""
        cfg = config_mod.load(self.settings.config_file)
        self.services.cfg = cfg
        self.services._quran = self.services._duas = None
        self.settings.cfg = cfg

    # -------------------------------------------------------------- helpers
    @staticmethod
    def key(body: dict) -> SessionKey:
        return SessionKey(body["source"], body["series"], body["recording"])

    def session_payload(self, session) -> dict:
        key = SessionKey(**session.state["key"])
        replay = self.replays.get(key.as_tuple())
        return {"state": session.state, "blockers": session.blockers(),
                "replay": None if not replay else {"next": replay["next"], "total": len(replay["actions"]),
                                                    "upcoming": [a["describe"] for a in
                                                                 replay["actions"][replay["next"]:replay["next"] + 5]]},
                "audio": self.services.audio_source(key.source, key.series, key.recording),
                "language": self.services.lecture_language(key.source, key.series, key.recording)}

    # -------------------------------------------------------------- API
    def api(self, method: str, path: str, query: dict, body: dict):
        s = self.services
        if method == "GET" and path == "/api/status":
            return {**s.status(), "flag_issues": FLAG_ISSUES}
        if method == "GET" and path == "/api/recordings":
            return s.recordings()

        if path == "/api/session/open":
            with self.lock:
                key = self.key(body)
                if body.get("reset") or key.as_tuple() not in self.sessions:
                    self.replays.pop(key.as_tuple(), None)
                    self.sessions[key.as_tuple()] = self.store.open(key, reset=bool(body.get("reset")))
                return self.session_payload(self.sessions[key.as_tuple()])
        if path == "/api/session/action":
            with self.lock:
                session = self._session(body)
                result = session.apply(body["action"], role=body.get("role", "first_level"))
                return {**self.session_payload(session), "result": result}
        if path == "/api/session/finalize":
            with self.lock:
                session = self._session(body)
                return {**session.finalize(s.runs_dir / "recordings"), **self.session_payload(session)}
        if path == "/api/session/reopen":
            with self.lock:
                session = self._session(body)
                session.reopen()
                return self.session_payload(session)

        if path == "/api/replay/start":
            with self.lock:
                key = self.key(body)
                d = s.recording_dir(key.source, key.series, key.recording)
                if not ((d / "v3.json").exists() and (d / "e2.json").exists()):
                    raise ReviewError("Replay needs this recording's reviewed v3.json and e2.json")
                session = self.store.open(key, reset=True)
                self.sessions[key.as_tuple()] = session
                v3 = json.loads((d / "v3.json").read_text(encoding="utf-8"))
                e2 = json.loads((d / "e2.json").read_text(encoding="utf-8"))
                self.replays[key.as_tuple()] = {"actions": plan(session.state, v3, e2),
                                                "runner": ActionRunner(session), "next": 0}
                return self.session_payload(session)
        if path == "/api/replay/step":
            with self.lock:
                key = self.key(body)
                replay = self.replays.get(key.as_tuple())
                if not replay:
                    raise ReviewError("No replay in progress for this recording")
                steps = max(1, int(body.get("steps", 1)))
                applied = []
                for _ in range(steps):
                    if replay["next"] >= len(replay["actions"]):
                        break
                    action = replay["actions"][replay["next"]]
                    replay["runner"].run(action, save=False)
                    applied.append({k: action.get(k) for k in ("op", "describe", "uid", "anchor")})
                    replay["next"] += 1
                replay["runner"].session.save()
                return {**self.session_payload(replay["runner"].session), "applied": applied}
        if path == "/api/replay/stop":
            with self.lock:
                self.replays.pop(self.key(body).as_tuple(), None)
                return self.session_payload(self._session(body))

        if path == "/api/lookup":
            return s.lookup(body["type"], body.get("fields", {}))
        if path == "/api/ai/suggest":
            return s.suggest(body["text"])

        if method == "GET" and path == "/api/jobs":
            return sorted(s.jobs.values(), key=lambda j: j["started"], reverse=True)
        if path == "/api/jobs":
            return s.start_job(body["kind"], body.get("params", {}))

        if method == "GET" and path == "/api/landing":
            from reviewer_panel import landing
            return landing.build("panel")
        if method == "GET" and path == "/api/settings":
            return self.settings.view()
        if path == "/api/settings":
            with self.lock:
                self.settings.save(body.get("values", {}), body.get("keys"))
                self.reload_config()
            return {**self.settings.view(), "status": s.status()}
        if path == "/api/settings/restore":
            with self.lock:
                self.settings.restore_defaults()
                self.reload_config()
            return {**self.settings.view(), "status": s.status()}
        if path == "/api/settings/test":
            stage = body["stage"]
            key = body.get("key") or os.environ.get(self.settings.cfg.get(f"llm.{stage}.api_key_env") or "", "")
            return s.probe_endpoint(body["base_url"], body["model"], key,
                                    key_env=self.settings.cfg.get(f"llm.{stage}.api_key_env"))
        if method == "GET" and path == "/api/pipeline/targets":
            return s.build_targets()
        if method == "GET" and path == "/api/rag/targets":
            return s.rag_targets()
        if path == "/api/rag/query":
            return s.rag_query(index=body["index"], scope=body["scope"], target=body["target"],
                               question=body["question"])
        if method == "GET" and path == "/api/kg/info":
            return {"graphs": sorted(s.kg_graphs()), "cqs": s.competency_questions()}
        if path == "/api/kg/query":
            return s.kg_query(graph=body["graph"], query=body["query"])
        raise LookupError(f"No route {method} {path}")

    def _session(self, body):
        key = self.key(body).as_tuple()
        if key not in self.sessions:
            stored = self.store.get(self.key(body))
            if stored is None:
                raise ReviewError("Open the recording first")
            self.sessions[key] = stored
        return self.sessions[key]


def make_handler(panel: Panel):
    class Handler(BaseHTTPRequestHandler):
        server_version = "MinaretReviewerPanel/1"

        def log_message(self, fmt, *args):  # keep the terminal quiet except for errors
            pass

        def _send(self, status, payload=None, *, content_type="application/json", raw: bytes | None = None,
                  headers: dict | None = None):
            data = raw if raw is not None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)

        def _dispatch(self, method):
            url = urlsplit(self.path)
            if url.path == "/api/audio":
                return self._audio(parse_qs(url.query))
            if not url.path.startswith("/api/"):
                return self._static(url.path)
            body = {}
            if method == "POST":
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
            query = {k: v[0] for k, v in parse_qs(url.query).items()}
            try:
                self._send(HTTPStatus.OK, panel.api(method, url.path, query, body))
            except Unavailable as exc:
                self._send(HTTPStatus.SERVICE_UNAVAILABLE, {"error": str(exc), "kind": "unavailable"})
            except (ReviewError, ValueError, KeyError) as exc:
                self._send(HTTPStatus.BAD_REQUEST, {"error": str(exc) if not isinstance(exc, KeyError)
                                                    else f"Missing field {exc}", "kind": "invalid"})
            except LookupError as exc:
                self._send(HTTPStatus.NOT_FOUND, {"error": str(exc)})
            except Exception as exc:  # noqa: BLE001
                self._send(HTTPStatus.INTERNAL_SERVER_ERROR,
                           {"error": f"{type(exc).__name__}: {exc}", "trace": traceback.format_exc(limit=4)})

        def do_GET(self):
            self._dispatch("GET")

        def do_POST(self):
            self._dispatch("POST")

        def _static(self, path):
            pages = {"": "landing.html", "/": "landing.html", "/review": "index.html", "/review/": "index.html"}
            name = pages.get(path, path.lstrip("/"))
            target = (STATIC / name).resolve()
            if STATIC.resolve() not in target.parents or not target.is_file():
                return self._send(HTTPStatus.NOT_FOUND, {"error": "not found"})
            ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype in ("application/javascript",):
                ctype += "; charset=utf-8"
            self._send(HTTPStatus.OK, raw=target.read_bytes(), content_type=ctype)

        def _audio(self, q):
            """Serve a local audio file referenced by a recording's trace.json, with Range support."""
            try:
                info = panel.services.audio_source(q["source"][0], q["series"][0], q["recording"][0])
            except (KeyError, ValueError):
                return self._send(HTTPStatus.BAD_REQUEST, {"error": "bad audio request"})
            if info.get("kind") != "file":
                return self._send(HTTPStatus.NOT_FOUND, {"error": "no local audio for this recording"})
            path = Path(info["path"])
            size = path.stat().st_size
            ctype = mimetypes.guess_type(str(path))[0] or "audio/mpeg"
            rng = self.headers.get("Range")
            start, end = 0, size - 1
            if rng and rng.startswith("bytes="):
                a, _, b = rng[6:].partition("-")
                start = int(a) if a else 0
                end = min(int(b), size - 1) if b else size - 1
            with open(path, "rb") as f:
                f.seek(start)
                data = f.read(end - start + 1)
            status = HTTPStatus.PARTIAL_CONTENT if rng else HTTPStatus.OK
            headers = {"Accept-Ranges": "bytes"}
            if rng:
                headers["Content-Range"] = f"bytes {start}-{end}/{size}"
            self._send(status, raw=data, content_type=ctype, headers=headers)

    return Handler


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True

    def server_bind(self):
        # HTTPServer.server_bind resolves the host's FQDN, which can hang on machines with slow
        # reverse DNS; a server bound to 127.0.0.1 does not need it.
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]


def main(argv=None):
    p = argparse.ArgumentParser(description="MINARET reviewer panel (local)")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--config", type=Path, default=None, help="Path to minaret.yaml")
    args = p.parse_args(argv)
    panel = Panel(config_mod.load(args.config))
    server = LocalServer(("127.0.0.1", args.port), make_handler(panel))
    print(f"Reviewer panel on http://127.0.0.1:{args.port}  (runs dir: {panel.services.runs_dir}; Ctrl+C to stop)",
          flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
