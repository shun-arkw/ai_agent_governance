# OpenAI Agents SDK 0.22.0 と Claude Agent SDK 0.2.144 のガバナンス機能調査

- **調査日**：2026年8月31日
- **対象**：
  - OpenAI Agents SDK for Python **0.22.0**
  - Claude Agent SDK for Python **0.2.144**
- **主な調査観点**：権限制御，Guardrail，Human-in-the-loop，Tool制御，Sandbox，監査・可観測性，トークン使用量，コスト計測・制御，MCP，企業利用時の限界
- **情報源の優先順位**：各社の公式ドキュメント，公式APIリファレンス，公式GitHubリポジトリ，PyPIの対象バージョンページを優先した．GitHub Issueを使用する場合は，公式仕様ではなく「公開状況に関する注意情報」としてのみ扱う．

---

## 0．本レポートの読み方と注意事項

本レポートは，OpenAI Agents SDKやClaude Agent SDKをこれまで利用したことがない読者でも，全体像から個々のガバナンス機能まで順番に理解できることを目的としている．

特に注意すべき点は，**「SDKに組み込まれている機能」と「OpenAI／AnthropicのAPIプラットフォーム側で提供される管理機能」は別物である**という点である．例えば，組織全体の月間API支出上限はSDKの機能ではなく，APIプラットフォーム側の機能である．本レポートでは両者を分離して記載する．

また，SDKは短期間で更新されるため，本レポートでは可能な限り対象バージョンで利用可能であることを確認した．現在の公式ドキュメントにしか確認できない項目については，対象バージョンへの存在を断定しないか，その旨を注記する．

### Claude Agent SDK 0.2.144についてのバージョン上の注意

PyPIでは`claude-agent-sdk==0.2.144`が**2026年8月21日**に公開されており，Source Distributionと複数プラットフォーム向けwheelが存在することを確認できる．一方，2026年8月24日に公式GitHubリポジトリで，「PyPIには0.2.144があるがGitHub Releasesでは0.2.143が最新として表示されている」というIssueが報告された．これは利用者によるIssueであり，Anthropicが0.2.144を無効と公式発表したことを意味しない．したがって，本レポートでは**PyPI上の0.2.144を調査対象として扱いつつ，GitHub Release表示との不整合が報告されていることを注記する**．

出典：[ANT-01]，[ANT-02]

---

# 1．まず理解しておくべき基礎知識

## 1.1 LLMとは

**LLM（Large Language Model，大規模言語モデル）**は，大量のテキスト等から学習し，入力された文章に対して文章や構造化データなどを生成するモデルである．OpenAIのGPT系モデルやAnthropicのClaude系モデルが代表例である．

通常のLLM利用では，概念的には次のような処理になる．

```text
ユーザー
   ↓ 質問
  LLM
   ↓ 回答
ユーザー
```

この場合，LLMは基本的に「入力を受けて出力を返す」役割であり，それだけではPC上のファイルを編集したり，外部APIを実行したり，複数ステップの作業を自律的に進めたりする仕組みは持たない．

---

## 1.2 AI Agentとは

**AI Agent**は，LLMを中心にしながら，Toolの利用や複数ステップの判断を組み合わせてタスクを遂行する仕組みである．

例えば「売上データを調べてレポートを作成して」という指示に対し，Agentは次のような処理を行い得る．

```text
ユーザー
   ↓
Agent
   ├─ 1．必要なデータを判断
   ├─ 2．データベース検索Toolを呼ぶ
   ├─ 3．結果を分析する
   ├─ 4．必要なら別のToolを呼ぶ
   └─ 5．最終回答を作る
```

OpenAIはAgents SDKにおけるAgentを，「instructions，tools，handoffs，guardrails，structured outputsなどのランタイム動作を設定したLLM」と説明している．

出典：[OAI-02]

---

## 1.3 Toolとは

**Tool**とは，AgentがLLMの文章生成以外の処理を行うために利用する機能である．例えば，

- ファイルを読む
- ファイルを書き換える
- データベースを検索する
- Web APIを呼び出す
- Shell commandを実行する
- 社内システムに登録する
- メールを送信する

などがToolになり得る．

Toolを利用できることでAgentの能力は大きく向上する一方，ガバナンス上のリスクも増える．例えば，単なる文章生成の誤りであれば回答を訂正すれば済む場合があるが，Agentが誤って本番データを削除するToolを呼び出した場合，実環境に影響が生じる可能性がある．

---

## 1.4 Agent Loopとは

**Agent Loop**とは，LLMによる判断とTool実行を繰り返す処理ループである．

```text
LLMを呼ぶ
   ↓
Toolが必要か？
 ┌─ Yes → Tool実行 → 結果をLLMへ → 再び判断
 │
 └─ No  → 最終回答
```

OpenAI Agents SDKの`Runner`も，LLM呼び出し，Tool call，handoff，最終出力の判定を繰り返す構造を持つ．Claude Agent SDKも同様に，複数回のTool利用を含むagentic loopを実行できる．

出典：[OAI-03]，[ANT-03]

---

## 1.5 Agent SDKとは

**Agent SDK**とは，Agentを実装するためのソフトウェア開発キットである．LLM APIを直接何度も呼び出してAgent Loopを自作する代わりに，SDKがTool呼び出し，状態管理，権限制御，ログ，承認などの仕組みを提供する．

今回比較するのは，

- **OpenAI Agents SDK**
- **Claude Agent SDK**

である．

両者ともAgent実装を支援するが，ガバナンス機能の設計思想は同一ではない．

---

# 2．AI Agent Governanceとは何か

本レポートでは，**AI Agent Governance**を「Agentが企業・組織のルールに沿って安全かつ管理可能な形で動作するための制御・監視の仕組み」と捉える．

実務では，少なくとも次の問いに答えられる必要がある．

| 観点 | 代表的な問い |
|---|---|
| Action | AgentはどのTool・操作を実行してよいか |
| Data | どのデータをAgentや外部Toolへ渡してよいか |
| Approval | 重要操作は人間の承認を必要とするか |
| Resource | 何ターン，何トークン，いくらまで利用してよいか |
| Isolation | Agentがどのファイルやネットワークへアクセスできるか |
| Audit | Agentが何を判断し，どのToolを使ったか追跡できるか |
| Accountability | 問題発生時に原因を確認し，停止・復旧できるか |

以下では，各SDKがこれらに対してどの機能を提供しているかを確認する．

---

# 3．最初に見る機能比較

以下は詳細説明を読む前の全体像である．「○」は対象バージョン／その時点までの公式履歴で機能を確認できるものを中心に記載している．

| ガバナンス領域 | OpenAI Agents SDK 0.22.0 | Claude Agent SDK 0.2.144 |
|---|---|---|
| 入力内容の検査 | Input Guardrail | `UserPromptSubmit` Hook |
| 最終出力の検査 | Output Guardrail | `Stop` Hook等でアプリ側実装 |
| Tool入力の検査 | Tool Input Guardrail | `PreToolUse` Hook |
| Tool出力の検査 | Tool Output Guardrail | `PostToolUse` Hook |
| Toolの動的な公開／非公開 | `is_enabled`，MCP Tool Filter | `tools`，`disallowed_tools`等 |
| ToolのAllow／Deny | Tool設定，Guardrail，MCP Filter等を組合せ | Permission system，`disallowed_tools` |
| 人間承認 | `needs_approval`，MCP approval | `can_use_tool`，Permission flow |
| 最大Agentターン | `max_turns` | `max_turns` |
| 1回のモデル出力上限 | `ModelSettings.max_tokens` | 下位APIの`max_tokens`等との組合せ |
| run単位のToken使用量取得 | `Usage` | `AssistantMessage.usage`，`ResultMessage`等 |
| run単位のUSDコスト推定 | 専用の`total_cost_usd`相当は確認できない | `total_cost_usd` |
| run単位のUSD予算停止 | 専用の`max_budget_usd`相当は確認できない | `max_budget_usd` |
| 長いAgent Loop用Token Budget | 専用の同等機能は確認できない | `task_budget`（advisory） |
| Tracing／Observability | Built-in Tracing，Hooks | Hooks，OpenTelemetry |
| Trace内の機密データ制御 | `trace_include_sensitive_data` | OTelのcontent logging設定等 |
| Sandbox | Sandbox Agents（Beta） | `SandboxSettings`＋安全なDeployment設計 |
| Filesystem権限 | Sandbox Manifest Permissions | Sandbox／Permission／実行環境 |
| Network制御 | Docker Sandboxで`network_mode="none"` | Sandbox network settings等 |
| MCP制御 | Tool filtering，approval | Permission，`allowed_tools`等 |
| 組織・Projectの支出制御 | OpenAI API Platform側 | Claude Platform側 |

