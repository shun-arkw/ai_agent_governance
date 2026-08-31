# Agent Governance Toolkit 4.1.0 調査レポート
## ― ガバナンス機能，Cost / Token Governance，Open Policy Agent 1.19.1，Cedar連携 ―

- **調査日**：2026年8月31日
- **対象**：
  - Microsoft Agent Governance Toolkit（AGT）**v4.1.0**
  - Open Policy Agent（OPA）**v1.19.1**
  - `cedarpy` **v4.8.7**
    - `cedarpy 4.8.7`が利用するCedar Policy engineは**v4.8.2**
- **調査方針**：
  - AGTについては，可能な限り**GitHubのv4.1.0タグに固定されたREADME・ソースコード**を一次情報として利用する．
  - 現在の`main`ブランチの機能を，根拠なくv4.1.0の機能として扱わない．
  - 公式ドキュメントの説明とv4.1.0の実装に差が見える場合は，実際のv4.1.0コードパスを優先して記載する．
  - 「公式仕様として確認できる事実」と「そこから導かれる実務上の考察」を区別する．

---

# 1．Executive Summary

Agent Governance Toolkit（AGT）は，OpenAI Agents SDKやClaude Agent SDKのようにAgentそのものを構築するためのSDKとは役割が異なる．AGTの中心的な目的は，**Agentが実行しようとする操作をAgentの外側にある決定論的なコードで検査し，Policyに基づいて許可・拒否・承認要求・記録するためのガバナンスLayerを提供すること**である．

AGT v4.1.0のREADMEでは，Policy Engine，Identity，Audit Logを中心に，AgentのTool call等を実行前にinterceptし，Policy EngineがdenyしたActionはToolへ到達させない構造が説明されている．また，OpenAI Agents SDK向けMiddleware，Claude Code向けGovernance plugin等のFramework Integrationも示されている．[AGT-01]

AGT 4.1.0の主要機能は，概ね次の領域に整理できる．

| 領域 | 主な機能 |
|---|---|
| Policy | YAML / JSON Policy，Agent targeting，Scope，Conflict Resolution，Policy inheritance |
| Policy Decision | allow，deny，warn，require_approval，log |
| Lifecycle Control | `pre_input`，`pre_tool`，`post_tool`，`pre_output` |
| External Policy | OPA / Rego，Cedar |
| Identity / Trust | Agent identity，DID，Trust，Delegation |
| Human Oversight | Human Approval |
| Audit | Tamper-evident Audit，decision record |
| Runtime | Privilege ring，termination control，execution validation |
| SRE | SLO，Error Budget，Circuit Breaker，Chaos Engineering |
| Cost | `CostGuard` |
| Token | `TokenBudgetTracker`，`ContextScheduler`，`GovernancePolicy.max_tokens` |
| MCP | MCP Security Gateway，Tool security scanning |
| Compliance | OWASP verification，Policy lint，integrity check |
| Integration | OpenAI Agents SDK，LangGraph，CrewAI，AutoGen等 |

特に本調査で重点を置いた**Cost Governance**について，AGT 4.1.0の`CostGuard`は少なくとも次の粒度でCostを扱える．[AGT-03]

```text
1回のCost Event
      ↓
Task（task_id）
      ↓
Agent（agent_id）
      ↓
Agent × Day
      ↓
Organization × Month
```

`agent_id`ごとに，日次使用額，残予算，利用率，当日のTask数，平均Task Cost，Throttle状態，Kill状態等を保持できる．Organization側では全AgentのCostが月間Budgetに集約される．

ただし，非常に重要な制約がある．

1. **AGTの`CostGuard`はOpenAIやAnthropic等の請求額を自動取得しない．**
   - Application側が`estimated_cost`や`cost_usd`を渡す必要がある．
2. **`per_task_limit`は1つの`CostGuard` instance全体の共通値である．**
3. **`per_agent_daily_limit`もAgent作成時の共通初期値である．**
4. Agent別に使用額を追跡することはできるが，「Agent Aは$1/task，Agent Bは$5/task」という異なるper-task上限を1つの`CostGuard`へ宣言する専用APIはv4.1.0では確認できない．
5. `check_task()`はBudgetを予約しないadvisory pre-checkであり，並行実行時にovershootし得る．
6. Budget-criticalな経路には，checkとchargeを1 lock内で行う`check_and_charge()`が用意されている．
7. `record_cost()`はBudget checkなしでCostを記録するため，それ単独は事前Enforcementではない．
8. `CostGuard`のstateはPython object上に保持されており，このclass単体は永続Billing DBではない．

また，AGT 4.1.0のPolicy Engineは外部Policy EngineとのIntegrationを実装しており，Native Policyで決定しなかった場合，**OPA / Rego，その後Cedar**を評価するコードパスが存在する．[AGT-06]

したがって，OPAやCedarはAGTと無関係な周辺技術ではなく，**AGTのPolicyを企業の既存Policy-as-Code基盤へ接続するための選択肢**として位置付けられる．

---

# 2．AGTとは何か

## 2.1 Agent SDKとの違い

OpenAI Agents SDKやClaude Agent SDKは，主に次のようなAgent Runtimeを作るために利用する．

```text
LLM
 + Instructions
 + Tools
 + Agent Loop
 + Session
 + Handoff
      ↓
AI Agent
```

一方，AGTはAgentそのものの推論を担うのではなく，Agentが外部へActionを起こす境界などにガバナンスを追加する．

```text
OpenAI / Claude / LangGraph / CrewAI ...
                  │
                  ▼
               AI Agent
                  │
                  ▼
                 AGT
       ┌──────────┼──────────┐
       │          │          │
    Policy     Identity    Audit
       │          │          │
       └──────────┼──────────┘
                  ▼
                 Tool
```

AGT v4.1.0 READMEは，Policy enforcement，identity，sandboxing，SREをautonomous AI agent向けに提供すると説明している．また，Tool call等をdeterministic application codeでinterceptする設計を明示している．[AGT-01]

---

# 3．なぜAgentの外側にPolicyが必要なのか

AgentのPromptに，

```text
重要なファイルは変更・削除しないでください
```

と記述することと，

```text
delete_file Toolが呼ばれた
        ↓
Policy Engine
        ↓
Policy違反なのでDENY
        ↓
Toolを実行しない
```

ことは異なる．

前者はLLMへのInstructionであり，後者はApplication側のControlである．

AGTが重視しているのは後者である．v4.1.0 READMEでは，Prompt-level safetyをcontrol surfaceとして扱わず，PolicyにdenyされたActionをToolへ到達させない構成が説明されている．[AGT-01]

---

# 4．重要用語

## 4.1 Policy

**Policy**とは，「どのActionを，どの条件で，許可・拒否・承認要求するか」を表すRuleである．

---

## 4.2 Policy-as-Code

**Policy-as-Code**とは，組織ルールを自然言語文書だけで管理するのではなく，YAML，JSON，Rego，Cedar等の機械的に評価可能な形式で定義する考え方である．

---

## 4.3 PDPとPEP

