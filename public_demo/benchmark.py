"""Run the deployed explorer UI against the real build and disposable scale fixtures."""
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import shutil
import subprocess
from tempfile import TemporaryDirectory
from threading import Thread

from public_demo.build import write_explorer


def run(site, repeats):
    html = (site / "index.html").read_text(encoding="utf-8")
    raw = re.search(r'<script id="snapshot" type="application/json">(.*?)</script>', html).group(1)
    snapshot = json.loads(raw)
    source = snapshot["rows"]
    if "chunks" in snapshot:
        source = [row for chunk in snapshot["chunks"]
                  for row in json.loads((site / chunk).read_text(encoding="utf-8"))]
    with TemporaryDirectory() as directory:
        root = Path(directory)
        shutil.copytree(site, root / "actual")
        scenarios = []
        for size in dict.fromkeys([len(source), 5000, 50000]):
            rows = source
            folder = "actual"
            if size != len(source):
                folder = str(size)
                target = root / folder
                shutil.copytree(site, target)
                rows = [[f"TEST{i:06d}", *rows[i % len(rows)][1:]] for i in range(size)]
                write_explorer(target, {"columns": snapshot["columns"], "rows": rows,
                                        "metrics": {**snapshot["metrics"], "total_incidents": size}})
            scenarios.append({"folder": folder, "size": size,
                              "expected": dict(zip(snapshot["columns"], rows[-1]))})
        handler = partial(SimpleHTTPRequestHandler, directory=root)
        with ThreadingHTTPServer(("127.0.0.1", 0), handler) as server:
            Thread(target=server.serve_forever, daemon=True).start()
            try:
                subprocess.run(["node", str(Path(__file__).with_name("benchmark.cjs")),
                                f"http://127.0.0.1:{server.server_port}", str(repeats)],
                               input=json.dumps(scenarios), text=True, check=True)
            finally:
                server.shutdown()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("site", type=Path)
    parser.add_argument("--repeats", type=int, choices=range(1, 11), default=3)
    args = parser.parse_args()
    run(args.site, args.repeats)
