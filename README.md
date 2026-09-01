# AI Agent Governance Python environment

Pythonで次のバージョンを固定した開発環境です。

- OpenAI Agents SDK `0.22.0`
- Claude Agent SDK `0.2.144`
- Agent Governance Toolkit `4.1.0`（`full` extra）
- Open Policy Agent `1.19.1`（外部CLI）
- `cedarpy 4.8.7`（Cedar Policy Engine `4.8.2`）

## 利用開始

```bash
source .venv/bin/activate
python --version
```

APIを実行するターミナルで、必要なキーを環境変数として設定します。

```bash
export OPENAI_API_KEY="..."
export OPENAI_DEFAULT_MODEL="gpt-5-nano"
export ANTHROPIC_API_KEY="..."
export ANTHROPIC_WORKSPACE_ID="..."
export CLAUDE_MODEL="claude-haiku-4-5-20251001"
```

`OPENAI_DEFAULT_MODEL` はOpenAI Agents SDKの既定モデルとして使われます。
Claude Agent SDKでは、`ClaudeAgentOptions(model=os.environ["CLAUDE_MODEL"])` のように
`CLAUDE_MODEL` を明示的に渡してください。少額のAPI残高を保護するため、サンプルや実行コードでも
高価格モデルへ暗黙に切り替えず、出力token上限とClaudeの `max_budget_usd` をrunごとに設定します。

## 環境の再作成

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## 動作確認

```bash
python -c 'import agents, claude_agent_sdk, agent_compliance; print("imports: OK")'
python -m pip check
agt --version
```

インストール済みの全依存バージョンを確認する場合は、仮想環境を有効化して
`python -m pip list` を実行してください。
