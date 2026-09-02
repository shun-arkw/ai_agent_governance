# Cost Governance実験：5スライド構成アウトライン

- 作成日：2026年9月3日
- 想定位置付け：AI Agent Governance全体発表のうち，Cost Governanceを説明する約5枚
- 想定説明時間：4〜6分
- 対象読者：本実験を初めて知る人
- 詳細結果：[`cost_governance_experiment_results_2026-09-03.md`](cost_governance_experiment_results_2026-09-03.md)

---

## 0．5スライドへ絞る方針

Cost Governance実験では12種類の結果を取得したが，本編ですべてを個別に説明すると，発表全体の
主題がCost実験へ偏ってしまう．そこで，個々のrunではなく，次の5つのメッセージへ集約する．

1. Cost Governanceは「Usage取得」「Budget設定」「超過時停止」「管理粒度」に分けて評価する．
2. OpenAIとClaudeのSDK単体では，取得できるCost情報とBudgetの種類が異なる．
3. ClaudeのUSD Budgetは実際に停止したが，設定額を超えてから停止した．
4. AGTを追加すると，Task，Agent，Organizationを横断して次のAPI呼び出しを拒否できた．
5. 実運用では，SDKのrun内制限とAGT等の横断Budgetを組み合わせる必要がある．

### 本編に残す実験

| 実験 | 残す理由 |
|---|---|
| OpenAI SDK baseline | Usageを取得できることを示す |
| OpenAI `max_turns=1` | USD Budgetはないが，Agent loopを停止できることを示す |
| Claude SDK baseline | Token usageと`total_cost_usd`を取得できることを示す |
| Claude `max_budget_usd=0.002` | SDK標準USD Budgetの停止とovershoot（超過分）を示す |
| AGT Task deny | API呼び出し前にCost 0で拒否できることを示す |
| AGT Agent deny | Agentごとに独立してBudget管理できることを示す |
| AGT Organization deny | 複数Agentを横断して停止できることを示す |

### 本編から外す内容

- 全12結果のToken／Cost一覧
- AGT＋OpenAIとAGT＋Claudeの同じ結果を別々のスライドで説明すること
- 全てのBudget値とCLI command
- `CostGuard` APIの細かな仕様
- 失敗試行・重複実行の経緯
- Source code全文
- 実験結果JSONの構造

これらは詳細レポートまたは質疑用Backupへ移す．

---

# Slide 1．Cost Governanceを何で評価するか

## このスライドの目的

実験の背景と評価軸を1枚で共有する．初見の聞き手が，以降の比較表を読める状態にする．

## タイトル案

> AI AgentのCost Governanceを4つの問いで評価する

## スライドへ書く内容

### 背景

```text
LLM呼び出し → Tool実行 → 再判断 → Tool実行 → …
```

Agentは複数のModel呼び出しを繰り返すため，1回のAPI利用よりCostが増大しやすい．さらに，多数の
TaskやAgentへ展開すると，Organization全体のCost管理が必要になる．

### 4つの評価軸

| 評価軸 | 問い |
|---|---|
| Usage取得 | Token数やUSD Costを取得できるか |
| Budget設定 | 最大turn，Token，USD等の上限を設定できるか |
| 超過時停止 | 上限へ達したとき，実行を本当に止められるか |
| 管理粒度 | run／Task，Agent，Organizationのどこまで管理できるか |

### 「Usage」の定義

本発表では，UsageをProvider APIの消費実績値として扱う．実験コードでは次の4項目を記録した．

| 項目 | 内容 |
|---|---|
| requests | Model APIの呼び出し回数 |
| input_tokens | 入力Token数 |
| output_tokens | 出力Token数 |
| total_tokens | 合計Token数 |

USD Costは，このUsageから導出する．ClaudeはSDKが`total_cost_usd`を返し，OpenAIはToken数と
固定価格表からApplication側で計算する．

### Usageが確定する時点

Usageは実行前の見積もりではなく，API応答後に確定する事後値である．

