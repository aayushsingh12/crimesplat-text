"""python -m crimetext <command> <case_dir>

  fetch     download the case page, linked files and photos; write numbered passages
  chunk     split passages into extraction chunks
  extract   run the LLM extraction (--backend claude-cli|ollama|files, --model NAME)
  build     validate claims, resolve entities, write build/bundle.json
  serve     open the dashboard (--port 8765)
  all       fetch, chunk, extract, build
"""
import argparse
import functools
import http.server
import sys
from pathlib import Path

from . import extract, fetch, fuse

ROOT = Path(__file__).resolve().parent.parent


class Handler(http.server.SimpleHTTPRequestHandler):
    case_dir: Path = None

    def translate_path(self, path):
        path = path.split("?", 1)[0].split("#", 1)[0]
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


def main():
    ap = argparse.ArgumentParser(prog="crimetext", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["fetch", "chunk", "extract", "build", "serve", "all"])
    ap.add_argument("case_dir", type=Path)
    ap.add_argument("--backend", default="claude-cli")
    ap.add_argument("--model", default="haiku")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--port", type=int, default=8765)
    a = ap.parse_args()
    c = a.case_dir
    if a.command in ("fetch", "all"):
        fetch.fetch(c)
    if a.command in ("chunk", "all"):
        print(extract.make_chunks(c), "chunks")
    if a.command in ("extract", "all"):
        extract.run(c, a.backend, a.model, a.force)
    if a.command in ("build", "all"):
        fuse.build(c)
    if a.command == "serve":
        Handler.case_dir = c.resolve()
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
        print(f"dashboard: http://127.0.0.1:{a.port}/")
        srv.serve_forever()


if __name__ == "__main__":
    sys.exit(main())
