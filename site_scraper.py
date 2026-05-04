import hashlib
import io
import re
from collections import deque
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

NEWS_KEYWORDS = [
    "ニュース", "お知らせ", "新着", "新情報", "トピックス",
    "news", "notice", "topics", "press", "release", "blog", "info",
]

# PDF は include_pdfs フラグで制御するため除外リストから外す
SKIP_EXTENSIONS = {".zip", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".mp4", ".mp3"}


@dataclass
class Page:
    url: str
    title: str
    text: str


@dataclass
class ScrapeResult:
    pages: list[Page] = field(default_factory=list)

    @property
    def combined_text(self) -> str:
        return "\n\n".join(f"【{p.title}】\n{p.text}" for p in self.pages)

    @property
    def content_hash(self) -> str:
        return hashlib.md5(self.combined_text.encode()).hexdigest()


class Scraper:
    def __init__(self, config: dict):
        self.timeout = config.get("timeout", 30)
        self.max_pages = config.get("max_pages", config.get("max_news_pages", 20))
        self.include_subdomains = config.get("include_subdomains", False)
        self.include_pdfs = config.get("include_pdfs", False)
        self.include_iframes = config.get("include_iframes", False)
        self.session = requests.Session()
        self.session.headers["User-Agent"] = config.get(
            "user_agent", "Mozilla/5.0 (compatible; sales-intelligence-agent/1.0)"
        )

    def _is_same_site(self, base_domain: str, netloc: str) -> bool:
        if netloc == base_domain:
            return True
        if self.include_subdomains and netloc.endswith("." + base_domain):
            return True
        return False

    def scrape(self, base_url: str) -> ScrapeResult:
        result = ScrapeResult()
        visited: set[str] = set()
        priority_queue: deque[str] = deque()
        normal_queue: deque[str] = deque()

        priority_queue.append(base_url)

        while (priority_queue or normal_queue) and len(result.pages) < self.max_pages:
            url = priority_queue.popleft() if priority_queue else normal_queue.popleft()

            if url in visited:
                continue
            visited.add(url)

            if url.lower().endswith(".pdf"):
                page = self._fetch_pdf(url)
                if page:
                    result.pages.append(page)
            else:
                html, page = self._fetch(url)
                if page:
                    result.pages.append(page)
                if html:
                    for link, is_priority in self._find_internal_urls(base_url, html, visited):
                        if is_priority:
                            priority_queue.append(link)
                        else:
                            normal_queue.append(link)

        return result

    def _fetch(self, url: str) -> tuple[str, Page | None]:
        try:
            resp = self.session.get(url, timeout=self.timeout)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "lxml")

            for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
                tag.decompose()

            title = soup.title.get_text(strip=True) if soup.title else url
            raw_text = soup.get_text(separator="\n")
            text = re.sub(r"\n{3,}", "\n\n", raw_text).strip()

            return resp.text, Page(url=url, title=title, text=text)
        except Exception as e:
            print(f"[scraper] {url} → {e}")
            return "", None

    def _fetch_pdf(self, url: str) -> Page | None:
        try:
            import pdfplumber
        except ImportError:
            print("[scraper] pdfplumber が未インストールです。pip install pdfplumber を実行してください。")
            return None
        try:
            resp = self.session.get(url, timeout=self.timeout)
            resp.raise_for_status()
            with pdfplumber.open(io.BytesIO(resp.content)) as pdf:
                pages_text = [p.extract_text() or "" for p in pdf.pages]
            text = "\n\n".join(t for t in pages_text if t.strip())
            title = url.split("/")[-1]
            return Page(url=url, title=title, text=text[:12000])
        except Exception as e:
            print(f"[scraper] PDF {url} → {e}")
            return None

    def _find_internal_urls(
        self, base_url: str, html: str, visited: set[str]
    ) -> list[tuple[str, bool]]:
        soup = BeautifulSoup(html, "lxml")
        base_domain = urlparse(base_url).netloc
        seen_in_this_call: set[str] = set()
        results: list[tuple[str, bool]] = []

        # <a> タグのリンク
        candidates: list[tuple[str, str]] = [
            (a["href"], a.get_text().lower()) for a in soup.find_all("a", href=True)
        ]

        # <iframe> の src（include_iframes=True のとき）
        if self.include_iframes:
            candidates += [
                (iframe["src"], "") for iframe in soup.find_all("iframe", src=True)
            ]

        for href, link_text in candidates:
            full_url = urljoin(base_url, href).split("#")[0]
            parsed = urlparse(full_url)

            if not self._is_same_site(base_domain, parsed.netloc):
                continue
            if parsed.scheme not in ("http", "https"):
                continue

            if full_url.lower().endswith(".pdf"):
                if not self.include_pdfs:
                    continue
            elif any(full_url.lower().endswith(ext) for ext in SKIP_EXTENSIONS):
                continue

            if full_url in visited or full_url in seen_in_this_call:
                continue

            seen_in_this_call.add(full_url)
            is_priority = any(
                kw.lower() in link_text or kw.lower() in href.lower()
                for kw in NEWS_KEYWORDS
            )
            results.append((full_url, is_priority))

        return results
