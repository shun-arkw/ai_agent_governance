# Cost Governance実API実験結果

- 実験完了日：2026年9月3日（JST）
- OpenAI Agents SDK：0.22.0
- Claude Agent SDK：0.2.144
- Agent Governance Toolkit：4.1.0
- OpenAIモデル：`gpt-5-nano`
- Claudeモデル：`claude-haiku-4-5-20251001`
- 除外：`gpt-oss-120b`

## 1．結論

計画した実API実験はすべて完了した．

| 対象 | Usage取得 | Budget設定 | 超過時停止 | task粒度 | agent粒度 | organization粒度 |
|---|---|---|---|---|---|---|
| OpenAI SDK単体 | ○ | turn／出力token | ○：`max_turns` | run usage | × | × |
| Claude SDK単体 | ○ | USD／turn | ○：`max_budget_usd` | run Budget | × | × |
| AGT＋OpenAI | ○：OpenAI usage | ○：推定USD | ○：次taskを事前拒否 | ○ | ○ | ○ |
| AGT＋Claude | ○：Claude usage／Cost | ○：推定USD＋run USD | ○：次taskを事前拒否 | ○ | ○ | ○ |

OpenAI Agents SDK単体はtoken usageを取得でき，`max_turns`によってAgent loopを停止できた．
一方，SDK標準のrun単位USD Budgetはないため，USD Costは固定価格表とusageからApplication側で
算出した．

Claude Agent SDK単体は`total_cost_usd`と`max_budget_usd`を利用できた．ただし，Budget停止は
モデル呼び出し境界で行われるため，設定額を厳密に超えない保証ではなかった．

AGT統合では，Providerの実Costまたは算出Costを`CostGuard`へ記録し，task，agent，organizationの
各上限によって次の実API呼び出しを事前拒否できた．

## 2．全実測結果

`API calls`は実際にProvider関数へ到達したtask数，`Stopped`はSDKまたはAGTによって完了しなかった
task数である．

| Result | Tasks | API calls | Stopped | Tokens | Effective Cost (USD) |
|---|---:|---:|---:|---:|---:|
| OpenAI SDK baseline | 1 | 1 | 0 | 418 | 0.00003385 |
| OpenAI SDK max-turns stop | 1 | 1 | 1 | 199 | 0.00002115 |
| Claude SDK baseline | 1 | 1 | 0 | 2,211 | 0.00378200 |
| Claude SDK budget stop | 1 | 1 | 1 | 0 | 0.00247000 |
| AGT＋OpenAI normal | 4 | 4 | 0 | 1,672 | 0.00013540 |
| AGT＋OpenAI task deny | 4 | 0 | 4 | 0 | 0.00000000 |
| AGT＋OpenAI agent deny | 4 | 2 | 2 | 836 | 0.00006770 |
| AGT＋OpenAI organization deny | 4 | 1 | 3 | 418 | 0.00003385 |
| AGT＋Claude normal | 4 | 4 | 0 | 8,840 | 0.01518200 |
| AGT＋Claude task deny | 4 | 0 | 4 | 0 | 0.00000000 |
| AGT＋Claude agent deny | 4 | 2 | 2 | 4,538 | 0.00796000 |
| AGT＋Claude organization deny | 4 | 1 | 3 | 2,207 | 0.00377000 |

保存された12結果のEffective Cost合計は`$0.03345595`である．OpenAIの値はusageと固定価格表から
計算した値，Claudeの値はSDKのclient-side estimateであり，請求のsource of truthではない．

## 3．SDK単体の停止挙動

### 3.1 OpenAI Agents SDK

正常系は2 requests，418 tokensで完了し，Application側推定Costは`$0.00003385`だった．

`max_turns=1`では，最初のモデル応答とTool実行までは行われたが，最終回答を生成する次のturnへ
進まず`MaxTurnsExceeded`となった．この時点のusageは1 request，199 tokens，推定Cost
`$0.00002115`として取得できた．

したがって，`max_turns`はUSD Budgetではないが，Agent loopのResource上限として実際に停止を
強制できる．

### 3.2 Claude Agent SDK

正常系は2 requests，2,211 tokensで完了し，`total_cost_usd`は`$0.003782`だった．

`max_budget_usd=0.002`では次の結果となった．

- 停止理由：`budget_exhausted`
- SDK推定Cost：`$0.00247`
- overshoot（超過分）：`$0.00047`（23.5%）
- Toolは1回実行済み
- terminal error payloadのusage：0 tokens