**重要**：この表は「どちらが優れているか」を単純に判定する表ではない．OpenAIはGuardrailを明示的な概念として提供する一方，ClaudeはPermissionとHooksによるTool実行制御が中心であり，実現方法が異なる．

---

# 4．OpenAI Agents SDK 0.22.0

## 4.1 OpenAI Agents SDKの基本構造

OpenAI Agents SDKでは，主に次の要素を組み合わせてAgentを構成する．

```text
Agent
├─ Instructions
├─ Model
├─ Tools
├─ Guardrails
├─ Handoffs
└─ Hooks

        ↓

Runner
└─ Agent Loopを実行
```

**Handoff**とは，処理を別のAgentへ引き渡す仕組みである．例えば「問い合わせ受付Agent」が内容を判定し，「請求担当Agent」へ処理を引き渡すような構成に利用できる．

OpenAIの公式説明では，Agents SDKは`Agent`と`Runner`を中心に，turn，tool，guardrail，handoff，sessionなどを管理する．

出典：[OAI-02]，[OAI-03]

---

# 5．OpenAI：Guardrails

## 5.1 Guardrailとは

**Guardrail**とは，Agentへの入力，Agentからの出力，Toolの入出力を検査し，条件違反時に処理を止めたり，結果を置き換えたりするための仕組みである．

OpenAI Agents SDKでは大きく，

1. Input Guardrail
2. Output Guardrail
3. Tool Input Guardrail
4. Tool Output Guardrail

を区別できる．

出典：[OAI-04]

---

## 5.2 Input Guardrail

**Input Guardrail**は，Agentへ渡された初期入力を検査する．

利用例としては，

- 個人情報が入力されていないか
- 業務対象外の質問ではないか
- Prompt Injectionらしい入力ではないか
- 禁止された依頼ではないか

などが考えられる．

条件違反時には**tripwire**を発火させられる．

### Tripwireとは

**Tripwire**は，Guardrailが「この処理を継続させるべきではない」と判断したことをSDKへ通知し，Agentの実行を停止させる仕組みである．

### 重要な制約

OpenAIの公式ドキュメントでは，Agent chainに対するInput Guardrailは**最初のAgent**にのみ実行されると説明されている．したがって，複数AgentをHandoffでつないだ場合に，すべてのAgentの入力へ自動的に同一Guardrailが適用されると解釈してはいけない．

出典：[OAI-04]，[OAI-05]

---

## 5.3 Output Guardrail

**Output Guardrail**は，Agentが生成した最終出力を検査する．

例えば，

- 個人情報の漏洩
- 機密情報の出力
- 禁止された回答
- Required formatへの不適合

などを確認できる．

こちらも基本的には，最終出力を生成するAgentに対して実行される．

### 0.22.0での重要な変更

OpenAI Agents SDK 0.22.0では，Output Guardrailがterminal function toolの最終出力をblockした場合のデータ分離が強化された．安全に履歴を再構築できる場合，元の`function_call_output` payloadは固定文言に置換される．安全に再構築できない形状の場合は，現在のresponse suffixを破棄する処理が導入されている．

これは，**Guardrailで拒否したデータがSession historyやRunState等へそのまま残存することを防ぐ方向の変更**と理解できる．

出典：[OAI-01]

---

## 5.4 Tool Input Guardrail

**Tool Input Guardrail**は，LLMがToolを実行しようとした際，Toolに渡される引数を実行前に検査する．

概念例：

```text
LLM
 ↓
delete_file("/important/master.csv")
 ↓
Tool Input Guardrail
 ↓
重要ファイルなので拒否
 ↓
Toolを実行しない
```

Tool Input Guardrailは，危険操作や不正な引数をTool実行前に防ぐ用途に利用できる．

---

## 5.5 Tool Output Guardrail

**Tool Output Guardrail**は，Toolが返した結果をLLMへ戻す前後の段階で検査する仕組みである．

例えば，データベース検索Toolが個人情報を大量に返した場合，

```text
Database Tool
 ↓
個人情報を含むResult
 ↓
Tool Output Guardrail
 ↓
拒否／置換
 ↓
LLM
```

のような処理を設計できる．

### 適用範囲に注意

公式ドキュメントでは，Tool Guardrailは`function_tool`等で作成する**FunctionTool**に適用され，すべての種類のToolへ無条件に適用されるわけではないことが説明されている．

出典：[OAI-04]

---

# 6．OpenAI：Toolの利用可否を制御する

## 6.1 `is_enabled`

FunctionTool等では，`is_enabled`を利用して，実行時のContextに応じてToolをAgentへ公開するかどうかを変更できる．

例：

```text
管理者ユーザー
   → delete_record Toolを公開

一般ユーザー
   → delete_record Toolを非公開
```

これにより，ユーザー属性や環境に応じた**Tool visibility**を実現できる．

### Tool visibilityとは

**Tool visibility**とは，LLMからそのToolが「利用可能なToolとして見えているか」を制御することである．Toolそのものの最終的な認可とは区別する必要がある．

OpenAIのContext Managementドキュメントは，`FunctionTool.is_enabled`やMCP tool filter等について，**モデルが生成するTool引数や保護対象Resourceへのアクセスを認可する仕組みの代替ではない**と明記している．最終的なAuthorizationはTool実装，Tool Input Guardrail，approval，MCP server側等でも実施する必要がある．

これは企業利用で非常に重要な点である．

出典：[OAI-06]，[OAI-07]

---

# 7．OpenAI：Human-in-the-loop

## 7.1 Human-in-the-loopとは

**Human-in-the-loop（HITL）**とは，Agentだけで処理を完結させず，重要な操作の途中で人間の承認・判断を挟む設計である．

例えば，

```text
Agent
 ↓
「顧客へ返金する」
 ↓
一時停止
 ↓
担当者が確認
 ├─ Approve → Tool実行
 └─ Reject  → Toolを実行しない
```

とできる．

---

## 7.2 `needs_approval`

OpenAI Agents SDKでは，Toolに`needs_approval=True`を設定することで，Tool実行前に承認を要求できる．

また，単純なTrue／Falseだけでなく，呼び出し内容に応じて承認要否を動的に決定できる．

例えば，

```text
read_order
→ 自動実行

refund_order(金額 < 1,000円)
→ 自動実行

refund_order(金額 >= 1,000円)
→ 人間承認
```

といった設計が可能である．

承認が必要なTool callが発生すると，runは中断状態となり，`RunResult.interruptions`等を通して承認対象を取得し，approve／reject後に再開できる．

公式ドキュメントでは，FunctionToolだけでなく，`Agent.as_tool()`，Shell Tool，Apply Patch Tool，MCP等にも関連する承認機構が説明されている．

出典：[OAI-08]

---

# 8．OpenAI：MCPのガバナンス

## 8.1 MCPとは

**MCP（Model Context Protocol）**は，AIアプリケーションと外部Tool・データソースを接続するためのオープンな標準である．

MCPを利用すると，Agentが外部のMCP Serverを介してToolを利用できる．一方，接続先が増えるため，どのMCP ServerとどのToolを許可するかがガバナンス上重要になる．

---

## 8.2 Tool Filtering

OpenAI Agents SDKでは，MCP Toolについて，

- 許可するTool
- blockするTool
- Contextに応じた動的Filter

を設定できる．

ただし，前述のとおりFilterは主として**Agentへ見せるToolを選ぶ仕組み**であり，MCP Server上の保護対象データに対する最終認可を置き換えるものではない．

---

## 8.3 MCP Approval

MCP Toolについても，`require_approval`等によりToolの実行前承認を設定できる．

したがって，OpenAI側ではMCPについて，

