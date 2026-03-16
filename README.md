# MUNBOT — MUN Position Paper Generator

A web app that generates Model UN position papers using a local LLM (Ollama), real-time web research, and your own position papers as style examples.

## Features

- **Web research** — runs 4 DuckDuckGo searches per generation and scrapes top sources for up-to-date facts
- **Few-shot style matching** — scores your existing position papers for relevance and uses the top 2 as style examples
- **Local LLM** — runs entirely on your machine via Ollama (no API keys, no data sent to the cloud)
- **Word-count enforcement** — automatically corrects papers that miss the target length
- **Proper `.docx` export** — Times New Roman 12pt, double-spaced, 1-inch margins, hanging indent on Works Cited

## Requirements

- Python 3.10+
- [Ollama](https://ollama.com) with `llama3.1:8b` pulled

## Setup

```bash
git clone https://github.com/Santa-Claws/MUNBOT.git
cd MUNBOT

pip install -r requirements.txt

# Install and start Ollama, then pull the model
ollama pull llama3.1:8b
ollama serve
```

Add your own `.txt` position papers to `position-papers/` — they are used as style examples and picked up automatically with no code changes needed.

## Running

```bash
uvicorn main:app --reload
```

Open `http://localhost:8000` in your browser.

## Usage

1. Enter a **topic**, **country**, optional **committee**, and **page count** (1–5)
2. Click **Generate Position Paper**
3. Watch the live progress log as the app researches, generates, and formats the paper
4. Download the `.docx` when ready

## Output Format

Generated papers follow standard MUN formatting:
- Committee and country as the header
- Three sections: Background, UN Involvement, Country Policy and Solutions
- MLA 9th edition Works Cited (not counted toward page length)

## File Structure

```
MUNBOT/
├── position-papers/     # Drop .txt papers here — auto-used as style examples
├── main.py              # FastAPI app and SSE streaming
├── research.py          # DuckDuckGo search + scraping
├── llm.py               # Ollama prompting and word-count enforcement
├── docx_writer.py       # .docx formatting
├── mun_guidelines.py    # MUN writing guide scraper (runs at startup)
├── templates/
│   └── index.html       # Frontend
└── generated/           # Output .docx files (gitignored)
```

## Configuration

At the top of `llm.py`:

```python
OLLAMA_MODEL = "llama3.1:8b"      # swap for any Ollama model
OLLAMA_BASE_URL = "http://localhost:11434"
```
