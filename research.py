"""
DuckDuckGo search + BeautifulSoup scraping for research context.
"""

import time
import requests
from bs4 import BeautifulSoup
from datetime import date


HEADERS = {"User-Agent": "Mozilla/5.0"}
SCRAPE_TIMEOUT = 8
MAX_SNIPPET = 2000


def _scrape(url: str) -> str:
    try:
        resp = requests.get(url, timeout=SCRAPE_TIMEOUT, headers=HEADERS)
        soup = BeautifulSoup(resp.text, "lxml")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        return soup.get_text(separator=" ", strip=True)[:MAX_SNIPPET]
    except Exception:
        return ""


def gather_research(topic: str, country: str) -> list[dict]:
    """
    Run 4 DDG searches, scrape top 3 URLs each.
    Returns list of {title, url, text} dicts.
    """
    queries = [
        f"{topic} United Nations background 2024 2025",
        f"{country} policy {topic} government position",
        f"{topic} humanitarian statistics facts",
        f"{country} foreign policy United Nations",
    ]

    sources: list[dict] = []
    seen_urls: set[str] = set()

    try:
        from ddgs import DDGS

        with DDGS() as ddgs:
            for query in queries:
                try:
                    results = list(ddgs.text(query, max_results=3))
                except Exception:
                    results = []

                for r in results:
                    url = r.get("href", "")
                    if not url or url in seen_urls:
                        continue
                    seen_urls.add(url)

                    scraped = _scrape(url)
                    text = scraped if scraped else r.get("body", "")[:MAX_SNIPPET]
                    if text:
                        sources.append(
                            {
                                "title": r.get("title", url),
                                "url": url,
                                "text": text,
                            }
                        )

                time.sleep(1.5)
    except Exception as e:
        print(f"[research] DDG error: {e}")

    return sources


def format_research_block(sources: list[dict]) -> str:
    today = date.today().strftime("%B %d, %Y")
    lines = []
    for i, s in enumerate(sources, 1):
        lines.append(
            f'[Source {i}] Title: "{s["title"]}" | URL: {s["url"]} | Accessed: {today}'
        )
        lines.append(f'Text: {s["text"][:MAX_SNIPPET]}')
        lines.append("")
    return "\n".join(lines)