外部Policy Engineを理解するために重要な概念である．

**PDP（Policy Decision Point）**は，「このActionを許可するか」を判断する場所である．

**PEP（Policy Enforcement Point）**は，PDPの判断に従い，実際にActionを通す／止める場所である．

```text
Agent
  │
  ▼
PEP ─── Policy Request ───► PDP
 │                           │
 │       Allow / Deny        │
 ◄───────────────────────────┘
 │
 ├─ Allow → Tool実行
 └─ Deny  → Block
```

OPA公式ドキュメントでも，OPAはPolicy decision-makingをPolicy enforcementから分離し，Softwareがstructured dataをOPAへ渡してdecisionを取得する構造を説明している．[OPA-02]

---

# 5．AGT 4.1.0のPackage構成

v4.0.0でPython packageが45個から5つのtop-level distributionへ統合され，v4.1.0タグのREADMEでも以下が確認できる．[AGT-01]

| Distribution | 主な内容 |
|---|---|
| `agent-governance-toolkit-core` | Policy engine，capability model，audit，MCP gateway，zero-trust identity，trust scoring，protocol bridges |
| `agent-governance-toolkit-runtime` | Privilege rings，Saga orchestration，termination control，execution plan validation |
| `agent-governance-toolkit-sre` | SLO，error budget，chaos engineering，circuit breaker |
| `agent-governance-toolkit-cli` | `agt` CLI，OWASP verification，integrity check，policy lint |
| `agent-governance-toolkit[full]` | 上記をまとめて導入するmeta package |

---

# 6．AGT Native Policy Engine

AGT 4.1.0にはYAML / JSONでPolicy documentを定義するNative Policy Engineが存在する．[AGT-04]

Policyには，Policy名，対象Agent，Scope，Rule，Default Action，Parent Policy等を設定できる．

---

# 7．Policyを適用できるStage

v4.1.0のPolicy Ruleは，次のAgent lifecycle stageで評価できる．[AGT-04]

| Stage | 意味 |
|---|---|
| `pre_input` | Agentが入力を処理する前 |
| `pre_tool` | Tool実行前 |
| `post_tool` | Tool実行後 |
| `pre_output` | Userへ最終出力する前 |

概念的には次のようになる．

```text
User Input
   │
   ├─ pre_input
   ▼
 Agent
   │
   ├─ pre_tool
   ▼
 Tool
   │
   ├─ post_tool
   ▼
 Agent
   │
   ├─ pre_output
   ▼
Final Output
```

OpenAI Agents SDKのInput／Tool／Output Guardrailと目的が重なる部分はあるが，AGTはVendorを跨いだ外部Governance Layerとして利用できることが特徴である．

---

# 8．Policy Action

v4.1.0の`PolicyDecision.action`で確認できる主なActionは次の5種類である．[AGT-04]

- `allow`
- `deny`
- `warn`
- `require_approval`
- `log`

`require_approval`ではapprover情報もDecisionに含められる．

---

# 9．AgentごとにPolicyを変えられるか

**可能である．**

AGT Policyは特定Agentまたは複数Agentをtargetにできるため，

```text
Policy A
→ Agent A

Policy B
→ Agent B

Global Policy
→ 全Agent
```

のような構成が可能である．またPolicy Scopeとしてglobal，tenant，agent等を扱い，複数Policyが競合した場合の解決にも利用する．

---

# 10．Conflict Resolution

Policy Engineは複数Ruleがmatchした場合のConflict Resolution Strategyを持つ．v4.1.0ソースでは次を確認できる．[AGT-04]

| Strategy | 概要 |
|---|---|
| `priority_first_match` | Priorityが最も高いRuleを利用 |
| `deny_overrides` | denyを優先 |
| `allow_overrides` | allowを優先 |
| `most_specific_wins` | より具体的なScopeを優先 |

これは企業でGlobal PolicyとAgent固有Policyを併用する際に重要である．

---

# 11．Fail-closed

**Fail-closed**とは，Policy評価に必要な情報や仕組みが正常に使えない場合，安全側としてActionを拒否する設計である．

AGT v4.1.0のPolicy Engineでは，適用Policyが存在しない場合のDefaultは`deny`である．[AGT-04]

また，OPA／Cedar evaluatorもevaluation exception時にdeny相当のDecisionを返す実装を持つ．[AGT-07][AGT-08]

---

# 12．v4.1.0のCost-aware Policy

AGT v4.1.0の公式Release Noteでは，Policy Engineに

> Dynamic policy conditions with time-based and cost-aware rules

が追加されたと記載されている．v4.1.0は2026年6月9日にReleaseされている．[AGT-02]

さらにPolicy EngineのAuthority Requestには`requested_spend`がcontextから取り込まれるコードも存在する．[AGT-06]

ただし，**Policy Engine自身がProviderのCostを自動計算するわけではない**．Policy contextへCost情報を提供するのはHost側の責任である．

---

# 13．Human-in-the-loop

AGTのNative Policyでは`require_approval` Actionを利用できる．

例えば，

```text
read_file
→ allow

send_email
→ require_approval

delete_database
→ deny
```

のようにActionのRiskに応じてPolicyを分けられる．

Human approvalはAgentのPromptに「確認してください」と書くのではなく，Policy Decisionとして外部化できる点が重要である．

---

# 14．Identity / Trust / Delegation

AGT coreにはZero-trust identity，Trust scoring，Delegation等の機能が含まれる．[AGT-01]

Agent Governanceでは，

```text
どのAgentが
どのToolを
どのResourceに対して
実行しようとしたか
```

を識別する必要があるため，Agent IdentityはPolicy・Audit・Costすべての共通基盤となる．

---

# 15．Audit

AGTはPolicy DecisionをAuditへ残す機能を重要なLayerとして扱う．v4.1.0 READMEのArchitectureでも，Policy Engine → Identity → Audit Logという構造が示され，Audit LogはTamper-evidentとして説明されている．[AGT-01]

**Tamper-evident**とは，過去のLogが改変された際に，その変更を検出可能にする性質である．

企業利用では，少なくとも，

- Agent ID
- Action
- Policy
- Decision
- Approver
- Timestamp
- Tool
- Resource
- Cost / Token情報

等をどこまで保持するかを設計する必要がある．

---

# 16．Runtime / SRE / MCP等の主要機能

AGT 4.1.0にはPolicy以外にも広範なGovernance機能がある．[AGT-01]

## Runtime

- Privilege rings
- Termination control
- Execution plan validation
- Saga orchestration

## SRE

- SLO
- Error Budget
- Circuit Breaker
- Chaos Engineering

## MCP Security

READMEではMCP Security GatewayのCapabilityとして，

- Tool poisoning detection
- Drift monitoring
- Typosquatting
- Hidden instruction scanning

等が示されている．

## Compliance / CLI

- `agt verify`
- `agt lint-policy`
- `agt red-team scan`
- Integrity check

等がある．

---

# 17．AGTとOpenAI Agents SDKの関係

