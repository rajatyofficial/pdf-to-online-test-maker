from __future__ import annotations

import hashlib
import io
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pdfplumber
from PIL import Image

from .ollama_client import OllamaClient
from .gemini_client import GeminiClient


SECTIONS = {
    "Reasoning": range(1, 26),
    "GK": range(26, 51),
    "Maths": range(51, 76),
    "English": range(76, 101),
}

SECTION_ORDER = ["Reasoning", "GK", "Maths", "English"]
OPTION_RE = re.compile(r"(?m)^\(([a-d])\)\s*")
QUESTION_RE = re.compile(r"\bQ(\d{1,3})\.")
ANSWER_RE = re.compile(r"\bAns\.\(([a-d])\)")
BAD_TEXT_MARKERS = ("�", "□", "\ufffd")
FIGURE_WORDS = ("figure", "diagram", "graph", "chart", "table", "image")
FORCED_LLM_SECTIONS = {"Maths", "Reasoning"}


@dataclass
class ParsedQuestion:
    number: int
    section: str
    raw_text: str
    display_text: str
    options: dict[str, str]
    answer: str | None
    parse_source: str
    confidence: float
    page_start: int | None = None
    page_end: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    assets: list[dict[str, Any]] = field(default_factory=list)


def parse_pdf(
    pdf_path: Path,
    test_name: str | None = None,
    use_llm: bool = True,
    ollama_model: str = "gemma",
    engine: str = "ollama",
) -> dict[str, Any]:
    pdf_path = Path(pdf_path)
    test_name = test_name or pdf_path.stem
    report: dict[str, Any] = {
        "source_file": pdf_path.name,
        "warnings": [],
        "llm": {
            "enabled": use_llm,
            "model": ollama_model,
            "used": 0,
            "succeeded": 0,
            "partial": 0,
            "rejected": 0,
            "failed": 0,
            "forced_sections": sorted(FORCED_LLM_SECTIONS),
            "status": "not_checked",
        },
    }

    with pdfplumber.open(pdf_path) as pdf:
        page_texts = [page.extract_text(x_tolerance=1, y_tolerance=3) or "" for page in pdf.pages]
        full_text = "\n".join(page_texts)
        marker_pages = _find_marker_pages(page_texts)
        questions = _parse_questions_from_text(full_text, marker_pages, report)
        image_assets = _extract_candidate_question_assets(pdf, page_texts, report)
        _attach_assets_to_questions(questions, image_assets)

        if use_llm:
            _run_llm_fallback(pdf, questions, report, ollama_model, engine)

    ordered = [questions[number] for number in sorted(questions)]
    report["question_count"] = len(ordered)
    report["answer_count"] = sum(1 for question in ordered if question.answer in ("a", "b", "c", "d"))
    report["asset_count"] = sum(len(question.assets) for question in ordered)
    report["manual_review_count"] = sum(1 for question in ordered if question.parse_source == "manual_review_needed")
    report["sections"] = {
        section: sum(1 for question in ordered if question.section == section) for section in SECTION_ORDER
    }

    _validate_import(ordered, report)

    return {
        "name": test_name,
        "source_filename": pdf_path.name,
        "questions": [_question_to_dict(question) for question in ordered],
        "report": report,
    }


def _parse_questions_from_text(
    full_text: str,
    marker_pages: dict[int, int],
    report: dict[str, Any],
) -> dict[int, ParsedQuestion]:
    matches = list(QUESTION_RE.finditer(full_text))
    if len(matches) != 100:
        report["warnings"].append(f"Expected 100 question markers, found {len(matches)}.")

    questions: dict[int, ParsedQuestion] = {}
    for index, match in enumerate(matches):
        number = int(match.group(1))
        end = matches[index + 1].start() if index + 1 < len(matches) else len(full_text)
        block = full_text[match.end() : end].strip()
        section = section_for_number(number)
        parsed = _parse_question_block(number, block)
        page_start = marker_pages.get(number)
        page_end = marker_pages.get(number + 1, page_start)
        if page_start and page_end and page_end < page_start:
            page_end = page_start

        if parsed["ok"]:
            question = ParsedQuestion(
                number=number,
                section=section,
                raw_text=parsed["question"],
                display_text=_to_display_text(parsed["question"], section),
                options={key: _to_display_text(value, section) for key, value in parsed["options"].items()},
                answer=parsed["answer"],
                parse_source="text_parser",
                confidence=_confidence_for(parsed["question"], parsed["options"], section),
                page_start=page_start,
                page_end=page_end,
                metadata={"text_parser": "ok"},
            )
        else:
            question = ParsedQuestion(
                number=number,
                section=section,
                raw_text=block,
                display_text=_to_display_text(block, section),
                options=parsed.get("options") or {"a": "", "b": "", "c": "", "d": ""},
                answer=parsed.get("answer"),
                parse_source="manual_review_needed",
                confidence=0.0,
                page_start=page_start,
                page_end=page_end,
                metadata={"text_parser": parsed["error"]},
            )
        questions[number] = question

    return questions