```text
MCP Server
    ↓
Tool Filter
    ↓
Agentから利用可能
    ↓
Approval
    ↓
MCP Tool実行
```

のように複数段階で制御できる．

公式ドキュメントは，MCP利用時には信頼できるServerを使用し，least privilegeを適用し，機密tokenをURLに埋め込まないことなども推奨している．

### Least privilegeとは

**Least privilege（最小権限）**とは，ユーザーやAgentへ業務遂行に必要な最小限の権限だけを与える原則である．

出典：[OAI-09]

---

# 9．OpenAI：実行量を制御する

Agentでは，「危険な操作を防ぐ」だけでなく，「いつまでもAgent Loopが続く」「大量のTokenを消費する」といったリソース面のリスクも管理する必要がある．

---

## 9.1 `max_turns`

`Runner.run()`等には`max_turns`がある．公式APIリファレンスでは，**1 turnは1回のAI invocationであり，その中で発生するTool callを含む**と説明されている．

設定されたturn数を超えると，通常は`MaxTurnsExceeded`が発生する．

```python
result = await Runner.run(
    agent,
    input="...",
    max_turns=10,
)
```

この機能は，

- 無限に近いAgent Loop
- 想定以上のAPI呼び出し
- 想定以上のTool反復

を抑制する一つの手段となる．

ただし，**turn数はToken数や金額そのものではない**．1 turnの入出力が非常に長ければ，少ないturn数でもToken消費量は大きくなり得る．

出典：[OAI-03]，[OAI-10]

---

## 9.2 `ModelSettings.max_tokens`

OpenAI Agents SDKの`ModelSettings.max_tokens`は，モデルが生成する**1回のmodel callの最大output token数**を設定するための項目である．

重要なのは，これはAgent Run全体のToken上限ではないことである．

```text
Agent Run
├─ Model Call 1 → max_tokensの対象
├─ Tool
├─ Model Call 2 → max_tokensの対象
├─ Tool
└─ Model Call 3 → max_tokensの対象
```

したがって，

- `max_turns`：Agent Loopの回数を抑える
- `max_tokens`：各Model Callの出力量を抑える

という役割の違いがある．

出典：[OAI-11]

---

# 10．OpenAI：Token Usageの計測

## 10.1 Usage

OpenAI Agents SDKはrun全体の利用量を`Usage`として追跡する．公式ドキュメントでは，次のような情報が示されている．

- `requests`
- `input_tokens`
- `output_tokens`
- `total_tokens`
- `request_usage_entries`
- cached token関連情報
- cache write token関連情報
- reasoning token関連情報

`request_usage_entries`を利用すると，run全体の合計だけでなく，各request単位のusageを確認できる．

これは，

- Agentごとの利用量分析
- 異常なToken消費の検出
- Cost計算
- Context管理

などに利用できる．

出典：[OAI-12]

---

## 10.2 Usageは「計測」であり「自動停止」とは別

`Usage`でToken数を取得できるからといって，自動的に「合計50,000 tokensになったらrunを停止する」というhard limitになるわけではない．

OpenAI Agents SDK 0.22.0の公開APIを調査した範囲では，Claude Agent SDKの`max_budget_usd`に直接対応する**run単位のUSD予算停止パラメータは確認できなかった**．

したがって，OpenAI Agents SDKで「1タスクあたり最大○ドル」等の独自Policyを強制したい場合は，

- Usageを計測する
- 利用モデルの価格と照合する
- application側で予算状態を保持する
- `max_turns`やmodel output limit等も併用する
- 必要に応じてrunを停止／再開する

などの設計を検討する必要がある．

ここでの記述は「OpenAIでコスト上限を設定できない」という意味ではない．後述する通り，**OpenAI API PlatformにはOrganization／Projectレベルの支出上限が存在する**．あくまで「Agents SDK 0.22.0のrun単位APIとして，Claudeの`max_budget_usd`と同等の専用パラメータを確認できない」という意味である．

---

# 11．OpenAI：TracingとAudit

## 11.1 Tracingとは

**Tracing**とは，Agentがどのような処理経路をたどったかを記録・追跡する仕組みである．

例えば，

```text
User Request
   ↓
Agent A
   ↓
LLM Call
   ↓
Tool X
   ↓
Handoff
   ↓
Agent B
   ↓
Final Output
```

という実行を後から追跡できる．

OpenAI Agents SDKにはBuilt-in Tracingがあり，公式ドキュメントではTracingはデフォルトで有効とされている．Agent，generation，function tool，guardrail，handoff等がTrace／Spanとして記録される．

### Spanとは

**Span**とは，Trace内の一つの処理区間である．例えば「LLMを1回呼んだ」「Toolを1回呼んだ」といった単位をSpanとして記録し，複数Spanをまとめたものが一連のTraceになる．

出典：[OAI-13]，[OAI-14]

---

## 11.2 機密データとTracing

TracingはAuditやDebugに有用である一方，PromptやTool入出力を記録すると，ログ自体に機密情報が含まれる可能性がある．

OpenAI Agents SDKでは`trace_include_sensitive_data`により，sensitive dataをTraceへ含めるかを設定できる．公式APIリファレンスでは，Generation SpanがLLM input/output，Function SpanがTool input/outputを保持し得ることが説明されている．

したがって，企業利用では「Traceを有効にするか」だけではなく，

- 何をTraceへ保存するか
- 誰がTraceを閲覧できるか
- 何日保存するか
- 個人情報を含めてよいか

まで決める必要がある．

出典：[OAI-15]

---

## 11.3 Lifecycle Hooks

**Hook**とは，Agentの特定イベント発生時にアプリケーション側の処理を呼び出すための仕組みである．

OpenAI Agents SDKでは，例えば，

- `on_agent_start`
- `on_agent_end`
- `on_llm_start`
- `on_llm_end`
- `on_tool_start`
- `on_tool_end`
- `on_handoff`

などのLifecycle Hookが提供されている．

これにより，

- 独自Audit Log
- Metrics
- 外部Observability基盤への送信
- 異常監視

などを実装できる．

ただし，Hookは「存在するだけで自動的にSecurity Policyを強制する」仕組みではない．Hookを使って何を記録し，何を拒否するかはアプリケーション設計に依存する．

出典：[OAI-16]

---

# 12．OpenAI：Sandbox Agents

## 12.1 Sandboxとは

**Sandbox**とは，Agentがファイル操作やcommand実行を行う環境を，ホスト環境からある程度分離する仕組みである．

OpenAI Agents SDK 0.22.0のドキュメントには**Sandbox Agents**が存在し，Beta機能として提供されている．Sandbox Agentは，persistent workspace上でファイル検索，編集，command実行，artifact作成等を行える．

出典：[OAI-17]

---

## 12.2 ManifestとFilesystem Permissions

Sandbox Agentでは，**Manifest**によってSandboxへ配置するファイルやDirectory等を定義する．

Manifest内のentryには`Permissions`を設定でき，owner／group／otherに対してRead，Write，Execute等のfilesystem permissionを設定できる．

ただし，OpenAIの公式ドキュメントは重要な注意として，Sandboxの`Permissions`は**Sandbox内にmaterializeされるfileのfilesystem permissionであり，モデルのTool承認PolicyやAPI credentialの認可とは別物**と説明している．

つまり，

```text
Filesystem Permission
≠
Tool Approval
≠
API Authorization
```

である．

出典：[OAI-18]

---

## 12.3 `run_as`

Sandbox内でTool操作を行うUser identityを`run_as`で指定できる．

これにより，Sandbox内のFilesystem permissionと実行Userを組み合わせられる．

---

## 12.4 Network

Docker Sandboxでは`network_mode="none"`を設定することでNetwork accessを無効化できる．公式ドキュメントでは，明示的にサポートされるNetwork modeとして`"none"`が説明されている．

したがって，少なくとも，

```text
Agent
 ↓
Docker Sandbox
 ↓
network_mode="none"
 ↓
外部Networkなし
```

という分離構成が可能である．

出典：[OAI-19]

---

# 13．OpenAI API Platform側のガバナンス

ここまでの機能は主にAgents SDKの機能であった．一方，OrganizationやProject全体を管理する機能はOpenAI API Platform側に存在する．

## 13.1 Project

OpenAI API PlatformではProject単位で，