```text
Model呼び出し → API応答 → Usage確定 → Cost算出 → Budget判定
```

したがって，Budget判定は常に「すでに消費したCost」を根拠に行われる．判定できる最短の境界は
1回のModel呼び出し直後である．そのため，上限へ達したことを検知して停止しても，その時点で実Costが
設定額を超えている場合がある．Slide 3で扱うClaudeの結果がこれに当たる．

## 強調する一文

> Usageを取得できることと，Budget超過を防げることは同じではない．

## 図案

左側にAgent loop，右側に管理粒度を置く．

```text
Agent loop                     管理粒度
Model → Tool → Model           Run → Task → Agent → Organization
```

## 発表時の補足

- Token BudgetとUSD Budgetも別物である．
- 同じToken数でも，ModelやInput／OutputによってCostが変わる．
- 今回はModel性能ではなく，Costを把握・制御する仕組みを比較した．
- Usageは実行前の見積もりではなく，API応答後に確定する事後値である．
- そのため，Budget判定は最短でも1 call分遅れる．Slide 3で扱う「停止したが既に超えていた」結果は，
  この構造から生じる．

## 想定説明時間

50〜60秒

---

# Slide 2．比較対象と共通実験設計

## このスライドの目的

何をどの条件で比較したかを説明し，AGTがAgent Runtimeではない点を明確にする．

## タイトル案

> 安価な実APIモデルを使い，同じTaskで比較

## スライドへ書く内容

### 比較対象

| 対象 | Model | 役割 |
|---|---|---|
| OpenAI Agents SDK 0.22.0 | `gpt-5-nano` | OpenAI Agent Runtime |
| Claude Agent SDK 0.2.144 | `claude-haiku-4-5-20251001` | Claude Agent Runtime |
| AGT 4.1.0 | 上記Runtimeと統合 | 複数Taskを横断するBudget Layer |

### 共通Task

```text
record_step Toolを1回呼び，結果を待って「done」と返す
```

- 外部ServiceやFileを変更しない．
- OpenAI／Claudeで同じ意味のToolを使う．
- 最小のTool TaskにしてAPI Costを抑える．

### AGT実験の管理階層

```text
org-demo
├── agent-a：task-a-1，task-a-2
└── agent-b：task-b-1，task-b-2
```

### 管理粒度の意味

| 粒度 | この実験での意味 |
|---|---|
| Task | Agentへ依頼する1回の処理．本実験では1回のAgent runに相当 |
| Agent | 複数Taskを実行する論理的な実行主体 |
| Organization | 複数AgentのCostをまとめて管理する最上位の論理Scope |

OrganizationはOpenAI／Anthropic Platform上の契約Organizationを意味するとは限らない．今回の
実験では，`org-demo`用に作成した1つのmemory上の`CostGuard` instanceをOrganization境界として
扱った．

## 図案

```text
SDK単体
Agent Runtime → Model API

AGT統合
AGT CostGuard → Agent Runtime → Model API
      ↑               │
      └── Cost／Usage ┘
```

## 強調する一文

> AGTはModelを実行せず，OpenAI／Claudeから得たCostを使って次のTaskを許可・拒否する．

## 発表時の補足

- 「AGT単体」と呼ばず，「AGT＋OpenAI」「AGT＋Claude」と表現する．
- OpenAIではToken usageを固定価格表でUSD換算した．
- ClaudeではSDKが返す`total_cost_usd`を利用した．
- Model間のCost絶対値はSystem Context等が違うため単純比較しない．
- Organizationについては，次のように口頭で補足する．  
  「ここでいうOrganizationは，複数AgentのCostを合算して共通上限を適用する論理的な管理範囲です．
  OpenAIやAnthropicの契約Organizationそのものを検証したわけではありません．」

## 想定説明時間

50〜60秒

---

# Slide 3．SDK単体：UsageとBudget停止の結果

## このスライドの目的

OpenAIとClaudeのSDK単体で，何を取得・制限できたかを比較する．

## タイトル案

> SDK単体では，OpenAIはturn制限，ClaudeはUSD Budgetを提供

