#!/usr/bin/env python3
"""Local dev server for the Brazil 2026 Journal photo review tool.

Serves this folder (the private Journal folder, including the photos/
export directory) the same as `python -m http.server` would, but also
exposes POST /api/save-edits, which writes the posted JSON straight to
data/photo-edits.json (with a one-deep .bak backup of whatever was there
before), then immediately rebuilds data/trip.json from the latest
legs/narrative/catalog/edits so the site reflects the save on next
reload -- no separate manual build step needed.

The save route is revision-checked: the page posts the `rev` it loaded and
the server refuses with 409 if the file on disk has moved on, so a second
tab cannot silently clobber the first.

This route is local-dev-only. It reads/writes files on THIS machine and
is not part of any file that would ever be published -- the Journal
folder itself is a private, local-only diary and is never deployed.

Usage:
    python review_server.py [port]        (default port 8000)
"""
import http.server
import json
import os
import sys
import urllib.parse
from pathlib import Path

SITE_ROOT_PATH = Path(__file__).resolve().parent
sys.path.insert(0, str(SITE_ROOT_PATH / "scripts"))
import build_trip_content  # noqa: E402  (needs sys.path tweak above)

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
SITE_ROOT = str(SITE_ROOT_PATH)
PHOTOS_DIR = os.path.join(SITE_ROOT, "photos")
DATA_DIR = SITE_ROOT_PATH / "data"
LEGS_PATH = DATA_DIR / "legs.json"
NARRATIVE_PATH = DATA_DIR / "narrative.json"
CATALOG_PATH = DATA_DIR / "photo-catalog.json"
EDITS_PATH = os.path.join(SITE_ROOT, "data", "photo-edits.json")
TRIP_PATH = DATA_DIR / "trip.json"
SAVE_ROUTE = "/api/save-edits"


class ReviewHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=SITE_ROOT, **kwargs)

    def do_POST(self):
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path != SAVE_ROUTE:
            self.send_error(404, "Not found")
            return

        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b""
        try:
            payload = json.loads(raw)
            if not isinstance(payload, dict) or "photos" not in payload:
                raise ValueError("Expected JSON object with a 'photos' key")
        except (json.JSONDecodeError, ValueError) as exc:
            self._send_json(400, {"ok": False, "error": str(exc)})
            return

        # Optimistic concurrency: the review page sends the rev it loaded. If the
        # file has moved on since (a second tab saved first), refuse rather than
        # silently overwriting that tab's work.
        current_rev = self._current_rev()
        posted_rev = payload.get("rev")
        if isinstance(posted_rev, int) and posted_rev != current_rev:
            self._send_json(409, {"ok": False, "rev": current_rev, "error": "stale rev"})
            return
        payload["rev"] = current_rev + 1

        os.makedirs(os.path.dirname(EDITS_PATH), exist_ok=True)
        # Keep a one-deep backup of whatever was there before overwriting,
        # so an in-tool mistake is always one file-copy away from undo.
        if os.path.exists(EDITS_PATH):
            with open(EDITS_PATH, "rb") as src:
                backup = src.read()
            with open(EDITS_PATH + ".bak", "wb") as dst:
                dst.write(backup)

        tmp_path = EDITS_PATH + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp_path, EDITS_PATH)  # atomic on both Windows and POSIX

        rebuild_error = self._rebuild_trip_json()
        response = {"ok": True, "rev": payload["rev"], "count": len(payload.get("photos", {}))}
        if rebuild_error:
            response["rebuildError"] = rebuild_error
        self._send_json(200, response)

    @staticmethod
    def _current_rev() -> int:
        """Revision number of the edits file on disk (0 when absent or unversioned)."""
        try:
            with open(EDITS_PATH, encoding="utf-8") as f:
                value = json.load(f).get("rev")
        except (OSError, json.JSONDecodeError):
            return 0
        return value if isinstance(value, int) else 0

    @staticmethod
    def _rebuild_trip_json() -> str | None:
        """Regenerate data/trip.json from the file just saved, so the site
        (index.html's fetch of data/trip.json) reflects this save the next
        time it's reloaded, with no separate manual build step required."""
        try:
            trip = build_trip_content.build_trip(
                build_trip_content.read_json(LEGS_PATH),
                build_trip_content.read_json(NARRATIVE_PATH),
                build_trip_content.read_json(CATALOG_PATH),
                build_trip_content.read_json(Path(EDITS_PATH)),
            )
            build_trip_content.write_json(TRIP_PATH, trip)
            return None
        except Exception as exc:  # noqa: BLE001 - report to the review page, don't crash the server
            print(f"Warning: failed to rebuild trip.json: {exc}")
            return str(exc)

    def _send_json(self, status, obj):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    if not os.path.isdir(PHOTOS_DIR):
        print(f"Warning: photos folder not found at {PHOTOS_DIR}")
        print("Run scripts\\build_photo_catalog.py after exporting photos there.")
    with http.server.ThreadingHTTPServer(("", PORT), ReviewHandler) as httpd:
        print(f"Serving {SITE_ROOT}")
        print(f"Journal diary: http://localhost:{PORT}/")
        print(f"Photo review:  http://localhost:{PORT}/photo-review.html")
        print("Press Ctrl+C to stop.")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nStopping server.")


if __name__ == "__main__":
    main()