- member／role
- API key
- model usage
- rate limits
- usage
- spend limit

等を管理できる．

出典：[OAI-20]

---

## 13.2 Spend Limit

2026年8月末時点のOpenAI公式Help Centerでは，OrganizationとProjectの両方について，月間API spend limitを設定できると説明されている．

さらに最新の説明では，

- **alertのみのSpend control**
- **API requestを停止させるhard spend limit**

の両方が存在する．Hard limitに到達した場合，`organization_spend_limit_exceeded`や`project_spend_limit_exceeded`等のerrorが返り得る．

一方，同じProject管理ページ内には従来のsoft thresholdに関する説明も残っているため，設定時にはUI上で「alert」と「enforced hard limit」のどちらを利用しているかを確認すべきである．

出典：[OAI-20]，[OAI-21]

---

## 13.3 Usage APIとCosts API

OpenAI APIにはUsage APIとCosts endpointが存在する．公式API Referenceは，UsageとCostが記録方法の差により完全一致しない場合があるため，**financial purposeではCosts endpointまたはUsage DashboardのCosts tabを利用することを推奨**している．

これは，Agents SDK内のToken Usageから概算Costを計算する方法と，請求・会計上のCost確認を区別すべきことを意味する．

出典：[OAI-22]

---

# 14．Claude Agent SDK 0.2.144

## 14.1 基本構造

Claude Agent SDK for Pythonは，Claude Codeのagent loop，Tool，context management等をプログラムから利用するためのSDKである．PyPIの0.2.144ページでは，Claude Code CLIがpackageにbundleされること，`query()`や`ClaudeSDKClient`を利用できることが確認できる．

概念的には，

```text
Python Application
      ↓
Claude Agent SDK
      ↓
Bundled Claude Code CLI
      ↓
Claude
      ↓
Tools / MCP / Files / Bash ...
```

という構造を持つ．

出典：[ANT-01]，[ANT-03]

---

# 15．Claude：Permission System

## 15.1 Permissionとは

**Permission**は，ClaudeがToolを実行しようとしたときに，その操作を許可するか，拒否するか，人間へ確認するかを決定する仕組みである．

Claude Agent SDKでは，Tool実行に対するPermission systemが中心的なガバナンス機能となる．

---

## 15.2 Permission評価の考え方

Claudeの公式Permission guideでは，概ね次のような評価レイヤーが説明されている．

1. Hooks
2. Deny rules
3. Permission mode
4. Allow rules
5. `can_use_tool`

特に重要なのは，**Deny ruleが強い優先度を持つ**ことである．また，Toolが事前承認されている場合は，`can_use_tool`まで到達しないケースがある．

出典：[ANT-04]

---

## 15.3 `allowed_tools`の誤解に注意

`allowed_tools`という名前から，「ここに書いたTool以外を使用できなくするallowlist」と誤解しやすい．

しかし，Claude Agent SDK 0.2.144のPyPI READMEには，`allowed_tools`は**listed toolsをauto-approveするpermission allowlistであり，unlisted toolをTool setから削除するものではない**と明記されている．

つまり，

```python
allowed_tools=["Read", "Write"]
```

としても，

```text
Read  → 事前承認
Write → 事前承認
Bash  → 必ず消える，とは限らない
```

ということである．

Toolをblockしたい場合は`disallowed_tools`等を利用する．

これはClaude Agent SDKをガバナンス用途で利用する際の非常に重要な注意点である．

出典：[ANT-01]，[ANT-05]

---

## 15.4 `disallowed_tools`

`disallowed_tools`はToolをdenyするための設定である．現在の公式Python API Referenceでは，

- `"Bash"`のようなbare tool nameを指定するとTool自体をContextから除外
- `"Bash(rm *)"`のようなscoped ruleでは，Tool自体は残し，該当callをdeny

と説明されている．Scoped denyは`bypassPermissions`を含むpermission modeでも適用されると記載されている．

出典：[ANT-05]

---

# 16．Claude：Permission Mode

**Permission Mode**とは，未確定のTool操作をどのように扱うかをまとめて変更する実行モードである．

公式ドキュメントで確認できる主要なmodeには次がある．

| Mode | 概要 |
|---|---|
| `default` | 通常のPermission flowを使用 |
| `dontAsk` | 事前承認されていない操作をAskせずdenyする方向のmode |
| `acceptEdits` | File edit等を自動承認する用途 |
| `plan` | Read-only中心のPlanning用途 |
| `bypassPermissions` | Permission checkをbypassする高権限mode |

`bypassPermissions`はガバナンス上特に注意が必要である．便利さのために全面的に利用すると，Permission layerを迂回する可能性があるため，本番運用では適用範囲を慎重に設計する必要がある．

> 注：Permission modeの型・surfaceはSDK更新で変化している．本レポートでは0.2.144までに確認できる主要modeを中心に記載し，後続版における追加modeの挙動までは0.2.144の仕様として断定しない．

出典：[ANT-04]，[ANT-05]

---

# 17．Claude：Hooks

## 17.1 Hookとは

Claude Agent SDKにおける**Hook**は，Claude自身ではなく，Claude Code application側がAgent Loopの特定地点で呼び出すcallbackである．

公式ドキュメントでは，Hooksの用途として，

- dangerous operationをblock
- Tool callをaudit
- Tool input／outputを変換
- Human approvalを組み込む
- Lifecycleを追跡

などが説明されている．

出典：[ANT-06]

---

## 17.2 Python SDKで確認できる主要Hook

公式Python API Referenceでは次のHook Eventが列挙されている．

- `PreToolUse`
- `PostToolUse`
- `PostToolUseFailure`
- `UserPromptSubmit`
- `Stop`
- `SubagentStop`
- `PreCompact`
- `Notification`
- `SubagentStart`
- `PermissionRequest`

出典：[ANT-05]

---

## 17.3 `PreToolUse`

**PreToolUse Hook**はTool実行前に呼ばれる．

ここでTool名や入力を検査し，

- allow
- deny
- ask

等の判断を返すことで，危険な操作を制御できる．

概念例：

```text
Claude
 ↓
Bash("rm -rf /important")
 ↓
PreToolUse Hook
 ↓
DENY
```

OpenAIにおけるTool Input Guardrailと目的が近い部分があるが，仕組み・APIは同一ではない．

---

## 17.4 `PostToolUse`

**PostToolUse Hook**はToolの実行後に利用できる．

例えば，

- Toolの実行結果をAudit Logへ記録
- 出力に機密情報が含まれていないか確認
- 追加情報をClaudeへ渡す

などを実装できる．

OpenAIのTool Output Guardrailと近い用途に使えるが，ClaudeではGuardrailという専用抽象ではなく，Hookを用いた実装が中心である．

---

# 18．Claude：Human-in-the-loop

## 18.1 `can_use_tool`

Claude Agent SDKでは，Tool実行に人間判断が必要になった場合，`can_use_tool` callbackを利用できる．

Callbackでは，

- approve
- inputを変更してapprove
- reject
- alternativeを提示

などが可能である．

実行イメージ：

```text
Claude
 ↓
Tool Request
 ↓
Permission Rules / Hooks
 ↓
人間判断が必要
 ↓
can_use_tool
 ↓
Approve / Reject
```

公式ドキュメントでは，Hookによって先にallow／denyできる場合があり，事前承認済みToolでは`can_use_tool`が呼ばれないことがある．

出典：[ANT-07]，[ANT-05]

---

# 19．Claude：Sandboxと実行環境の分離

## 19.1 `SandboxSettings`

Claude Agent SDKのPython APIには`SandboxSettings`があり，command sandboxingやNetwork restrictionを構成できる．

Sandboxは，AgentにBash等を許可する場合に，「Agentが直接ホスト環境全体を操作する」状態を避けるための重要な防御層である．

出典：[ANT-05]，[ANT-08]

---

## 19.2 Network

ClaudeのSandbox設定ではNetwork関連設定を行える．一方，公式ドキュメント上，Network Sandboxがすべての種類のNetwork accessを自動的に一括制御するとは限らず，例えばWebFetch等はPermission rule側で制御される場合がある．

したがって，

```text
Sandbox Network Rule
+
Tool Permission
+
Deployment Network Policy
```