本レポートでは，overshootを，Budget上限へ達したと判定して停止した時点で，実Costが既に設定額を
超えていた金額として扱う．§5の並行実行に関する記述も同じ意味である．

Claude Agent SDK 0.2.144はBudget到達時に通常完了の`ResultMessage`だけで終了せず，
`ResultError`も送出した．ただし，例外のraw result payloadからCost，停止理由，turn数を回収できた．
一方，このerror payloadではusageが0として返ったため，Budget停止時のtoken usageはこの経路だけでは
正確に取得できなかった．

## 4．AGT統合結果

実験内の階層は次のとおりである．

```text
org-demo
├── agent-a
│   ├── task-a-1
│   └── task-a-2
└── agent-b
    ├── task-b-1
    └── task-b-2
```

### 4.1 正常系

十分なBudgetでは，OpenAI，Claudeとも4 taskすべてが完了した．各taskの実CostがAgent別に加算され，
同じ`CostGuard`のOrganization合計にも反映された．

### 4.2 task上限

`estimated_task_usd > per_task_limit`となる条件では，OpenAI，Claudeとも4 taskすべてを
API呼び出し前に拒否した．Provider関数の呼び出し数とCostはいずれも0だった．

### 4.3 agent上限

Agent AとAgent Bの最初のtaskだけを許可し，それぞれの2番目のtaskをdaily limitで拒否した．
一方のAgentが上限へ達しても，別Agentの最初のtaskは実行できたため，Agent別Budgetが分離されている
ことを確認した．

### 4.4 organization上限

Agent Aの最初のtaskだけを許可し，残るAgent AのtaskとAgent Bの全taskをorganization monthly
Budgetで拒否した．したがって，1つの`CostGuard`をOrganization境界として複数Agentを横断した
停止が可能だった．

## 5．AGT統合の制約

実験では実Costを記録するため，taskを逐次実行して次の経路を使用した．

```text
CostGuard.check_task(estimated_cost)
    ↓ allow
実API task
    ↓
Providerの実Cost／算出Cost
    ↓
CostGuard.record_cost(actual_cost)
```

この方式には次の制約がある．

1. 実CostはAPI応答後に確定するため，実行中の1 task分はovershootし得る．
2. `check_task()`はBudgetを予約しないため，並行実行ではovershootし得る．
3. `check_and_charge()`は原子的だが，AGT 4.1.0には推定額を実Costへ精算・返金する専用APIがない．
4. `CostGuard`はOpenAI／ClaudeのCostを自動取得せず，Application側Adapterが必要である．
5. `CostGuard`のstateはmemory上にあり，このclass単体では永続化されない．

また，AGT 4.1.0はreason文字列をUSD小数2桁，summaryのCostを主に小数4桁へ丸める．そのため，
`gpt-5-nano`のようなmicro-cost実験では，判定自体は正しいにもかかわらず`$0.00 remaining`や
`spent_today_usd: 0.0`と表示される場合があった．正確な分析には，本実験JSONが保持する丸め前の
Provider Costを利用する必要がある．

## 6．Costに関する注意

保存済み結果の合計`$0.03345595`とは別に，次の実行が発生した．

- OpenAI：初期設定`max_output_tokens=128`による不完了run．APIへ到達したがusageを回収できなかった．
- Claude：最初のBudget停止run．Budget到達エラーになったが，修正前コードでは結果を保存できなかった．
- AGT＋Claude正常系：結果待機の判断により同条件を再実行した．先行runも後から完了し，先行結果
  `$0.015382`は同名JSONへの後続書き込みで置き換えられた．

したがって，実際の請求総額は保存済みJSONの合計より大きい．正確な請求額はOpenAI／Anthropicの
Platform側Usageをsource of truthとして確認する必要がある．

## 7．再現と検証

個別のJSON結果は`demo/cost_governance/results/`に保存した．このDirectoryのJSONはAPI実験の
local artifactとしてGit管理対象外である．

比較表は次のコマンドで再生成できる．

```bash
python demo/cost_governance/compare_results.py demo/cost_governance/results/*.json
```

APIを呼ばないAdapterテストは次で実行できる．

```bash
python -m unittest discover -s demo/cost_governance -p 'test_*.py' -v
```

全12結果について，期待したAPI呼び出し数と停止task数を次のコマンドで機械的に照合し，
すべてPASSした．

```bash
python demo/cost_governance/validate_results.py
```