v4.1.0 READMEのFramework Supportでは，**OpenAI Agents SDKはMiddleware**として掲載されている．[AGT-01]

したがって，

```text
OpenAI Agents SDK
  ├─ Agent
  ├─ Tool
  ├─ Guardrails
  └─ Handoff
        │
        ▼
       AGT
  ├─ Common Policy
  ├─ Identity
  ├─ Cost
  └─ Audit
```

のような多層構成を考えられる．

OpenAI固有Guardrailを捨ててAGTだけに置き換える必要はなく，SDK固有制御と企業横断Policyを併用する設計が可能である．

---

# 18．AGTとClaude系の関係

v4.1.0 READMEには**Claude Code**向けGovernance Pluginが掲載されている．[AGT-01]

ただしClaude CodeとClaude Agent SDKは同一のproduct surfaceではない．今回確認したv4.1.0のFramework Support表だけから，

> AGT 4.1.0にはClaude Agent SDK専用Adapterが公式提供される

とは断定しない．Claude Agent SDKと組み合わせる場合にはTool wrapperやApplication Middleware等の追加Integrationを検討する必要がある可能性がある．

---

# 19．Cost Governance：CostGuardの位置付け

AGT 4.1.0の`CostGuard` sourceには，

> `Public Preview — basic implementation`

と明記されている．またclassは「Cost tracking, budgeting, and anomaly detection」と説明されている．[AGT-03]

したがって，CostGuardはAgent Cost Governanceに有用なprimitiveであるが，**Providerの正式請求台帳や永続FinOps platformそのものではない**．

---

# 20．CostRecord：何を記録できるか

1回のCost Eventには，少なくとも次の情報がある．[AGT-03]

```text
agent_id
task_id
cost_usd
timestamp
breakdown
metadata
```

`breakdown`は`dict[str, float]`であり，Application側が例えば，

```python
{
    "llm": 0.52,
    "web_search": 0.08,
    "database": 0.03,
}
```

のような内訳を渡すことが可能である．

ただし，この内訳schemaはAGTが自動的に定義・計測するものではない．

---

# 21．Costを把握できる粒度

## 21.1 Task単位

`task_id`付きでCost Eventを記録できる．

## 21.2 Agent単位

`agent_id`ごとに`AgentBudget`が作られ，次の状態を確認できる．[AGT-03]

- `daily_limit_usd`
- `spent_today_usd`
- `remaining_today_usd`
- `utilization_percent`
- `task_count_today`
- `avg_cost_per_task`
- `throttled`
- `killed`

## 21.3 Organization単位

全AgentのCostは`_org_spent_month`へ合算され，`org_monthly_budget`と比較される．[AGT-03]

---

# 22．CostGuardの3つの基本Limit

Constructorでは次を設定する．[AGT-03]

```python
CostGuard(
    per_task_limit=2.0,
    per_agent_daily_limit=100.0,
    org_monthly_budget=5000.0,
)
```

つまり，

```text
Per Task
   ↓
Per Agent / Day
   ↓
Organization / Month
```

という3階層である．

---

# 23．異なるAgentごとにCostを分けて把握できるか

**できる．**

`CostGuard`内部では`agent_id`をkeyとしてAgentBudgetを保持する．Agent AとAgent Bの使用額は独立して集計される．[AGT-03]

したがって，

```text
Agent A：今日 $24.3
Agent B：今日 $7.8
Agent C：今日 $61.2
```

のようなAgent別把握は可能である．

---

# 24．Agentごとに異なるDaily Limitを設定できるか

ここは，「使用額をAgent別に把握できるか」と「上限値をAgent別に設定できるか」を分ける必要がある．

新しいAgentBudgetを作成するv4.1.0のコードでは，

```python
daily_limit_usd=self.per_agent_daily_limit
per_task_limit_usd=self.per_task_limit
```

が使われる．[AGT-03]

つまり，Constructorで指定した`per_agent_daily_limit`が**新規Agentの共通初期値**になる．

`AgentBudget.daily_limit_usd`はPython objectのfieldとして存在するため，Applicationコードからobjectを書き換えること自体は技術上可能である．しかしv4.1.0の`CostGuard`には，`set_agent_budget(agent_id, ...)`のような専用のAgent別Budget configuration APIは確認できなかった．

したがって本レポートでは，

> **Agent別に使用額は管理されるが，異なるDaily Limitを宣言的に登録するfirst-class APIは確認できない**

と整理する．

---

# 25．Agentごとに異なるPer-task Limitを設定できるか

さらに注意が必要である．

`AgentBudget`には`per_task_limit_usd` fieldが存在するが，実際にTask Cost超過を検査するコードは，

```python
cost_usd > self.per_task_limit
```

と**CostGuard全体の`self.per_task_limit`**を参照する．[AGT-03]

したがって，

```text
Agent A → $1 / task
Agent B → $5 / task
```

のような異なるper-task limitを，**1つのCostGuard instanceにAgent別設定する専用機能はv4.1.0では確認できない**．

これはCostGuardのAPI表だけを見た場合には見落としやすく，source implementationまで確認する必要がある重要な点である．

---

# 26．Agent別Cost Policyを実現するには

以下は**設計案**であり，AGT公式が唯一の正解として指定するArchitectureではない．

### 方法1：CostGuard instanceを分ける

```text
CostGuard A（$1/task）
    ↓
Agent A

CostGuard B（$5/task）
    ↓
Agent B
```

### 方法2：AGT Native PolicyをAgent別に設定する

Policy EngineはAgent targetingを持つため，Cost値をcontextへ渡してAgent別Ruleを作る．

### 方法3：OPAへCostとAgent IDを渡す

```rego
allow if {
    input.agent_id == "agent-a"
    input.estimated_cost <= 1.0
}
```

### 方法4：CedarのContextへCost情報を渡す

AgentをPrincipalとして，CostやEnvironmentをContext条件に利用する．

---

# 27．CostGuardはOpenAI／ClaudeのCostを自動取得するか

**自動取得しない．**

APIはApplication側から，

```python
guard.check_task(
    agent_id="agent-a",
    estimated_cost=...
)
```

や，

```python
guard.record_cost(
    agent_id="agent-a",
    task_id="task-001",
    cost_usd=...
)
```

としてCost値を渡す設計である．[AGT-03]

したがって，Providerとの間には次のような変換Layerが必要になる．

```text
OpenAI / Anthropic / Tool Provider
              │
              ▼
        Usage / Cost Data
              │
              ▼
       Application Layer
       ├─ Price lookup
       ├─ Currency / model
       └─ Cost normalization
              │
              ▼
          AGT CostGuard
```

---

# 28．OpenAI Agents SDKとのCost連携例

前回調査したOpenAI Agents SDKではToken Usageを取得できる．そのため概念的には，

```text
OpenAI Usage
   ↓
Input / Output / Cache Token
   ↓
Model priceと照合
   ↓
USD Cost
   ↓
AGT CostGuard
```

と連携できる．

ただし，AGT 4.1.0が自動的にOpenAI Usageを読み取ってCostGuardへ登録することを，本調査で確認したv4.1.0一次情報は保証していない．