## スライドへ書く内容

### 実測結果

| 対象 | Usage／Cost取得 | 設定した上限 | 実際の停止結果 |
|---|---|---|---|
| OpenAI SDK | 418 tokens，推定`$0.00003385` | `max_turns=1` | Tool実行後，最終回答前に停止 |
| Claude SDK | 2,211 tokens，SDK推定`$0.003782` | `max_budget_usd=0.002` | `budget_exhausted`で停止 |

### `turn`と`max_turns`の意味

本実験では，**1 turnを，AgentがModelを1回呼び出して次の行動を判断する単位**として説明する．
Toolを実行した結果を受けてModelが再判断する場合は，次のturnになる．`max_turns`は，このAgent loopで
許容する最大turn数であり，Token数やUSD Costの上限ではない．

```text
通常実行
Turn 1：Model判断 → record_step Tool
Turn 2：Tool結果を受けてModel判断 → 最終回答「done」

max_turns=1
Turn 1：Model判断 → record_step Tool
Turn 2へ進む前に停止 → 最終回答なし
```

### Claudeのovershoot（超過分）

本発表では，**overshoot（超過分）を，Budget上限へ達したと判定して停止した時点で，実Costが既に
設定額を超えていた金額**として説明する．以降はovershootと表記する．

評価軸の「超過時停止」は，上限へ達したときに実行を止められるかを問う．一方overshootは，止めたにも
かかわらず既に超えていた量であり，別の概念である．

したがってovershootは，制御が失敗した量ではなく，制御が正しく働いてもなお避けられなかった量で
ある．Claudeの`max_budget_usd`が機能しなかったのではなく，設定額を厳密に超えない上限ではなかった，
という意味になる．

原因はSlide 1で述べたUsageの確定時点にある．Costは呼び出しが完了して初めて確定するため，Budget
判定は1回のModel呼び出しが終わった後になる．したがって，その1 call分は上限を超え得る．

```text
設定Budget     $0.00200
停止時Cost     $0.00247
overshoot      $0.00047（23.5%）
```

本実験は逐次実行のため，overshootは1 call分に留まった．並行実行では複数callが同時に確定するため，
幅はさらに広がり得る．

### `client-side estimate`の意味

Claude Agent SDKが返す`total_cost_usd`は，SDKがclient側でToken数と価格表から算出した推定USDで
あり，Anthropicの請求Systemが確定した金額ではない．

| 用語 | 意味 | 本実験での該当 |
|---|---|---|
| client-side estimate | SDKまたはApplicationがUsageと価格表から算出した推定USD | Claudeの`total_cost_usd`，OpenAIの算出Cost |
| Provider Billing | Provider Platform側が確定する請求額 | 本実験では照合していない |

OpenAI側もApplicationが同じ方法で算出しているため，**算出主体が違うだけで，どちらもestimateで
ある点は同じ**である．本発表のUSD値はGovernance挙動の比較用であり，請求額のsource of truthでは
ない．

### 比較結果

| 観点 | OpenAI SDK | Claude SDK |
|---|---|---|
| Token usage | ○ | ○ |
| SDKが返すUSD Cost | ×：Application側計算 | ○：client-side estimate |
| USD Budget | SDK標準では× | ○：`max_budget_usd` |
| Agent loop停止 | ○：`max_turns` | ○：Budget／turn |
| Agent／Organization横断 | SDK標準では× | SDK標準では× |

## 図案

OpenAIとClaudeを左右に分ける．OpenAI側には2 turnの小さな流れ，Claude側にはBudget線を少し
越えて停止する図を置く．

```text
OpenAI                              Claude Cost
Turn 1 → Tool → Turn 2             0 ── Budget $0.002 ── Stop $0.00247
max_turns=1では ↑ の前で停止
```

## 強調する一文

> Claudeはrun単位USD Budgetを持つが，設定額を厳密に超えない上限ではなかった．

## 発表時の補足