def _parse_question_block(number: int, block: str) -> dict[str, Any]:
    answer_match = ANSWER_RE.search(block)
    if not answer_match:
        return {"ok": False, "error": f"Q{number}: missing answer marker"}

    before_answer = block[: answer_match.start()].strip()
    option_matches = list(OPTION_RE.finditer(before_answer))
    if len(option_matches) != 4:
        return {
            "ok": False,
            "error": f"Q{number}: expected 4 options, found {len(option_matches)}",
            "answer": answer_match.group(1),
        }

    question_text = before_answer[: option_matches[0].start()].strip()
    options: dict[str, str] = {}
    for index, option_match in enumerate(option_matches):
        option_key = option_match.group(1)
        option_end = option_matches[index + 1].start() if index + 1 < len(option_matches) else len(before_answer)
        options[option_key] = before_answer[option_match.end() : option_end].strip()

    if not question_text or any(not options[key] for key in ("a", "b", "c", "d")):
        return {"ok": False, "error": f"Q{number}: blank question or option", "answer": answer_match.group(1)}

    return {"ok": True, "question": question_text, "options": options, "answer": answer_match.group(1)}


def _extract_candidate_question_assets(pdf: pdfplumber.PDF, page_texts: list[str], report: dict[str, Any]) -> list[dict[str, Any]]:
    collected: list[dict[str, Any]] = []
    hash_counts: dict[str, int] = {}
    position_counts: dict[str, int] = {}

    rendered_pages: dict[int, Image.Image] = {}
    for page_index, page in enumerate(pdf.pages, start=1):
        if not page.images:
            continue
        rendered = page.to_image(resolution=144).original.convert("RGB")
        rendered_pages[page_index] = rendered
        scale_x = rendered.width / float(page.width)
        scale_y = rendered.height / float(page.height)

        for image_info in page.images:
            bbox = (
                max(0, int(image_info["x0"] * scale_x)),
                max(0, int(image_info["top"] * scale_y)),
                min(rendered.width, int(image_info["x1"] * scale_x)),
                min(rendered.height, int(image_info["bottom"] * scale_y)),
            )
            if bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
                continue
            crop = rendered.crop(bbox)
            image_bytes = _image_to_png(crop)
            digest = hashlib.sha256(image_bytes).hexdigest()
            position_key = _position_key(
                image_info["x0"],
                image_info["top"],
                image_info["x1"],
                image_info["bottom"],
                page.width,
                page.height,
            )
            hash_counts[digest] = hash_counts.get(digest, 0) + 1
            position_counts[position_key] = position_counts.get(position_key, 0) + 1
            collected.append(
                {
                    "page": page_index,
                    "bbox_pdf": [image_info["x0"], image_info["top"], image_info["x1"], image_info["bottom"]],
                    "bbox_px": list(bbox),
                    "page_width": page.width,
                    "page_height": page.height,
                    "bytes": image_bytes,
                    "sha256": digest,
                    "position_key": position_key,
                    "mime_type": "image/png",
                    "text_chars_on_page": len(page_texts[page_index - 1].strip()),
                }
            )

    page_regions = _build_page_question_regions(pdf)
    candidates: list[dict[str, Any]] = []
    excluded = 0
    for asset in collected:
        if _looks_like_ad_or_repeated_asset(asset, hash_counts, position_counts):
            excluded += 1
            continue
        question_number = _question_for_asset(asset, page_regions)
        if not question_number:
            excluded += 1
            continue
        asset["question_number"] = question_number
        candidates.append(asset)

    report["image_filter"] = {
        "seen": len(collected),
        "kept": len(candidates),
        "excluded": excluded,
    }
    return candidates


