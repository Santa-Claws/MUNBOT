"""
Ollama client, prompt construction, and word-count enforcement.

Two-model architecture:
  GENERATION_MODEL  — writes the actual content (fast, small)
  CORRECTION_MODEL  — dedicated length-enforcement pass (even smaller/faster)
"""

import os
import re
import glob

import ollama

from mun_guidelines import get_guidelines
from research import format_research_block

# ---------------------------------------------------------------------------
# Model config — swap here for deployment
# ---------------------------------------------------------------------------
GENERATION_MODEL  = "llama3.2:3b"   # primary content writer
CORRECTION_MODEL  = "llama3.2:1b"   # length enforcer only
OLLAMA_BASE_URL   = "http://localhost:11434"

# ---------------------------------------------------------------------------
# Calibration
# ---------------------------------------------------------------------------
PAPERS_DIR       = os.path.join(os.path.dirname(__file__), "position-papers")
CHARS_PER_EXAMPLE = 2000

# 261 words/page calibrated from France corpus paper (783 body words / 3 pages)
WORDS_PER_PAGE   = 261
SECTION_WEIGHTS  = [0.28, 0.20, 0.52]   # Background / UN Involvement / Policy+Solutions

# Per-section tolerance before triggering correction pass
SECTION_TOL_LOW  = 0.85
SECTION_TOL_HIGH = 1.15

# Final whole-paper tolerance after correction
FINAL_TOL_LOW    = 0.92
FINAL_TOL_HIGH   = 1.08


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

def _count_words(text: str) -> int:
    return len(text.split())


def _count_body_words(text: str) -> int:
    """Words before 'Works Cited'."""
    lower = text.lower()
    idx = lower.find("works cited")
    return _count_words(text[:idx] if idx != -1 else text)


# ---------------------------------------------------------------------------
# Ollama helpers
# ---------------------------------------------------------------------------

def _chat(model: str, messages: list[dict]) -> str:
    client = ollama.Client(host=OLLAMA_BASE_URL)
    return client.chat(model=model, messages=messages).message.content


def _gen(messages: list[dict]) -> str:
    return _chat(GENERATION_MODEL, messages)


def _fix(messages: list[dict]) -> str:
    return _chat(CORRECTION_MODEL, messages)


# ---------------------------------------------------------------------------
# Text cleanup
# ---------------------------------------------------------------------------

_MAIN_SECTION_RE  = re.compile(r'^[123]\.\s+(Background|UN Involvement|Country Policy)', re.IGNORECASE)
_SUBHEADER_RE     = re.compile(r'^[A-Z]\.\s+[A-Z]')
_NUM_SUBHEADER_RE = re.compile(r'^\d+\.\s+[A-Z][a-z]')


def _strip_markdown(text: str) -> str:
    text = re.sub(r'\*{1,3}([^*\n]+)\*{1,3}', r'\1', text)
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    lines = text.splitlines()
    cleaned = []
    for line in lines:
        s = line.strip()
        if _SUBHEADER_RE.match(s):
            continue
        if _NUM_SUBHEADER_RE.match(s) and not _MAIN_SECTION_RE.match(s):
            continue
        if re.match(r'^[\*\-]\s+', s):
            content = re.sub(r'^[\*\-]\s+', '', s)
            if cleaned and cleaned[-1].strip():
                prev = cleaned[-1].rstrip()
                sep = ', and ' if not prev.endswith('.') else ' Additionally, '
                cleaned[-1] = prev + sep + content[0].lower() + content[1:]
            else:
                cleaned.append(content)
            continue
        cleaned.append(line)
    return '\n'.join(cleaned)


def _ensure_header(text: str, section_title: str) -> str:
    """Strip stray intro lines and guarantee the section header is line 1."""
    lines = text.strip().splitlines()
    if not lines:
        return section_title
    for i, line in enumerate(lines):
        if re.match(r'^\d+\.', line.strip()):
            lines = lines[i:]
            break
    if not re.match(r'^\d+\.', lines[0].strip()):
        lines.insert(0, section_title)
    return '\n'.join(lines)


# ---------------------------------------------------------------------------
# Section definitions
# ---------------------------------------------------------------------------

SECTIONS = [
    ("1. Background",
     "the historical background and global context of the issue"),
    ("2. UN Involvement",
     "the UN's role, key resolutions, and past international actions on this issue"),
    ("3. Country Policy and Solutions",
     "the country's official position, existing policies, and proposed solutions"),
]


