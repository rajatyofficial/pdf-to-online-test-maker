from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .parser import SECTION_ORDER, parsed_without_blobs


import sys
if getattr(sys, 'frozen', False):
    DB_PATH = Path(sys.executable).resolve().parent / "data" / "app.sqlite"
else:
    DB_PATH = Path(__file__).resolve().parent.parent / "data" / "app.sqlite"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS tests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                source_filename TEXT NOT NULL,
                imported_at TEXT NOT NULL,
                question_count INTEGER NOT NULL,
                import_report TEXT NOT NULL,
                parsed_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                test_id INTEGER NOT NULL REFERENCES tests(id) ON DELETE CASCADE,
                number INTEGER NOT NULL,
                section TEXT NOT NULL,
                raw_text TEXT NOT NULL,
                display_text TEXT NOT NULL,
                options_json TEXT NOT NULL,
                correct_answer TEXT NOT NULL,
                parse_source TEXT NOT NULL,
                confidence REAL NOT NULL,
                metadata_json TEXT NOT NULL,
                UNIQUE(test_id, number)
            );

            CREATE TABLE IF NOT EXISTS question_assets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question_id INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
                asset_type TEXT NOT NULL DEFAULT 'image',
                mime_type TEXT NOT NULL,
                data BLOB NOT NULL,
                sha256 TEXT NOT NULL,
                page_number INTEGER,
                bbox_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                test_id INTEGER NOT NULL REFERENCES tests(id) ON DELETE CASCADE,
                attempt_no INTEGER NOT NULL,
                label TEXT NOT NULL,
                mode TEXT NOT NULL,
                selected_sections_json TEXT NOT NULL,
                score REAL NOT NULL,
                max_score REAL NOT NULL,
                correct_count INTEGER NOT NULL,
                wrong_count INTEGER NOT NULL,
                skipped_count INTEGER NOT NULL,
                accuracy REAL NOT NULL,
                started_at TEXT NOT NULL,
                completed_at TEXT NOT NULL,
                duration_seconds REAL NOT NULL,
                section_metrics_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS responses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                attempt_id INTEGER NOT NULL REFERENCES attempts(id) ON DELETE CASCADE,
                question_id INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
                selected_option TEXT,
                correct INTEGER NOT NULL,
                time_spent_seconds REAL NOT NULL,
                flagged INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )

def get_setting(key: str) -> str | None:
    init_db()
    with connect() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None

def set_setting(key: str, value: str | None) -> None:
    init_db()
    with connect() as conn:
        if value is None:
            conn.execute("DELETE FROM settings WHERE key = ?", (key,))
        else:
            conn.execute(
                """
                INSERT INTO settings (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, value)
            )



def save_parsed_test(parsed: dict[str, Any]) -> int:
    init_db()
    name = _unique_test_name(parsed["name"])
    now = utc_now()
    clean_json = parsed_without_blobs({**parsed, "name": name})

    with connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO tests (name, source_filename, imported_at, question_count, import_report, parsed_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                name,
                parsed["source_filename"],
                now,
                len(parsed["questions"]),
                json.dumps(parsed["report"], ensure_ascii=False),
                json.dumps(clean_json, ensure_ascii=False),
            ),
        )
        test_id = int(cursor.lastrowid)
        for question in parsed["questions"]:
            question_cursor = conn.execute(
                """
                INSERT INTO questions
                    (test_id, number, section, raw_text, display_text, options_json, correct_answer,
                     parse_source, confidence, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    test_id,
                    question["number"],
                    question["section"],
                    question["raw_text"],
                    question["display_text"],
                    json.dumps(question["options"], ensure_ascii=False),
                    question["answer"] or "",
                    question["parse_source"],
                    question["confidence"],
                    json.dumps(question["metadata"], ensure_ascii=False),
                ),
            )
            question_id = int(question_cursor.lastrowid)
            for asset in question.get("assets", []):
                conn.execute(
                    """
                    INSERT INTO question_assets
                        (question_id, mime_type, data, sha256, page_number, bbox_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        question_id,
                        asset["mime_type"],
                        asset["bytes"],
                        asset["sha256"],
                        asset["page"],
                        json.dumps(asset["bbox_pdf"], ensure_ascii=False),
                        now,
                    ),
                )
    return test_id


def _unique_test_name(base_name: str) -> str:
    with connect() as conn:
        existing = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM tests WHERE name = ? OR name LIKE ?",
                (base_name, f"{base_name} (%)"),
            )
        }
    if base_name not in existing:
        return base_name
    index = 2
    while f"{base_name} ({index})" in existing:
        index += 1
    return f"{base_name} ({index})"


def list_tests() -> list[dict[str, Any]]:
    init_db()
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT t.*,
                   COUNT(a.id) AS attempt_count,
                   MAX(a.completed_at) AS last_attempt_at
            FROM tests t
            LEFT JOIN attempts a ON a.test_id = t.id
            GROUP BY t.id
            ORDER BY t.imported_at DESC
            """
        ).fetchall()
    return [_row_to_test(row) for row in rows]


