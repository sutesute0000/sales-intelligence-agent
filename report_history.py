import os
from datetime import datetime


class HistoryWriter:
    def __init__(self, dir_path: str):
        self.dir_path = dir_path
        os.makedirs(self.dir_path, exist_ok=True)

    def write(self, site_cards: list[dict], hypothesis: dict | None) -> str:
        ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        filename = f"{ts}.md"
        path = os.path.join(self.dir_path, filename)

        lines = [
            f"# Sales Intelligence Report — {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            "",
            f"対象事業者数: {len(site_cards)}",
            "",
        ]

        for card in site_cards:
            name = card["name"]
            a = card["analysis"]
            lines.append(f"## {name}")
            lines.append("")
            if a.get("summary"):
                lines.append("### ニュース差分サマリ")
                lines.append(a["summary"])
                lines.append("")

            if a.get("updated_hypothesis_md"):
                lines.append("### 最新の営業仮説")
                lines.append("")
                lines.append(a["updated_hypothesis_md"])
                lines.append("")

        if hypothesis:
            lines.append("---")
            lines.append("")
            lines.append("## 営業仮説（横断分析）")
            lines.append("")
            lines.append(f"**最優先ターゲット:** {hypothesis.get('hot_targets', '')}")
            lines.append("")
            lines.append("### 1週間以内のアクション")
            for a in hypothesis.get("weekly_actions", []):
                lines.append(f"- {a}")
            lines.append("")
            lines.append(f"**戦略的視点:** {hypothesis.get('strategic_view', '')}")
            lines.append("")
            qs = hypothesis.get("open_questions", [])
            if qs:
                lines.append("### ヒアリング項目")
                for q in qs:
                    lines.append(f"- {q}")
                lines.append("")

        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        return path