def _attach_assets_to_questions(questions: dict[int, ParsedQuestion], assets: list[dict[str, Any]]) -> None:
    for asset in assets:
        question = questions.get(asset["question_number"])
        if not question:
            continue
        question.assets.append(asset)
        question.metadata["has_question_asset"] = True
        if question.section in ("Reasoning", "Maths"):
            question.confidence = min(question.confidence, 0.86)


def _run_llm_fallback(
    pdf: pdfplumber.PDF,
    questions: dict[int, ParsedQuestion],
    report: dict[str, Any],
    model: str,
    engine: str,
) -> None:
    report["llm"]["status"] = f"running ({engine})"
    if engine == "gemini":
        from . import db
        key = db.get_setting("gemini_api_key")
        client = GeminiClient(api_key=key or "")
    else:
        client = OllamaClient(model=model)
    available, message = client.is_available()
    report["llm"]["status"] = message
    if not available:
        for question in questions.values():
            if engine == "gemini" or _needs_llm(question):
                question.metadata["llm"] = message
                if question.section in FORCED_LLM_SECTIONS:
                    question.metadata["llm_forced_reason"] = "math_latex_conversion"
        return

    for question in questions.values():
        if engine != "gemini" and not _needs_llm(question):
            continue
        crops = _question_crops(pdf, question)
        if not crops:
            question.metadata["llm"] = "No crop could be produced for LLM fallback."
            report["llm"]["failed"] += 1
            continue
        report["llm"]["used"] += 1
        result = client.extract_question_json(
            images=crops,
            expected_question_number=question.number,
            deterministic_text=question.raw_text,
            section=question.section,
            force_latex=question.section in FORCED_LLM_SECTIONS,
        )
        if not result.ok or not result.data:
            if _apply_partial_llm_data(question, result.data, model, result.error):
                report["llm"]["partial"] += 1
            else:
                question.metadata["llm"] = result.error or "LLM fallback failed."
                if "llm_rejected" in question.metadata:
                    report["llm"]["rejected"] += 1
                else:
                    report["llm"]["failed"] += 1
                if question.parse_source != "text_parser":
                    question.parse_source = "manual_review_needed"
            continue

        data = result.data
        display_text = data["display_text"].strip()
        options = {key: data["options"][key].strip() for key in ("a", "b", "c", "d")}
        if question.section in FORCED_LLM_SECTIONS:
            display_text = _ensure_latex_delimiters(display_text)
            options = {key: _ensure_latex_delimiters(value) for key, value in options.items()}
            rejection = _llm_math_rejection_reason(question, display_text, options)
            if rejection:
                question.metadata["llm_rejected"] = {"model": model, "reason": rejection}
                report["llm"]["rejected"] += 1
                continue
        question.display_text = display_text
        question.raw_text = question.raw_text or data["display_text"].strip()
        question.options = options
        if data.get("answer") in ("a", "b", "c", "d"):
            question.answer = data["answer"]
        question.parse_source = "llm_fallback"
        question.confidence = 0.9
        question.metadata["llm"] = {"model": model, "notes": data.get("notes", "")}
        report["llm"]["succeeded"] += 1


def _apply_partial_llm_data(
    question: ParsedQuestion,
    data: dict[str, Any] | None,
    model: str,
    error: str | None,
) -> bool:
    if question.section not in FORCED_LLM_SECTIONS or not isinstance(data, dict):
        return False
    if error and ("different question" in error or "advertisement" in error or "non-question" in error):
        return False

    changed = False
    display_text = data.get("display_text")
    if isinstance(display_text, str) and display_text.strip():
        candidate_text = _ensure_latex_delimiters(display_text.strip())
        rejection = _llm_math_rejection_reason(question, candidate_text, question.options)
        if rejection:
            question.metadata["llm_rejected"] = {"model": model, "partial": True, "reason": rejection}
        else:
            question.display_text = candidate_text
            changed = True

    options = data.get("options")
    if isinstance(options, dict):
        normalized: dict[str, str] = {}
        for key, value in options.items():
            clean_key = str(key).strip().lower().strip("(). ")
            if clean_key in {"a", "b", "c", "d"} and str(value).strip():
                normalized[clean_key] = _ensure_latex_delimiters(str(value).strip())
        if set(normalized) == {"a", "b", "c", "d"} and not _llm_math_rejection_reason(question, question.display_text, normalized):
            question.options = normalized
            changed = True

    if changed:
        question.parse_source = "llm_fallback_partial"
        question.confidence = min(question.confidence, 0.82)
        question.metadata["llm"] = {"model": model, "partial": True, "validation_error": error}
    return changed