# ---------------------------------------------------------------------------
# Generation model: write one section
# ---------------------------------------------------------------------------

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
    example_text = "".join(f"---EXAMPLE {i+1}---\n{ex}\n\n" for i, ex in enumerate(examples))
    n_paragraphs = 2 if target_words < 180 else 3

    system = (
        f"You are an expert MUN delegate writing one section of a formal position paper.\n\n"
        f"STYLE EXAMPLES — match this tone exactly:\n{example_text}"
        f"RULES:\n"
        f"- Write ONLY the \"{section_title}\" section\n"
        f"- First line must be exactly: {section_title}\n"
        f"- Write {n_paragraphs}–4 dense prose paragraphs totaling ~{target_words} words\n"
        f"- Formal third-person policy language. No markdown, no bullets, no sub-headers.\n\n"
        f"RESEARCH CONTEXT:\n{research_block}"
    )
    user = (
        f'Write the "{section_title}" section (~{target_words} words).\n'
        f"Country: {country} | Committee: {committee} | Topic: {topic}\n"
        f"Coverage: {section_description}\n"
        f"Output ONLY the section header and body paragraphs."
    )
    text = _gen([{"role": "system", "content": system}, {"role": "user", "content": user}])
    text = _strip_markdown(text)
    return _ensure_header(text, section_title)


# ---------------------------------------------------------------------------
# Correction model: enforce word count on a section
# ---------------------------------------------------------------------------

def _correct_length(
    section_text: str,
    section_title: str,
    target_words: int,
) -> str:
    """
    Dedicated length-enforcement pass using the smaller CORRECTION_MODEL.
    Prompt is intentionally minimal — just count and adjust.
    """
    actual = _count_words(section_text)
    delta  = target_words - actual
    action = f"ADD approximately {delta} words by elaborating on existing points" \
             if delta > 0 else \
             f"REMOVE approximately {-delta} words by condensing sentences"

    system = (
        "You are a text editor. Your only job is to adjust the length of the provided "
        "MUN position paper section to hit a word count target.\n"
        "Rules:\n"
        "- Keep the section header on line 1 unchanged\n"
        "- Keep the same formal MUN tone and all factual content\n"
        "- Do NOT add bullet points, sub-headers, or markdown\n"
        "- Output ONLY the revised section text, nothing else"
    )
    user = (
        f"Target: ~{target_words} words (currently {actual} words).\n"
        f"Action: {action}.\n\n"
        f"SECTION TO ADJUST:\n{section_text}"
    )
    text = _fix([{"role": "system", "content": system}, {"role": "user", "content": user}])
    text = _strip_markdown(text)
    return _ensure_header(text, section_title)


# ---------------------------------------------------------------------------
# Works Cited (generation model)
# ---------------------------------------------------------------------------

def _generate_works_cited(sources: list[dict]) -> str:
    from datetime import date
    today = date.today().strftime("%d %b. %Y")

    sources_text = "".join(
        f"{i}. Title: {s['title']}\n   URL: {s['url']}\n   Accessed: {today}\n\n"
        for i, s in enumerate(sources[:10], 1)
    )
    system = (
        "You are a citation formatter. Output ONLY 'Works Cited' as the header, "
        "then one MLA 9th edition citation per source. "
        "Format each as: Publisher. \"Title.\" Website, Date, URL.\n"
        "No numbering, no bullets, no commentary."
    )
    user = f"Format as MLA 9th edition Works Cited:\n\n{sources_text}"
    text = _gen([{"role": "system", "content": system}, {"role": "user", "content": user}])
    text = _strip_markdown(text)
    if not re.match(r"^works cited", text.strip(), re.IGNORECASE):
        text = "Works Cited\n" + text.strip()
    return text.strip()


# ---------------------------------------------------------------------------
# Deterministic sentence trimmer (hard fallback for over-long text)
# ---------------------------------------------------------------------------

def _trim_sentences(text: str, target: int) -> str:
    """Remove sentences from the end of paragraphs until at/under target words."""
    # Split into paragraphs, trim sentences from the longest one first
    paras = [p for p in text.split('\n') if p.strip()]
    while _count_words('\n'.join(paras)) > int(target * 1.03):
        # Find the longest paragraph (skip the section header line)
        longest_i = max(
            (i for i, p in enumerate(paras) if not re.match(r'^\d+\.', p.strip())),
            key=lambda i: _count_words(paras[i]),
            default=None,
        )
        if longest_i is None:
            break
        sentences = re.split(r'(?<=[.!?])\s+', paras[longest_i].strip())
        if len(sentences) <= 1:
            break
        sentences.pop()   # remove last sentence
        paras[longest_i] = ' '.join(sentences)
    return '\n'.join(paras)


# ---------------------------------------------------------------------------
# Final whole-paper length correction (iterative, uses 3b model)
# ---------------------------------------------------------------------------

