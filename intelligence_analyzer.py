import json
import re
import time

from google import genai


RESEARCH_PLAN_PROMPT = """\
あなたは「{company_self}」{department}の営業インテリジェンスAIです。

【自社の立場】
{role}

【提供可能な自社サービス】
{offerings}

【自社のスタンス】
{stance}

【補足の自社情報】
{extra_context}

【今日の日付】
{today}

================================================================
監視対象事業者: {company}

### (A) 前日までの営業仮説
{prev_hypothesis}

### (B) 今日のニュース差分
{diff_text}
================================================================

今日のニュースを「前日までの仮説」に照らして解釈し、{company} について以下を行ってください：

1. 今日のニュース差分だけでは不足する背景情報・補足情報を判断する
2. 市場動向、競合動向、制度動向、関連する過去発表などを調べるための検索クエリを作る
3. 追加調査が不要な場合は search_queries を空配列にする

以下のJSONのみで回答してください（説明文・コードブロック不要）:
{{
  "search_queries": ["追加調査用の検索クエリ"],
  "research_focus": ["追加調査で確認したい観点"]
}}
"""


SITE_HYPOTHESIS_PROMPT = """\
あなたは「{company_self}」{department}の営業インテリジェンスAIです。

【自社の立場】
{role}

【提供可能な自社サービス】
{offerings}

【自社のスタンス】
{stance}

【補足の自社情報】
{extra_context}

【今日の日付】
{today}

================================================================
監視対象事業者: {company}

### (A) 前日までの営業仮説
{prev_hypothesis}

### (B) 今日のニュース差分
{diff_text}

### (C) 背景・補足情報として取得した追加Web調査結果
{related_research}
================================================================

前日までの仮説、今日のニュース差分、必要に応じて実施したWeb調査結果を統合し、
{company} について営業シグナルを抽出し、最新の営業仮説とレポートを作成してください。

更新方針:
1. 部長・役員級が短時間で状況把握できる、コンサルティングブリーフの文体で書く
2. 前日までの仮説と矛盾する新情報がある場合は、理由が分かる形で修正する
3. Web調査結果は、ニュース差分だけでは不足する市場背景・競合動向・制度動向の補強に使う
4. 事実、解釈、営業示唆を分け、過度に断定せず「仮説」として表現する
5. ニュース差分から営業機会が薄い場合は、relevance_score を低くする
6. 多少長くてもよいが、読み手が次の判断に移れる粒度に整理する

以下のJSONのみで回答してください（説明文・コードブロック不要）:
{{
  "summary": "今日のニュース差分と追加調査を踏まえた動向概要（2〜3文）",
  "signals": [
    {{
      "topic": "今日検出された具体的な動向（事実ベース、1文）",
      "relevance_score": 0以上10以下の整数,
      "relevance_reason": "なぜ自社にとって関連するか（80字以内）",
      "fit_services": ["関連する自社サービス名（複数可、なければ空配列）"],
      "approach": "具体的な営業アプローチ案（60〜120字、誰に何をどう聞くか）"
    }}
  ],
  "inferred_concerns": ["この事業者が抱えている可能性が高い課題"],
  "updated_hypothesis_md": "更新後の仮説ファイル全体のmarkdown内容（後述のテンプレート形式そのまま）"
}}

relevance_score の基準:
- 9-10: 即座に提案可能な明確な機会
- 7-8: 高い可能性
- 5-6: 注視すべき動向
- 1-4: 営業機会との関連が薄い
- 0: 関連なし

updated_hypothesis_md のテンプレート（このまま文字列に格納）:

# {company} — 営業仮説（最終更新: {today}）

## エグゼクティブサマリ
（今日の差分と既存仮説を踏まえた総括を2〜3文。何が起きており、当社にとってなぜ重要かを端的に述べる）

## 観察された動向
- 事実: （ニュース・公開情報から確認できる重要事実を1〜2文）
- 解釈: （その動きが事業戦略・設備投資・運用課題に何を示唆するかを1〜2文）
- 注目度: （高/中/低のいずれかと理由を1文）

## 営業仮説
- 潜在課題: （事業者が抱えていそうな課題を2〜3文）
- 当社の入り口: （データセンタ、回線利用、コールセンタ業務受託のどこに接点があるかを2〜3文）
- 確認すべき論点: （誰に何を聞くべきかを3点以内）

## 推奨アクション
- （次に取るべき営業アクションを優先度順に3点以内）
"""


HYPOTHESIS_PROMPT = """\
あなたは「{company_self}」{department}の営業戦略AIです。

【自社の立場】
{role}

【提供可能な自社サービス】
{offerings}

【補足の自社情報】
{extra_context}

================================================================
今日検出されたシグナル（複数事業者横断）:
{cards}
================================================================

これらを横断的に分析し、自社相互接続部としての営業戦略を提示してください。
以下のJSONのみで回答してください（説明文・コードブロック不要）:
{{
  "hot_targets": "最優先で動くべき事業者と理由（200字以内）",
  "weekly_actions": ["1週間以内のアクション1", "アクション2", "アクション3"],
  "strategic_view": "業界横断トレンドと相互接続部への示唆（200字以内）",
  "open_questions": ["事業者にヒアリングすべき質問・確認事項"]
}}
"""


