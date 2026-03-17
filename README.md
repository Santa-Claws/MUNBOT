# MUNBOT — MUN Position Paper Generator

A web app that generates Model UN position papers using a local LLM (Ollama), real-time web research, and your own position papers as style examples.

## Features

- **Web research** — runs 4 DuckDuckGo searches per generation and scrapes top sources for up-to-date facts
- **Few-shot style matching** — scores your existing position papers for relevance and uses the top 2 as style examples
- **Local LLM** — runs entirely on your machine via Ollama (no API keys, no data sent to the cloud)
- **Two-model architecture** — a fast generation model writes the content; a dedicated smaller model handles length correction
- **Iterative word-count enforcement** — per-section correction, full-paper iterative passes, and a deterministic sentence trimmer as a hard fallback
- **Accurate page lengths** — calibrated to 230 words/page from actual docx rendering (body only, Works Cited never counts); validated across all 5 page specs (1–5 pages) with mean errors within ±5%
- **Proper `.docx` export** — Times New Roman 12pt, double-spaced, 1-inch margins, hanging indent on Works Cited

## Requirements

- Python 3.10+
- [Ollama](https://ollama.com) with the models below pulled

## Setup

```bash
git clone https://github.com/Santa-Claws/MUNBOT.git
cd MUNBOT

pip install -r requirements.txt

# Install and start Ollama, then pull the models
ollama pull llama3.2:3b   # generation model
ollama pull llama3.2:1b   # length correction model
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
- Committee and country as the header (no labels)
- Three sections: `1. Background`, `2. UN Involvement`, `3. Country Policy and Solutions`
- MLA 9th edition Works Cited (not counted toward page length)

## How Word Count Works

The target is **230 words per page** (body only), calibrated empirically from actual `.docx` rendering in LibreOffice/Word — not from raw word counts, which overestimate capacity by ~12% due to header lines and paragraph-break waste. Length is enforced in three layers:

1. **Per-section correction** — after each section is generated, the 1b model trims or expands it to hit its individual target
2. **Final iterative pass** — up to 3 attempts using the 3b model to bring the whole paper into the 92–108% tolerance band
3. **Hard fallback** — if still over, sentences are deterministically removed from the longest paragraph until within range

## Configuration

At the top of `llm.py`:

```python
GENERATION_MODEL = "llama3.2:3b"   # primary content writer
CORRECTION_MODEL = "llama3.2:1b"   # length enforcer
OLLAMA_BASE_URL  = "http://localhost:11434"
```

Swap either model for any model you have pulled in Ollama. For deployment on better hardware, larger models (e.g. `llama3.1:8b`, `llama3.3:70b`) will produce higher quality output.

## Calibration Results

Word-count calibration was run across 25 tests (5 per page spec, 1–5 pages) using varied topics and countries. All 5 page specs converged to **WORDS_PER_PAGE = 230** on the first calibration round.

| Page spec | Target words | Mean actual | Mean error |
|-----------|-------------|-------------|------------|
| 1 page    | 230         | 232         | +0.9%      |
| 2 pages   | 460         | 451         | -2.0%      |
| 3 pages   | 690         | 686         | -0.6%      |
| 4 pages   | 920         | 904         | -1.7%      |
| 5 pages   | 1150        | 1136        | -1.2%      |

Graphs and raw data are in `calibration/`. The calibration script (`calibrate.py`) can be re-run any time with `python calibrate.py --stub-research`.

## File Structure

```
MUNBOT/
├── position-papers/     # Drop .txt papers here — auto-used as style examples
├── calibration/         # Calibration graphs and JSON results
├── main.py              # FastAPI app and SSE streaming
├── research.py          # DuckDuckGo search + scraping
├── llm.py               # Two-model generation, length enforcement
├── docx_writer.py       # .docx formatting
├── mun_guidelines.py    # MUN writing guide scraper (runs at startup)
├── calibrate.py         # Word-count calibration test suite
├── templates/
│   └── index.html       # Frontend
└── generated/           # Output .docx files (gitignored)
```
