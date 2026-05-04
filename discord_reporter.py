from datetime import datetime, timezone

import requests

DEFAULT_FOOTER = "sales-intelligence-agent"

COLOR_HOT = 0xFF4444     # ホットシグナル（score >= hot_score）
COLOR_NOTABLE = 0x0099FF  # 通常シグナル（score >= min_score）
COLOR_HYPOTHESIS = 0xFF9900
COLOR_NONE = 0x888888
COLOR_ERROR = 0xCC0000


class Reporter:
    def __init__(self, webhook_url: str, hot_score: int = 8, footer_text: str | None = None):
        self.webhook_url = webhook_url
        self.hot_score = hot_score
        self.footer_text = footer_text or DEFAULT_FOOTER

    def send_full_report(self, site_cards: list[dict], hypothesis: dict | None):
        for card in site_cards:
            self._post({"embeds": [self._make_card_embed(card)]})
        if hypothesis:
            self._post({"embeds": [self._make_hypothesis_embed(hypothesis)]})

    def send_error(self, company: str, error: str):
        embed = {
            "title": f"⚠️ {company} — エラー",
            "description": f"```{error[:1000]}```",
            "color": COLOR_ERROR,
            "timestamp": _now(),
            "footer": {"text": self.footer_text},
        }
        self._post({"embeds": [embed]})

    def _make_card_embed(self, card: dict) -> dict:
        name = card["name"]
        analysis = card["analysis"]
        hypothesis_md = analysis.get("updated_hypothesis_md", "")
        signals = card.get("filtered_signals", [])
        max_score = max((s.get("relevance_score", 0) for s in signals), default=0)
        is_hot = max_score >= self.hot_score
        marker = "🔥" if is_hot else "📝"

        fields = []
        hypothesis_chunks = list(_chunks(_truncate(hypothesis_md, 3000), 1000)) or ["—"]
        for idx, chunk in enumerate(hypothesis_chunks, start=1):
            fields.append({
                "name": "レポート" if idx == 1 else f"レポート（続き {idx}）",
                "value": chunk or "—",
                "inline": False,
            })

        return {
            "title": f"{marker} {name}",
            "description": _truncate(f"**差分ニュースサマリ**\n{analysis.get('summary', '')}", 900),
            "color": COLOR_HOT if is_hot else COLOR_NOTABLE,
            "fields": fields,
            "timestamp": _now(),
            "footer": {"text": self.footer_text},
        }

    def _make_hypothesis_embed(self, hypothesis: dict) -> dict:
        actions = hypothesis.get("weekly_actions", [])
        actions_text = "\n".join(f"• {a}" for a in actions) or "—"
        questions = hypothesis.get("open_questions", [])
        questions_text = "\n".join(f"• {q}" for q in questions) or "—"

        return {
            "title": "💡 営業仮説（横断分析）",
            "description": _truncate(hypothesis.get("hot_targets", ""), 600),
            "color": COLOR_HYPOTHESIS,
            "fields": [
                {"name": "1週間以内のアクション", "value": _truncate(actions_text, 1024), "inline": False},
                {"name": "戦略的視点", "value": _truncate(hypothesis.get("strategic_view", "—"), 1024), "inline": False},
                {"name": "ヒアリング項目", "value": _truncate(questions_text, 1024), "inline": False},
            ],
            "timestamp": _now(),
            "footer": {"text": self.footer_text},
        }

    def _post(self, payload: dict):
        resp = requests.post(self.webhook_url, json=payload)
        resp.raise_for_status()


def _chunks(text: str, size: int):
    for i in range(0, len(text), size):
        yield text[i : i + size]


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
