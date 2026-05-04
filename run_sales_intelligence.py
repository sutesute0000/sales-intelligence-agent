import os
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml
from dotenv import load_dotenv

from change_detector import DiffDetector
from discord_reporter import Reporter
from intelligence_analyzer import Analyzer
from report_history import HistoryWriter
from site_scraper import Scraper
from state_store import StateDB
from web_researcher import Researcher

HYPOTHESES_DIR = Path("hypotheses")
ENV_PREFIX = "SALES_INTEL"


def load_config(path: str | None = None) -> dict:
    config_path = Path(
        path
        or os.environ.get(f"{ENV_PREFIX}_CONFIG")
        or _first_existing_config()
    )
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _first_existing_config() -> str:
    for path in ("config.local.yaml", "config.yaml"):
        if Path(path).exists():
            return path
    sys.exit("[main] 設定ファイルが見つかりません。config.local.yaml を作成してください。")


def select_targets(targets: list[dict]) -> list[dict]:
    selected = targets

    target_filter = os.environ.get(f"{ENV_PREFIX}_TARGETS", "").strip()
    if target_filter:
        wanted = {item.strip() for item in target_filter.split(",") if item.strip()}
        selected = [
            target
            for target in selected
            if target.get("name") in wanted or target.get("url") in wanted
        ]
        print(f"[main] {ENV_PREFIX}_TARGETS により {len(selected)}/{len(targets)} 件を選択")

    batch_total = int(os.environ.get(f"{ENV_PREFIX}_BATCH_TOTAL", "1"))
    batch_index = int(os.environ.get(f"{ENV_PREFIX}_BATCH_INDEX", "0"))
    if batch_total < 1:
        sys.exit(f"[main] {ENV_PREFIX}_BATCH_TOTAL は1以上を指定してください。")
    if batch_index < 0 or batch_index >= batch_total:
        sys.exit(f"[main] {ENV_PREFIX}_BATCH_INDEX は 0 以上 {ENV_PREFIX}_BATCH_TOTAL 未満を指定してください。")
    if batch_total > 1:
        before = len(selected)
        selected = [
            target
            for idx, target in enumerate(selected)
            if idx % batch_total == batch_index
        ]
        print(f"[main] バッチ分割 {batch_index + 1}/{batch_total}: {len(selected)}/{before} 件を選択")

    if not selected:
        sys.exit(f"[main] 実行対象が0件です。{ENV_PREFIX}_TARGETS またはバッチ設定を確認してください。")

    return selected


def load_prev_hypothesis(name: str) -> str:
    path = HYPOTHESES_DIR / f"{name}.md"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""


def save_hypothesis(name: str, content: str):
    HYPOTHESES_DIR.mkdir(exist_ok=True)
    (HYPOTHESES_DIR / f"{name}.md").write_text(content, encoding="utf-8")