---

# 29．Claude Agent SDKとのCost連携例

前回調査したClaude Agent SDKでは`total_cost_usd`等のclient-side estimateを取得できる．概念的には，

```text
Claude Agent SDK
   ↓
total_cost_usd
   ↓
AGT CostGuard
```

とできる．

この場合でも，Provider estimateと正式請求額を区別し，必要ならPlatformのUsage & Cost API等と照合する設計が必要である．

---

# 30．`check_task()`はHard Enforcementか

`check_task()`はTask実行前にBudget内か確認できるが，v4.1.0ソースは明確に，

> advisory checkであり，budgetをreserveしない

と説明している．[AGT-03]

例えば，

```text
残Budget：$1.00

Task A：$0.80
Task B：$0.80
```

がほぼ同時にcheckされた場合，両方がcheckを通過し，後で合計$1.60になる可能性がある．

---

# 31．`check_and_charge()`

Budget-criticalな経路向けには`check_and_charge()`が用意されている．

このmethodは，checkとcost reservation / recordingを1つのlock内でatomicに行い，並行callerが同じ残Budgetを二重に利用する問題を抑える．[AGT-03]

**Atomic**とは，途中で他の処理に割り込まれない一つの処理単位として扱うことを意味する．

---

# 32．`record_cost()`の注意

`record_cost()`はactual costを記録するmethodであるが，v4.1.0ソースは，

> costをunconditionally recordし，budgetを先にcheckしない

と明記している．[AGT-03]

したがって，

```text
record_cost()
```

だけで「Budget超過Actionを絶対に実行させない」ことはできない．

---

# 33．Throttle / Kill

CostGuardはAgentの日次利用率に応じてThrottleやKill状態を設定できる．Constructorのdefaultでは`kill_switch_threshold=0.95`であり，READMEやTutorialでもauto-throttle / kill switchがCost Control機能として説明されている．[AGT-03][AGT-09]

Organization全体の月間Budget利用率がKill thresholdをcrossした場合，`_org_killed=True`となり，保持しているAgentBudgetもkilledに設定するコードが存在する．[AGT-03]

---

# 34．Cost Alert

DefaultのAlert thresholdはソース上で複数段階として管理される．Cost EventにはSeverityとBudgetActionがあり，Alert，Throttle，Kill等の状態変化を記録できる．[AGT-03]

---

# 35．Cost Anomaly Detection

CostGuardには簡易的なAnomaly Detectionがある．

Cost historyが一定数蓄積された後，Z-scoreに基づき通常から大きく外れたCostをAlertできる．[AGT-03]

**Z-score**は，値が平均から標準偏差何個分離れているかを表す指標である．

ただしこれは「Public Preview — basic implementation」のCostGuardに含まれる簡易機能であり，高度なFinOps anomaly detectorと同一視しない方がよい．

---

# 36．Daily / Monthly Resetの注意

v4.1.0には`reset_daily()`があり，docstringには「call at start of each day」と記載されている．[AGT-03]

つまり，日付変更を自動検知して必ずresetするschedulerがCostGuard内部にあるわけではなく，Application側から適切なタイミングで呼ぶ必要がある．

また，本調査で確認したv4.1.0のCostGuard sourceには，`reset_month()`／`reset_monthly()`に相当するpublic methodは確認できなかった．

Organization monthly spendを長期間運用する場合には，instance lifecycleや外部state storeを含めた設計が必要になる．

---

# 37．CostGuardのState Persistence

`CostGuard`は，

- Agent budget map
- Cost records
- Alerts
- Organization monthly spend

等をPython objectのmemory内で保持する実装である．[AGT-03]

したがって，このclass単体を「Process restartを跨ぐ正式なBilling Ledger」と解釈すべきではない．

Enterprise運用では，DatabaseやFinOps基盤へCost Eventを永続化する設計を検討する必要がある．

---

# 38．Token Governanceの全体像

AGT 4.1.0にはCostとは別にToken関連の複数機能がある．

少なくとも，

1. `GovernancePolicy.max_tokens`
2. `TokenBudgetTracker`
3. `ContextScheduler`

を区別する必要がある．

---

# 39．`GovernancePolicy.max_tokens`

`GovernancePolicy`には`max_tokens`，`max_tool_calls`，`allowed_tools`，`blocked_patterns`，`require_human_approval`，timeout，concurrency等の設定が存在する．[AGT-10]

これはFramework Integration等でAgent実行Policyを定義するための構造である．

---

# 40．TokenBudgetTracker

`TokenBudgetTracker`は`agent_id`ごとに，

- prompt tokens
- completion tokens
- total tokens

を記録する．[AGT-11]

Statusとして，

```text
used
limit
remaining
percentage
is_warning
is_exceeded
```

を取得できる．

---

# 41．TokenBudgetTrackerの上限粒度

ここにもCostGuardと似た注意点がある．

TrackerはAgentごとに使用量を分けて保持するが，1つのTracker instanceが持つ`self._max_tokens`は1個である．Constructorへ`GovernancePolicy`を渡した場合も，そのPolicyの`max_tokens`をTracker全体の上限として採用する．[AGT-11]

したがって，

```text
Agent A → 5,000 tokens
Agent B → 50,000 tokens
```

という異なる上限を同じTrackerのAgent mapへ直接登録する構造ではない．

---

# 42．TokenBudgetTrackerはHard Stopか

`record_usage()`はTokenを加算し，`is_exceeded`等を含むStatusを返す．Warning callbackもある．[AGT-11]

しかし，確認したv4.1.0の`TokenBudgetTracker` class自体には，「上限超過時にExceptionをraiseしてAgentを停止する」処理はない．

したがって，

> **TokenBudgetTrackerはTracking / Warning primitiveであり，単体ではHard Enforcementではない**

と理解するのが適切である．

---

# 43．ContextScheduler

`ContextScheduler`はTokenを共有Resourceとして配分する，よりEnforcement-orientedな機能である．[AGT-12]

Globalな`total_budget`を持ち，`allocate()`時に，

```text
agent_id
task
priority
max_tokens
```

を指定できる．

ここでは，Agent／Taskごとに明示的な`max_tokens` capを渡すことができる．

```text
Agent A → max_tokens=2,000
Agent B → max_tokens=5,000
```

という個別Allocationが可能である．

---

# 44．ContextSchedulerのPriority

v4.1.0ソースではDefault minimum context sizeとして次が確認できる．[AGT-12]

| Priority | Minimum Token |
|---|---:|
| CRITICAL | 4000 |
| HIGH | 2000 |
| NORMAL | 1000 |
| LOW | 500 |

---

# 45．ContextSchedulerのHard Enforcement

`record_usage()`でAllocationに対するToken利用率が100%に達すると，

- stopped状態を設定
- `SIGSTOP`をemit
- `BudgetExceeded` Exceptionをraise

する．[AGT-12]

したがってTokenBudgetTrackerよりも明確な停止機構を持つ．

---