を分離して考える必要がある．

---

## 19.3 Defense in Depth

AnthropicのSecure Deployment guideは，Agentを本番導入する場合に**Defense in Depth**を推奨している．

### Defense in Depthとは

**Defense in Depth（多層防御）**とは，一つのSecurity機能だけに依存せず，

- Container isolation
- Filesystem restriction
- Network restriction
- Credential isolation
- Permission
- Human approval

など複数の防御層を組み合わせる考え方である．

特にAgentはToolを通して実環境へ作用できるため，「Promptで禁止したから安全」と考えるべきではない．

出典：[ANT-08]

---

# 20．Claude：MCP

Claude Agent SDKもMCP Serverを利用できる．

MCP ToolはPermission systemの対象となり，Tool名は一般に`mcp__<server>__<tool>`の形式で扱われる．必要なMCP Toolのみを事前承認することができる．

また，現在のPython API Referenceには`strict_mcp_config`があり，Trueの場合，programmatically渡したMCP serverだけを使用し，Projectの`.mcp.json`，User settings，Plugin経由のMCP Server等を無視する設定が説明されている．

このような設定は，「開発者が想定していないMCP Serverが環境設定から追加される」ことを防ぐ設計に利用できる．

ただし，MCP Server自体のResource Authorizationも別途必要であり，SDK側のTool permissionだけを最終認可と考えるべきではない．

出典：[ANT-05]，[ANT-09]

---

# 21．Claude：Settingsの分離

Claude Agent SDKにはUser／Project／Local等のSetting sourceがあり，`setting_sources`によって読み込む設定を制御できる．

これは，あるDeveloperのローカル設定が意図せず本番Agentへ影響することを避けるうえで重要である．

ただし，Managed Policy等，programmatic optionとは別の高優先度設定が存在するため，どのLayerの設定が最終的に適用されるかを理解して運用する必要がある．

出典：[ANT-10]

---

# 22．Claude：File Checkpointing

`enable_file_checkpointing=True`により，SDKが対応するFile edit操作について変更状態を追跡し，巻き戻しに利用できる．

これは**誤操作を事前に防止するPermissionではなく，変更後のRecoveryを支援する機能**である．

公式ドキュメントでは，Write／Edit等で行われた変更の追跡と，Bash command経由の変更等には制約があることが説明されている．

したがって，

```text
Permission / Hook
→ 事故を防ぐ

Checkpointing
→ 事故後の復旧を助ける
```

という役割分担で考えるべきである．

出典：[ANT-11]

---

# 23．Claude：`max_turns`

`ClaudeAgentOptions.max_turns`は，Agentic turnの最大数を設定する．現在の公式Python API Referenceでは「Maximum agentic turns（tool-use round trips）」と説明されている．

```python
options = ClaudeAgentOptions(
    max_turns=10,
)
```

Agent Loopが必要以上に長く続くことを抑える基本的な制御となる．

出典：[ANT-05]

---

# 24．Claude：`max_budget_usd`

## 24.1 概要

Claude Agent SDKには，OpenAI Agents SDK 0.22.0との比較で特に重要な`max_budget_usd`がある．

```python
options = ClaudeAgentOptions(
    max_budget_usd=1.0,
)
```

公式Python API Referenceでは，**client-side cost estimateが指定USD値に到達したときqueryを停止する**と説明されている．

`max_budget_usd`は0.1.6で追加されたことが公式CHANGELOGに記載されているため，0.2.144より前から存在することを確認できる．

出典：[ANT-05]，[ANT-12]

---

## 24.2 厳密な請求額Hard Capではない

ここは非常に重要である．

Anthropicの公式exampleでは，Budget checkは各API call完了後に行われるため，**最終Costが指定Budgetを1 API call分程度超える可能性**が説明されている．

したがって，

```text
max_budget_usd = 1.00
```

は，「請求額が数学的に絶対1.00 USDを超えない」という意味ではない．

さらに，判定に使われる`total_cost_usd`自体もclient-side estimateである．したがって，財務上の正式請求確認にはPlatform側のUsage／Cost機能を利用する必要がある．

出典：[ANT-13]，[ANT-14]

---

# 25．Claude：Token UsageとCost Tracking

Claude Agent SDKでは，現在の公式Cost Tracking guideで，

- AssistantMessage単位のusage
- `ResultMessage`
- `total_cost_usd`
- model別usage／cost

等を取得できることが説明されている．

Usageにはinput／outputやcache関連のToken情報が含まれる．

### 重要な注意

`total_cost_usd`は**client-side estimate**である．公式ドキュメントは，価格変更，未知のmodel，Billing rule等によって実際の請求額とずれる可能性があるため，end-user billingやfinancial decisionのsource of truthとして利用しないよう説明している．

出典：[ANT-14]

---

# 26．Claude：`task_budget`

## 26.1 `task_budget`とは

Claude Agent SDKには`task_budget`がある．これは0.1.51で追加されたことが公式CHANGELOGから確認できるため，0.2.144にも含まれる機能である．

現在のPython API Referenceでは，

```python
ClaudeAgentOptions(
    task_budget={"total": 50000}
)
```

のように設定し，API側の`output_config.task_budget`へ送信すると説明されている．

出典：[ANT-05]，[ANT-15]

---

## 26.2 通常のToken Limitとの違い

Anthropic PlatformのTask Budget公式ドキュメントでは，Task BudgetはAgentic Loop全体について，

- Thinking
- Tool call
- Tool result
- Output

等を含むToken BudgetをClaude自身に認識させる仕組みと説明されている．

モデルは残Budgetのcountdownを認識し，残量に応じて作業の優先順位を調整し，終了に向けて自己調整する．

出典：[ANT-16]

---

## 26.3 `task_budget`はHard Capではない

**最重要点である．**

Anthropicは公式ドキュメントで，Task Budgetを**advisory，not enforced**と明記している．

### Advisory Budgetとは

**Advisory Budget**とは，「このBudgetを目安として行動せよ」とモデルへ知らせる制御であり，実行基盤が必ずその値で機械的に切断するHard Capとは異なる．

Claudeは処理の途中ではBudgetを多少超えることがある．

Anthropicは，Hardな1-request output token上限には`max_tokens`を利用し，Task Budgetと組み合わせることを説明している．

したがって，

```text
task_budget
→ Agent Loop全体に対する自己調整用のSoft / Advisory Budget

max_tokens
→ 各API requestの出力を止めるHard Ceiling

max_budget_usd
→ client-side estimated USDを基準にqueryを停止
```

という違いを理解する必要がある．

出典：[ANT-16]

---

# 27．Claude：ObservabilityとAudit

## 27.1 OpenTelemetry

Claude Agent SDK／Claude Code runtimeはOpenTelemetryによるObservabilityを利用できる．

### OpenTelemetryとは

**OpenTelemetry（OTel）**は，分散システムのTrace，Metric，Log等を標準的な形式で収集・転送するためのオープンなObservability frameworkである．

Claudeの公式Observability guideでは，SDKが起動するClaude Code CLIのinstrumentationを利用し，

- Token／Cost
- Session
- Tool decision
- Event
- Trace

等をObservability backendへ送れることが説明されている．

出典：[ANT-17]

---

## 27.2 Content Logging

PromptやTool result等をLogに残すとAuditには役立つが，機密情報を含むリスクがある．

AnthropicのObservabilityドキュメントでは，contentに関するTelemetryは明示的に設定して利用する設計となっており，何を記録するかを環境設定で調整できる．

OpenAI同様，

```text
ログが多い
→ Auditしやすい
→ 機密情報が残るリスクも増える
```

というtrade-offがある．

出典：[ANT-17]

---

# 28．Claude Platform側のCost／Rate Governance

SDK内の`max_budget_usd`とは別に，Claude Platform側にもOrganization／Workspace単位の利用制御がある．

公式Rate Limitsドキュメントでは，

- Organizationのmonthly spend limit
- Workspace単位のcustom spend limit
- Requests per minute
- Input Tokens per minute
- Output Tokens per minute

等が説明されている．

### Rate Limitとは

**Rate Limit**とは，一定時間内に送信できるRequest数やToken数を制限する仕組みである．月間Cost Limitとは異なり，「短時間に大量アクセスすること」を制御する目的が中心である．

