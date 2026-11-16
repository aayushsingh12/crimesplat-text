"""python -m crimetext <command> <case_dir>

  fetch     download the case page, linked files and photos; write numbered passages
  chunk     split passages into extraction chunks
  extract   run the LLM extraction (--backend claude-cli|ollama|files, --model NAME)
  build     validate claims, resolve entities, write build/bundle.json
  serve     open the dashboard (--port 8765); review decisions and scene pins are saved through it
  scene     attach a 3D splat: --splat FILE_OR_PACKAGE --id ID --title T --location NAME [--note N]
  all       fetch, chunk, extract, build
"""
import argparse
import sys
from pathlib import Path

from . import extract, fetch, fuse, scenes, server

ROOT = Path(__file__).resolve().parent.parent


def main():
    ap = argparse.ArgumentParser(prog="crimetext", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["fetch", "chunk", "extract", "build", "serve", "scene", "all"])
    ap.add_argument("case_dir", type=Path)
    ap.add_argument("--backend", default="claude-cli")
    ap.add_argument("--model", default="haiku")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--splat", type=Path)
    ap.add_argument("--id", default="scene01")
    ap.add_argument("--title", default="")
    ap.add_argument("--location", default="")
    ap.add_argument("--pipeline-dir", type=Path, default=ROOT / "pipelines" / "image")
    ap.add_argument("--note", default="")
    a = ap.parse_args()
    c = a.case_dir
    if a.command in ("fetch", "all"):
        fetch.fetch(c)
    if a.command in ("chunk", "all"):
        print(extract.make_chunks(c), "chunks")
    if a.command in ("extract", "all"):
        extract.run(c, a.backend, a.model, a.force)
    if a.command == "scene":
        scenes.add(c, a.splat, a.id, a.title or a.id, a.location, a.note, a.pipeline_dir)
        fuse.build(c)
    if a.command in ("build", "all"):
        fuse.build(c)
    if a.command == "serve":
        server.serve(c, a.port)


if __name__ == "__main__":
    sys.exit(main())