def _needs_llm(question: ParsedQuestion) -> bool:
    if question.section in FORCED_LLM_SECTIONS:
        return True
    if question.parse_source != "text_parser":
        return True
    if question.confidence < 0.75:
        return True
    text = f"{question.raw_text}\n" + "\n".join(question.options.values())
    lowered = text.lower()
    if any(marker in text for marker in BAD_TEXT_MARKERS):
        return True
    if question.section in ("Reasoning", "Maths") and any(word in lowered for word in FIGURE_WORDS) and not question.assets:
        return True
    return False


def _question_crops(pdf: pdfplumber.PDF, question: ParsedQuestion) -> list[bytes]:
    if not question.page_start:
        return []
    crops: list[bytes] = []
    page_indices = range(question.page_start, min(question.page_end or question.page_start, question.page_start + 1) + 1)
    regions = _build_page_question_regions(pdf)
    for page_number in page_indices:
        page = pdf.pages[page_number - 1]
        rendered = page.to_image(resolution=180).original.convert("RGB")
        scale_x = rendered.width / float(page.width)
        scale_y = rendered.height / float(page.height)
        region = _region_for_question(regions.get(page_number, []), question.number)
        if region:
            top = max(0, int((region["top"] - 24) * scale_y))
            bottom = min(rendered.height, int((region["bottom"] + 24) * scale_y))
        else:
            top = 0
            bottom = rendered.height
        crop = rendered.crop((0, top, rendered.width, bottom))
        crops.append(_image_to_jpeg(crop))
    return crops[:2]


def _build_page_question_regions(pdf: pdfplumber.PDF) -> dict[int, list[dict[str, Any]]]:
    regions: dict[int, list[dict[str, Any]]] = {}
    for page_number, page in enumerate(pdf.pages, start=1):
        words = page.extract_words(x_tolerance=1, y_tolerance=3) or []
        markers: list[dict[str, Any]] = []
        for word in words:
            match = QUESTION_RE.fullmatch(word.get("text", ""))
            if match:
                markers.append({"number": int(match.group(1)), "top": float(word["top"])})
        markers.sort(key=lambda item: item["top"])
        page_regions = []
        for index, marker in enumerate(markers):
            bottom = markers[index + 1]["top"] if index + 1 < len(markers) else page.height - 24
            page_regions.append({"number": marker["number"], "top": marker["top"], "bottom": bottom})
        regions[page_number] = page_regions
    return regions


def _region_for_question(regions: list[dict[str, Any]], question_number: int) -> dict[str, Any] | None:
    for region in regions:
        if region["number"] == question_number:
            return region
    return None


def _question_for_asset(asset: dict[str, Any], page_regions: dict[int, list[dict[str, Any]]]) -> int | None:
    regions = page_regions.get(asset["page"], [])
    if not regions:
        return None
    _, top, _, bottom = asset["bbox_pdf"]
    center = (top + bottom) / 2
    for region in regions:
        if region["top"] <= center <= region["bottom"]:
            return int(region["number"])
    return None


def _looks_like_ad_or_repeated_asset(
    asset: dict[str, Any],
    hash_counts: dict[str, int],
    position_counts: dict[str, int],
) -> bool:
    if hash_counts.get(asset["sha256"], 0) > 2:
        return True
    if position_counts.get(asset["position_key"], 0) > 2:
        return True
    x0, top, x1, bottom = asset["bbox_pdf"]
    width = x1 - x0
    height = bottom - top
    page_area = asset["page_width"] * asset["page_height"]
    image_area = width * height
    if top < 95:
        return True
    if image_area > page_area * 0.55:
        return True
    if asset["text_chars_on_page"] < 30 and image_area > page_area * 0.25:
        return True
    return False


