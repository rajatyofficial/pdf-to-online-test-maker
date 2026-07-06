from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
from typing import Any

from .ollama_client import OllamaResult


class GeminiClient:
    def __init__(self, api_key: str, model: str = "gemini-1.5-flash") -> None:
        self.api_key = api_key
        self.model = model
        self.host = "https://generativelanguage.googleapis.com/v1beta/models"

    def is_available(self) -> tuple[bool, str]:
        if not self.api_key:
            return False, "Gemini API key is missing. Please add it in Settings."
        return True, "Gemini API is ready."

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

        # Import _build_prompt from OllamaClient so we don't have to duplicate the massive prompt string
        # We can just instantiate OllamaClient to get the prompt
        from .ollama_client import OllamaClient
        prompt = OllamaClient()._build_prompt(expected_question_number, deterministic_text, section, force_latex)

        parts = [{"text": prompt}]
        for image in images:
            encoded = base64.b64encode(image).decode("ascii")
            parts.append({
                "inline_data": {
                    "mime_type": "image/jpeg",
                    "data": encoded
                }
            })

        payload = {
            "contents": [{"parts": parts}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": 0.0,
            }
        }

        request = urllib.request.Request(
            f"{self.host}/{self.model}:generateContent?key={self.api_key}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode("utf-8")
            return OllamaResult(False, error=f"Gemini API error ({exc.code}): {err_body}")
        except (OSError, urllib.error.URLError, TimeoutError) as exc:
            return OllamaResult(False, error=f"Gemini request failed: {exc}")

        try:
            response_payload = json.loads(raw)
            candidates = response_payload.get("candidates", [])
            if not candidates:
                return OllamaResult(False, error="Gemini returned no candidates.")
            
            content = candidates[0].get("content", {})
            parts = content.get("parts", [])
            if not parts:
                return OllamaResult(False, error="Gemini returned empty content parts.")
            
            model_text = parts[0].get("text", "{}")
            
            # Repair valid JSON escapes that were actually meant as LaTeX commands by the LLM
            model_text = model_text.replace("\\f", "\\\\f")
            model_text = model_text.replace("\\t", "\\\\t")
            model_text = model_text.replace("\\n", "\\\\n")
            model_text = model_text.replace("\\r", "\\\\r")
            model_text = model_text.replace("\\b", "\\\\b")
            
            data = json.loads(model_text)
        except json.JSONDecodeError as exc:
            return OllamaResult(False, error=f"Gemini returned invalid JSON: {exc}")

        error = OllamaClient()._validate_data(data, expected_question_number)
        if error:
            return OllamaResult(False, data=data, error=error)
        return OllamaResult(True, data=data)

    def classify_image(self, image: bytes) -> OllamaResult:
        available, message = self.is_available()
        if not available:
            return OllamaResult(False, error=message)

        from .ollama_client import OllamaClient
        
        parts = [
            {"text": "Does this image crop contain the start of an MCQ question? Answer exactly 'yes' or 'no' in strict JSON format: {\"is_question\": true/false}. It must include the question number and text."},
            {
                "inline_data": {
                    "mime_type": "image/jpeg",
                    "data": base64.b64encode(image).decode("ascii")
                }
            }
        ]

        payload = {
            "contents": [{"parts": parts}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": 0.0,
            }
        }

        request = urllib.request.Request(
            f"{self.host}/{self.model}:generateContent?key={self.api_key}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read().decode("utf-8")
        except (OSError, urllib.error.URLError, TimeoutError) as exc:
            return OllamaResult(False, error=f"Gemini request failed: {exc}")

        try:
            response_payload = json.loads(raw)
            candidates = response_payload.get("candidates", [])
            if not candidates:
                return OllamaResult(False, error="Gemini returned no candidates.")
            
            model_text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "{}")
            data = json.loads(model_text)
            return OllamaResult(True, data=data)
        except json.JSONDecodeError as exc:
            return OllamaResult(False, error=f"Gemini returned invalid JSON: {exc}")