出典：[ANT-18]

---

## 28.1 Usage & Cost API

AnthropicはAdmin APIとしてUsage／Costを取得する機能を提供している．正式なCost分析や組織レベルの集計には，SDKの`total_cost_usd`推定値だけではなく，Platform側のUsage & Cost情報を利用することが適切である．

出典：[ANT-19]

---

# 29．Token・Cost Governanceを比較する

この部分は企業利用で特に重要であるため，制御の「種類」を分けて比較する．

| 制御 | OpenAI Agents SDK 0.22.0 | Claude Agent SDK 0.2.144 |
|---|---|---|
| Input Token計測 | ○ | ○ |
| Output Token計測 | ○ | ○ |
| Cache関連Token計測 | ○ | ○ |
| Reasoning関連Usage | ○ | Model／API構成に依存 |
| Request単位Usage | ○ | ○ |
| Run全体Usage | ○ | ○ |
| 1回のModel Output上限 | `ModelSettings.max_tokens` | API側`max_tokens`等 |
| Agent Turn上限 | `max_turns` | `max_turns` |
| Agent Loop全体のAdvisory Token Budget | 専用同等項目を確認できない | `task_budget` |
| SDK内のUSD Cost estimate | Usageから別途算出可能 | `total_cost_usd` |
| SDK run単位のUSD停止 | 専用同等項目を確認できない | `max_budget_usd` |
| Organization／Project等のSpend Limit | Platform側 | Platform側 |
| 請求確認用Cost API | Costs endpoint | Usage & Cost API |

---

# 30．「上限」という言葉を4種類に分ける

Token／Cost管理では「Budget」「Limit」「Cap」をすべて同じものとして扱うと誤解が生じる．

## 30.1 Hard Token Cap

一定のToken生成量に到達すると，システムが生成を終了させるもの．

例：

- Model requestの`max_tokens`

---

## 30.2 Turn Cap

Agent LoopのAI invocation／round trip回数を制限するもの．

例：

- OpenAI `max_turns`
- Claude `max_turns`

これはToken数そのものではない．

---

## 30.3 Advisory Budget

モデルへ残Budgetを知らせ，自己調整させるもの．値を絶対に超えない保証ではない．

例：

- Claude `task_budget`

---

## 30.4 Estimated-cost Stop

Client側で推定Costを計算し，閾値に達したら後続処理を停止するもの．

例：

- Claude `max_budget_usd`

これは実請求額そのもののHard Capと完全には一致しない．

---

## 30.5 Platform Hard Spend Limit

OrganizationやProject等でtracked spendが閾値に到達すると，後続API Requestを拒否するもの．

例：

- OpenAI PlatformのOrganization／Project hard spend limit
- Claude PlatformのOrganization／Workspace spend controls

これは個々のAgent runの制御より上位のLayerである．

---

# 31．ガバナンス機能を処理フロー上に配置する

## 31.1 OpenAI Agents SDK

```text
User Input
   │
   ▼
Input Guardrail
   │
   ▼
Agent / LLM
   │
   ├─────────────┐
   │             │
   │        Tool visibility
   │        is_enabled / MCP filter
   │             │
   ▼             ▼
Tool Call ──→ Approval
   │             │
   ▼             ▼
Tool Input Guardrail
   │
   ▼
Tool Execution
   │
   ▼
Tool Output Guardrail
   │
   ▼
Agent / LLM
   │
   ▼
Output Guardrail
   │
   ▼
Final Output

全体を横断：
- max_turns
- ModelSettings.max_tokens
- Usage
- Tracing
- Lifecycle Hooks
- Sandbox
```

---

## 31.2 Claude Agent SDK

```text
User Input
   │
   ▼
UserPromptSubmit Hook
   │
   ▼
Claude
   │
   ▼
Tool Request
   │
   ▼
PreToolUse Hook
   │
   ▼
Deny Rules
   │
   ▼
Permission Mode
   │
   ▼
Allow Rules
   │
   ▼
can_use_tool / Human Approval
   │
   ▼
Tool Execution
   │
   ▼
PostToolUse Hook
   │
   ▼
Claude
   │
   ▼
Stop Hook / Result

全体を横断：
- max_turns
- max_budget_usd
- task_budget
- Usage / total_cost_usd
- Sandbox
- OpenTelemetry
```

この図は，各社公式仕様を理解しやすくするために本レポートで整理したものであり，各社がこの図そのものを公式アーキテクチャとして提示しているわけではない．

---

# 32．両SDKの特徴を整理する

## 32.1 OpenAI Agents SDKの特徴

公式APIから確認できる特徴をガバナンス観点で整理すると，

1. **Input／Output／ToolにGuardrailという明示的な検査概念がある**
2. `needs_approval`によるHuman-in-the-loopをToolに組み込める
3. MCP Tool FilteringとApprovalを利用できる
4. Built-in Tracingがあり，Agent実行を追跡しやすい
5. Usageをrun／request単位で収集できる
6. `max_turns`と`max_tokens`で実行量を一定範囲に抑えられる
7. Sandbox AgentでFilesystem／Shell等を分離できる
8. 0.22.0ではGuardrail rejection時のdata isolationが強化されている

一方，0.22.0の公開API調査では，Claudeの`max_budget_usd`のような**run単位USD予算停止専用パラメータは確認できない**．

---

## 32.2 Claude Agent SDKの特徴

1. **Permission systemがTool実行ガバナンスの中心にある**
2. `disallowed_tools`やPermission Mode等でTool操作を制御できる
3. `PreToolUse`等のHookで決定論的な検査・Auditを追加できる
4. `can_use_tool`によるHuman-in-the-loopを構成できる
5. `max_budget_usd`でrunの推定Costを基準に停止できる
6. `task_budget`で長いAgentic LoopにToken Budgetを認識させられる
7. Sandbox，Secure Deployment，Permissionを組み合わせた多層防御を構成できる
8. OpenTelemetryによる外部Observability基盤との統合が可能である

一方，`allowed_tools`は「それ以外をすべて禁止するTool whitelist」ではないため，名称だけから挙動を判断してはいけない．

---

# 33．SDK単体で何が不足するか

ここからは，公式仕様の列挙ではなく，**上記の調査結果から導く実務上の考察**である．

## 33.1 SDKごとにPolicyの記述方法が異なる

例えば，共通Policyとして，

> 「重要ファイルを変更・削除してはいけない」

を設定したいとする．

OpenAI Agents SDKでは，

- Tool visibility
- Tool Input Guardrail
- Tool approval
- Sandbox filesystem permission

等を組み合わせることになる．

Claude Agent SDKでは，

- Permission rule
- `disallowed_tools`
- `PreToolUse` Hook
- Sandbox
- Human approval

等を組み合わせることになる．

つまり，同じ組織Policyを適用する場合でも，SDKごとに実装方法が異なる．

---

## 33.2 Cost PolicyもSDK間で差がある

例えば，

> 「Agent 1回の処理は1 USDまで」

というPolicyを考える．

Claudeでは`max_budget_usd`という専用optionがある．ただしclient-side estimateであり，1 API call分の超過可能性がある．

OpenAI Agents SDK 0.22.0では，同等のrun-level USD parameterを確認できないため，

- Usage取得
- Model priceとの照合
- App側Budget管理
- Turn／Token limit
- Platform hard spend limit

等を組み合わせる必要がある．

---

## 33.3 「共通Policy Layer」が必要になる可能性

複数Vendor／複数Agent SDKを企業で同時利用する場合，SDK固有設定だけでPolicyを管理すると，

```text
会社Policy
├─ OpenAI用Policy実装
├─ Claude用Policy実装
├─ 別SDK用Policy実装
└─ ...
```

となり，Policyの重複・不整合が起こりやすい．

そこで，組織の共通PolicyをSDKより上位で定義し，

```text
                Enterprise Policy
        ┌──────────┼──────────┐
        │          │          │
   Action       Cost       Audit
   Policy       Policy     Policy
        │          │          │
        └──────────┼──────────┘
                   ↓
          SDK-specific Adapter
          ┌────────┴────────┐
          ↓                 ↓
 OpenAI Agents SDK   Claude Agent SDK
```

のようにSDK固有機能へ変換するLayerを設けることには合理性がある．

