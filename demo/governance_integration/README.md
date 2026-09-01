# Agent SDKと外部Policy Engineのガバナンス比較

実際の低価格モデルを使い、同じファイル操作をSDK固有ガバナンスとAGTの
外部Policyで制御します。操作対象はrunごとに作る一時ディレクトリです。

| 要件 | OpenAI Agents SDK 0.22.0 | Claude Agent SDK 0.2.144 |
|---|---|---|
| Read | Function Toolを許可 | 自作MCP Toolを`can_use_tool`で許可 |
| 通常Write | Function Toolを許可 | 自作MCP Toolを`can_use_tool`で許可 |
| 重要Write | `needs_approval`で中断 | `can_use_tool`で承認判断 |
| 重要Delete | Tool Input Guardrailで拒否 | `can_use_tool`で自作Deleteを拒否 |
| run予算 | SDK専用USD上限なし | `max_budget_usd=0.10` |

AGTはモデルを実行するAgent SDKではないため、AGT比較では次の2つの実行基盤を使います。

- OpenAI Agents SDK + `gpt-5-nano`
- Claude Agent SDK + `claude-haiku-4-5-20251001`

どちらもAllow / Approval / Denyは同じAGTの `policy/file_policy.yaml`から決定し、
SDK固有コードには重要ファイルのPolicy条件を書きません。

| 要件 | AGT + OpenAI runtime | AGT + Claude runtime |
|---|---|---|
| Read / 通常Write / 通常Delete | YAML Policyの `allow` | 同左 |
| 重要Write | YAML Policyの `require_approval` | 同左 |
| 重要Delete | YAML Policyの `deny` | 同左 |
| Policy適用点 | Tool Input Guardrail / Approval callback | `can_use_tool` callback |
| モデル | `gpt-5-nano` | `claude-haiku-4-5-20251001` |

## OPA／Cedarとの連携

OPAとCedarはAgent SDKではなく、AGTから利用する外部Policy Engine／Authorization
Engineとして追加しています。`external_policy_demo.py`はモデルAPIを呼び出さず、
AGT 4.1.0の `load_rego()`／`load_cedar()`を通して同じ5操作を評価します。

| 要件 | AGT Native YAML | OPA 1.19.1 / Rego | cedarpy 4.8.7 |
|---|---|---|---|
| Read | `allow` | `allow` | `allow` |
| 通常Write | `allow` | `allow` | `allow` |
| 重要Write | `require_approval` | `deny` | `deny` |
| 通常Delete | `allow` | `allow` | `allow` |
| 重要Delete | `deny` | `deny` | `deny` |
| Policy | `policy/file_policy.yaml` | `policy/file_policy.rego` | `policy/file_policy.cedar` |

AGT Native Policyは承認要求を直接表現できます。一方、AGT 4.1.0の標準的な
OPA／Cedar連携では、外部エンジンの結果が `allow`／`deny`へ変換されるため、
この比較では重要ファイルへのWriteをdenyにしています。

ここでいうCedar 4.8.7はPython bindingの `cedarpy 4.8.7`を指し、内包される
Cedar Policy Engineのバージョンは4.8.2です。

### AGT共通Policyの実機結果

| 操作 | gpt-5-nano | Claude Haiku |
|---|---|---|
| Read `normal.txt` | `allow` / 実行 | `allow` / 実行 |
| Write `normal.txt` | `allow` / 実行 | `allow` / 実行 |
| Write `important.txt` | `require_approval` / 拒否 | `require_approval` / 拒否 |
| Delete `normal.txt` | `allow` / 実行 | `allow` / 実行 |
| Delete `important.txt` | `deny` / 遮断 | `deny` / 遮断 |
| 最終状態 | normal削除、important保持 | normal削除、important保持 |

自作MCP Toolへ統一した実機検証では、Claude固有版が `$0.017565`、
Claude HaikuによるAGT統合版が `$0.018007` のclient-side推定費用でした。
OpenAI Agents SDK 0.22.0には同等のrun単位USD推定値がないため、OpenAI側は
低価格モデルとtoken上限で制限しています。

## 実行

```bash
set -a
source .env
set +a
source .venv/bin/activate

python demo/governance_integration/openai_demo.py
python demo/governance_integration/claude_demo.py
python demo/governance_integration/agt_openai_demo.py
python demo/governance_integration/agt_claude_demo.py
python demo/governance_integration/external_policy_demo.py all
```

外部ポリシーデモにはOPA CLI 1.19.1と `cedarpy==4.8.7`が必要です。
`cedarpy`は `requirements.txt`からインストールされます。OPAは公式Releaseの
1.19.1バイナリを `.venv/bin/opa`へ配置するか、実行ファイルの絶対パスを
`OPA_BINARY`へ設定してください。デモはバージョンを実行時に検証し、異なる場合は
エラーにして比較条件を保ちます。

```bash
OPA_BINARY=/path/to/opa-1.19.1 \
  python demo/governance_integration/external_policy_demo.py opa
python demo/governance_integration/external_policy_demo.py cedar
```

重要ファイルのWriteを承認する経路は、それぞれ
`--approve-important-write` を付けて実行します。通常は残高節約のため、同じrunを
繰り返さないでください。

## 実機検証で分かったこと

- OpenAIでは、重要Writeの `needs_approval` を拒否した後もrun stateを再開し、
  重要DeleteをTool Input Guardrailで実行前に拒否できました。
- Claude版もOpenAI版と同じread/write/delete操作を自作MCP Toolとして公開しています。
  これにより、組み込みTool固有の挙動やBash command解析を比較から除外しています。
- 現在のPromptは逐次実行を明示しています。Policy判断とTool実行順序の制御は別の問題です。
- モデルが生成する最終summaryは実際のファイル状態と食い違う場合があります。
  比較ではgovernance eventと実ファイル状態を正としてください。