class Analyzer:
    def __init__(self, config: dict, api_key: str, self_context: dict):
        self.client = genai.Client(api_key=api_key)
        self.model = config.get("model", "gemini-2.5-flash")
        self.self_context = self_context

    def plan_research(self, name: str, prev_hypothesis: str, diff_text: str, today: str) -> dict:
        prompt = RESEARCH_PLAN_PROMPT.format(
            company_self=self.self_context["company"],
            department=self.self_context["department"],
            role=self.self_context["role"].strip(),
            offerings=self._format_list(self.self_context["offerings"]),
            stance=self.self_context["stance"].strip(),
            extra_context=self._format_extra_context(),
            today=today,
            company=name,
            prev_hypothesis=prev_hypothesis or "（初回のため空）",
            diff_text=diff_text,
        )
        return self._call(prompt)

    def update_site_hypothesis(
        self,
        name: str,
        prev_hypothesis: str,
        diff_text: str,
        related: list[dict],
        today: str,
    ) -> dict:
        prompt = SITE_HYPOTHESIS_PROMPT.format(
            company_self=self.self_context["company"],
            department=self.self_context["department"],
            role=self.self_context["role"].strip(),
            offerings=self._format_list(self.self_context["offerings"]),
            stance=self.self_context["stance"].strip(),
            extra_context=self._format_extra_context(),
            today=today,
            company=name,
            prev_hypothesis=prev_hypothesis or "（初回のため空）",
            diff_text=diff_text,
            related_research=self._format_research(related),
        )
        return self._call(prompt)

    def generate_hypothesis(self, site_cards: list[dict]) -> dict:
        prompt = HYPOTHESIS_PROMPT.format(
            company_self=self.self_context["company"],
            department=self.self_context["department"],
            role=self.self_context["role"].strip(),
            offerings=self._format_list(self.self_context["offerings"]),
            extra_context=self._format_extra_context(),
            cards=self._format_cards(site_cards),
        )
        return self._call(prompt)

    def _call(self, prompt: str) -> dict:
        retry_delays = [20, 60, 120]
        last_error = None

        for attempt in range(len(retry_delays) + 1):
            try:
                response = self.client.models.generate_content(
                    model=self.model,
                    contents=prompt,
                )
                text = response.text.strip()
                text = re.sub(r"^```json\s*", "", text)
                text = re.sub(r"\s*```$", "", text)
                return json.loads(text)
            except Exception as e:
                last_error = e
                message = str(e)
                is_retryable = (
                    "503" in message
                    or "UNAVAILABLE" in message
                    or "high demand" in message
                )
                if not is_retryable or attempt >= len(retry_delays):
                    raise

                delay = retry_delays[attempt]
                print(f"[analyzer] Gemini一時エラー。{delay}秒後に再試行します ({attempt + 1}/{len(retry_delays)}) → {e}")
                time.sleep(delay)

        raise last_error

    @staticmethod
    def _format_list(items: list[str]) -> str:
        return "\n".join(f"- {item}" for item in items)

    def _format_extra_context(self) -> str:
        extra = self.self_context.get("extra_context", {})
        if not extra:
            return "（なし）"

        lines = []
        for key, value in extra.items():
            title = str(key).replace("_", " ")
            lines.append(f"### {title}")
            if isinstance(value, list):
                lines.extend(f"- {item}" for item in value)
            elif isinstance(value, dict):
                for child_key, child_value in value.items():
                    if isinstance(child_value, list):
                        lines.append(f"- {child_key}:")
                        lines.extend(f"  - {item}" for item in child_value)
                    else:
                        lines.append(f"- {child_key}: {child_value}")
            else:
                lines.append(str(value).strip())
            lines.append("")

        return "\n".join(lines).strip()

    @staticmethod
    def _format_cards(site_cards: list[dict]) -> str:
        lines = []
        for card in site_cards:
            name = card["name"]
            a = card["analysis"]
            lines.append(f"### {name}")
            lines.append(f"概要: {a.get('summary', '')}")
            for s in a.get("signals", []):
                lines.append(
                    f"- [score {s.get('relevance_score', '?')}] {s.get('topic', '')} "
                    f"/ fit: {', '.join(s.get('fit_services', [])) or 'なし'} "
                    f"/ approach: {s.get('approach', '')}"
                )
            concerns = a.get("inferred_concerns", [])
            if concerns:
                lines.append(f"推定される困り事: {', '.join(concerns)}")
            lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _format_signals(signals: list[dict], concerns: list[str]) -> str:
        lines = []
        if signals:
            lines.append("営業シグナル:")
            for s in signals:
                fit = ", ".join(s.get("fit_services", [])) or "なし"
                lines.append(
                    f"- [score {s.get('relevance_score', '?')}] {s.get('topic', '')} "
                    f"/ 理由: {s.get('relevance_reason', '')} / fit: {fit} "
                    f"/ approach: {s.get('approach', '')}"
                )
        else:
            lines.append("営業シグナル: なし")

        if concerns:
            lines.append("推定課題:")
            lines.extend(f"- {c}" for c in concerns)
        return "\n".join(lines)

    @staticmethod
    def _format_research(related: list[dict]) -> str:
        if not related:
            return "（追加Web調査なし）"

        lines = []
        for item in related:
            lines.append(f"検索クエリ: {item.get('query', '')}")
            hits = item.get("hits", [])
            if not hits:
                lines.append("- 検索結果なし")
                continue
            for hit in hits[:3]:
                title = hit.get("title", "")
                body = hit.get("body", "")
                href = hit.get("href", "")
                lines.append(f"- {title}: {body} ({href})")
        return "\n".join(lines)
