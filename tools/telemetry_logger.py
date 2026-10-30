"""Record engine telemetry sent from Stormworks by the telemetry microcontroller.

    uv run tools/telemetry_logger.py [out_dir] [--port 38480]

Leave it running, load an engine test boat (tools/engine_test_boats.py) on open water and wait
for phase=done (about 7 minutes). Each run is appended to <out_dir>/<run>.csv; stop with Ctrl+C.
The game only sends to localhost, and only while this is listening.
"""
import argparse
import contextlib
import csv
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from swhull.telemetry import PORT  # noqa: E402

FIELDS = ["wall", "run", "phase", "step", "s", "throttle", "rps", "fuel", "temp", "speed"]


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out", nargs="?", default="telemetry")
    parser.add_argument("--port", type=int, default=PORT)
    args = parser.parse_args()
    os.makedirs(args.out, exist_ok=True)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            url = urlparse(self.path)
            row = {k: v[0] for k, v in parse_qs(url.query).items()}
            run = "".join(c for c in row.get("run", "unnamed") if c.isalnum() or c in "-_") or "unnamed"
            if url.path == "/log":
                path = os.path.join(args.out, f"{run}.csv")
                new = not os.path.exists(path)
                with open(path, "a", newline="", encoding="utf-8") as f:
                    writer = csv.DictWriter(f, FIELDS, extrasaction="ignore")
                    if new:
                        writer.writeheader()
                    writer.writerow({**row, "wall": f"{time.time():.1f}", "run": run})
                print(f"{run:>8} {row.get('phase', '?'):>7} step {row.get('step', '?'):>2} "
                      f"throttle {row.get('throttle', '?'):>5} rps {row.get('rps', '?'):>8} "
                      f"speed {row.get('speed', '?'):>8} temp {row.get('temp', '?'):>7} fuel {row.get('fuel', '?')}",
                      flush=True)
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *_):
            pass

    server = HTTPServer(("127.0.0.1", args.port), Handler)
    print(f"Listening on 127.0.0.1:{args.port}; writing {os.path.abspath(args.out)}. Ctrl+C stops.", flush=True)
    with contextlib.suppress(KeyboardInterrupt):
        server.serve_forever()


if __name__ == "__main__":
    main()