- OpenAIの`max_turns`はUSD Budgetではなく，Agent loopのResource上限である．
- 口頭では，次のように説明する．  
  「このTaskは，1回目のModel呼び出しでToolを選び，Tool結果を受けた2回目のModel呼び出しで
  最終回答を作ります．`max_turns=1`にすると，Toolは実行されますが，2回目のModel判断へ進む前に
  停止しました．」
- OpenAIでもApplication側実装を追加すればUSD制御は可能だが，SDK標準機能ではない．
- Claude Budget停止時は`ResultError`となり，Costと停止理由は取得できたが，error payloadのusageは
  0 tokensだった．この点は口頭または脚注に留める．
- overshootは実装Bugではなく，事後確定するCostでBudgetを判定する構造から生じる．
- ClaudeとOpenAIのUSD値はどちらもestimateであり，算出主体が違うだけである．

## 想定説明時間

70〜90秒

---

# Slide 4．AGT：Task／Agent／Organization単位の停止結果

## このスライドの目的

AGTを追加する価値を，機能一覧ではなく実際のAPI実行数で示す．

## タイトル案

> AGTは複数Task／Agentを横断して次のAPI呼び出しを拒否

## スライドへ書く内容

### 実行フロー

```text
check_task(推定Cost)
       ↓
 allow／deny
   │       └─ deny：APIを呼ばず停止
   ↓
実API Task
   ↓
実Costをrecord_cost()
```

### 実測結果

OpenAIとClaudeで同じ制御結果になったため，1つの表へ統合する．

| Budgetケース | API実行数 | 停止数 | 確認できたこと |
|---|---:|---:|---|
| Normal | 4/4 | 0 | Task CostをAgent／Organizationへ集計 |
| Task上限 | 0/4 | 4 | 全TaskをAPI前に拒否，Cost 0 |
| Agent上限 | 2/4 | 2 | agent-a／agent-bの2番目を個別に拒否 |
| Organization上限 | 1/4 | 3 | Agentを横断して残りを拒否 |

### Agent上限の図

```text
agent-a：task-a-1 ○ → task-a-2 ×
agent-b：task-b-1 ○ → task-b-2 ×
```

### Organization上限の図

```text
task-a-1 ○ → Organization残Budget不足
task-a-2 ×，task-b-1 ×，task-b-2 ×
```

## 強調する一文

> DenyされたTaskではProvider APIへ到達せず，OpenAI／Claudeのどちらでも同じ粒度別停止を確認した．

## 発表時の補足

- AGTがProvider Costを自動取得したわけではなく，Application AdapterがCostを渡している．
- Organizationは，今回の実験では1つの`CostGuard` instanceとして表現した．
- Task別に異なる上限を設定したのではなく，`per_task_limit`はinstance共通値である．
- OpenAI／ClaudeごとのToken・Cost詳細は見せず，制御結果が同じだった点に集中する．

## 想定説明時間

70〜90秒

---

# Slide 5．結論：SDK内制限と横断Budgetを組み合わせる

## このスライドの目的

4つの評価軸への回答と，実運用上のArchitectureを1枚でまとめる．

## タイトル案

> Cost Governanceは1つの機能では完結しない

## スライドへ書く内容

### 最終比較

| 観点 | OpenAI SDK単体 | Claude SDK単体 | AGT統合 |
|---|---|---|---|
| Usage取得 | Token | Token＋推定USD | Provider値をHostから入力 |
| Budget | turn／output token | run単位USD／turn | Task／Agent／Organization |
| 停止 | Agent loop内 | Agent loop内 | 次TaskのAPI呼び出し前 |
| 主な管理範囲 | 1 run | 1 run | 複数run／Agent横断 |

### 実験から得た考察

1. **停止境界が異なる**  
   SDKはrun内部，AGTは次Taskの開始前を主に制御する．
2. **overshootは起こり得る**  
   実CostはAPI応答後に確定するため，1 call／1 task分は上限を超える可能性がある．
3. **AGTにはAdapterが必要**  
   Provider UsageをUSDへ変換し，AGTへ渡すApplication実装が必要である．