def _correct_paper_length(paper_text: str, target_total: int, emit) -> str:
    """
    Iterative final pass: up to 3 attempts with the generation model,
    then deterministic sentence trimming as hard fallback.
    """
    lower  = paper_text.lower()
    wc_idx = lower.find("works cited")
    wc_part = paper_text[wc_idx:].strip() if wc_idx != -1 else ""

    def _get_body():
        lo = paper_text.lower()
        ix = lo.find("works cited")
        return paper_text[:ix].strip() if ix != -1 else paper_text.strip()

    section_pattern = re.compile(
        r'(\d+\. (?:Background|UN Involvement|Country Policy[^\n]*))',
        re.IGNORECASE,
    )

    for attempt in range(3):
        body   = _get_body()
        actual = _count_words(body)
        low    = int(target_total * FINAL_TOL_LOW)
        high   = int(target_total * FINAL_TOL_HIGH)

        if low <= actual <= high:
            break   # within tolerance

        # Find section spans
        matches = list(section_pattern.finditer(body))
        if not matches:
            break

        spans = []
        for j, m in enumerate(matches):
            s = m.start()
            e = matches[j + 1].start() if j + 1 < len(matches) else len(body)
            spans.append((s, e, m.group(1)))

        # Over target → trim the biggest section
        # Under target → expand the smallest section
        over = actual > high
        target_span = (
            max(spans, key=lambda sp: _count_words(body[sp[0]:sp[1]]))
            if over else
            min(spans, key=lambda sp: _count_words(body[sp[0]:sp[1]]))
        )
        start, end, title = target_span
        sec_text   = body[start:end].strip()
        sec_actual = _count_words(sec_text)
        sec_target = sec_actual + (target_total - actual)

        emit(f"[4/5] Length pass {attempt+1} ({actual}→{target_total} words, "
             f"{'trimming' if over else 'expanding'} '{title}')…")

        # Use 3b generation model for better instruction following
        action = (
            f"SHORTEN by removing ~{actual - target_total} words total from this section"
            if over else
            f"EXPAND by adding ~{target_total - actual} words of relevant detail to this section"
        )
        system = (
            "You are editing one section of an MUN position paper for length.\n"
            "Rules:\n"
            "- Keep the section header on line 1 unchanged\n"
            "- Keep formal MUN tone; preserve all factual content when trimming\n"
            "- No bullet points, no markdown\n"
            "- Output ONLY the revised section, nothing else"
        )
        user = (
            f"Target for this section: ~{sec_target} words (currently {sec_actual}).\n"
            f"{action}.\n\nSECTION:\n{sec_text}"
        )
        fixed = _gen([{"role": "system", "content": system},
                      {"role": "user", "content": user}])
        fixed = _strip_markdown(fixed)
        fixed = _ensure_header(fixed, title)

        body_new = body[:start] + fixed + "\n" + body[end:]
        paper_text = body_new.strip() + ("\n\n" + wc_part if wc_part else "")

    # Hard fallback: if still over, deterministically trim sentences
    body   = _get_body()
    actual = _count_words(body)
    if actual > int(target_total * FINAL_TOL_HIGH):
        emit(f"[4/5] Hard trim ({actual}→{target_total} words)…")
        trimmed = _trim_sentences(body, target_total)
        paper_text = trimmed.strip() + ("\n\n" + wc_part if wc_part else "")

    return paper_text


# ---------------------------------------------------------------------------
# Main entry point
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
    target_total   = pages * WORDS_PER_PAGE

    _emit("[2/5] Loading style examples from corpus…")
    examples = _select_examples(topic, country)

    _emit("[3/5] Building prompt…")
    research_block = format_research_block(sources)

    section_targets = [int(target_total * w) for w in SECTION_WEIGHTS]
    sections        = []
    labels          = ["Background", "UN Involvement", "Country Policy and Solutions"]

    for i, (title, description) in enumerate(SECTIONS):
        _emit(f"[4/5] Generating section {i+1}/3: {labels[i]}…")
        sec = _generate_section(
            title, description, topic, country, committee_line,
            section_targets[i], research_block, examples,
        )

        # Per-section length check → correction model
        sec_words = _count_words(sec)
        low  = int(section_targets[i] * SECTION_TOL_LOW)
        high = int(section_targets[i] * SECTION_TOL_HIGH)
        if not (low <= sec_words <= high):
            _emit(f"[4/5] Correcting section {i+1} ({sec_words}→{section_targets[i]} words)…")
            sec = _correct_length(sec, title, section_targets[i])

        sections.append(sec)

    _emit("[4/5] Generating Works Cited…")
    works_cited = _generate_works_cited(sources)

    paper_text = (
        f"{committee_line}\n{country}\n\n"
        + "\n\n".join(sections)
        + "\n\n"
        + works_cited
    )

    # Final whole-paper length enforcement
    paper_text = _correct_paper_length(paper_text, target_total, _emit)

    return paper_text
