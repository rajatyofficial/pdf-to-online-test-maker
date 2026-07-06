# Local MCQ Test Maker

A local-first web app for importing same-structure SSC MCQ PDFs, storing tests in SQLite, and attempting them in test, practice, or section-sprint mode.

## Run

```powershell
.\run_app.ps1
```

Then open:

```text
http://127.0.0.1:8765
```

## LLM Fallback (Vision & Parsing)

The deterministic PDF parser runs first. If a question is malformed, contains complex math (LaTeX), or likely needs visual help, the app can call a vision-capable LLM to repair and extract it.

You can choose between **Local (Ollama)** or **Cloud (Google Gemini)** in the app during import.

### Option 1: Local Ollama (Offline)

Runs completely offline on your own hardware. 

Recommended setup:

```powershell
ollama pull qwen2.5vl:3b
```

### Option 2: Google Gemini (Cloud)

If you don't have a powerful GPU or want faster processing, you can use the Google Gemini API (`gemini-2.5-flash`).

1. Get a Gemini API key from [Google AI Studio](https://aistudio.google.com/).
2. In the app, click **Settings** (gear icon) and save your API key.
3. During PDF import or Maths rebuild, select **Gemini** as the LLM Engine.

*Note: If no LLM is available or configured, clean text PDFs still import. Uncertain questions are simply marked for manual review.*

## Data

Persistent data is stored locally in:

```text
data/app.sqlite
```