4. **本番では永続化が必要**  
   `CostGuard`のmemory stateだけでは，複数processや月次管理を継続できない．

### 推奨構成

```text
SDKのrun内制限
  max turns／max tokens／Claude USD Budget
                     ＋
AGT等の横断Budget
  Task／Agent／Organization
                     ＋
永続Cost Ledger／Provider Billing
  長期集計／請求照合
```

## 最後に強調する一文

> Run内部はSDK，複数Task／Agentの横断管理は外部Budget Layer，正確な長期管理は永続Ledgerで補う．

## 発表時の補足

- 「AGTがあればSDKのBudgetは不要」という結論ではない．
- Claudeのrun内BudgetとAGTのOrganization Budgetは競合ではなく，異なる階層を担当する．
- OpenAI SDK標準にUSD Budgetがなくても，Usageを利用したApplication側制御は可能である．
- AGTの`check_task()`はBudgetを予約しないため，並行実行では別途予約・精算設計が必要である．

## 想定説明時間

60〜80秒

---

# 5枚に収めるための情報配置

## Slide本体に載せる数値

次の数値だけに絞る．

- OpenAI baseline：418 tokens，推定`$0.00003385`
- OpenAI stop：`max_turns=1`で停止
- Claude baseline：2,211 tokens，`$0.003782`
- Claude stop：Budget`$0.002`，停止時`$0.00247`，overshoot 23.5%
- AGT：Normal 4/4，Task 0/4，Agent 2/4，Organization 1/4

## Slide本体に載せない数値

- AGT正常系のProvider別Total Tokens
- AGT正常系のProvider別Total Cost
- 保存結果全体のCost合計
- 各Taskの個別Cost
- 失敗試行のCost

これらはGovernanceの結論を変えず，スライドを読みにくくするため，本編から外す．

## 脚注へ置く内容

- OpenAI Costは固定価格表を使ったApplication側推定．
- Claude CostはSDKのclient-side estimateで，請求のsource of truthではない．
- Claude Budget停止時の0 tokensはerror payload上の値であり，実消費0ではない．
- 実験は逐次実行であり，並行実行の実API検証は行っていない．

---

# 質疑用Backupとして準備する内容

本編の5枚には含めないが，質問された場合に提示できるよう，次を1〜2枚のBackupへまとめてもよい．

## Backup 1．全実測結果

詳細レポートの「全実測結果」表をそのまま利用する．

参照：[`cost_governance_experiment_results_2026-09-03.md`](cost_governance_experiment_results_2026-09-03.md)

## Backup 2．AGT実装上の制約

- `check_task()`はadvisory checkであり，Budgetを予約しない．
- `check_and_charge()`は原子的だが，推定額と実Costの精算APIがない．
- `CostGuard`はProvider Costを自動取得しない．
- Stateはmemory上にあり，永続化されない．
- Micro-costではreason／summaryの丸めにより`$0.00`と表示される場合がある．

---

# 枚数をさらに減らす場合

## 4枚構成

Slide 1とSlide 2を統合する．

1. 背景・評価軸・実験対象
2. SDK単体結果
3. AGT粒度別結果
4. 最終比較・考察

ただし，初見の聞き手には比較対象と実験設計の説明が短くなりすぎるため，基本は5枚を推奨する．

## 6枚構成

AGTを少し重視したい場合は，Slide 4を次の2枚へ分割する．

1. AGT統合フロー
2. Task／Agent／Organizationの実測結果

それ以外のスライドは5枚構成と同じにする．

---

# 表現上の注意

- 「AGT単体で実APIを実行した」と表現しない．  
  → 「AGT＋OpenAI／Claude Runtime」とする．
- 「AGTがCostを自動取得した」と表現しない．  
  → Host側AdapterがCostを渡した．
- 「ClaudeはBudgetを超えない」と表現しない．  
  → 実験では23.5%のovershootがあった．
- 「OpenAIではUSD Budgetを実現できない」と断定しない．  
  → SDK標準ではないが，Application側実装は可能．
