# Sales Intelligence Agent

公開ニュースを収集し、差分から営業シグナルと仮説を生成してDiscordへ通知するPythonアプリです。

## 公開するもの / 公開しないもの

このリポジトリには主要処理だけを置き、対象事業者名、自社情報、実行履歴、仮説、DB、Webhook URL、APIキーは置かない構成です。

公開してよいもの:

- `run_sales_intelligence.py`, `intelligence_analyzer.py`, `site_scraper.py` などの主要処理
- `config.example.yaml`
- `.env.example`

公開しないもの:

- `config.yaml`
- `config.local.yaml`
- `.env`
- `state.db`
- `reports/`
- `hypotheses/`

## ローカル設定

`config.example.yaml` を参考に、ローカル専用の `config.local.yaml` または `config.yaml` を作成します。

```bash
cp config.example.yaml config.local.yaml
```

環境変数は `.env` に設定します。

```bash
GEMINI_API_KEY=...
DISCORD_WEBHOOK_URL=...
```

任意の設定ファイルを明示する場合は `SALES_INTEL_CONFIG` を使います。

```bash
SALES_INTEL_CONFIG=config.local.yaml python run_sales_intelligence.py
```

## GitHub Actions

GitHub Actionsで実行する場合は、対象事業者名や自社情報をリポジトリに置かず、Repository secrets に `SALES_INTEL_CONFIG_YAML` として `config.local.yaml` の中身を登録します。

必要なSecrets:

- `SALES_INTEL_CONFIG_YAML`
- `SALES_INTEL_CONFIG_YAML_B64`（推奨。`SALES_INTEL_CONFIG_YAML` の代わりにbase64化した設定を登録）
- `GEMINI_API_KEY`
- `DISCORD_WEBHOOK_URL`

`SALES_INTEL_CONFIG_YAML_B64` を使う場合:

```bash
base64 -i config.local.yaml
```

出力された文字列をGitHub Secretsへ登録します。

手動実行時は、GitHub Actionsの `workflow_dispatch` inputs で実行対象を制御できます。

- `targets`: 対象名またはURLをカンマ区切りで指定。空なら全件。
- `batch_total`: 対象を何分割するか。
- `batch_index`: 実行する分割番号。0始まり。

例: 8件の対象を2分割して前半だけ実行する場合は `batch_total=2`, `batch_index=0` を指定します。後半は `batch_index=1` です。

状態DBや仮説ファイルはGitHub cacheに保存しないため、GitHub上に業務情報を残しません。継続状態が必要な場合は、公開リポジトリではなくローカル環境または社内管理の実行環境で運用してください。