def get_test(test_id: int, include_answers: bool = False) -> dict[str, Any] | None:
    init_db()
    with connect() as conn:
        test = conn.execute("SELECT * FROM tests WHERE id = ?", (test_id,)).fetchone()
        if not test:
            return None
        questions = conn.execute(
            "SELECT * FROM questions WHERE test_id = ? ORDER BY number",
            (test_id,),
        ).fetchall()
        asset_rows = conn.execute(
            """
            SELECT qa.id, qa.question_id, qa.mime_type, qa.sha256, qa.page_number, qa.bbox_json
            FROM question_assets qa
            JOIN questions q ON q.id = qa.question_id
            WHERE q.test_id = ?
            ORDER BY qa.id
            """,
            (test_id,),
        ).fetchall()

    assets_by_question: dict[int, list[dict[str, Any]]] = {}
    for asset in asset_rows:
        assets_by_question.setdefault(asset["question_id"], []).append(
            {
                "id": asset["id"],
                "mime_type": asset["mime_type"],
                "sha256": asset["sha256"],
                "page_number": asset["page_number"],
                "bbox": json.loads(asset["bbox_json"]),
                "url": f"/api/assets/{asset['id']}",
            }
        )

    return {
        **_row_to_test(test),
        "questions": [_row_to_question(row, assets_by_question.get(row["id"], []), include_answers) for row in questions],
    }


def get_asset(asset_id: int) -> tuple[str, bytes] | None:
    init_db()
    with connect() as conn:
        row = conn.execute("SELECT mime_type, data FROM question_assets WHERE id = ?", (asset_id,)).fetchone()
    if not row:
        return None
    return row["mime_type"], row["data"]