- 「Organization Budgetが永続的に保存される」と表現しない．  
  → 今回はmemory上の1つの`CostGuard` instanceで表現した．
- OpenAIとClaudeのCost差をModel価格差として説明しない．  
  → System ContextやToken数が異なるため，Governance挙動の比較に限定する．

---

# ChatGPT等でスライドを作成する際の注意事項

## 1．一緒に渡す資料

このアウトラインだけでも内容案は作成できるが，数値の再確認と既存発表への統合のため，可能であれば
次の資料も同時に渡す．ChatGPTからMarkdown内のlocal linkを自動的に開けるとは限らないため，
必要なFileは個別にUploadする．

### 必須

1. `cost_governance_experiment_slide_outline_2026-09-03.md`  
   5枚の構成・情報量・Storylineの基準とする．
2. `cost_governance_experiment_results_2026-09-03.md`  
   数値と実験結果を確認するsource of truthとする．

### 可能であれば追加

3. 発表全体の最新スライドまたは構成案  
   Cost Governanceの前後との重複や文脈を調整するために使う．
4. 既存スライドのTemplate／Screenshot  
   Font，Color，余白，Header，Footer等を合わせるために使う．
5. Logo，指定Font，Color code等のDesign asset  
   所属組織や発表会のFormatがある場合に渡す．

## 2．事前に決めて伝える情報

スライド生成を依頼する前に，少なくとも次を明示する．

| 項目 | 指定例 |
|---|---|
| 発表全体の時間 | 15分 |
| Cost Governanceの時間 | 4〜6分 |
| 聞き手 | LLMの基本は知るがAgent SDK／AGTは初見 |
| スライド枚数 | 本編5枚を厳守 |
| Aspect ratio | 16:9 |
| 言語 | 日本語 |
| 出力形式 | PowerPoint／Google Slides原稿／Marp等 |
| Speaker Notes | 各Slideへ付ける |
| Citation | 各Slide脚注または最後にまとめる |
| 前のSlide | 例：Tool／Policy Governanceの比較 |
| 次のSlide | 例：全体の考察・結論 |

特に「前のSlide」と「次のSlide」を伝えると，Cost Governanceだけが独立した発表のように見えることを
防ぎやすい．

## 3．文字過多を防ぐ制作ルール

このアウトラインは制作に必要な候補を多めに含むため，すべてをSlide本文へ転記しない．生成時には
次の制約を明示する．

- 1 SlideにつきMessageは1つとする．
- Slide titleは内容名ではなく，可能な限り結論を表す文にする．
- 本文は最大3〜5項目とする．
- 1項目は原則2行以内とする．
- 表は1 Slideにつき最大1つとする．
- 長い説明，例外，API仕様はSpeaker Notesへ移す．
- 図，表，比較Cardのいずれかを中心にし，すべてを同時に置かない．
- Source code全文やCLI commandは本編へ載せない．
- 全12結果を本編へ載せない．
- Backupの内容を本編5枚へ混ぜない．

### Slideごとの優先要素

| Slide | 本体へ残す要素 | Speaker Notesへ移す要素 |
|---|---|---|
| 1 | 4つの評価軸，Agent loop図 | TokenとUSDの細かな違い，Usageの定義と確定時点 |
| 2 | 比較対象，共通Task，AGTの位置 | Version詳細，Cost変換方法の詳細 |
| 3 | OpenAI／Claude比較，`max_turns`の意味，Claude overshoot | `ResultError`，usage 0の注意，overshootとclient-side estimateの定義 |
| 4 | AGTの4ケース結果，Agent／Organizationの違い | API名，Budget値，丸め問題 |
| 5 | 最終比較，推奨Architecture | 並行実行，予約・精算，永続化詳細 |

## 4．図表作成上の注意

### Slide 1

- Agent loopと管理粒度を左右に分ける．
- 背景説明を文章で詰め込まず，矢印で「複数callになる」ことを見せる．

### Slide 2

