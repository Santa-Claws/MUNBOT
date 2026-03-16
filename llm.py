"""
Ollama client, prompt construction, and word-count enforcement.
Section-by-section generation for reliable formatting with small LLMs.
"""

import os
import re
import glob

import ollama

from mun_guidelines import get_guidelines
from research import format_research_block

OLLAMA_MODEL = "llama3.1:8b"
OLLAMA_BASE_URL = "http://localhost:11434"

PAPERS_DIR = os.path.join(os.path.dirname(__file__), "position-papers")
CHARS_PER_EXAMPLE = 2000

# Calibrated to France corpus paper: 783 body words / 3 pages = 261 w/page.
# Section split: Background 28%, UN Involvement 20%, Policy+Solutions 52%
WORDS_PER_PAGE = 261
SECTION_WEIGHTS = [0.28, 0.20, 0.52]   # must sum to 1.0

TOLERANCE_LOW = 0.88
TOLERANCE_HIGH = 1.12


# ---------------------------------------------------------------------------
# Few-shot example selection
# ---------------------------------------------------------------------------

def _load_papers() -> list[tuple[str, str]]:
    papers = []
    for path in glob.glob(os.path.join(PAPERS_DIR, "*.txt")):
        try:
            with open(path, encoding="utf-8", errors="ignore") as f:
                papers.append((os.path.basename(path), f.read()))
        except Exception:
            pass
    return papers


def _score_paper(content: str, keywords: list[str]) -> int:
    lower = content.lower()
    return sum(1 for kw in keywords if kw.lower() in lower)


def _select_examples(topic: str, country: str, n: int = 2) -> list[str]:
    papers = _load_papers()
    if not papers:
        return []
    keywords = topic.split() + country.split()
    scored = sorted(papers, key=lambda p: _score_paper(p[1], keywords), reverse=True)
    return [content[:CHARS_PER_EXAMPLE] for _, content in scored[:n]]


# ---------------------------------------------------------------------------
# Word counting
# ---------------------------------------------------------------------------

def _count_body_words(text: str) -> int:
    lower = text.lower()
    idx = lower.find("works cited")
    body = text[:idx] if idx != -1 else text
    return len(body.split())


def _count_words(text: str) -> int:
    return len(text.split())


# ---------------------------------------------------------------------------
# Ollama call
# ---------------------------------------------------------------------------

def _chat(messages: list[dict]) -> str:
    client = ollama.Client(host=OLLAMA_BASE_URL)
    response = client.chat(model=OLLAMA_MODEL, messages=messages)
    return response.message.content


# ---------------------------------------------------------------------------
# Section generation
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Text cleanup
# ---------------------------------------------------------------------------

_MAIN_SECTION_RE = re.compile(r'^[123]\.\s+(Background|UN Involvement|Country Policy)', re.IGNORECASE)
_SUBHEADER_RE = re.compile(r'^[A-Z]\.\s+[A-Z]')           # "A. Title"
_NUM_SUBHEADER_RE = re.compile(r'^\d+\.\s+[A-Z][a-z]')    # "2. Some subtitle" (not main sections)


def _strip_markdown(text: str) -> str:
    """Remove markdown and structural noise from LLM output."""
    # Remove bold/italic markers
    text = re.sub(r'\*{1,3}([^*\n]+)\*{1,3}', r'\1', text)
    # Remove hash headers
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)

    lines = text.splitlines()
    cleaned = []
    for line in lines:
        stripped = line.strip()

        # Skip lettered sub-headers (A. Title, B. Title...)
        if _SUBHEADER_RE.match(stripped):
            continue

        # Skip numbered sub-headers that aren't the 3 main sections
        if _NUM_SUBHEADER_RE.match(stripped) and not _MAIN_SECTION_RE.match(stripped):
            continue

        # Convert bullet/list lines into prose appended to previous paragraph
        if re.match(r'^[\*\-]\s+', stripped):
            content = re.sub(r'^[\*\-]\s+', '', stripped)
            if cleaned and cleaned[-1].strip():
                prev = cleaned[-1].rstrip()
                sep = ', and ' if not prev.endswith('.') else ' Additionally, '
                cleaned[-1] = prev + sep + content[0].lower() + content[1:]
            else:
                cleaned.append(content)
            continue

        cleaned.append(line)

    return '\n'.join(cleaned)


SECTIONS = [
    ("1. Background", "background history and global context of the issue"),
    ("2. UN Involvement", "the UN's role, resolutions, and past international actions on this issue"),
    ("3. Country Policy and Solutions", "the country's position, policies, and proposed solutions"),
]