ただし，これはOpenAIまたはAnthropicが「必ず共通Policy Layerを導入すべき」と公式に要求しているという意味ではなく，**今回の比較結果から導かれる設計上の考察**である．

---

# 34．共通化を検討すべきPolicy領域

今回の比較から，共通Policyとして少なくとも以下を検討できる．

## 34.1 Action Policy

- 利用可能Tool
- 禁止Tool
- 禁止Command
- 書き込み可能Resource
- 外部API call可否

---

## 34.2 Data Policy

- 個人情報をLLMへ送信できるか
- 機密データを外部MCP Serverへ渡せるか
- Tool Resultをモデルへ戻す前にmaskするか
- TraceへPrompt／Tool Resultを保存してよいか

---

## 34.3 Approval Policy

- File readは自動許可
- File writeは条件付き
- Deleteは人間承認
- External communicationは人間承認
- 金銭操作は必ず人間承認

といったPolicyである．

---

## 34.4 Cost Policy

少なくとも次を別々に管理する必要がある．

- Max turns
- Per-call output token
- Per-task token target
- Per-run cost
- Per-user daily cost
- Per-project monthly cost
- Organization monthly cost

---

## 34.5 Audit Policy

- Agent ID
- User ID
- 使用Model
- Input
- Tool
- Tool arguments
- Tool result
- Approval result
- Token usage
- Cost
- Error
- Handoff
- Timestamp

等のうち，何を保存するかを決める．

ただし，Input／Tool Resultをそのまま保存すると機密情報がLogへ流出する可能性があるため，Data PolicyとAudit Policyを同時に設計する必要がある．

---

# 35．「SDK機能がある＝ガバナンスが完成」ではない理由

Guardrail，Hook，Permissionなどの仕組みは，**Policyを実装するためのメカニズム**であり，企業のPolicyそのものではない．

例えば`PreToolUse Hook`が存在しても，そのHookに，

```text
何を危険Commandとするか
```

が定義されていなければ，企業固有の制御は完成しない．

同様にInput Guardrailも，

```text
何を機密情報とするか
何を禁止するか
違反時に停止するか
```

を実装して初めて実際のPolicyになる．

したがって，

```text
SDK Governance Feature
        ↓
Policy Enforcement Mechanism

Enterprise Governance Policy
        ↓
何を許可／禁止／記録するか
```

は分けて考える必要がある．

---

# 36．実務で特に注意すべき誤解

## 36.1 「allowed_toolsに書いていないからClaudeは使えない」

**誤り．**

0.2.144のPyPI READMEは，`allowed_tools`はToolをauto-approveするものであり，unlisted ToolをToolsetから取り除くものではないと明記している．Blockには`disallowed_tools`等を利用する．

出典：[ANT-01]

---

## 36.2 「OpenAIのis_enabledでToolを隠したから認可は完了」

**不十分．**

OpenAI公式Context Managementは，Tool visibilityとResource Authorizationを区別している．Tool実装やGuardrail，approval，Server側authorizationを併用すべきである．

出典：[OAI-06]

---

## 36.3 「Claude task_budget=50000なら50000 Tokenで必ず止まる」

**誤り．**

Task Budgetはadvisoryであり，Hard Capではない．

出典：[ANT-16]

---

## 36.4 「Claude max_budget_usd=1なら請求額は絶対1 USD以下」

**誤り．**

Budget checkはAPI call後であり，1 call分程度超過する可能性がある．また，`total_cost_usd`はclient-side estimateである．

出典：[ANT-13]，[ANT-14]

---

## 36.5 「TracingをONにすればAuditは安全」

**不十分．**

Tracingは監査可能性を高めるが，PromptやTool Resultに機密情報がある場合，Logへの保存自体がData Governance上の問題になり得る．

出典：[OAI-15]，[ANT-17]

---

## 36.6 「SandboxがあるからTool Permissionは不要」

**誤り．**

Sandboxは実行環境のIsolationを提供するが，「業務上その操作を許可するべきか」というAuthorization／Approvalとは異なる．両者を組み合わせる必要がある．

出典：[OAI-18]，[ANT-08]

---

# 37．結論

OpenAI Agents SDK 0.22.0とClaude Agent SDK 0.2.144は，どちらもAgent Governanceに利用できる多くの機能を持つが，設計の中心は異なる．

OpenAI Agents SDKでは，

- Input／Output／Tool Guardrails
- Human-in-the-loop
- Tool visibility
- MCP filtering／approval
- Built-in Tracing
- Usage tracking
- Sandbox Agents

が主要な仕組みである．特にGuardrailを入力・出力・Toolの境界へ明示的に配置できる点が特徴的である．

Claude Agent SDKでは，

- Permission system
- `allowed_tools`／`disallowed_tools`
- Hooks
- `can_use_tool`
- Sandbox
- `max_turns`
- `max_budget_usd`
- `task_budget`
- Usage／Cost tracking
- OpenTelemetry

等が主要な仕組みである．特にTool PermissionとHooks，さらにrun-levelのestimated USD budgetを組み合わせられる点が重要である．

Token／Cost Governanceについては，「Token計測」「各requestの出力上限」「Agent turn上限」「Advisory Token Budget」「run-level Cost stop」「Organization／ProjectレベルのHard Spend Limit」を混同せず，それぞれ別の制御として設計する必要がある．

また，両SDKの機能は企業Policyを自動的に定義するものではない．複数SDKを利用する環境では，Action，Data，Cost，Approval，Audit等の共通Policyを上位で管理し，各SDK固有のGuardrail／Permission／Hook等へ対応付ける設計を検討する価値がある．

---

# 38．参考文献・一次情報

以下は，本レポートで主要根拠として利用した情報源である．Webドキュメントは更新されるため，**参照日は2026年8月31日**とする．

## OpenAI

### [OAI-01] OpenAI Agents SDK — Release process / changelog
- OpenAI
- 0.22.0のbreaking change，Output Guardrail rejection時のdata isolation，Usage checkpoint等
- https://openai.github.io/openai-agents-python/release/

### [OAI-02] OpenAI Agents SDK — Agents
- Agentの定義，Tools，Handoffs，Guardrails等
- https://openai.github.io/openai-agents-python/agents/

### [OAI-03] OpenAI Agents SDK — Running agents
- Runner，Agent Loop，`max_turns`
- https://openai.github.io/openai-agents-python/running_agents/

### [OAI-04] OpenAI Agents SDK — Guardrails
- Input Guardrail，Output Guardrail，Tool Guardrails，Tripwire
- https://openai.github.io/openai-agents-python/guardrails/

### [OAI-05] OpenAI Agents SDK — Runner API Reference
- `max_turns`の定義，Input Guardrailが最初のAgentにのみ適用されること等
- https://openai.github.io/openai-agents-python/ref/run/

### [OAI-06] OpenAI Agents SDK — Context management
- Contextを利用したPolicy，Tool exposureとauthorizationの違い
- https://openai.github.io/openai-agents-python/context/

### [OAI-07] OpenAI Agents SDK — Tools
- Toolの動的有効化等
- https://openai.github.io/openai-agents-python/tools/

### [OAI-08] OpenAI Agents SDK — Human-in-the-loop
- `needs_approval`，interruptions，approve／reject
- https://openai.github.io/openai-agents-python/human_in_the_loop/

### [OAI-09] OpenAI Agents SDK — Model Context Protocol (MCP)
- MCP，Tool filtering，approval，security considerations
- https://openai.github.io/openai-agents-python/mcp/

### [OAI-10] OpenAI Agents SDK — Runner API Reference
- 1 turnの定義，`MaxTurnsExceeded`
- https://openai.github.io/openai-agents-python/ja/ref/run/

### [OAI-11] OpenAI Agents SDK — Model settings
- `max_tokens`等
- https://openai.github.io/openai-agents-python/ref/model_settings/

### [OAI-12] OpenAI Agents SDK — Usage
- Input／Output／Total Tokens，request usage entries，cache／reasoning usage
- https://openai.github.io/openai-agents-python/usage/

### [OAI-13] OpenAI Agents SDK — Tracing
- Built-in Tracing
- https://openai.github.io/openai-agents-python/tracing/