def submit_attempt(payload: dict[str, Any]) -> dict[str, Any]:
    init_db()
    test_id = int(payload["test_id"])
    mode = str(payload["mode"])
    selected_sections = payload.get("selected_sections") or SECTION_ORDER
    responses = payload.get("responses") or []
    started_at = payload.get("started_at") or utc_now()
    completed_at = payload.get("completed_at") or utc_now()
    duration_seconds = float(payload.get("duration_seconds") or 0)

    with connect() as conn:
        question_rows = conn.execute(
            "SELECT id, number, section, correct_answer FROM questions WHERE test_id = ?",
            (test_id,),
        ).fetchall()
        questions_by_id = {row["id"]: row for row in question_rows if row["section"] in selected_sections}
        max_attempt_no = conn.execute(
            "SELECT COALESCE(MAX(attempt_no), 0) AS max_attempt_no FROM attempts WHERE test_id = ?",
            (test_id,),
        ).fetchone()["max_attempt_no"]
        attempt_no = int(max_attempt_no) + 1
        label = "Original" if attempt_no == 1 else f"Reattempt {attempt_no - 1}"

        response_by_question = {int(item["question_id"]): item for item in responses if int(item["question_id"]) in questions_by_id}
        section_metrics = {
            section: {"total": 0, "correct": 0, "wrong": 0, "skipped": 0, "score": 0.0, "time_spent_seconds": 0.0}
            for section in selected_sections
        }
        correct_count = wrong_count = skipped_count = 0
        score = 0.0

        for question_id, question in questions_by_id.items():
            section = question["section"]
            section_metrics[section]["total"] += 1
            response = response_by_question.get(question_id, {})
            selected = response.get("selected_option")
            time_spent = float(response.get("time_spent_seconds") or 0)
            section_metrics[section]["time_spent_seconds"] += time_spent
            if selected not in ("a", "b", "c", "d"):
                skipped_count += 1
                section_metrics[section]["skipped"] += 1
                continue
            if selected == question["correct_answer"]:
                correct_count += 1
                score += 2
                section_metrics[section]["correct"] += 1
                section_metrics[section]["score"] += 2
            else:
                wrong_count += 1
                score -= 0.5
                section_metrics[section]["wrong"] += 1
                section_metrics[section]["score"] -= 0.5

        attempted = correct_count + wrong_count
        accuracy = round((correct_count / attempted) * 100, 2) if attempted else 0.0
        max_score = len(questions_by_id) * 2

        cursor = conn.execute(
            """
            INSERT INTO attempts
                (test_id, attempt_no, label, mode, selected_sections_json, score, max_score,
                 correct_count, wrong_count, skipped_count, accuracy, started_at, completed_at,
                 duration_seconds, section_metrics_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                test_id,
                attempt_no,
                label,
                mode,
                json.dumps(selected_sections, ensure_ascii=False),
                score,
                max_score,
                correct_count,
                wrong_count,
                skipped_count,
                accuracy,
                started_at,
                completed_at,
                duration_seconds,
                json.dumps(section_metrics, ensure_ascii=False),
            ),
        )
        attempt_id = int(cursor.lastrowid)

        for question_id, question in questions_by_id.items():
            response = response_by_question.get(question_id, {})
            selected = response.get("selected_option")
            correct = int(selected == question["correct_answer"]) if selected in ("a", "b", "c", "d") else 0
            conn.execute(
                """
                INSERT INTO responses
                    (attempt_id, question_id, selected_option, correct, time_spent_seconds, flagged)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    attempt_id,
                    question_id,
                    selected if selected in ("a", "b", "c", "d") else None,
                    correct,
                    float(response.get("time_spent_seconds") or 0),
                    int(bool(response.get("flagged"))),
                ),
            )

    return get_attempt(attempt_id) or {"id": attempt_id}


def delete_test(test_id: int) -> bool:
    init_db()
    with connect() as conn:
        cursor = conn.execute("DELETE FROM tests WHERE id = ?", (test_id,))
        return cursor.rowcount > 0


def delete_attempt(attempt_id: int) -> bool:
    init_db()
    with connect() as conn:
        cursor = conn.execute("DELETE FROM attempts WHERE id = ?", (attempt_id,))
        return cursor.rowcount > 0


def update_maths_questions_from_parsed(test_id: int, parsed: dict[str, Any]) -> dict[str, Any]:
    init_db()
    maths_questions = [question for question in parsed["questions"] if question["section"] == "Maths"]
    now = utc_now()
    with connect() as conn:
        existing = conn.execute("SELECT import_report, parsed_json FROM tests WHERE id = ?", (test_id,)).fetchone()
        if not existing:
            raise ValueError("Test not found")

        for question in maths_questions:
            row = conn.execute(
                "SELECT id FROM questions WHERE test_id = ? AND number = ?",
                (test_id, question["number"]),
            ).fetchone()
            if not row:
                continue
            conn.execute(
                """
                UPDATE questions
                SET raw_text = ?, display_text = ?, options_json = ?, correct_answer = ?,
                    parse_source = ?, confidence = ?, metadata_json = ?
                WHERE id = ?
                """,
                (
                    question["raw_text"],
                    question["display_text"],
                    json.dumps(question["options"], ensure_ascii=False),
                    question["answer"] or "",
                    question["parse_source"],
                    question["confidence"],
                    json.dumps(question["metadata"], ensure_ascii=False),
                    row["id"],
                ),
            )

        report = json.loads(existing["import_report"])
        report["llm"] = parsed["report"].get("llm", report.get("llm", {}))
        report["maths_rebuilt_at"] = now
        report["maths_rebuilt_count"] = len(maths_questions)

        parsed_json = json.loads(existing["parsed_json"])
        by_number = {question["number"]: question for question in parsed_json.get("questions", [])}
        for question in maths_questions:
            clean_question = {key: value for key, value in question.items() if key != "assets"}
            clean_question["assets"] = []
            by_number[question["number"]] = clean_question
        parsed_json["questions"] = [by_number[number] for number in sorted(by_number)]
        parsed_json["report"] = report

        conn.execute(
            "UPDATE tests SET import_report = ?, parsed_json = ? WHERE id = ?",
            (json.dumps(report, ensure_ascii=False), json.dumps(parsed_json, ensure_ascii=False), test_id),
        )

    return {"updated": len(maths_questions), "report": parsed["report"]}


