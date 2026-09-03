# Cost Governance実API比較

実API実験は2026年9月3日に完了しました。結果と考察は
[`docs/cost_governance_experiment_results_2026-09-03.md`](../../docs/cost_governance_experiment_results_2026-09-03.md)
を参照してください。

GPT-5／Claude Opus 5による追加実験は，既存結果を保持したまま
[`docs/cost_governance_experiment_results_gpt5_opus5_2026-09-03.md`](../../docs/cost_governance_experiment_results_gpt5_opus5_2026-09-03.md)
および`results/gpt5-opus5/`へ分離して保存しています。各scriptの`--model`でモデルIDを明示できます。

OpenAI Agents SDK、Claude Agent SDK、およびAGT 4.1.0を追加した同じRuntimeを、
安価なモデルと副作用のないToolで比較します。

| Script | Runtime | Budget制御 |
|---|---|---|
| `openai_sdk_cost.py` | `gpt-5-nano` | `max_turns`、出力token上限 |
| `claude_sdk_cost.py` | Claude Haiku | `max_budget_usd`、`max_turns` |
| `agt_openai_cost.py` | `gpt-5-nano` | AGT task／agent／organization Budget |
| `agt_claude_cost.py` | Claude Haiku | Claude run Budget＋AGT横断Budget |

AGT専用の疑似Cost実験はありません。AGT統合版は実際にAPIを呼び、OpenAIでは
SDKのusageから算出したCost、Claudeでは`ResultMessage.total_cost_usd`を
`CostGuard.record_cost()`へ渡します。

## 安全設計

- すべてのpaid実験は`--live`なしではAPIを呼びません。
- Toolは整数をメモリへ記録するだけで、ファイルや外部サービスを変更しません。
- tracingとproject設定の読み込みを無効化しています。
- 高価格モデルへのfallbackは設定しません。
- OpenAIはreasoning effortを`minimal`へ固定し、出力上限を512 tokenにします。
- 結果のファイル保存は`--output`を明示した場合だけ行います。
- API KeyやWorkspace IDはJSONへ保存しません。

## 実行前の確認

```bash
source .venv/bin/activate
set -a
source .env
set +a

python demo/cost_governance/openai_sdk_cost.py --help
python demo/cost_governance/claude_sdk_cost.py --help
```

`pricing.json`は実験条件を再現するための固定入力です。OpenAIのlive実験前に公式価格を
確認し、価格または確認日が変わっていれば更新してください。OpenAIのUSD値はSDKが返す
請求額ではなく、この価格表とusageによるアプリ側推定です。cached inputの割引は適用しません。

Claudeの`total_cost_usd`もclient-side estimateであり、請求のsource of truthではありません。

## SDK単体

まず各Providerを1 taskずつ実行し、通常時のusageとCostを確認します。

```bash
python demo/cost_governance/openai_sdk_cost.py \
  --live \
  --output demo/cost_governance/results/openai-sdk.json

python demo/cost_governance/claude_sdk_cost.py \
  --live \
  --max-budget-usd 0.02 \
  --output demo/cost_governance/results/claude-sdk.json
```

ClaudeのBudget停止は、通常実行で得たCostより小さい`--max-budget-usd`を指定して
別の結果ファイルへ保存します。極端に小さい値では最初のモデル呼び出しがBudgetを
超える可能性があります。

## AGT＋実API

AGT統合版は、次の4 taskを逐次実行します。

```text
org-demo
├── agent-a: task-a-1, task-a-2
└── agent-b: task-b-1, task-b-2
```

```bash
python demo/cost_governance/agt_openai_cost.py \
  --live \
  --estimated-task-usd 0.005 \
  --per-task-limit-usd 0.02 \
  --per-agent-daily-limit-usd 0.04 \
  --org-monthly-budget-usd 0.08 \
  --output demo/cost_governance/results/agt-openai.json

python demo/cost_governance/agt_claude_cost.py \
  --live \
  --estimated-task-usd 0.005 \
  --per-task-limit-usd 0.02 \
  --per-agent-daily-limit-usd 0.04 \
  --org-monthly-budget-usd 0.08 \
  --claude-task-budget-usd 0.02 \
  --output demo/cost_governance/results/agt-claude.json
```

AGTによる拒否を安価に確認する場合は、APIを呼ぶ前に確実に拒否される条件を使えます。

```bash
python demo/cost_governance/agt_openai_cost.py \
  --live \
  --estimated-task-usd 0.02 \
  --per-task-limit-usd 0.01
```

この場合は4 taskすべてが`agt_precheck_denied`になり、API Costは発生しません。

Agent／Organization停止を確認する場合は、最初の正常実行で得たtask Costを基準に、
`--estimated-task-usd`と各上限を設定してください。モデルのCostは毎回同一ではないため、
固定の停止用既定値は設けていません。

## AGT連携の重要な制約

統合版は、実Costを正確に記録するために次の逐次処理を使います。

```text
check_task(estimated cost)
        ↓ allow
実API task
        ↓
record_cost(actual／calculated cost)
```

実CostはAPI応答後に確定するため、1 task分のovershootは起こり得ます。また、
`check_task()`はBudgetを予約しないので並行実行には使用できません。AGT 4.1.0の
`check_and_charge()`は原子的ですが、推定額を実Costへ精算・返金するAPIがないため、
この実験では使用しません。この制約は各JSON結果にも記録されます。

## オフラインテスト

テストはAPIを呼びません。実際のAGT `CostGuard`へ固定Costを渡し、統合アダプターが
拒否後にProvider関数を呼ばないことを検証します。

```bash
python -m unittest discover -s demo/cost_governance -p 'test_*.py' -v
```

## 結果比較

保存したJSONから同じ指標のMarkdown表を生成できます。

```bash
python demo/cost_governance/compare_results.py \
  demo/cost_governance/results/openai-sdk.json \
  demo/cost_governance/results/claude-sdk.json \
  demo/cost_governance/results/agt-openai.json \
  demo/cost_governance/results/agt-claude.json
```

完了した全liveケースのAPI呼び出し数と停止数は次で再検証できます。

```bash
python demo/cost_governance/validate_results.py
```