### [OAI-14] OpenAI Agents SDK — Configuration
- Tracingのdefault等
- https://openai.github.io/openai-agents-python/config/

### [OAI-15] OpenAI Agents SDK — RunConfig / Tracing configuration
- `trace_include_sensitive_data`
- https://openai.github.io/openai-agents-python/ref/run/

### [OAI-16] OpenAI Agents SDK — Lifecycle
- RunHooks／AgentHooks
- https://openai.github.io/openai-agents-python/ref/lifecycle/

### [OAI-17] OpenAI Agents SDK — Sandbox Agents Quickstart
- Sandbox AgentsがBetaであること，persistent workspace等
- https://openai.github.io/openai-agents-python/sandbox_agents/

### [OAI-18] OpenAI Agents SDK — Sandbox concepts
- Manifest，Filesystem Permissions，`run_as`
- https://openai.github.io/openai-agents-python/sandbox/guide/

### [OAI-19] OpenAI Agents SDK — Sandbox clients
- Docker Sandboxの`network_mode="none"`
- https://openai.github.io/openai-agents-python/sandbox/clients/

### [OAI-20] OpenAI Help Center — Managing projects in the API platform
- Project role，rate limit，spend limit
- https://help.openai.com/en/articles/9186755

### [OAI-21] OpenAI Help Center — Troubleshooting API usage and spend limits
- Organization／Project hard spend limit，error code
- https://help.openai.com/en/articles/6614457

### [OAI-22] OpenAI API Reference — Usage / Costs
- Usage API，Costs endpoint，financial purposeでCostsを推奨する説明
- https://platform.openai.com/docs/api-reference/usage/

### [OAI-23] PyPI — openai-agents 0.22.0
- 対象versionのpackage page
- https://pypi.org/project/openai-agents/0.22.0/

---

## Anthropic / Claude

### [ANT-01] PyPI — claude-agent-sdk 0.2.144
- 対象versionのpackage page，release date，README，`allowed_tools`の挙動等
- https://pypi.org/project/claude-agent-sdk/0.2.144/

### [ANT-02] Anthropic GitHub Issue #1234
- PyPI 0.2.144とGitHub Releases表示の不整合に関する利用者報告
- **注意：公式仕様ではなくIssue報告である**
- https://github.com/anthropics/claude-agent-sdk-python/issues/1234

### [ANT-03] Claude Agent SDK — Overview
- SDKのagent loop，tools，context management等
- https://code.claude.com/docs/en/agent-sdk/overview

### [ANT-04] Claude Agent SDK — Configure permissions
- Permission evaluation，Permission Mode，allow／deny
- https://code.claude.com/docs/en/agent-sdk/permissions

### [ANT-05] Claude Agent SDK — Python Reference
- `ClaudeAgentOptions`，`max_turns`，`max_budget_usd`，`disallowed_tools`，Hooks，Sandbox，`task_budget`等
- https://code.claude.com/docs/en/agent-sdk/python

### [ANT-06] Claude Agent SDK — Hooks
- `PreToolUse`，`PostToolUse`，Audit，Block等
- https://code.claude.com/docs/en/agent-sdk/hooks

### [ANT-07] Claude Agent SDK — Handle approvals and user input
- `can_use_tool`，Human approval
- https://code.claude.com/docs/en/agent-sdk/user-input

### [ANT-08] Claude Agent SDK — Securely deploying AI agents
- Sandbox，Isolation，Least privilege，Defense in Depth
- https://code.claude.com/docs/en/agent-sdk/secure-deployment

### [ANT-09] Claude Agent SDK — MCP
- MCP ToolのPermission等
- https://code.claude.com/docs/en/agent-sdk/mcp

### [ANT-10] Claude Agent SDK — Modifying system prompts / settings related reference
- Setting sources，settings isolation
- https://code.claude.com/docs/en/agent-sdk/python

### [ANT-11] Claude Agent SDK — File checkpointing
- File change trackingとrewind
- https://code.claude.com/docs/en/agent-sdk/file-checkpointing

### [ANT-12] Claude Agent SDK Python — CHANGELOG
- `max_budget_usd`が0.1.6で追加された履歴
- `task_budget`が0.1.51で追加された履歴
- https://github.com/anthropics/claude-agent-sdk-python/blob/main/CHANGELOG.md

### [ANT-13] Claude Agent SDK Python — `max_budget_usd` official example
- API call後のbudget check，1 API call分程度の超過可能性
- https://github.com/anthropics/claude-agent-sdk-python/blob/main/examples/max_budget_usd.py

### [ANT-14] Claude Agent SDK — Track cost and usage
- `total_cost_usd`，Usage，client-side estimateのaccuracy caveat
- https://code.claude.com/docs/en/agent-sdk/cost-tracking

### [ANT-15] Claude Agent SDK Python — CHANGELOG
- `task_budget`追加履歴
- https://github.com/anthropics/claude-agent-sdk-python/blob/main/CHANGELOG.md

### [ANT-16] Claude Platform Docs — Task budgets
- Task Budgetの仕組み，Agentic Loop全体，AdvisoryでHard Capではないこと
- https://platform.claude.com/docs/en/build-with-claude/task-budgets

### [ANT-17] Claude Agent SDK — Observability with OpenTelemetry
- Metrics，Logs，Events，Traces
- https://code.claude.com/docs/en/agent-sdk/observability

### [ANT-18] Claude Platform Docs — Rate limits
- Organization／WorkspaceのSpend／Rate制御
- https://platform.claude.com/docs/en/api/rate-limits

### [ANT-19] Claude Platform Docs — Usage and Cost API
- Organization-levelのUsage／Cost取得
- https://platform.claude.com/docs/en/api/usage-cost-api

---

# 39．調査上の未確定事項・継続確認が必要な点

正確性を優先するため，以下は「存在しない」と断定せず，今回確認できた範囲を明記する．

1. **OpenAI Agents SDKのrun単位USD hard cap**
   - 0.22.0の公開API／公式ドキュメント上，Claudeの`max_budget_usd`と直接対応する専用parameterは確認できなかった．
   - OpenAI Platform側にはOrganization／Project spend limitが存在する．
   - 独自run-level cost policyはUsage等を用いてapplication側で構築可能であるが，その具体的な停止方式はアプリ設計に依存する．

2. **Claude `task_budget`のHard Limit性**
   - これは未確定ではなく，公式に**advisoryでありHard Capではない**ことを確認済みである．
   - 「Token budget」という名称だけから強制上限と解釈しないこと．

3. **Claude 0.2.144のRelease表示**
   - PyPIには0.2.144が存在する．
   - GitHub Releases表示との不整合がIssueで報告されている．
   - そのため，本レポートではTarget versionの存在はPyPIを根拠とし，GitHub Release表示の不整合は注記に留めた．

4. **Platformの料金・Limit値**
   - 料金，tier，default limit等は変更されやすいため，本レポートでは固定の金額・RPM値を極力記載していない．
   - 実運用前に各社Platformの最新設定画面・Pricingを再確認する必要がある．

---

# 40．要点だけを再掲

- OpenAI Agents SDKは**Guardrails，HITL，Tracing**が理解の中心となる．
- Claude Agent SDKは**Permissions，Hooks，Sandbox，Budget**が理解の中心となる．
- OpenAIの`is_enabled`やMCP Filterは**Tool visibility**であり，最終Resource Authorizationの代替ではない．
- Claudeの`allowed_tools`は**「それ以外を禁止」ではなく「指定Toolを事前承認」**である．
- OpenAIの`max_turns`と`max_tokens`は，それぞれTurn数と1回のModel Outputを制御する．
- Claudeの`max_budget_usd`はrun-level cost制御に有用だが，**client-side estimate**であり，1 API call分程度超過し得る．
- Claudeの`task_budget`はAgent Loop全体を意識させるToken Budgetだが，**advisoryでありHard Capではない**．
- 正式な請求・組織全体のCost Governanceには，各社Platform側のUsage／Cost／Spend Limitを併用する．
- Sandbox，Permission，Guardrail，Approval，Auditは役割が異なり，一つだけで全ガバナンスを代替できない．
- 複数Agent SDKを企業で利用する場合，共通PolicyをSDK固有機能へ変換する上位Layerを検討する合理性がある．