def _generate_section(
    section_title: str,
    section_description: str,
    topic: str,
    country: str,
    committee: str,
    target_words: int,
    research_block: str,
    examples: list[str],
) -> str:
    """Generate a single section and return its text (header + paragraphs)."""
    guidelines = get_guidelines()

    example_text = ""
    for i, ex in enumerate(examples, 1):
        example_text += f"---EXAMPLE {i}---\n{ex}\n\n"

    system = f"""You are an expert MUN delegate writing one section of a formal position paper.

MUN STYLE EXAMPLES (match this tone and density exactly):
{example_text}
RULES:
- Write ONLY the section titled "{section_title}" — nothing else
- Start with the header "{section_title}" on its own line
- Follow with {2 if target_words < 200 else 3}–4 dense prose paragraphs totaling ~{target_words} words
- Formal, third-person, policy-focused language
- No bullet points, no sub-headers, no markdown
- Use facts from the research context below

RESEARCH CONTEXT:
{research_block}"""

    user = (
        f'Write the "{section_title}" section (~{target_words} words) for a position paper on:\n'
        f"Country: {country}\n"
        f"Committee: {committee}\n"
        f"Topic: {topic}\n"
        f"This section covers: {section_description}.\n"
        f"Output ONLY the section header and paragraphs. No introduction, no other sections."
    )

    text = _chat([
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ])
    text = _strip_markdown(text)

    # Ensure the section header is present and clean
    lines = text.strip().splitlines()
    if not lines:
        return f"{section_title}\n"

    # Strip any stray intro lines before the header
    for i, line in enumerate(lines):
        if re.match(r"^\d+\.", line.strip()):
            lines = lines[i:]
            break

    # If header is missing, prepend it
    if not re.match(r"^\d+\.", lines[0].strip()):
        lines.insert(0, section_title)

    return "\n".join(lines)


def _generate_works_cited(sources: list[dict]) -> str:
    """
    Generate a Works Cited section from the raw source dicts.
    Falls back to a best-effort MLA format if the LLM fails.
    """
    from datetime import date
    today = date.today().strftime("%d %b. %Y")

    system = (
        "You are a citation formatter. For each source provided, output exactly one "
        "MLA 9th edition citation. Format: Publisher. \"Title.\" Website, Date, URL.\n"
        "Output ONLY the header 'Works Cited' followed by one citation per line. "
        "No numbering, no bullet points, no extra commentary."
    )

    sources_text = ""
    for i, s in enumerate(sources[:10], 1):
        sources_text += f"{i}. Title: {s['title']}\n   URL: {s['url']}\n   Accessed: {today}\n\n"

    user = f"Format these as MLA 9th edition Works Cited entries:\n\n{sources_text}"

    text = _chat([
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ])
    text = _strip_markdown(text)

    if not re.match(r"^works cited", text.strip(), re.IGNORECASE):
        text = "Works Cited\n" + text.strip()
    return text.strip()


# ---------------------------------------------------------------------------
# Word-count correction for a single section
# ---------------------------------------------------------------------------

def _correct_section(
    section_text: str,
    section_title: str,
    target_words: int,
    topic: str,
    country: str,
    committee: str,
    research_block: str,
    examples: list[str],
) -> str:
    actual = _count_words(section_text)
    direction = "expand" if actual < target_words else "trim"
    guidelines = get_guidelines()
    example_text = "".join(f"---EXAMPLE {i+1}---\n{ex}\n\n" for i, ex in enumerate(examples))

    system = f"""You are rewriting one section of an MUN position paper.
MUN STYLE EXAMPLES:
{example_text}
RESEARCH CONTEXT:
{research_block}"""

    user = (
        f'Rewrite this "{section_title}" section so it is ~{target_words} words '
        f"(currently {actual} words). {direction.capitalize()} the content proportionally. "
        f"Output ONLY the section header and paragraphs.\n\n"
        f"CURRENT TEXT:\n{section_text}"
    )
    text = _chat([
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ])
    return _strip_markdown(text).strip()


# ---------------------------------------------------------------------------
# Main generation entry point
# ---------------------------------------------------------------------------

def generate_paper(
    topic: str,
    country: str,
    committee: str,
    pages: int,
    sources: list[dict],
    progress_cb=None,
) -> str:
    def _emit(msg: str):
        if progress_cb:
            progress_cb(msg)

    committee_line = committee.strip() if committee.strip() else "United Nations General Assembly"
    target_total = pages * WORDS_PER_PAGE

    # Step 2
    _emit("[2/5] Loading style examples from corpus…")
    examples = _select_examples(topic, country)

    # Step 3
    _emit("[3/5] Building prompt…")
    research_block = format_research_block(sources)

    # Step 4: generate each section
    _emit("[4/5] Generating section 1/3: Background…")
    section_targets = [int(target_total * w) for w in SECTION_WEIGHTS]

    sections = []
    section_labels = ["Background", "UN Involvement", "Country Policy and Solutions"]
    for i, (title, description) in enumerate(SECTIONS):
        if i > 0:
            _emit(f"[4/5] Generating section {i+1}/3: {section_labels[i]}…")
        sec_text = _generate_section(
            title, description, topic, country, committee_line,
            section_targets[i], research_block, examples,
        )
        # Word-count check per section
        sec_words = _count_words(sec_text)
        low = int(section_targets[i] * TOLERANCE_LOW)
        high = int(section_targets[i] * TOLERANCE_HIGH)
        if not (low <= sec_words <= high):
            _emit(f"[4/5] Correcting section {i+1} ({sec_words}→{section_targets[i]} words)…")
            sec_text = _correct_section(
                sec_text, title, section_targets[i],
                topic, country, committee_line, research_block, examples,
            )
        sections.append(sec_text)

    # Step 4e: Works Cited
    _emit("[4/5] Generating Works Cited…")
    works_cited = _generate_works_cited(sources)

    # Assemble
    paper_text = (
        f"{committee_line}\n{country}\n\n"
        + "\n\n".join(sections)
        + "\n\n"
        + works_cited
    )

    return paper_text