- OpenAI／Claude SDKとAGTを同列の3製品比較図にしない．
- SDKはRuntime，AGTは外側のBudget Layerとして上下または前後関係で描く．
- `Task → Agent → Organization`の包含関係をTreeまたは括弧で示す．
- OrganizationをProvider契約単位と誤解させないよう，「複数Agentをまとめる論理Scope」と短く注記する．

### Slide 3

- OpenAIとClaudeを左右の比較Cardにする．
- OpenAI側は`Turn 1 → Tool → Turn 2 → Final`を小さく描き，`max_turns=1`の停止位置を示す．
- Claudeの`$0.002 → $0.00247`は，小さなGaugeまたは直線でovershootを視覚化する．
- OpenAIとClaudeのCostを棒Chartで比較しない．Model価格比較と誤解されるためである．

### Slide 4

- 4ケースのAPI実行数を中心にする．
- `4/4 → 0/4 → 2/4 → 1/4`を色で示す．
- AgentとOrganizationの違いは，小さなTreeまたは○／×の並びで示す．

### Slide 5

- 最終比較表と推奨Architectureを両方大きく載せない．
- 比較表を主にする場合，Architectureは下部へ3 Layerの短い図として置く．
- Architectureを主にする場合，比較結果は3つの短い結論へ変換する．

## 5．正確性に関する必須ルール

生成AIへ，次を変更・推測しないよう明示する．

- 実験結果の数値を丸め直したり，見栄えのために変更しない．
- 提供資料にない実験結果や機能を追加しない．
- OpenAIのUSD CostをSDKが直接返したように説明しない．
- Claudeの`total_cost_usd`を実請求額として断定しない．
- AGTがProvider Usage／Costを自動取得したように説明しない．
- AGTをAgent Runtimeとして描かない．
- ClaudeのBudgetが設定額を厳密に超えないと説明しない．
- Claude Budget停止結果の0 tokensを「API未利用」と解釈しない．
- AGTのOrganization Budgetが永続DBへ保存されると説明しない．
- OrganizationをOpenAI／Anthropic Platformの契約Organizationとして説明しない．
- `max_turns`をTool呼び出し回数やToken上限として説明しない．
- Usageを実行前の見積もり値として説明しない．API応答後に確定する事後値である．
- overshootをSDKの実装Bugとして説明しない．Costが事後確定する構造上の帰結である．
- `total_cost_usd`やApplication算出Costを確定請求額として説明しない．いずれもclient側のestimateで
  ある．
- SDK標準で提供されない機能を「実現不可能」と断定しない．
- OpenAIとClaudeのCost差をModelの価格性能差として結論付けない．

## 6．推奨する作成手順

最初からPowerPoint等を生成させるのではなく，次の順序で確認する．

```text
1. 5枚のStoryboardを文章で作成
       ↓
2. Messageと情報量を確認
       ↓
3. 図表のLayoutを確認
       ↓
4. 数値と表現を結果Reportと照合
       ↓
5. PowerPoint／Slides／Marp等を生成
       ↓
6. 既存発表へ挿入して前後のつながりを調整
```

Storyboard段階では，各Slideについて次を出力させる．

- Slide title
- 最も伝えたい一文
- Slide本文
- 図表のLayout
- Speaker Notes
- 脚注／Source
- 前後SlideへのTransition

## 7．そのまま利用できるPrompt

以下の`［ ］`部分を発表条件に合わせて変更して使用する．