# 46．CostとTokenは別々に管理すべき

Token数とUSD Costは同一ではない．

同じ10,000 tokensでも，

- Model
- Provider
- Input / Output
- Cache
- Reasoning
- Tool cost

によってCostは変わる．

AGT 4.1.0でも，Token Budget系componentとCostGuardは別componentである．

企業利用では，

```text
Token Governance
+
Cost Governance
```

を分けて設計し，必要に応じて相互変換することが重要である．

---

# 47．Open Policy Agent（OPA）1.19.1

## 47.1 OPAとは

OPAはCNCFのopen-source general-purpose policy engineである．OPA公式ドキュメントは，Policy decision-makingをSoftwareから分離し，Softwareがstructured dataをOPAへ渡すことでPolicy Decisionを取得する仕組みを説明している．[OPA-02]

OPA Policyは**Rego**というDeclarative Languageで記述する．

---

# 48．OPA 1.19.1のVersion

OPA v1.19.1は2026年8月17日にReleaseされた．公式Release NoteではGo 1.26.6でOPAをbuildし，HTTP handlerやcrypto builtinが利用するGo standard library上の脆弱性へ対応したReleaseとされている．また，

> otherwise the same code as v1.19.0

と明記されている．[OPA-01]

したがって1.19.1は大きなPolicy機能追加版ではなく，security-orientedなbuild updateとして理解できる．

---

# 49．Regoとは

RegoはOPAのPolicy Languageである．複雑なstructured dataに対し，DeclarativeにRuleを記述できる．[OPA-02]

例：

```rego
package agent

default allow := false

allow if {
    input.agent.role == "analyst"
    input.action == "read"
}
```

OPAはBooleanだけでなく，arbitrary structured dataをPolicy Decisionとして返すこともできる．[OPA-02]

---

# 50．OPAを外部Policy Engineにする意味

OPAにはPolicy Engineだけでなく，分散環境でPolicyを運用するためのManagement API群がある．公式ドキュメントでは，

- **Bundles**：Policy / Data distribution
- **Decision Logs**：Decision telemetry
- **Status**：Agent telemetry
- **Discovery**：Dynamic configuration

が説明されている．[OPA-03]

ただし，OPA公式ドキュメントは，

> OPA does not provide a control plane service out-of-the-box

とも明記している．[OPA-03]

つまりOPA自体にManagement APIはあるが，企業用Central Control Plane全体を自動で提供するわけではない．

---

# 51．OPA Decision Logs

Decision Loggingを有効にすると，Policy Decision APIのResponseに`decision_id`を含められる．[OPA-04]

Agent GovernanceにOPAを利用する場合，

```text
Agent Action
   ↓
OPA Decision
   ↓
decision_id
   ↓
Audit / Incident analysis
```

のように，Policy DecisionとAgent Auditを関連付けられる可能性がある．

---

# 52．AGT 4.1.0とOPA

AGT v4.1.0の`OPAEvaluator`には，

- `remote`
- `local`

の2 modeがある．[AGT-07]

## Remote

OPA REST APIをQueryする．

## Local

`opa eval` subprocess等を利用してRegoを評価する．

evaluation exception時は`allowed=False`のDecisionを返すため，fail-closed方向の挙動である．

---

# 53．AGT `load_rego()`の評価順

v4.1.0の`PolicyEngine.load_rego()` docstringには，

> YAML rules are checked first, and if no rule matches, the Rego policy is consulted.

と記載されている．[AGT-06]

つまりOPAはNative Policyと常に並列に多数決するのではなく，Native RuleでDecisionが確定しなかった場合のfallback pathとして扱われる．

---

# 54．AGT経由のOPA Decisionの注意

OPA自体はarbitrary structured decisionを返せる．[OPA-02]

しかしAGT v4.1.0のPolicyEngine fallback pathでは，

```text
data.<package>.allow
```

をQueryし，`OPADecision.allowed`をAGTの`allow`／`deny`へmappingしている．[AGT-06]

したがって，

> **OPA自体の表現力**
>
> と
>
> **AGT v4.1.0標準fallback integrationで利用されるDecision表現**

は区別する必要がある．

---

# 55．OPAでCost Policyを作れるか

**Policy Decisionとしては可能である．**

OPAはarbitrary structured inputを受けられるため，

```json
{
  "agent_id": "agent-a",
  "estimated_cost": 1.2,
  "spent_today": 8.6,
  "daily_limit": 10.0
}
```

を渡して，

```rego
allow if {
    input.spent_today + input.estimated_cost <= input.daily_limit
}
```

のようなPolicyを作れる．

ただしOPAはBilling Meterではない．Costの計測・累積・Provider price取得は別componentで行い，Policy inputとしてOPAへ渡す必要がある．

---

# 56．Cedarとcedarpy 4.8.7

## 56.1 Version表記の注意

今回の指定「Cedar 4.8.7」について，AGTのPython Integrationが利用する`cedarpy`を確認すると，PyPIのversion対応表は次の通りである．[CEDAR-01]

```text
cedarpy 4.8.7
      ↓
Cedar Policy engine 4.8.2
```

`cedarpy`はmajor / minorをCedar engineに合わせつつ，bug fix等で独自のpatch versionを増やすため，patch numberは一致しないことがある．

したがって本レポートでは，

> **cedarpy 4.8.7（Cedar Policy engine 4.8.2）**

と表記する．

またPyPIは，`cedarpy`についてAWSまたはCedar Policy teamによるofficial supportではないと明記している．[CEDAR-01]

---

# 57．Cedarとは

CedarはAuthorization Policy Language / Engineである．

Authorization requestを次の4要素で表す．[CEDAR-02]

- **Principal**
- **Action**
- **Resource**
- **Context**

頭文字を取ってP / A / R / Cと考えると理解しやすい．

```text
Principal：誰が
Action   ：何を
Resource ：何に対して
Context  ：どの状況で
```

Agent Governanceでは例えば，

```text
Principal = Agent::"analyst-agent"
Action    = Action::"ReadData"
Resource  = Dataset::"sales"
Context   = { environment: "production" }
```

のように表現できる．

---

# 58．CedarのDecision Model

CedarはAuthorization requestに対して`Allow`または`Deny`を返す．公式Referenceでは，Authorization algorithmの重要な性質として次を説明している．[CEDAR-02]

1. **Default deny**
2. **Forbid overrides permit**
3. **Skip on error**

### Default deny

明示的なpermit policyが成立しなければDenyとなる．

### Forbid overrides permit

permitが成立していても，forbidが成立すればDenyになる．

### Skip on error

あるPolicyのevaluationがerrorでも，そのPolicyはAuthorization Decisionの計算からskipされる．

Applicationはdiagnosticsを確認し，errorが存在した場合に追加の安全判断を行うこともできる．

---

# 59．Cedar SchemaとValidation

CedarではSchemaを定義し，PolicyをSchema againstでvalidateできる．[CEDAR-03]

これにより，

- Entity type typo
- Attribute typo
- Action mismatch
- Type mismatch

