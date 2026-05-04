import difflib
import hashlib
from dataclasses import dataclass

from site_scraper import Page


@dataclass
class DiffResult:
    has_changes: bool
    added_text: str
    is_first_run: bool


class DiffDetector:
    MAX_DIFF_CHARS = 12000

    def detect(self, prev_data: dict | None, current_pages: list[Page]) -> DiffResult:
        # 初回 or 旧フォーマット（pages_data なし）
        if prev_data is None or prev_data.get("pages") is None:
            return DiffResult(has_changes=False, added_text="", is_first_run=True)

        prev_pages = prev_data["pages"]
        added_parts = []

        for page in current_pages:
            curr_hash = hashlib.md5(page.text.encode()).hexdigest()

            if page.url not in prev_pages:
                # 新規ページ
                added_parts.append(f"【新規ページ】{page.title}\n{page.text[:3000]}")
            elif prev_pages[page.url]["hash"] != curr_hash:
                # 内容が変化したページ
                prev_lines = prev_pages[page.url]["content"].splitlines(keepends=True)
                curr_lines = page.text.splitlines(keepends=True)
                diff = difflib.Differ().compare(prev_lines, curr_lines)
                added = "".join(line[2:] for line in diff if line.startswith("+ ")).strip()
                label = f"【更新】{page.title}"
                added_parts.append(f"{label}\n{added if added else page.text[:3000]}")

        has_changes = bool(added_parts)
        added_text = "\n\n".join(added_parts)[: self.MAX_DIFF_CHARS]

        return DiffResult(
            has_changes=has_changes,
            added_text=added_text,
            is_first_run=False,
        )