```text
添付した以下の資料を基に，AI Agent Governance発表の中で使用する
Cost Governanceパートのスライドを設計してください．

1. cost_governance_experiment_slide_outline_2026-09-03.md
2. cost_governance_experiment_results_2026-09-03.md
3. ［発表全体の構成または既存スライド］
4. ［Design template／参考スライド］

発表条件：
- 発表全体：［15分］
- Cost Governance部分：［4〜6分］
- 聞き手：［LLMの基本は知るが，Agent SDKとAGTは初見］
- Cost Governanceの前：［Tool／Policy Governanceの比較］
- Cost Governanceの後：［全体の考察・結論］
- 出力Format：［PowerPoint／Google Slides原稿／Marp］
- Aspect ratio：16:9
- 言語：日本語

最重要要件：
- 本編は必ず5枚にしてください．
- 1枚につき主張は1つにしてください．
- Slide本文は最大3〜5項目とし，長い説明はSpeaker Notesへ移してください．
- 図，表，比較Cardのいずれか1つを各Slideの中心にしてください．
- 全12実験の詳細値やSource code全文は本編に載せないでください．
- Backupの内容を本編5枚へ追加しないでください．
- 数値は添付した実験結果Reportと完全に一致させてください．
- 添付資料にない情報を推測で追加しないでください．

使用する構成：
1. Cost Governanceの4つの評価軸
2. 比較対象と共通実験設計
3. OpenAI／Claude SDK単体の結果
4. AGTのTask／Agent／Organization別停止結果
5. 最終比較と実運用への示唆

正確性に関する注意：
- AGTはAgent Runtimeではありません．「AGT＋OpenAI／Claude Runtime」と表現してください．
- AGTがProvider Costを自動取得したとは説明しないでください．
- OpenAIのUSD CostはToken usageと固定価格表によるApplication側推定です．
- ClaudeのCostはSDKのclient-side estimateで，実請求額のsource of truthではありません．
- ClaudeではBudget $0.002に対して$0.00247までovershootしました．
- OpenAIとClaudeのCost差をModel価格差として結論付けないでください．
- Taskは1回のAgent run，Agentは複数Taskを実行する論理主体として説明してください．
- Organizationは複数AgentのCostをまとめる論理Scopeです．OpenAI／Anthropicの契約Organizationを
  検証した実験ではありません．今回はmemory上の1つのCostGuard instanceで表現しています．
- turnはAgentがModelを1回呼び出して次の行動を判断する単位として説明してください．
- max_turnsはAgent loopの最大turn数であり，Tool呼び出し回数，Token上限，USD上限ではありません．
- Usageは実行前の見積もりではなく，API応答後に確定する事後値です．そのためBudget判定は
  最短でも1 call分遅れます．
- overshootは実装Bugではなく，Costが事後確定する構造から生じる現象として説明してください．
- OpenAIの通常実行は，Turn 1でToolを選択・実行し，Turn 2で最終回答を生成しました．
  max_turns=1ではTool実行後，Turn 2へ進む前に停止しました．

まずPowerPoint等を作成せず，以下を含む5枚のStoryboardをMarkdownで提示してください．
- Slide title
- 最も伝えたい一文
- 本文
- 図表の具体的なLayout
- Speaker Notes
- 脚注／Source
- 前後SlideへのTransition

Storyboardを確認するまで，最終スライド生成には進まないでください．
```

## 8．Storyboard確認Checklist

生成されたStoryboardについて，次を確認してから最終スライドを作る．

### Storyline

- 5枚だけで「目的→方法→結果→考察」を追えるか．
- Slide 1で定義した4つの評価軸へSlide 5で回答しているか．
- Cost Governance部分だけが発表全体から独立して見えないか．

### 情報量

- 各Slideの主張が1つに絞られているか．
- 発表者が読まなくても，図表から主要結果を理解できるか．
- Slide 3〜5が表と文章で過密になっていないか．

### 正確性

- OpenAI／Claude／AGTの役割を混同していないか．
- Task，Agent，Organizationの包含関係を初見の聞き手が理解できるか．
- OrganizationをProvider Platformの契約Organizationとして誤解させていないか．
- `turn`と`max_turns`の意味，今回の停止位置が説明されているか．
- USD Costの算出主体を正しく区別しているか．
- Claudeのovershootを隠していないか．
- AGTの粒度別API実行数が`4/4，0/4，2/4，1/4`になっているか．
- 脚注に推定値と実験上の制約が記載されているか．

### Design

- 16:9で文字が小さくなっていないか．
- Colorだけに依存せず，○／×やLabelでも結果を区別できるか．
- 既存スライドのFont，Color，余白，Header／Footerと揃っているか．
