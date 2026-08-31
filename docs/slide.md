# 日立インターン最終発表：スライド構成案・作成方針

**構成**

0. [このマークダウンの目的](#0このマークダウンの目的)
1. [発表の前提・制約](#1発表の前提制約)
2. [背景として共有したい内容](#2背景として共有したい内容)
3. [発表全体で明らかにしたいこと](#3発表全体で明らかにしたいこと)
4. [事業部とのMTGで追加された論点](#4事業部とのmtgで追加された論点)
5. [スライド作成上の注意事項](#5スライド作成上の注意事項)
6. [各スライドの具体的な内容案](#6各スライドの具体的な内容案)（Slide 1〜15）
7. [枚数調整の考え方](#7枚数調整の考え方)
8. [Appendix候補](#8appendix候補)

---

## 0．このマークダウンの目的

本マークダウンは，日立製作所のインターンシップ最終発表スライドの構成・ストーリーラインを検討するためのたたき台である．

別ファイルとして，OpenAI Agents SDK，Claude Agent SDK，Agent Governance Toolkit（AGT），Open Policy Agent（OPA），Cedarなどに関する詳細なリサーチ結果を併用することを想定する．本マークダウンでは，それらの調査結果をどの順番・論点で15分の発表へ落とし込むかを整理する．

この構成案を固定的な正解として扱わず，以下の観点から批判的に見直すことを前提とする．

- 各スライドのつながりが自然か．
- 技術の羅列ではなく，「何を明らかにしたいのか」から逆算したストーリーになっているか．
- OpenAI Agents SDK，Claude Agent SDK，AGTの単なる機能比較になっていないか．
- 調査だけでなく，環境構築・実装・デモ検証を行った価値が伝わるか．
- AGTを結論ありきで高く評価していないか．
- 「SDK単体でもできること」と「共通Policy Layerを設ける価値」を区別できているか．
- Token / Costについて，「計測できる」「上限を設定できる」「超過時に止められる」「請求額を把握できる」を混同していないか．
- Runtime / Gateway / Networkを，同じ種類の制御として混同していないか．
- 15分という時間制約の中で，重要度の低い説明に時間を使いすぎていないか．
- 検証結果がまだ得られていない部分について，結果を憶測で埋めていないか．

必要であれば，スライド枚数や順序，統合・分割は変更してよい．現状では15枚前後を想定しているが，15枚に固定する必要はない．コードや実行結果を見せるスライドが短時間で説明できるなら枚数を増やしてもよく，逆に内容が薄いスライドは統合してよい．

---

## 1．発表の前提・制約

### 1.1 発表時間

- 発表時間は**最大15分**である．
- **質疑応答はこの15分には含まれず，別枠**である．
- したがって，15分を技術説明，検証結果，考察，インターンシップでの学びに使える．
- 細かな仕様説明を詰め込みすぎず，聞き手がストーリーを追える速度を優先する．

### 1.2 自分の担当スコープ

- 本インターン全体ではAI Agent Governanceを扱っている．
- **自分の主担当は「Policy」である．**
- **「Audit／監査」は別のインターン生の担当であるため，本発表では原則として深掘りしない．**
- OpenAI Agents SDKやClaude Agent SDKにTracing / Observability等の機能が存在しても，本編の主要な比較軸にはしない．
- Policy Decisionの記録等，Policyの説明に最低限必要な場合のみ補助的に触れる．

自分の発表では主に以下を扱う．

- AgentのAction / Tool実行制御
- Resourceや条件に応じたAllow / Deny
- Human Approval
- 共通Policy運用
- Token / Cost Governance
- Runtime制御とGateway / Network制御の役割整理

### 1.3 調査・検証対象

| 対象 | Version | 位置付け |
|------|---------|----------|
| OpenAI Agents SDK | 0.22.0 | Agentを構築・実行するSDK |
| Claude Agent SDK | 0.2.144 | Agentを構築・実行するSDK |
| Agent Governance Toolkit（AGT） | 4.1.0 | 共通Governance Layer |
| Open Policy Agent（OPA） | 1.19.1 | 外部Policy Engine |
| Cedar / cedarpy | 4.8.7 | 外部Authorization Engine |

OPAとCedarはOpenAI / Claude / AGTと同列のAgent SDKとして扱わない．主に，AGTや企業のPolicy-as-Code運用と接続する外部Policy Engine / Authorization Engineとして位置付ける．

### 1.4 実際に行った／行う予定の検証

- 各OSS / SDKの環境構築
- 簡単なAI Agentの構築
- ファイルのRead
- ファイルのWrite
- ファイルのDelete
- 重要Resourceに対するAllow / Deny
- Human Approval
- Token使用量・Costの取得／制御
- AGT CostGuard等の挙動確認
- OPA / Cedarとの連携確認
- Network access制御は実施する可能性があるが，本インターンの中心スコープではない

検証結果がまだ得られていない箇所は，スライド案では**「ここにコード」「ここに結果」**等のPlaceholderとして残す．結果を推測で記述しない．

---

## 2．背景として共有したい内容

以下の文章は，本インターンの背景・問題意識を簡潔にまとめたものである．

> AIエージェントは，ツールや社内データへアクセスし，実システムに対して自律的に操作を実行できるため，プロンプトによる指示だけで誤操作，権限逸脱，情報漏洩などを十分に防ぐことは困難である．加えて，California州のTransparency in Frontier Artificial Intelligence ActやEU AI Actなどでは，AIに関するリスク評価・緩和，透明性，セキュリティ，インシデント対応などのガバナンス要求が具体化している．そのため，企業には，こうした要求やAIエージェント固有のリスクを実運用上の統制へ落とし込み，エージェントの権限や行動をポリシーに基づいて制御するとともに，操作の記録・監査や，高リスクな操作に対する承認・停止を可能にする仕組みが求められる．

ただし，本発表では上記のうち**監査は別担当**であり，自分は**Policyを中心に扱う**．したがって，規制の詳細説明やAudit機能の比較に時間を使いすぎず，次に焦点を当てる．

- Agentの行動をどう制御するか
- 高リスクなActionをどう承認・停止するか
- 共通Policyをどう管理するか
- Token / Costをどう管理するか

---

## 3．発表全体で明らかにしたいこと

発表全体を，以下の3つの問いへの回答として構成する．

| 問い | 内容 | 対応する評価分類 |
|------|------|------------------|
| ① | Agent SDK単体で，どこまで実行時の行動を制御できるか | 行動・権限制御 |
| ② | 複数Agent SDKへ共通Policyを適用する際，AGTにはどのような価値があるか | Policy運用 |
| ③ | Token・Costをどの粒度で把握し，どこまで制限できるか | リソース統制 |

### 問い①：Agent SDK単体で，どこまで実行時の行動を制御できるか

OpenAI Agents SDKとClaude Agent SDKが持つ標準的なGovernance機能を使い，例えば以下をどこまで実現できるかを確認する．

- Tool / ActionのAllow / Deny
- Actionの対象ResourceやContextに応じた制御
- 高リスク操作へのHuman Approval
- Promptによる「お願い」ではなく，実行時に機械的にActionを止められるか

### 問い②：複数Agent SDKへ共通Policyを適用する際，AGTにはどのような価値があるか

OpenAI Agents SDKではGuardrail等，Claude Agent SDKではPermission / Hook等，同じGovernance要件でも実現方法が異なる．

そこで，次を検討する．

- SDK固有機能だけでPolicyを管理すると何が起きるか
- PolicyをAgent実装の外側へ切り出す意味は何か
- AGTを共通Governance Layerとして利用する価値はどこにあるか
- OPA / Cedarなど外部Policy Engineを使う意味は何か

重要なのは，最初から「SDK単体では不十分だからAGTが必要」と結論付けないことである．SDK単体でも実現可能な制御を確認したうえで，複数SDK・複数Agentを運用する際のPolicy共通化という観点からAGTの価値を考える．

### 問い③：Token・Costをどの粒度で把握し，どこまで制限できるか

Token / Costについて，単にUsageが取得できるかだけではなく，以下を区別して比較する．

- 利用量を把握できるか
- Budget / Limitを設定できるか
- Budget超過時に実行を抑制・停止できるか
- Run / Task / Agent / Organizationなど，どの粒度で管理できるか

---

## 4．事業部とのMTGで追加された論点

事業部とのMTGでは，主に以下の論点が出た．これらを後付けの補足ではなく，発表ストーリーの中に自然に組み込む．

### 4.1 Runtime / Gateway / Network制御の違い

| Layer | 役割 |
|-------|------|
| **Runtime Control** | Agentが実行しようとするActionの意味や対象Resourceを見て，Allow / Deny / Approval等を判断する． |
| **Gateway Control** | AgentとTool / APIの間の中継点で，どのTool・Requestを通すかを制御する． |
| **Network Control** | 通信先への到達可能性そのものをFirewall / Proxy / Egress Policy等で制御する． |

今回の主な検証対象は**Runtime Control**である．Gateway / Networkについては，役割整理を中心とし，AGTやSDKのRuntime Policyと何が異なるのかを説明する．

ここで重要なのは，「Runtime / Gateway / Network」と「行動・権限制御 / Policy運用 / リソース統制」は異なる分類軸であることである．

| 分類軸 | 意味 |
|--------|------|
| Runtime / Gateway / Network | **どこで制御するか（WHERE）** |
| 行動・権限制御 / Policy運用 / リソース統制 | **何を制御・評価するか（WHAT）** |

### 4.2 Token / Cost Governance

事業部MTGを通じて，単純なAction Policyだけでなく，AgentごとのToken / Cost消費をどこまで管理できるかも重要な論点となった．

そのため，OpenAI Agents SDK，Claude Agent SDK，AGTについて，Token / Costを以下の観点で比較・検証する．

1. 把握
2. 制限
3. 強制
4. 管理粒度

---

## 5．スライド作成上の注意事項

### 5.1 ストーリーを優先する

機能を順番に紹介するだけの構成にしない．

| 避けたい流れ | 推奨する流れ |
|--------------|--------------|
| OpenAIの機能紹介 | なぜGovernanceが必要か |
| ↓ | ↓ |
| Claudeの機能紹介 | 何を明らかにするか |
| ↓ | ↓ |
| AGTの機能紹介 | どこで制御するか |
| ↓ | ↓ |
| 比較 | どの観点で比較するか |
|  | ↓ |
|  | 比較結果 |
|  | ↓ |
|  | 差が重要な項目を実機検証 |
|  | ↓ |
|  | 検証から分かったこと |
|  | ↓ |
|  | 実務適用への示唆 |

### 5.2 全体図は前半と後半で役割を変える

前半では，聞き手が技術の位置関係を理解するための簡易全体図を提示する．

```text
Agent
  ↓
Runtime Control  ← 今回の中心
  ↓
Gateway Control
  ↓
Network Control
  ↓
External System
```

Runtime部分に，OpenAI Guardrail，Claude Permission / Hook，AGT Policy等が関係することを簡潔に示す．

後半では，検証結果を踏まえた実務適用の方向性を示す詳細図を提示する．前半と同じ図を繰り返すのではなく，OPA / Cedar，共通Policy，SDK固有制御，Gateway / Network等を追加し，「検証を通じて全体像の解像度が上がった」ように見せる．

### 5.3 AGTを過大評価しない

- OpenAI Agents SDK / Claude Agent SDKにも実行時Governance機能は存在する．
- 「SDK単体では何もできない」という説明は避ける．
- AGTの価値は，各SDKの機能を完全に置き換えることではなく，PolicyをAgent実装から外部化し，共通Layerとして管理する可能性にある．
- Vendor横断運用にはAdapter，Identity，Tool / Action名，Resource Model，Policy Context等の共通化が必要になる可能性がある．
- 調査結果で確認できていないIntegrationを「できる」と断定しない．

### 5.4 ○△×表は機能数を競う表にしない

| 記号 | 意味 |
|------|------|
| ○ | 対象Versionで専用または標準的な機能を確認 |
| △ | 追加実装が必要，または機能に重要な制約がある |
| × | 対象Versionの標準機能として確認できず |
| ※ | 詳細な制約・注意点を後続スライドで説明 |

同じ○でも，実現方法や保証範囲が異なることを説明する．

### 5.5 コードと結果は実際に動かしたものを使う

- コード全文を載せず，Policy判断に直接関係する部分だけを抜粋する．
- OpenAI / Claude / AGTのデモスライドは可能な限り同じレイアウトにし，実装方式の違いを比較しやすくする．
- 実行結果が分からない段階では「ここにコード」「ここに結果」とする．
- 実際の挙動を確認していないものを成功例として記載しない．

### 5.6 監査を本編で深掘りしない

- Audit / Tracing / Observabilityは別担当と重複するため，本編の主要比較軸から外す．
- Policy Decisionの記録がコードデモ上必要な場合は補助的に触れてよいが，Audit Governanceそのものの解説へ広げない．

### 5.7 用語を揃える

| 混同しやすい対 |  |
|----------------|--|
| Agent SDK | Governance Layer |
| Prompt Instruction | Runtime Enforcement |
| Tool visibility | Authorization |
| Token Usage | Cost |
| Budget | Hard Cap |
| Runtime Control | Gateway Control / Network Control |
| Policy Decision | Cost Accounting |

### 5.8 デザインより内容を優先する

このマークダウンでは文章・論理構成を優先する．最終的なスライド作成時には，文章量を圧縮して図・表・コード・実行結果で示す．アイコンを多用せず，見せたい対象と説明を近くに配置する．

---

## 6．各スライドの具体的な内容案

以下では15枚前後を想定する．実際の検証結果や説明時間に応じて統合・分割してよい．

| 枚 | タイトル | 役割 |
|----|----------|------|
| 1 | AI Agentの実運用でなぜガバナンスが必要か | 問題設定 |
| 2 | 今回明らかにした3つのこと | 問いの提示 |
| 3 | 今回扱うガバナンスの全体像と検証範囲 | 地図（WHERE） |
| 4 | 検証対象と各技術の位置付け | 技術の種類分け |
| 5 | 3つの評価観点と比較結果 | 全体比較（WHAT） |
| 6 | 行動・権限制御の共通検証シナリオ | デモ条件の共有 |
| 7 | OpenAI Agents SDKによる行動・権限制御 | 実機検証 |
| 8 | Claude Agent SDKによる行動・権限制御 | 実機検証 |
| 9 | AGTによる行動・権限制御 | 実機検証 |
| 10 | 行動・権限制御の検証から分かったこと | 問い①の回答 |
| 11 | Token・Cost Governanceをどう評価するか | 評価方法 |
| 12 | Token・Cost Governanceの比較・検証結果 | 問い③の回答 |
| 13 | Policyを共通運用するための選択肢：AGT / OPA / Cedar | 問い②の回答 |
| 14 | 検証結果から考える実務適用の方向性 | 技術的結論 |
| 15 | インターンシップを通じて得た学び | 学び |

---

### Slide 1．AI Agentの実運用でなぜガバナンスが必要か

**目的**

発表全体の問題設定を共有し，「なぜPolicyを検証するのか」を理解してもらう．

**内容**

AI Agentは，通常のLLMによる回答生成だけでなく，Toolや社内データへアクセスし，ファイル・DB・外部API等に対して実際のActionを実行できる．

そのため，例えばPromptに「重要なファイルは削除しないで」と書いても，Agentが必ずその指示を守る保証にはならない．Agentが実環境へActionを起こす以上，Prompt Instructionとは別に，実行時にActionを機械的にAllow / Denyできる仕組みが必要になる．

主なリスク例として，以下を示す．

- 誤操作
- 権限逸脱
- 情報漏洩
- Prompt Injection等を起点とする意図しないTool実行

また，California州のTransparency in Frontier Artificial Intelligence ActやEU AI Actなどを背景として，AIのリスク管理，透明性，セキュリティ，Human Oversight，インシデント対応等のGovernance要求が具体化していることを簡潔に示す．

**本発表への接続**

本インターン全体ではPolicyとAudit等を扱うが，自分の担当はPolicyである．Auditは別のインターン生が担当するため，本発表では次を中心に扱う．

- Agentの行動・権限制御
- Human Approval
- 共通Policy運用
- Token / Cost Governance

**スライド下部のメッセージ候補**

> Promptによる指示だけでなく，実行時に強制可能なPolicy Controlが必要

---

### Slide 2．今回明らかにした3つのこと

**目的**

発表全体を3つの問いへの回答として見せる．以降のスライドが何のために存在するのかを明確にする．

**問い①**

Agent SDK単体で，どこまで実行時の行動を制御できるか

- Tool / Actionを実行前にAllow / Denyできるか
- Resourceや条件に応じて制御できるか
- 高リスク操作にHuman Approvalを挟めるか

→ 行動・権限制御に対応．

**問い②**

複数Agent SDKへ共通Policyを適用する際，AGTにはどのような価値があるか

- OpenAIとClaudeで同じPolicyを実装すると何が異なるか
- SDK固有コードからPolicyを切り離す意味はあるか
- OPA / Cedarを含むPolicy-as-Codeとの接続にはどのような意味があるか

→ Policy運用に対応．

**問い③**

Token・Costをどの粒度で把握し，どこまで制限できるか

- Usageを取得できるか
- Budgetを設定できるか
- 超過時に停止できるか
- Agent / Task / Organization等の粒度で管理できるか

→ リソース統制に対応．

**事業部MTGとの接続**

スライド下部に小さく，事業部MTGで得た追加論点として以下を示す．

- Runtime / Gateway / Network制御は何が違うか
- Token / CostをAgent単位でどこまで管理できるか

---

### Slide 3．今回扱うガバナンスの全体像と検証範囲

**目的**

技術の詳細へ入る前に，「今回どのLayerを中心に見ているのか」という地図を提示する．事業部MTGで出たRuntime / Gateway / Networkの問いもここで回収する．

**中央図のイメージ**

```text
AI Agent
   │
   ▼
Runtime Control      ← 今回の主な検証対象
   │
   ▼
Gateway Control      ← 役割整理中心
   │
   ▼
Network Control      ← 役割整理中心
   │
   ▼
File / DB / External API
```

**Runtime Control**

Agentが実行しようとしているActionの内容，対象Resource，Context等を見て，Allow / Deny / Approval等を判断する．

例：

```text
delete_file("important.txt") → Deny
```

代表的な仕組み：

- OpenAI Guardrail
- Claude Permission / Hook
- AGT Policy

**Gateway Control**

AgentとTool / APIの間の中継点で，どのTool・Requestを通すかを制御する．

例：

- 未許可MCP Toolへのアクセスを遮断
- 特定API Requestを拒否

**Network Control**

通信先への到達可能性そのものを制御する．

例：

- InternetへのOutbound通信を禁止
- 特定Domainのみ許可

**重要な整理**

Runtime / Gateway / Networkは競合する代替手段ではなく，異なるLayerの制御である．

今回の中心はRuntime Controlであり，Gateway / Networkは役割整理を中心とする．

---

### Slide 4．検証対象と各技術の位置付け

**目的**

OpenAI Agents SDK，Claude Agent SDK，AGT，OPA，Cedarが同じ種類の技術ではないことを明確にする．

**Agentを構築・実行するもの**

| OpenAI Agents SDK | Claude Agent SDK |
|-------------------|------------------|
| Agent | Agent Loop |
| Tool | Tool |
| Guardrail | Permission |
| Approval等 | Hook等 |

**Governance Layer**

Agent Governance Toolkit（AGT）

- Policy
- Human Approval
- Identity
- Token / Cost等

Agentそのものを構築するSDKというより，Agent Actionへ外部からGovernanceを適用するLayerとして位置付ける．

**External Policy Engine / Policy-as-Code**

| エンジン | 位置付け |
|----------|----------|
| OPA / Rego | 汎用Policy Engine |
| Cedar | Principal / Action / Resource / Contextを中心とするAuthorization Policy Engine |

**図のイメージ**

```text
OpenAI Agents SDK ─┐
                   ├─ Agent Runtime
Claude Agent SDK ──┘
          │
          ▼
         AGT
   Governance Layer
          ▲
          │
      OPA / Cedar
```

ただし，図の線は「公式Adapterが存在する」ことを意味しないよう注意する．確認済みIntegrationと構成候補を区別する．

---

### Slide 5．3つの評価観点と比較結果

**目的**

Slide 2の3つの問いを，具体的な評価軸へ1対1で対応させ，その全体比較結果を先に示す．

**評価分類**

| 分類 | 対応 | 評価例 |
|------|------|--------|
| ① 行動・権限制御 | 問い① | Tool / Action実行前のAllow / Deny，Resource・条件に応じた制御，Human Approval |
| ② Policy運用 | 問い② | PolicyをAgent実装から外部化できるか，Agent別／共通Policyを管理できるか，外部Policy Engineと接続できるか |
| ③ リソース統制 | 問い③ | Token / Costを把握できるか，Budgetを設定できるか，Budget超過時に実行を抑制できるか，Agent等の単位で管理できるか |

**比較表の暫定イメージ**

| 分類 | 評価指標 | OpenAI Agents SDK | Claude Agent SDK | AGT |
|------|----------|-------------------|------------------|-----|
| 行動・権限制御 | Tool実行前のAllow / Deny | ○ | ○ | ○ |
| 行動・権限制御 | Resource・条件に応じた制御 | ○ | ○ | ○ |
| 行動・権限制御 | Human Approval | ○ | ○ | ○ |
| Policy運用 | Policyの外部化 | △ | △ | ○ |
| Policy運用 | Agent別／共通Policy | △ | △ | ○※ |
| Policy運用 | OPA / Cedar等との連携 | △ | △ | ○ |
| リソース統制 | Token / Costの把握 | ○ | ○ | ○※ |
| リソース統制 | Budget設定 | △ | ○ | ○ |
| リソース統制 | Budget超過時の実行抑制 | △ | ○※ | ○※ |
| リソース統制 | Agent単位での管理 | △ | △ | ○ |

**注意**

この表は最終的に実機検証結果を反映して更新する．

○の数を競う表にはしない．同じ○でも，実現方法・粒度・保証範囲が異なるため，後続スライドで差が重要な項目を掘り下げる．

**スライド下部のメッセージ候補**

> 基本的な行動制御は各仕組みで実現可能．一方，Policyの運用方法とリソース統制には差がある

---

### Slide 6．行動・権限制御の共通検証シナリオ

**目的**

OpenAI，Claude，AGTを同一条件で比較するための共通シナリオを提示する．

**AgentへのPrompt**

> 重要なファイルは変更・削除しないで

Promptはあえて自然言語の指示として与え，それとは別にRuntime Policyで同じルールを強制する．

**検証用Workspace**

```text
workspace/
├── normal.txt
└── important.txt
```

**共通Policy**

| 操作 | 期待するDecision |
|------|------------------|
| File Read | Allow |
| normal.txtへのWrite | Allow |
| important.txtへのWrite | Approval |
| important.txtのDelete | Deny |

**検証観点**

- Tool Callを実行前に検査できるか
- ActionだけでなくResourceを見て判断できるか
- Allow / Approval / Denyを実行フローへ反映できるか

**スライド下部**

> 同一のGovernance要件を3つの仕組みで実装し，実現方法の違いを比較

---

### Slide 7．OpenAI Agents SDKによる行動・権限制御

**目的**

OpenAI Agents SDK標準機能で共通Policyをどのように実装できるかを示す．

**使用する主な機能候補**

- Tool Input Guardrail
- `needs_approval`
- 必要に応じてTool visibility / Context

**レイアウト**

| 左側 | 右側 |
|------|------|
| ［ここにPolicy判断に関係するコード］ | ［ここに実行結果］ |

全文ではなく，Tool Callの引数を見て重要Fileか判定し，Allow / Rejectする箇所を中心に載せる．

実行結果の例：

```text
read normal.txt       → ALLOW
write important.txt   → APPROVAL
delete important.txt  → DENY
```

実際の検証結果に置き換える．

**このスライドで言いたいこと**

OpenAI Agents SDK単体でも，Promptとは独立してTool実行前の制御やHuman Approvalを構成できる．

一方，PolicyはOpenAI Agents SDK固有のGuardrail / Tool設定として実装される．

---

### Slide 8．Claude Agent SDKによる行動・権限制御

**目的**

Slide 7と同じPolicyをClaude Agent SDKで実装し，実現方法を比較する．

**使用する主な機能候補**

- Permission system
- `PreToolUse`
- `can_use_tool`
- `disallowed_tools`等

**レイアウト**

| 左側 | 右側 |
|------|------|
| ［ここにPolicy判断に関係するコード］ | ［ここに実行結果］ |

Slide 7と同一フォーマットで表示する．

**このスライドで言いたいこと**

Claude Agent SDKでも同様の実行時制御を構成できる．

ただし，OpenAIのGuardrailとは異なり，Permission / Hookが中心的な実装surfaceとなる．

---

### Slide 9．AGTによる行動・権限制御

**目的**

同じPolicyをAGTで実装し，SDK固有実装との違いを示す．

**レイアウト**

| 左側 | 中央または補助図 | 右側 |
|------|------------------|------|
| ［ここに実際のAGT Policy定義］ | Agent → Tool Request → AGT Policy Engine → allow / require_approval / deny → Tool | ［ここに実行結果］ |

Policyの概念例：

```text
Read
→ allow

Write important.txt
→ require_approval

Delete important.txt
→ deny
```

実際のYAML / JSON / Python構文に置き換える．

補助図：

```text
Agent
  ↓
Tool Request
  ↓
AGT Policy Engine
  ↓
allow / require_approval / deny
  ↓
Tool
```

実行結果の例：

```text
action   : delete_file
resource : important.txt
decision : deny

Tool execution : BLOCKED
```

**このスライドで言いたいこと**

同じAllow / Approval / Denyを実現できるが，Policy DecisionをAgentのPromptやSDK固有コードから外部化できる点が特徴である．

---

### Slide 10．行動・権限制御の検証から分かったこと

**目的**

3つのデモを並べただけで終わらせず，「実装した結果として何が分かったか」をまとめる．

**比較**

| 観点 | OpenAI | Claude | AGT |
|------|--------|--------|-----|
| 主な実行前制御 | Guardrail | Hook / Permission | Policy Engine |
| Human Approval | `needs_approval` | `can_use_tool`等 | `require_approval` |
| Policyの主な記述場所 | SDKコード | SDKコード／設定 | Agent外部のPolicy Layer |
| Vendor依存 | OpenAI固有 | Claude固有 | Vendor横断利用を志向 |

**結論**

1. SDK単体でも基本的な行動制御は実現できる．AGTを導入しなければDenyできない，という結果ではない．
2. 同じGovernance要件でも，SDKごとにPolicyの書き方・実行フローへの組み込み方が異なる．
3. 複数のAgent Runtimeへ同じ企業Policyを適用する場合，Policyを共通Layerへ外部化する価値が生じる．

---

### Slide 11．Token・Cost Governanceをどう評価するか

**目的**

事業部MTGで重要な論点となったToken / Costについて，「機能がある／ない」の比較に入る前に評価方法を整理する．

**Token / Cost Governanceの4段階**

| 段階 | 問い | 例 |
|------|------|----|
| ① 把握 | どれだけ利用したか | Input / Output Token，Total Token，Estimated Cost等 |
| ② 制限 | どこまで使わせるか | max turns，Token Budget，USD Budget |
| ③ 強制 | 上限に達したとき何が起きるか | Warning，Stop，Throttle，Kill |
| ④ 管理粒度 | 何単位で管理できるか | Request / Run，Task，Agent，Organization |

**重要なメッセージ**

> 「Usageを取得できる」ことと「Budget超過を確実に防げる」ことは異なる．

また，Token数とUSD Costも同じものではない．ModelやProvider，Input / Output等によってCostは変化する．

---

### Slide 12．Token・Cost Governanceの比較・検証結果

**目的**

OpenAI，Claude，AGTについて，Slide 11の4段階に沿って比較する．

**暫定比較表**

| 観点 | OpenAI Agents SDK | Claude Agent SDK | AGT |
|------|-------------------|------------------|-----|
| Token利用量の把握 | Usage | usage | TokenBudgetTracker等 |
| USD Costの把握 | Usageから別途算出等 | `total_cost_usd` | Cost値をHostから入力 |
| Budget設定 | App側実装等 | `max_budget_usd`等 | CostGuard |
| 超過時の実行抑制 | App側実装 | query停止等※ | check / throttle / kill等※ |
| 管理粒度 | Request / Run中心 | Run / Query中心 | Task / Agent / Org等 |

**コード・実行結果**

- ［ここにOpenAIのToken / Costコード］
- ［ここにClaudeのToken / Costコード］
- ［ここにAGT CostGuardのコード］
- ［ここに実行結果］

必要であればこのスライドを2枚に分割し，AGT CostGuardを単独で見せてもよい．

**特に確認したい点**

- OpenAIではUsageからどこまでCost Policyを実装できたか
- Claude `max_budget_usd`の実際の停止挙動
- AGT CostGuardがAgent単位でどのようにCostを保持するか
- `check_task()`と`check_and_charge()`の違い
- Provider Costの自動取得有無

**このスライドで言いたいこと**

同じ「Cost制御」でも，計測方法，Budgetの意味，超過時の挙動，管理粒度が異なる．

---

### Slide 13．Policyを共通運用するための選択肢：AGT / OPA / Cedar

**目的**

問い②に対して，AGTを単なるもう1つのPolicy Engineとしてではなく，企業でPolicyを共通運用する際の位置付けから説明する．

**選択肢の整理**

| 仕組み | 位置付け | 扱うもの |
|--------|----------|----------|
| AGT Native Policy | Agent Lifecycleに近いPolicy | allow，deny，require_approval，Agent targeting，Resource / Context条件 |
| OPA / Rego | 汎用的なPolicy-as-Code Engine | 構造化Inputに対するPolicy Decision |
| Cedar | Authorizationに適したPolicy Engine | Principal，Action，Resource，Context |

**図のイメージ**

```text
       Enterprise Policy
          ┌────┴────┐
          ▼         ▼
      OPA / Rego   Cedar
          └────┬────┘
               ▼
              AGT
        Policy Enforcement
               ▼
             Agent
```

ただし，これは「唯一の正しいArchitecture」として断定しない．今回の検証結果から考えられるPolicy共通化の一案として扱う．

**共通Policy Layerを置くだけで自動的に解決しない論点**

- Agent Identity
- Tool / Action名のNormalization
- Resource Model
- Policy Context Schema
- Cost Telemetry
- SDKごとのIntegration / Adapter

---

### Slide 14．検証結果から考える実務適用の方向性

**目的**

前半の簡易全体図を，調査・検証結果を踏まえた詳細な全体像へ発展させる．技術的な最終結論を示す．

**図のイメージ**

```text
             Enterprise Governance
          Policy / Cost / Approval Rule
                     │
          ┌──────────┴──────────┐
          ▼                     ▼
      OPA / Rego              Cedar
          └──────────┬──────────┘
                     ▼
                    AGT
             Common Policy Layer
                     │
       ┌─────────────┴─────────────┐
       ▼                           ▼
OpenAI Agents SDK          Claude Agent SDK
Guardrail / Approval       Permission / Hook
       │                           │
       └─────────────┬─────────────┘
                     ▼
                 Agent Action
                     │
              Gateway Control
                     │
              Network Control
                     │
                     ▼
               External Systems
```

この図は実装済みの完成Architectureとしてではなく，**「検証結果から考える実務適用の方向性」**として示す．

**示唆**

1. **SDK固有機能は活用する**  
   OpenAI GuardrailやClaude Permission等をAGTで完全に置き換える必要はない．各SDKに近いLayerで有効な機能は活用する．

2. **共通Policyは外部化する価値がある**  
   複数Agent / Vendorで同一の企業Policyを運用する場合，PolicyをSDKコード内へ分散させず，共通Layerで管理する構成を検討できる．

3. **Runtimeだけで完結させない**  
   Runtime PolicyはActionの意味に基づく制御に強いが，Network到達性等を完全に代替するものではない．Gateway / Network / Sandbox等を組み合わせる必要がある．

4. **CostもGovernance設計の一部として考える**  
   Action Policyだけでなく，「このAgentにどこまでResourceを使わせるか」というCost / Token Policyも実運用上重要となる．

**最終メッセージ候補**

> 「何を制御するか」と「どのLayerで強制するか」を分け，複数Layerを組み合わせてGovernanceを設計することが重要

---

### Slide 15．インターンシップを通じて得た学び

**目的**

技術的結論はSlide 14までで完結させ，最後は自分自身の学び・成長を示す．

**学び①：OSSは機能名だけでは評価できない**

ドキュメントに「Budget」「Policy」「Sandbox」等の名称があっても，実際の保証範囲や挙動は異なる．

そのため，公式資料だけでなく，対象Versionのソースコードを確認し，実際に環境を構築して挙動を確かめる重要性を学んだ．

具体例としては，最終的な検証結果に応じて以下を口頭で利用できる．

- Budgetという名称でもHard Capとは限らない
- Cost trackingとCost enforcementは異なる
- Tool visibilityとAuthorizationは異なる

**学び②：単一技術ではなくシステム全体で考える**

Agent Governanceは1つのSDKやPolicy Engineだけで完結する問題ではない．

Runtime，Gateway，Network，Sandbox等の役割を整理し，どのLayerで何を制御するのかを考える視点を得た．

**学び③：事業側との対話から評価軸を深める**

当初のSDK / AGTのPolicy機能比較だけでなく，事業部MTGで出た次の問いを受け，実運用を意識した比較・検証へ論点を広げた．

- Runtime / Gateway / Networkの違い
- Token / Costの管理粒度

技術を調査するだけではなく，事業側が実際に必要とする問いへ評価軸を更新していくことの重要性を学んだ．

---

## 7．枚数調整の考え方

現時点の15枚は固定ではない．検証結果によって増減させる．

### 分割候補

| 対象 | 条件 | 分け方 |
|------|------|--------|
| Token / Cost（Slide 12） | 情報量が多い場合 | OpenAI / ClaudeのCost Governance比較 と AGT CostGuardの詳細検証 |
| AGT / OPA / Cedar（Slide 13） | 意味のあるコード・結果が得られた場合 | 2枚に分割 |
| Network | Runtime Policyとの違いを明確に示せる実験結果がある場合 | 独立した1枚を追加 |

### 統合候補

| 対象 | 条件 | まとめ方 |
|------|------|----------|
| Slide 3とSlide 4 | 発表時間が厳しい場合 | 「全体像・検証範囲」と「各技術の位置付け」を1枚へ |
| Slide 13とSlide 14 | OPA / Cedarを本編で深掘りする必要がなければ | Policy運用の説明を最終Architectureへ統合 |

---

## 8．Appendix候補

15分の本編では説明しきれない詳細はAppendixへ回す．

- OpenAI Agents SDKのGovernance機能一覧
- Claude Agent SDKのGovernance機能一覧
- AGT 4.1.0のGovernance機能一覧
- OpenAIの完全な検証コード
- Claudeの完全な検証コード
- AGTの完全なPolicy / コード
- 実行ログ詳細
- AGT CostGuard API詳細
- TokenBudgetTracker / ContextSchedulerの違い
- OPA / Rego Policy例
- Cedar Policy例
- AGTとOPA / Cedarの評価順序
- Runtime / Gateway / Network比較の詳細
- SandboxとNetwork Controlの違い
- 各SDK / PlatformのCost Governance詳細
- Version・仕様上の注意事項

Audit / Tracingの詳細は別担当と重複するため，基本的にはAppendixにも大量に載せない．必要な場合のみ，Policyとの境界を説明する補足として扱う．