def _position_key(x0: float, top: float, x1: float, bottom: float, page_width: float, page_height: float) -> str:
    width = x1 - x0
    height = bottom - top
    values = (
        round(x0 / page_width, 2),
        round(top / page_height, 2),
        round(width / page_width, 2),
        round(height / page_height, 2),
    )
    return "|".join(str(value) for value in values)


def _find_marker_pages(page_texts: list[str]) -> dict[int, int]:
    marker_pages: dict[int, int] = {}
    for page_number, text in enumerate(page_texts, start=1):
        for match in QUESTION_RE.finditer(text):
            marker_pages[int(match.group(1))] = page_number
    return marker_pages


def _confidence_for(question: str, options: dict[str, str], section: str) -> float:
    text = f"{question}\n" + "\n".join(options.values())
    confidence = 0.98
    if any(marker in text for marker in BAD_TEXT_MARKERS):
        confidence -= 0.4
    if len(question.strip()) < 12:
        confidence -= 0.25
    if section in ("Maths", "Reasoning") and any(word in text.lower() for word in FIGURE_WORDS):
        confidence -= 0.15
    return max(0.0, min(1.0, confidence))


def _to_display_text(text: str, section: str) -> str:
    text = _normalize_spacing(text)
    if section != "Maths":
        return text
    return _latexize_basic_math(text)


