from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass
class OllamaResult:
    ok: bool
    data: dict[str, Any] | None = None
    error: str | None = None


class OllamaClient:
    def __init__(self, model: str = "gemma", host: str = "http://127.0.0.1:11434") -> None:
        self.model = model
        self.host = host.rstrip("/")

    def is_available(self) -> tuple[bool, str]:
        try:
            with urllib.request.urlopen(f"{self.host}/api/tags", timeout=2) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (OSError, urllib.error.URLError, TimeoutError) as exc:
            return False, f"Ollama is not reachable: {exc}"
        except json.JSONDecodeError:
            return False, "Ollama responded, but the response was not valid JSON."

        models = {item.get("name") for item in payload.get("models", [])}
        if self.model not in models and f"{self.model}:latest" not in models:
            return False, f"Ollama is running, but {self.model} is not pulled."
        return True, f"{self.model} is ready."

    def extract_question_json(
        self,
        images: list[bytes],
        expected_question_number: int | None = None,
        deterministic_text: str = "",
        section: str | None = None,
        force_latex: bool = False,
    ) -> OllamaResult:
        available, message = self.is_available()
        if not available:
            return OllamaResult(False, error=message)

        prompt = self._build_prompt(expected_question_number, deterministic_text, section, force_latex)
        encoded_images = [base64.b64encode(image).decode("ascii") for image in images]
        payload = {
            "model": self.model,
            "prompt": prompt,
            "images": encoded_images,
            "format": "json",
            "stream": False,
            "options": {"temperature": 0},
        }

        request = urllib.request.Request(
            f"{self.host}/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                raw = response.read().decode("utf-8")
        except (OSError, urllib.error.URLError, TimeoutError) as exc:
            return OllamaResult(False, error=f"Ollama request failed: {exc}")

        try:
            response_payload = json.loads(raw)
            model_text = response_payload.get("response", "{}")
            
            # Repair valid JSON escapes that were actually meant as LaTeX commands by the LLM
            # For example, \frac becomes \f (form feed) and \text becomes \t (tab) if not double-escaped.
            model_text = model_text.replace("\\f", "\\\\f")
            model_text = model_text.replace("\\t", "\\\\t")
            model_text = model_text.replace("\\n", "\\\\n")
            model_text = model_text.replace("\\r", "\\\\r")
            model_text = model_text.replace("\\b", "\\\\b")
            
            data = json.loads(model_text)
        except json.JSONDecodeError as exc:
            return OllamaResult(False, error=f"Ollama returned invalid JSON: {exc}")

        error = self._validate_data(data, expected_question_number)
        if error:
            return OllamaResult(False, data=data, error=error)
        return OllamaResult(True, data=data)

    def classify_image(self, image: bytes) -> OllamaResult:
        available, message = self.is_available()
        if not available:
            return OllamaResult(False, error=message)

        payload = {
            "model": self.model,
            "prompt": (
                "Classify this PDF image crop for an exam parser. "
                "Return strict JSON only: "
                "{\"kind\":\"question_content|advertisement|header_logo|watermark|other\","
                "\"confidence\":0.0,\"reason\":\"short\"}."
            ),
            "images": [base64.b64encode(image).decode("ascii")],
            "format": "json",
            "stream": False,
            "options": {"temperature": 0},
        }
        request = urllib.request.Request(
            f"{self.host}/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                raw = response.read().decode("utf-8")
            response_payload = json.loads(raw)
            return OllamaResult(True, data=json.loads(response_payload.get("response", "{}")))
        except Exception as exc:  # Ollama/image classification is optional.
            return OllamaResult(False, error=str(exc))

    def _build_prompt(
        self,
        expected_question_number: int | None,
        deterministic_text: str,
        section: str | None,
        force_latex: bool,
    ) -> str:
        question_hint = (
            f"The expected question number is {expected_question_number}. "
            if expected_question_number is not None
            else ""
        )
        section_hint = f"The section is {section}. " if section else ""
        latex_hint = (
            "This is a Maths question and LaTeX conversion is mandatory. "
            "Read the rendered image crop first; use the deterministic text only as a hint because PDF text extraction may split equations incorrectly. "
            "Convert mathematical expressions, equations, fractions, exponents, roots, coordinates, formulas, and symbolic operations into KaTeX-compatible LaTeX using $...$ or $$...$$. "
            "For roots, write $\\sqrt{11}$, never $\\sqrt{}$11. "
            "For fractions, write $\\frac{1}{x}$, never 1/x when it is part of a formula. "
            "Keep ordinary words outside math delimiters; never wrap a full English sentence in $...$ or \\text{...}. "
            "Do not escape normal spaces with backslashes. "
            "Good examples: If $x = \\sqrt{11}$, determine $x + \\frac{1}{x}$. "
            "Write ratios and percentages as normal text unless they are inside a formula. "
            "Other examples: $\\frac{22}{7}$, $y = mx + 7$, $(2, 13)$, $3 + 2.8 - 1.5$, $\\pi r^2$. "
            if force_latex
            else ""
        )
        deterministic_hint = (
            "The deterministic text parser saw this partial text:\n"
            f"{deterministic_text[:2500]}\n\n"
            if deterministic_text
            else ""
        )
        return (
            "You are extracting one SSC MCQ question from a PDF crop. "
            "Ignore institute ads, logos, watermarks, and promotional content. "
            f"{question_hint}"
            f"{section_hint}"
            f"{latex_hint}"
            f"{deterministic_hint}"
            "Return strict JSON only with this shape: "
            "{"
            "\"question_number\": number, "
            "\"display_text\": \"question text, using LaTeX delimiters $...$ or $$...$$ for math where useful\", "
            "\"options\": {\"a\":\"...\",\"b\":\"...\",\"c\":\"...\",\"d\":\"...\"}, "
            "\"answer\": \"a|b|c|d|null\", "
            "\"needs_image\": true, "
            "\"contains_ad\": false, "
            "\"notes\": \"short note\""
            "}. "
            "The display_text must contain only the question stem, not answer options or the answer marker. "
            "Each option value must contain only that option's text, not text from other options. "
            "Do not solve the question. Use the answer marker only if it is visible in the crop. "
            "If the crop is not a question, set contains_ad true and options to empty strings."
        )

    def _validate_data(self, data: dict[str, Any], expected_question_number: int | None) -> str | None:
        if not isinstance(data, dict):
            return "LLM output is not an object."
        if data.get("contains_ad") is True:
            return "LLM classified the crop as advertisement/non-question."
        question_number = data.get("question_number")
        if isinstance(question_number, str):
            question_number = question_number.strip().lower().removeprefix("q").strip(". ")
        try:
            question_number = int(question_number)
        except (TypeError, ValueError):
            return "LLM returned an invalid question number."
        if expected_question_number is not None and question_number != expected_question_number:
            return "LLM returned a different question number."
        options = data.get("options")
        if not isinstance(options, dict):
            return "LLM did not return exactly four options."
        normalized_options: dict[str, str] = {}
        for key, value in options.items():
            clean_key = str(key).strip().lower().strip("(). ")
            if clean_key in {"a", "b", "c", "d"}:
                normalized_options[clean_key] = str(value).strip()
        data["options"] = normalized_options
        if set(normalized_options.keys()) != {"a", "b", "c", "d"}:
            return "LLM did not return exactly four options."
        if not all(normalized_options[key] for key in ("a", "b", "c", "d")):
            return "LLM returned blank options."
        answer = data.get("answer")
        if isinstance(answer, str):
            answer = answer.strip().lower().strip("(). ")
            if "|" in answer:
                answer = answer.split("|")[0].strip()
        if answer == "null" or answer == "":
            answer = None
        data["answer"] = answer
        if answer not in ("a", "b", "c", "d", None):
            return "LLM returned an invalid answer marker."
        if not isinstance(data.get("display_text"), str) or not data["display_text"].strip():
            return "LLM returned blank question text."
        return None