def run():
    load_dotenv()

    gemini_api_key = os.environ.get("GEMINI_API_KEY")
    discord_webhook = os.environ.get("DISCORD_WEBHOOK_URL")

    if not gemini_api_key:
        sys.exit("[main] GEMINI_API_KEY が設定されていません。.env を確認してください。")
    if not discord_webhook:
        sys.exit("[main] DISCORD_WEBHOOK_URL が設定されていません。.env を確認してください。")

    config = load_config()
    self_context = config["self_context"]
    signals_cfg = config.get("signals", {})
    min_score = signals_cfg.get("min_score", 5)
    hot_score = signals_cfg.get("hot_score", 8)
    today = datetime.now(ZoneInfo("Asia/Tokyo")).strftime("%Y-%m-%d")

    db = StateDB(config["state"]["db_path"])
    scraper = Scraper(config["scraper"])
    detector = DiffDetector()
    analyzer = Analyzer(config["gemini"], api_key=gemini_api_key, self_context=self_context)
    researcher = Researcher()
    report_cfg = config.get("reports", {})
    reporter = Reporter(
        discord_webhook,
        hot_score=hot_score,
        footer_text=report_cfg.get("footer"),
    )
    history = HistoryWriter(config.get("reports", {}).get("dir", "reports"))

    # Phase 1: スクレイプ + 差分検知（API呼び出しなし）
    pending = []

    targets = select_targets(config["targets"])

    for target in targets:
        name = target["name"]
        url = target["url"]
        print(f"\n[main] 処理中: {name} ({url})")

        try:
            result = scraper.scrape(url)
            if not result.pages:
                print(f"[main] {name}: ページ取得失敗。スキップ。")
                continue
            print(f"[main] {name}: {len(result.pages)}ページ取得")

            prev_data = db.get(url)
            diff = detector.detect(prev_data, result.pages)

            if diff.is_first_run:
                print(f"[main] {name}: 初回取得")
                diff_text = result.combined_text[:12000]
            elif not diff.has_changes:
                print(f"[main] {name}: 変化なし。以降の処理をスキップします")
                continue
            else:
                diff_text = diff.added_text

            pending.append({
                "name": name,
                "url": url,
                "diff_text": diff_text,
                "pages": result.pages,
                "prev_hypothesis": load_prev_hypothesis(name),
                "has_changes": diff.is_first_run or diff.has_changes,
            })

        except Exception as e:
            print(f"[main] {name}: エラー → {e}")
            try:
                reporter.send_error(name, str(e))
            except Exception:
                pass

    if not pending:
        db.close()
        print("\n[main] 処理対象なし。完了。")
        return

    # Phase 2: 差分から補足検索クエリを作り、検索結果込みで営業仮説を更新
    site_cards = []
    last_gemini_call_at = 0.0

    def wait_for_gemini_slot():
        nonlocal last_gemini_call_at
        interval = 10
        elapsed = time.monotonic() - last_gemini_call_at
        if elapsed < interval:
            wait_seconds = interval - elapsed
            print(f"[main] Gemini呼び出し間隔調整: {wait_seconds:.1f}秒待機")
            time.sleep(wait_seconds)
        last_gemini_call_at = time.monotonic()

    for item in pending:
        name = item["name"]
        url = item["url"]

        print(f"\n[main] {name}: 補足検索クエリを生成中... (today={today})")
        try:
            wait_for_gemini_slot()
            research_plan = analyzer.plan_research(
                name=name,
                prev_hypothesis=item["prev_hypothesis"],
                diff_text=item["diff_text"],
                today=today,
            )
        except Exception as e:
            print(f"[main] {name}: 検索クエリ生成エラー → {e}")
            continue

        queries = research_plan.get("search_queries", [])
        if queries:
            print(f"[main] {name}: 背景・補足情報を収集中... ({len(queries)} queries)")
        else:
            print(f"[main] {name}: 追加Web調査なしで仮説を更新します")
        related = researcher.research(queries)

        print(f"[main] {name}: 検索結果を踏まえて営業仮説・レポートを作成中...")
        try:
            wait_for_gemini_slot()
            analysis = analyzer.update_site_hypothesis(
                name=name,
                prev_hypothesis=item["prev_hypothesis"],
                diff_text=item["diff_text"],
                related=related,
                today=today,
            )
        except Exception as e:
            print(f"[main] {name}: 仮説更新エラー → {e}")
            continue

        analysis["search_queries"] = queries

        all_signals = analysis.get("signals", [])
        filtered = sorted(
            [s for s in all_signals if s.get("relevance_score", 0) >= min_score],
            key=lambda s: s.get("relevance_score", 0),
            reverse=True,
        )
        print(f"[main] {name}: シグナル {len(all_signals)}件中、{len(filtered)}件が閾値以上")

        if not filtered:
            db.save(url, item["pages"])
            print(f"[main] {name}: 閾値以上のシグナルなし。通知・仮説更新をスキップします")
            continue

        updated_md = analysis.get("updated_hypothesis_md")
        if updated_md:
            save_hypothesis(name, updated_md)
            print(f"[main] {name}: 仮説を更新しました")

        db.save(url, item["pages"])

        site_cards.append({
            "name": name,
            "analysis": analysis,
            "filtered_signals": filtered,
            "related": related,
            "max_score": filtered[0].get("relevance_score", 0),
        })

    db.close()

    site_cards.sort(key=lambda c: c["max_score"], reverse=True)

    if not site_cards:
        print("\n[main] レポート対象なし。Discordへの送信はスキップ。")
        print("[main] 完了。")
        return

    # Phase 3: Discord送信 + 履歴保存
    try:
        reporter.send_full_report(site_cards, hypothesis=None)
        print("[main] Discord送信完了")
    except Exception as e:
        print(f"[main] Discord送信エラー → {e}")

    try:
        path = history.write(site_cards, hypothesis=None)
        print(f"[main] 履歴保存: {path}")
    except Exception as e:
        print(f"[main] 履歴保存エラー → {e}")

    print("\n[main] 完了。")


if __name__ == "__main__":
    run()
