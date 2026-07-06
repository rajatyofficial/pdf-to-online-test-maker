from __future__ import annotations

import cgi
import json
import mimetypes
import os
import shutil
import sys
import tempfile
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from app import db
from app.ollama_client import OllamaClient
from app.parser import parse_pdf


if getattr(sys, 'frozen', False):
    ROOT = Path(sys._MEIPASS).resolve()
    DATA_ROOT = Path(sys.executable).resolve().parent
else:
    ROOT = Path(__file__).resolve().parent
    DATA_ROOT = ROOT

STATIC_DIR = ROOT / "static"
UPLOAD_DIR = DATA_ROOT / "data" / "uploads"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765


class MCQHandler(SimpleHTTPRequestHandler):
    server_version = "LocalMCQTestMaker/1.0"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/":
            self._send_file(STATIC_DIR / "index.html")
        elif path.startswith("/api/"):
            self._handle_api_get(path)
        else:
            self._send_file(STATIC_DIR / path.lstrip("/"))

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/api/tests/import":
            self._handle_import()
        elif path == "/api/settings":
            self._handle_save_settings()
        elif path == "/api/attempts/submit":
            payload = self._read_json()
            self._send_json(db.submit_attempt(payload))
        elif path.startswith("/api/tests/") and path.endswith("/rebuild-maths"):
            self._handle_rebuild_maths(path)
        else:
            self._send_json({"error": "Not found"}, status=404)

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path.startswith("/api/tests/"):
            deleted = db.delete_test(int(path.rsplit("/", 1)[-1]))
            if not deleted:
                self._send_json({"error": "Test not found"}, status=404)
                return
            self._send_json({"ok": True})
            return
        if path.startswith("/api/attempts/"):
            deleted = db.delete_attempt(int(path.rsplit("/", 1)[-1]))
            if not deleted:
                self._send_json({"error": "Attempt not found"}, status=404)
                return
            self._send_json({"ok": True})
            return
        self._send_json({"error": "Not found"}, status=404)

    def _handle_api_get(self, path: str) -> None:
        if path == "/api/health":
            available, message = OllamaClient().is_available()
            
            gemini_key = db.get_setting("gemini_api_key")
            gemini_available = bool(gemini_key)
            gemini_message = "Gemini API is ready." if gemini_key else "Gemini API key is missing. Please add it in Settings."
            
            self._send_json({"ok": True, "ollama": {"available": available, "message": message}, "gemini": {"available": gemini_available, "message": gemini_message}})
            return
        if path == "/api/settings":
            gemini_key = db.get_setting("gemini_api_key")
            masked_key = f"{gemini_key[:6]}...{gemini_key[-4:]}" if gemini_key and len(gemini_key) > 10 else ("***" if gemini_key else "")
            self._send_json({"settings": {"gemini_api_key": masked_key, "has_gemini_key": bool(gemini_key)}})
            return
        if path == "/api/tests":
            self._send_json({"tests": db.list_tests()})
            return
        if path.startswith("/api/tests/"):
            parts = path.strip("/").split("/")
            if len(parts) == 3:
                test = db.get_test(int(parts[2]), include_answers=False)
                if not test:
                    self._send_json({"error": "Test not found"}, status=404)
                    return
                self._send_json(test)
                return
            if len(parts) == 4 and parts[3] == "review":
                test = db.get_test(int(parts[2]), include_answers=True)
                if not test:
                    self._send_json({"error": "Test not found"}, status=404)
                    return
                self._send_json(test)
                return
        if path == "/api/history":
            self._send_json({"history": db.list_history()})
            return
        if path.startswith("/api/attempts/"):
            attempt = db.get_attempt(int(path.rsplit("/", 1)[-1]))
            if not attempt:
                self._send_json({"error": "Attempt not found"}, status=404)
                return
            self._send_json(attempt)
            return
        if path.startswith("/api/assets/"):
            asset = db.get_asset(int(path.rsplit("/", 1)[-1]))
            if not asset:
                self._send_json({"error": "Asset not found"}, status=404)
                return
            mime_type, data = asset
            self.send_response(200)
            self.send_header("Content-Type", mime_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        self._send_json({"error": "Not found"}, status=404)
        
    def _handle_save_settings(self) -> None:
        payload = self._read_json()
        if "gemini_api_key" in payload:
            key = payload["gemini_api_key"].strip()
            if key:
                db.set_setting("gemini_api_key", key)
            else:
                db.set_setting("gemini_api_key", None)
        self._send_json({"ok": True})

    def _handle_import(self) -> None:
        form = cgi.FieldStorage(
            fp=self.rfile,
            headers=self.headers,
            environ={
                "REQUEST_METHOD": "POST",
                "CONTENT_TYPE": self.headers.get("Content-Type", ""),
                "CONTENT_LENGTH": self.headers.get("Content-Length", "0"),
            },
        )
        if "pdf" not in form:
            self._send_json({"error": "Missing PDF upload."}, status=400)
            return
        file_item = form["pdf"]
        filename = Path(file_item.filename or "uploaded.pdf").name
        if not filename.lower().endswith(".pdf"):
            self._send_json({"error": "Please upload a PDF file."}, status=400)
            return

        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        safe_filename = _safe_filename(filename)
        target = UPLOAD_DIR / safe_filename
        suffix = 2
        while target.exists():
            target = UPLOAD_DIR / f"{Path(safe_filename).stem}-{suffix}.pdf"
            suffix += 1
        with target.open("wb") as output:
            shutil.copyfileobj(file_item.file, output)

        use_llm = str(form.getfirst("use_llm", "true")).lower() == "true"
        model = str(form.getfirst("ollama_model", "gemma"))
        engine = str(form.getfirst("engine", "ollama")).lower()
        try:
            parsed = parse_pdf(target, test_name=Path(filename).stem, use_llm=use_llm, ollama_model=model, engine=engine)
            test_id = db.save_parsed_test(parsed)
            saved = db.get_test(test_id, include_answers=False)
            self._send_json({"test": saved, "report": parsed["report"]})
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=500)

    def _handle_rebuild_maths(self, path: str) -> None:
        parts = path.strip("/").split("/")
        if len(parts) != 4:
            self._send_json({"error": "Not found"}, status=404)
            return
        test_id = int(parts[2])
        test = db.get_test(test_id, include_answers=True)
        if not test:
            self._send_json({"error": "Test not found"}, status=404)
            return
        pdf_path = _find_source_pdf(test["source_filename"])
        if not pdf_path:
            self._send_json({"error": f"Source PDF not found: {test['source_filename']}"}, status=404)
            return
        payload = self._read_json() if int(self.headers.get("Content-Length", "0")) else {}
        model = str(payload.get("ollama_model") or "qwen2.5vl:3b")
        try:
            parsed = parse_pdf(pdf_path, test_name=test["name"], use_llm=True, ollama_model=model)
            result = db.update_maths_questions_from_parsed(test_id, parsed)
            saved = db.get_test(test_id, include_answers=False)
            self._send_json({"test": saved, "updated": result["updated"], "report": result["report"]})
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=500)

    def _send_file(self, path: Path) -> None:
        path = path.resolve()
        if not str(path).startswith(str(STATIC_DIR.resolve())) or not path.exists() or not path.is_file():
            self._send_json({"error": "Not found"}, status=404)
            return
        content_type, _ = mimetypes.guess_type(str(path))
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        data = self.rfile.read(length).decode("utf-8")
        return json.loads(data or "{}")

    def _send_json(self, payload: dict, status: int = 200) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def _safe_filename(filename: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in "._- " else "_" for char in filename).strip()
    return cleaned or "uploaded.pdf"


def _find_source_pdf(filename: str) -> Path | None:
    candidates = [
        UPLOAD_DIR / filename,
        ROOT / filename,
    ]
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate
    matches = sorted(UPLOAD_DIR.glob(f"{Path(filename).stem}*.pdf"))
    return matches[0] if matches else None


def main() -> None:
    os.chdir(ROOT)
    db.init_db()
    port = int(os.environ.get("MCQ_PORT", DEFAULT_PORT))
    host = os.environ.get("MCQ_HOST", DEFAULT_HOST)
    with ThreadingHTTPServer((host, port), MCQHandler) as httpd:
        url = f"http://{host}:{port}"
        print(f"Local MCQ Test Maker running at {url}")
        
        # Give the server a moment to bind, then open the browser
        import threading
        def open_browser():
            import time
            time.sleep(0.5)
            webbrowser.open(url)
        threading.Thread(target=open_browser, daemon=True).start()
        
        httpd.serve_forever()


if __name__ == "__main__":
    main()