等をDeployment前に検出しやすくできる．

Policy-as-Codeを大規模に管理する場合，RuleのSyntaxだけでなく，PolicyがDomain Modelと整合しているかを事前検証できる点が重要である．

---

# 60．cedarpy 4.8.7

`cedarpy`はRust製Cedar Policy libraryをPythonから利用するbindingであり，[CEDAR-01]

- `is_authorized`
- Schema validation
- Policy formatting
- Batch authorization
- Parsed PolicySetの再利用

等を提供する．

---

# 61．AGT 4.1.0のCedar Integration

v4.1.0の`CedarEvaluator`には次のmodeがある．[AGT-08]

- `auto`
- `cedarpy`
- `cli`
- `builtin`

`cedarpy` modeではPython binding経由でCedarを呼び出し，CLI modeではCedar CLI subprocessを利用する．

`builtin`は簡易evaluatorである．source codeではprincipal / resource constraintを完全には扱えず，そのようなPolicyに対して本物のCedar EngineまたはCLIを利用するようerrorを返す実装がある．[AGT-08]

---

# 62．Cedar `auto` modeの重要な注意

v4.1.0のdocstringには`auto`がcedarpy → CLI → builtinのように見える説明がある．

しかし実際の`evaluate()`コードでは，

```text
auto
 ↓
cedarpy available?
 ├─ Yes → cedarpy
 └─ No
      ↓
   CLI available?
    ├─ Yes → CLI
    └─ No → DENY + error
```

であり，**builtinへ自動fallbackしない**．`builtin`を使うにはmodeを明示する必要がある．[AGT-08]

これは安全性の観点から重要な実装上の事実である．

---

# 63．AGTからCedarへ渡すRequest

AGT v4.1.0はCedar requestを，

- `agent_did`または`principal`
- Action
- `resource`
- その他Context

から組み立てる．[AGT-08]

したがってAgent IdentityをPrincipalとして，Resource-level Authorizationへ利用できる．

---

# 64．AGT Policy評価順序

v4.1.0 Policy Engineの実装では，概ね次の順序でDecisionを返す．[AGT-06]

```text
1．Native YAML / JSON Policy
           ↓ no decision
2．Authority Resolver
           ↓ no terminal decision
3．OPA / Rego
           ↓ error / no usable decision
4．Cedar
           ↓ error / no usable decision
5．Default Action
```

重要なのは，OPAとCedarを必ず両方評価してAND／ORするわけではないことである．

OPAがerrorなしでDecisionを返した場合，通常その時点でPolicyDecisionがreturnされ，Cedarまでは進まない．

---

# 65．Native Policy / OPA / Cedar比較

| 観点 | AGT Native Policy | OPA / Rego | Cedar |
|---|---|---|---|
| 主目的 | Agent Governance | General-purpose Policy | Authorization |
| 言語 | YAML / JSON | Rego | Cedar |
| Input | Agent Context | Arbitrary structured data | Principal / Action / Resource / Context |
| Decision表現 | allow / deny / warn / approval / log | Arbitrary structured output可能 | Allow / Deny |
| AGT標準fallback時 | Native Action | 主にallow / denyへmapping | allow / denyへmapping |
| Agent Lifecycle | Native stageあり | Host側からcontextを渡す | Host側からP/A/R/Cを渡す |
| Agent targeting | Native | Input / dataで表現 | Principalで表現しやすい |
| Cost Policy | Contextで条件化 | Costをinputすれば可能 | CostをContextに入れれば可能 |
| Cost Metering | なし | なし | なし |
| Human Approval | Native actionあり | AGT fallbackではboolean中心 | Allow / Deny中心 |
| Policy distribution | AGT運用 | Bundle / Management API | Host側Policy store |
| Decision telemetry | AGT Audit | OPA Decision Logs | Host側で記録 |

---

# 66．OPAとCedarはCostGuardの代わりになるか

**完全な代替ではない．**

OPA／Cedarは，

> このCost状態ならActionを許可するか

という**Decision**には向いている．

一方，

> 今日Agent Aが合計いくら使ったか

という**Accounting State**を自動計測・累積するものではない．

したがって役割は，

```text
Cost Metering / Accounting
         │
         ▼
 CostGuard / FinOps DB
         │
         ▼
   Policy Context
      ┌──┴──┐
      ▼     ▼
     OPA   Cedar
      │     │
      └──┬──┘
         ▼
 Allow / Deny
```

のように分けると理解しやすい．

---

# 67．企業向けCost Governance Architectureの例

以下は今回の調査から導かれる**設計例**であり，AGT公式が唯一のReference Architectureとして指定しているものではない．

```text
OpenAI / Anthropic / Other Provider
                │
                ▼
          Usage Metadata
                │
                ▼
          Cost Normalizer
      ┌─────────┼─────────┐
      │ model   │ tokens  │ tool cost
      └─────────┼─────────┘
                ▼
          normalized USD
                │
                ▼
           AGT CostGuard
      ┌─────────┼──────────┐
      │         │          │
     Task      Agent       Org
      │         │          │
      └─────────┼──────────┘
                ▼
          Persistent DB
                │
                ▼
        OPA / Cedar Policy
                │
                ▼
           Allow / Deny
```

このArchitectureでは，Provider固有のToken／Cost形式をNormalizerで共通化し，AGTでは共通`agent_id`／`task_id`で管理する．

---

# 68．複数Agentで共通Policy Layerを設ける意味

OpenAI Agents SDKとClaude Agent SDKでは，Policyを表現する仕組みが異なる．

```text
OpenAI
→ Guardrails / Approval / Tracing

Claude
→ Permissions / Hooks / Sandbox / Budget
```

そのまま各SDK固有設定だけで運用すると，

```text
Enterprise Policy
 ├─ OpenAI用実装
 ├─ Claude用実装
 ├─ LangGraph用実装
 └─ 独自Agent用実装
```

とPolicyが分散しやすい．

AGT＋OPA／Cedarのような外部Layerを設ければ，

```text
                Enterprise Policy
             ┌────────┴────────┐
             ▼                 ▼
         OPA / Rego          Cedar
       General Policy     Authorization
             └────────┬────────┘
                      ▼
                     AGT
              Policy Enforcement
          ┌───────────┼───────────┐
          ▼           ▼           ▼
       OpenAI       Claude      Other
```

という構成を検討できる．

ただし，本当に共通Policy Layerとして成立させるためには，

- Agent Identityの統一
- Tool名のNormalization
- Resource modelの統一
- Cost telemetryのNormalization
- Policy Context Schema
- Audit Schema
- Persistent State
- Failure時のFail-closed設計

まで設計する必要がある．

---

# 69．Version上の注意：ACSについて

AGT v4.1.0タグのREADMEにはAgent Control Specification（ACS）への参照が存在し，`policy-engine/` directoryもv4.1.0 tag内に存在する．

しかし同じ`policy-engine/README.md`は，

> ACS is folded into AGT as the AGT 5.0 policy layer

と明記している．[AGT-13]

したがって，

