"""Local dashboard server: static files, the case folder, and the write actions of the dashboard.

Binds to 127.0.0.1 only. Every write goes to a file in the case folder, so the folder stays the
record: review/decisions.json + log.jsonl, scenes/<id>/anchors.json, documents/, photos/, video/.
"""
from __future__ import annotations

import http.server
import json
import urllib.parse
from pathlib import Path

from . import extract, fuse, imagepipe, ingest, review, scenes

ROOT = Path(__file__).resolve().parent.parent
IMG = (".jpg", ".jpeg", ".png", ".webp")
VID = (".mp4", ".mov", ".mkv", ".avi", ".webm")
MAX_UPLOAD = 600 * 1024 * 1024


class Handler(http.server.SimpleHTTPRequestHandler):
    case_dir: Path = None

    def translate_path(self, path):
        path = urllib.parse.unquote(path.split("?", 1)[0].split("#", 1)[0])
        if path.startswith("/case/"):
            base, rel = self.case_dir, path[len("/case/"):]
        else:
            base, rel = ROOT / "dashboard", path.lstrip("/") or "index.html"
        target = (base / rel).resolve()
        return str(target if str(target).startswith(str(base.resolve())) else base / "index.html")

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        data = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}
        try:
            if url.path == "/api/scene_query":
                return self._json(scenes.query(self.case_dir, q.get("scene", ""), q.get("text", "")))
            if url.path == "/api/image_pipeline":
                return self._json(imagepipe.status(self.case_dir, q.get("scene", "")))
            if url.path == "/api/video":
                d = self.case_dir / "video"
                files = [{"file": p.name, "bytes": p.stat().st_size} for p in sorted(d.iterdir()) if p.suffix.lower() in VID] if d.exists() else []
                return self._json({"files": files})
        except Exception as e:
            return self._json({"error": str(e)}, 400)
        return super().do_GET()

    def do_POST(self):
        url = urllib.parse.urlparse(self.path)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}
        c = self.case_dir
        try:
            n = int(self.headers.get("Content-Length", 0) or 0)
            if n > MAX_UPLOAD:
                raise ValueError("file too large")
            raw = self.rfile.read(n) if n else b""
            rebuild = True
            if url.path == "/api/upload":
                kind, name = q.get("kind"), q.get("name", "upload")
                if kind == "document":
                    out = ingest.add_document(c, name, raw, q.get("title", ""), q.get("doc_type", "other"), q.get("date", ""), q.get("author", ""))
                elif kind == "photo":
                    out = ingest.save_media(c, "photos", name, raw, IMG)
                    caps = c / "photos" / "captions.json"
                    d = json.loads(caps.read_text()) if caps.exists() else {}
                    d[out["file"]] = {"caption": q.get("caption", ""), "source_url": None, "uploaded": True}
                    caps.write_text(json.dumps(d, indent=2, ensure_ascii=False))
                elif kind == "scene_photo":
                    sid = q.get("scene", "")
                    if not (c / "scenes" / sid / "scene.json").exists():
                        raise ValueError("unknown scene")
                    out = ingest.save_media(c, f"scenes/{sid}/photos", name, raw, IMG)
                elif kind == "video":
                    out, rebuild = ingest.save_media(c, "video", name, raw, VID), False
                else:
                    raise ValueError("kind must be document, photo, scene_photo or video")
            else:
                body = json.loads(raw or b"{}")
                if url.path == "/api/review":
                    out = review.decide(c, body["key"], body["decision"], body.get("note", ""), body.get("reviewer", ""))
                elif url.path == "/api/anchor":
                    out = scenes.set_anchor(c, body["scene"], body["entity"], body.get("xyz", [0, 0, 0]), body.get("placed_by", ""),
                                            bool(body.get("remove")), "[for demo purposes]" in body["entity"])
                elif url.path == "/api/extract":
                    cfg = json.loads((c / "case.json").read_text()).get("llm", {})
                    done = []
                    extract.run(c, cfg.get("backend", "claude-cli"), cfg.get("model", "haiku"), log=done.append)
                    out = {"log": done}
                elif url.path == "/api/rebuild":
                    out = {}
                elif url.path == "/api/image_pipeline/run":
                    out, rebuild = imagepipe.run(c, body["scene"]), False
                else:
                    return self._json({"error": "not found"}, 404)
            if rebuild:
                out = (out if isinstance(out, dict) else {"result": out}) | {"stats": fuse.build(c, log=lambda *_: None)["stats"]}
            self._json(out)
        except Exception as e:
            self._json({"error": f"{e}"}, 400)


def serve(case_dir: Path, port: int):
    Handler.case_dir = case_dir.resolve()
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"dashboard: http://127.0.0.1:{port}/")
    srv.serve_forever()