def _latexize_basic_math(text: str) -> str:
    # Repair old malformed fallback output before adding any new markup.
    text = re.sub(r"\$\\sqrt\{\}\$\s*([A-Za-z0-9]+)", r"$\\sqrt{\1}$", text)
    text = re.sub(r"√\s*\(?\s*([A-Za-z0-9]+)\s*\)?", r"$\\sqrt{\1}$", text)
    
    # Repair dropped backslashes from invalid LLM JSON escapes (e.g. \sqrt became sqrt)
    text = re.sub(r"(?<!\\)\b(sqrt|pi|theta|alpha|beta|gamma|Delta|Sigma|Omega|mu|nu|phi|psi|sin|cos|tan)\b", r"\\\1", text)

    text = re.sub(r"\b(\d+)\s*/\s*(\d+)\b", r"$\\frac{\1}{\2}$", text)
    text = re.sub(r"\b1\s*/\s*([A-Za-z])\b", r"$\\frac{1}{\1}$", text)
    replacements = {
        "\u03c0": r"$\pi$",
        "\u00d7": r"$\times$",
        "\u00f7": r"$\div$",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    text = _wrap_common_math_expression(text)
    return text


def _ensure_latex_delimiters(text: str) -> str:
    text = _unwrap_plain_latex_text(_latexize_basic_math(_normalize_spacing(text)))
    if "$" in text:
        return text
    if "\\" in text:
        return f"${text}$"
    return text


def _wrap_common_math_expression(text: str) -> str:
    if "$" in text:
        return text
    mathish = re.search(r"[A-Za-z0-9)]\s*[=+\-*/^]\s*[A-Za-z0-9(]", text)
    if not mathish:
        return text
    if len(text) <= 80 and not text.endswith("?"):
        return f"${text}$"
    return re.sub(
        r"([A-Za-z]\s*=\s*[A-Za-z0-9+\-*/^ ()]+)",
        lambda match: f"${match.group(1).strip()}$",
        text,
        count=1,
    )


def _llm_math_rejection_reason(
    question: ParsedQuestion,
    display_text: str,
    options: dict[str, str],
) -> str | None:
    if question.section not in FORCED_LLM_SECTIONS:
        return None

    fields = {"question": display_text, **{f"option {key}": value for key, value in options.items()}}
    for label, value in fields.items():
        issue = _latex_quality_issue(value)
        if issue:
            return f"{label}: {issue}"

    if question.raw_text:
        raw_words = _word_tokens(question.raw_text)
        display_words = _word_tokens(_plain_latex_text(display_text))
        if len(raw_words) >= 8 and len(display_words) < max(4, len(raw_words) // 3):
            return "LLM question text lost too many readable words."
    return None


def _latex_quality_issue(text: str) -> str | None:
    text = _normalize_spacing(text)
    if text.count("$") % 2:
        return "unmatched LaTeX delimiter."
    if "\\text{" in text and "$" not in text:
        return "raw \\text{} command outside math delimiters."
    compact_probe = re.sub(r"\\[A-Za-z]+|[{}$]", "", text)
    if re.search(r"[A-Za-z]{24,}", compact_probe):
        return "possible missing spaces between words."

    whole_math = re.fullmatch(r"\$(.+)\$", text, flags=re.DOTALL)
    if whole_math and _looks_like_prose_math(whole_math.group(1)):
        return "ordinary prose was wrapped as one math expression."

    for segment in re.findall(r"\$(.+?)\$", text, flags=re.DOTALL):
        if _looks_like_prose_math(segment):
            return "ordinary prose appears inside math delimiters."
    return None


def _looks_like_prose_math(segment: str) -> bool:
    words = re.findall(r"[A-Za-z]{2,}", segment.replace(r"\ ", " "))
    if "\\text" in segment and len(words) >= 3:
        return True
    if segment.count(r"\ ") >= 3 and len(words) >= 4:
        return True
    latex_names = {
        "frac",
        "sqrt",
        "pi",
        "times",
        "div",
        "theta",
        "alpha",
        "beta",
        "gamma",
        "degree",
    }
    prose_words = [word for word in words if word.lower() not in latex_names]
    return len(prose_words) >= 5


def _unwrap_plain_latex_text(text: str) -> str:
    return re.sub(r"^\\text\{([^{}]*)\}$", r"\1", text.strip())


def _plain_latex_text(text: str) -> str:
    text = re.sub(r"\\text\{([^{}]*)\}", r"\1", text)
    text = re.sub(r"\\[A-Za-z]+", " ", text)
    return text.replace("$", " ")


def _word_tokens(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9]+", text)


def _normalize_spacing(text: str) -> str:
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.replace("\r\n", "\n").split("\n")]
    return "\n".join(line for line in lines if line)


def _validate_import(questions: list[ParsedQuestion], report: dict[str, Any]) -> None:
    numbers = [question.number for question in questions]
    if numbers != list(range(1, 101)):
        report["warnings"].append("Question numbers are not exactly Q1-Q100 in order.")
    for section in SECTION_ORDER:
        count = sum(1 for question in questions if question.section == section)
        if count != 25:
            report["warnings"].append(f"{section} has {count} questions instead of 25.")
    invalid = [
        question.number
        for question in questions
        if set(question.options.keys()) != {"a", "b", "c", "d"} or question.answer not in ("a", "b", "c", "d")
    ]
    if invalid:
        report["warnings"].append(f"Questions needing review: {invalid[:20]}")


def section_for_number(number: int) -> str:
    for section, numbers in SECTIONS.items():
        if number in numbers:
            return section
    return "Unknown"


def _image_to_png(image: Image.Image) -> bytes:
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()


def _image_to_jpeg(image: Image.Image) -> bytes:
    image.thumbnail((1600, 1600))
    output = io.BytesIO()
    image.save(output, format="JPEG", quality=88, optimize=True)
    return output.getvalue()


def _question_to_dict(question: ParsedQuestion) -> dict[str, Any]:
    return {
        "number": question.number,
        "section": question.section,
        "raw_text": question.raw_text,
        "display_text": question.display_text,
        "options": question.options,
        "answer": question.answer,
        "parse_source": question.parse_source,
        "confidence": question.confidence,
        "page_start": question.page_start,
        "page_end": question.page_end,
        "metadata": question.metadata,
        "assets": [
            {
                "bytes": asset["bytes"],
                "mime_type": asset["mime_type"],
                "sha256": asset["sha256"],
                "page": asset["page"],
                "bbox_pdf": asset["bbox_pdf"],
            }
            for asset in question.assets
        ],
    }


def parsed_without_blobs(parsed: dict[str, Any]) -> dict[str, Any]:
    clean = json.loads(json.dumps(parsed, default=lambda value: "<blob>"))
    for question in clean.get("questions", []):
        for asset in question.get("assets", []):
            asset.pop("bytes", None)
    return clean