> v4.1.0 tag内にACS sourceが存在する

ことと，

> ACSをv4.1.0の正式な主要Policy Runtimeとして扱う

ことは同義ではない．

本レポートではv4.1.0のPolicy説明について，v4.1.0で実際に存在する`agentmesh.governance.PolicyEngine`，OPA / Cedar adapter，CostGuard等を中心に扱い，後続のACS Runtime固有機能を無条件にv4.1.0へ帰属させていない．

---

# 70．AGT 4.1.0の主な限界・運用注意点

1. **Public Preview**
   - v4.1.0 READMEはPublic Previewと明記しており，GA前にBreaking Changeが起こり得る．[AGT-01]

2. **Cost自動取得ではない**
   - CostGuardへApplicationがCost値を渡す必要がある．

3. **Agent別Cost追跡とAgent別Limit設定は別**
   - Agentごとにspent stateを持てるが，1つのCostGuardにAgent別per-task limitを宣言する専用APIは確認できない．

4. **`check_task()`はBudget Reservationではない**
   - 並行実行ではovershootし得る．

5. **`record_cost()`は事前Budget Checkをしない**

6. **CostGuard stateはmemory上**
   - 外部永続化が必要になり得る．

7. **Daily resetはHost側で呼ぶ必要がある**
   - Monthly reset public methodは確認できない．

8. **TokenBudgetTrackerは主にTracking / Warning**
   - Hard StopはContextScheduler等と区別する．

9. **OPA / CedarはCost Meterではない**
   - Cost stateは外部からInputとして与える．

10. **OPA → Cedarはfallback順序**
    - 標準PolicyEngineが両方を常に合成評価するわけではない．

11. **AGTはOS kernel enforcementではない**
    - v4.1.0 READMEはApplication middleware layerでのEnforcementであり，同Process boundaryを共有すると説明している．OS-level isolationにはContainer等を併用することが推奨される．[AGT-01]

---

# 71．質問への直接回答

## Q1．AGTにはどのようなガバナンス機能があるか

主要カテゴリとして，

- Policy-as-Code
- Tool前後等のLifecycle Policy
- Agent-specific Policy
- Human Approval
- Identity / Trust / Delegation
- Audit
- Runtime / Kill Switch
- SRE
- MCP Security
- Token Budget
- Cost Budget
- External Policy Engine（OPA / Cedar）
- Compliance / Policy lint
- Framework Integration

がある．

---

## Q2．AGTではどの粒度でCostを把握できるか

少なくとも，

- Cost Event
- Task
- Agent
- Agent × Day
- Organization × Month
- 任意Cost breakdown

で記録・集計できる．

---

## Q3．異なるAgentごとに使用額を分けて確認できるか

**できる．**

`agent_id`ごとにAgentBudget stateが作られる．

---

## Q4．Agentごとに異なる日次Cost上限を設定できるか

**専用のfirst-class APIはv4.1.0のCostGuardでは確認できない．**

新しいAgentBudgetは共通`per_agent_daily_limit`から初期化される．

---

## Q5．Agent Aは$1/task，Agent Bは$5/taskにできるか

1つのCostGuardの標準per-task判定は`self.per_task_limit`を参照するため，**そのままではAgent別per-task limitにならない**．

実現方法として，

- CostGuardを分ける
- Native PolicyをAgent別にする
- OPAへAgent ID＋Costを渡す
- Cedar ContextへCostを渡す

等を検討できる．

---

## Q6．AGTはOpenAI／ClaudeのCostを勝手に取得してくれるか

**CostGuard単体では取得しない．**

ProviderのUsage / Cost情報をApplication側で取得し，AGTへ渡す必要がある．

---

## Q7．TokenもAgent別に把握できるか

`TokenBudgetTracker`では`agent_id`別に利用量を記録できる．

ただし1つのTrackerが持つlimitは1つである．

`ContextScheduler`ではAllocationごとに`max_tokens`を指定できるため，Agent／Taskごとの個別Token capを設定しやすい．

---

## Q8．Cost超過時に自動停止できるか

CostGuardにはThrottle／Kill状態やBudget checkがある．Budget-criticalな並行実行では`check_and_charge()`が重要である．

Token側ではContextSchedulerが100%到達時に`SIGSTOP`と`BudgetExceeded`を発生させる．

---

## Q9．OPAはなぜ使うのか

既存のInfrastructure / API / Kubernetes等で利用しているRego PolicyをAgent Governanceへ再利用しやすくし，Policy DecisionをApplication codeから外部化するためである．

またBundles，Decision Logs，Discovery等のManagement APIを利用できる．

---

## Q10．Cedarはなぜ使うのか

AgentをPrincipal，Tool操作をAction，File／Database等をResourceとして表現する**Authorization Policy**に適しているためである．

Schema Validationにより，Policyの型・Entity modelの不整合を事前検出できる点も特徴である．

---

# 72．最終結論

AGT 4.1.0は，単なるLLM Guardrail libraryではなく，

```text
Policy
Identity
Trust
Audit
Runtime
SRE
MCP Security
Token
Cost
Compliance
```

を横断するAgent Governance Toolkitである．

特にPolicyについては，Native YAML / JSON PolicyだけでなくOPA / RegoとCedarへのIntegrationを持ち，既存のEnterprise Policy-as-Code基盤と接続できる．

Cost Governanceでは，`CostGuard`がTask，Agentの日次使用量，Organizationの月次Budgetという階層を持ち，Alert，Throttle，Kill，Anomaly Detection等を提供する．

一方で，AGTはProvider Billing情報を自動取得するわけではなく，Cost値はApplicationから渡す必要がある．また，Agent別利用額の追跡はできても，1つのCostGuardにおいてAgentごとに異なるper-task limitを設定する専用機構は確認できない．このような高度なAgent-specific Cost Policyには，AGT Native Policy，OPA，Cedar，複数CostGuard，または外部FinOps stateとの組み合わせを検討する必要がある．

この点から，AGTの価値は，

> 「OpenAIやClaude SDKに元々あるGovernance機能を完全に置き換える」

ことよりも，

> **異なるAgent Runtimeの外側で，Identity，Policy，Cost，Audit等を共通のGovernance Layerとして管理する**

ことにあると考えられる．

この最後の評価は，本調査で確認した機能差から導いた**考察**であり，Microsoftが公式に唯一のArchitectureとして要求しているという意味ではない．

---

# 73．参考文献・一次情報

## Agent Governance Toolkit

### [AGT-01] Microsoft Agent Governance Toolkit v4.1.0 — README
v4.1.0 tag固定．Architecture，Public Preview，Packages，Framework Integration，Security boundary等．  
https://github.com/microsoft/agent-governance-toolkit/blob/v4.1.0/README.md

### [AGT-02] Microsoft Agent Governance Toolkit — Release v4.1.0
2026年6月9日Release．Dynamic policy conditions with time-based and cost-aware rules等．  
https://github.com/microsoft/agent-governance-toolkit/releases/tag/v4.1.0