def list_history() -> list[dict[str, Any]]:
    init_db()
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT a.*, t.name AS test_name
            FROM attempts a
            JOIN tests t ON t.id = a.test_id
            ORDER BY a.completed_at DESC
            """
        ).fetchall()
    return [_row_to_attempt(row) for row in rows]


def get_attempt(attempt_id: int) -> dict[str, Any] | None:
    init_db()
    with connect() as conn:
        attempt = conn.execute(
            """
            SELECT a.*, t.name AS test_name
            FROM attempts a
            JOIN tests t ON t.id = a.test_id
            WHERE a.id = ?
            """,
            (attempt_id,),
        ).fetchone()
        if not attempt:
            return None
        responses = conn.execute(
            """
            SELECT r.*, q.number, q.section, q.display_text, q.options_json, q.correct_answer
            FROM responses r
            JOIN questions q ON q.id = r.question_id
            WHERE r.attempt_id = ?
            ORDER BY q.number
            """,
            (attempt_id,),
        ).fetchall()
    data = _row_to_attempt(attempt)
    data["responses"] = [
        {
            "question_id": row["question_id"],
            "number": row["number"],
            "section": row["section"],
            "display_text": row["display_text"],
            "options": json.loads(row["options_json"]),
            "correct_answer": row["correct_answer"],
            "selected_option": row["selected_option"],
            "correct": bool(row["correct"]),
            "time_spent_seconds": row["time_spent_seconds"],
            "flagged": bool(row["flagged"]),
        }
        for row in responses
    ]
    return data


def _row_to_test(row: sqlite3.Row) -> dict[str, Any]:
    report = json.loads(row["import_report"]) if "import_report" in row.keys() else {}
    return {
        "id": row["id"],
        "name": row["name"],
        "source_filename": row["source_filename"],
        "imported_at": row["imported_at"],
        "question_count": row["question_count"],
        "import_report": report,
        "attempt_count": row["attempt_count"] if "attempt_count" in row.keys() else None,
        "last_attempt_at": row["last_attempt_at"] if "last_attempt_at" in row.keys() else None,
    }


def _row_to_question(row: sqlite3.Row, assets: list[dict[str, Any]], include_answers: bool) -> dict[str, Any]:
    data = {
        "id": row["id"],
        "number": row["number"],
        "section": row["section"],
        "raw_text": row["raw_text"],
        "display_text": row["display_text"],
        "options": json.loads(row["options_json"]),
        "parse_source": row["parse_source"],
        "confidence": row["confidence"],
        "metadata": json.loads(row["metadata_json"]),
        "assets": assets,
    }
    if include_answers:
        data["correct_answer"] = row["correct_answer"]
    return data


def _row_to_attempt(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "test_id": row["test_id"],
        "test_name": row["test_name"],
        "attempt_no": row["attempt_no"],
        "label": row["label"],
        "mode": row["mode"],
        "selected_sections": json.loads(row["selected_sections_json"]),
        "score": row["score"],
        "max_score": row["max_score"],
        "correct_count": row["correct_count"],
        "wrong_count": row["wrong_count"],
        "skipped_count": row["skipped_count"],
        "accuracy": row["accuracy"],
        "started_at": row["started_at"],
        "completed_at": row["completed_at"],
        "duration_seconds": row["duration_seconds"],
        "section_metrics": json.loads(row["section_metrics_json"]),
    }
