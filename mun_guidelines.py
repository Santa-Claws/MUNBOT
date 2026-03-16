"""
Scrape and cache MUN writing guidelines at app startup.
"""

import requests
from bs4 import BeautifulSoup

_cached_guidelines: str = ""

GUIDE_URLS = [
    "https://bestdelegate.com/how-to-write-a-position-paper/",
    "https://www.unausa.org/model-un/how-to-prepare/writing-a-position-paper",
]

DDGS_QUERY = '"how to write MUN position paper" guide'


def _scrape_url(url: str, max_chars: int = 1000) -> str:
    try:
        resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        soup = BeautifulSoup(resp.text, "lxml")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        text = soup.get_text(separator=" ", strip=True)
        return text[:max_chars]
    except Exception:
        return ""


def _scrape_pdf(url: str, max_pages: int = 3, max_chars: int = 1000) -> str:
    try:
        import io
        import PyPDF2

        resp = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        reader = PyPDF2.PdfReader(io.BytesIO(resp.content))
        text = ""
        for i, page in enumerate(reader.pages):
            if i >= max_pages:
                break
            text += page.extract_text() or ""
        return text[:max_chars]
    except Exception:
        return ""


def load_guidelines() -> None:
    global _cached_guidelines
    parts = []

    for url in GUIDE_URLS:
        text = _scrape_url(url)
        if text:
            parts.append(f"[Source: {url}]\n{text}")

    # Try NMUN PDF
    pdf_text = _scrape_pdf(
        "https://www.nmun.org/assets/documents/NMUNPPGuide.pdf"
    )
    if pdf_text:
        parts.append(f"[Source: NMUN PDF Guide]\n{pdf_text}")

    # DuckDuckGo search for additional sources
    try:
        from ddgs import DDGS
        import time

        with DDGS() as ddgs:
            results = list(ddgs.text(DDGS_QUERY, max_results=3))
        time.sleep(1.0)
        for r in results:
            url = r.get("href", "")
            if url and url not in GUIDE_URLS:
                text = _scrape_url(url, max_chars=800)
                if text:
                    parts.append(f"[Source: {url}]\n{text}")
                    break  # one extra source is enough
    except Exception:
        pass

    _cached_guidelines = "\n\n".join(parts)
    print(f"[mun_guidelines] Loaded {len(_cached_guidelines)} chars of guidelines.")


def get_guidelines() -> str:
    return _cached_guidelines