### [AGT-03] AGT v4.1.0 — `agent_sre/cost/guard.py`
`CostGuard`，`CostRecord`，`AgentBudget`，`check_task`，`check_and_charge`，`record_cost`，Throttle，Kill，Anomaly Detection，reset等．  
https://github.com/microsoft/agent-governance-toolkit/blob/v4.1.0/agent-governance-python/agent-sre/src/agent_sre/cost/guard.py

### [AGT-04] AGT v4.1.0 — Native Policy Engine
Policy，PolicyRule，PolicyDecision，Scope，Conflict Resolution，Default deny，Human Approval等．  
https://github.com/microsoft/agent-governance-toolkit/blob/v4.1.0/agent-governance-python/agent-mesh/src/agentmesh/governance/policy.py

### [AGT-05] AGT v4.1.0 — CHANGELOG
v4.0.0までのPackage consolidation，Security，Audit等の変更履歴．  
https://github.com/microsoft/agent-governance-toolkit/blob/v4.1.0/CHANGELOG.md

### [AGT-06] AGT v4.1.0 — Policy evaluation / OPA / Cedar integration
Native → Authority → Rego → Cedar → Defaultの評価コード，`load_rego()`／`load_cedar()`．  
https://github.com/microsoft/agent-governance-toolkit/blob/v4.1.0/agent-governance-python/agent-mesh/src/agentmesh/governance/policy.py

### [AGT-07] AGT v4.1.0 — OPA Adapter
Remote OPA REST API，Local `opa eval`，fail-closed error behavior．  
https://github.com/microsoft/agent-governance-toolkit/blob/v4.1.0/agent-governance-python/agent-mesh/src/agentmesh/governance/opa.py

### [AGT-08] AGT v4.1.0 — Cedar Adapter
cedarpy / CLI / builtin，auto modeの実際のfallback，P/A/R/C request mapping．  
https://github.com/microsoft/agent-governance-toolkit/blob/v4.1.0/agent-governance-python/agent-mesh/src/agentmesh/governance/cedar.py

### [AGT-09] AGT — Cost Governance Tutorial
CostGuardのBudget Model，Alert，Throttle，Killの公式Tutorial．  
https://github.com/microsoft/agent-governance-toolkit/blob/main/docs/tutorials/51-cost-governance.md

> 注：このTutorialは`main`ブランチの資料であるため，v4.1.0への帰属判断にはv4.1.0 tagのsource codeを優先した．

### [AGT-10] AGT v4.1.0 — `GovernancePolicy`
`max_tokens`，`max_tool_calls`，allowed tools，human approval，timeout，concurrency等．  
https://github.com/microsoft/agent-governance-toolkit/blob/v4.1.0/agent-governance-python/agent-os/src/agent_os/integrations/base.py

### [AGT-11] AGT v4.1.0 — `TokenBudgetTracker`
Agent別Token usage，warning，`is_exceeded`，single tracker limitの実装．  
https://github.com/microsoft/agent-governance-toolkit/blob/v4.1.0/agent-governance-python/agent-os/src/agent_os/integrations/token_budget.py

### [AGT-12] AGT v4.1.0 — `ContextScheduler`
Shared Token Pool，priority，Agent／Task別`max_tokens` allocation，SIGWARN，SIGSTOP，BudgetExceeded．  
https://github.com/microsoft/agent-governance-toolkit/blob/v4.1.0/agent-governance-python/agent-os/src/agent_os/context_budget.py

### [AGT-13] AGT v4.1.0 tag — Agent Control Specification README
v4.1.0 tagにsourceが存在する一方，「AGT 5.0 policy layerとしてfolded in」と明記されるVersion上の注意．  
https://github.com/microsoft/agent-governance-toolkit/blob/v4.1.0/policy-engine/README.md

---

## Open Policy Agent

### [OPA-01] Open Policy Agent — Release v1.19.1
2026年8月17日Release．Go 1.26.6によるsecurity updateで，code自体はv1.19.0と同一と説明．  
https://github.com/open-policy-agent/opa/releases/tag/v1.19.1

### [OPA-02] Open Policy Agent — Official Documentation
OPAの定義，Rego，structured input，Policy DecisionとEnforcementの分離．  
https://www.openpolicyagent.org/docs

### [OPA-03] OPA — Management APIs and Architecture
Bundles，Decision Logs，Status，Discovery，Control Plane serviceはout-of-the-boxでは提供しない点．  
https://www.openpolicyagent.org/docs/management-introduction

### [OPA-04] OPA — Decision Logs
Decision logging，`decision_id`等．  
https://www.openpolicyagent.org/docs/management-decision-logs

### [OPA-05] OPA — Bundles
Policy / Data distribution．  
https://www.openpolicyagent.org/docs/management-bundles

### [OPA-06] OPA — Policy Language
Rego reference．  
https://www.openpolicyagent.org/docs/policy-language

---

## Cedar / cedarpy

### [CEDAR-01] PyPI — cedarpy 4.8.7
cedarpy 4.8.7とCedar Policy engine 4.8.2のversion対応，Python bindingの機能，official support上の注意．  
https://pypi.org/project/cedarpy/4.8.7/

### [CEDAR-02] Cedar Policy Language Reference — Authorization
Principal / Action / Resource / Context，Default deny，Forbid overrides permit，Skip on error．  
https://docs.cedarpolicy.com/auth/authorization.html

### [CEDAR-03] Cedar Policy Language Reference — Policy Validation
Schema-based Policy Validation．  
https://docs.cedarpolicy.com/policies/validation.html

### [CEDAR-04] Cedar Policy Language Reference — Basic Policy Syntax
permit / forbid等．  
https://docs.cedarpolicy.com/policies/syntax-policy.html

---

# 74．情報の確度について

本レポートでは，AGTについて以下の優先順位で情報を扱った．

1. v4.1.0タグに固定されたsource code
2. v4.1.0 Release Note
3. v4.1.0タグのREADME / CHANGELOG
4. Microsoft AGTの現在のTutorial
5. OPA / Cedarの公式Documentation
6. PyPIの該当Version page

特に次の項目は，Tutorialの概要説明だけでなく**v4.1.0の実装を直接確認**している．

- CostGuardのAgent別state
- `per_task_limit`の実際の参照先
- `check_task()`がBudgetをreserveしないこと
- `check_and_charge()`のatomic性
- `record_cost()`がBudgetを先にcheckしないこと
- Organization monthly spendのin-memory集計
- `reset_daily()`の存在
- TokenBudgetTrackerがAgent別usageを持つ一方，limitはTracker instance単位であること
- ContextSchedulerのAgent／Task別`max_tokens`
- ContextSchedulerのSIGSTOP / BudgetExceeded
- Native Policy → OPA → Cedar → Defaultの評価順序
- Cedar `auto` modeがbuiltinへsilent fallbackしないこと
- cedarpy 4.8.7がCedar engine 4.8.2を利用すること

不明確な箇所については，「存在しない」と推測で断定するのではなく，「今回確認したv4.1.0 public API / sourceでは専用機構を確認できない」と記述した．
