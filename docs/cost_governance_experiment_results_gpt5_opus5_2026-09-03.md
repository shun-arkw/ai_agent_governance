# Cost Governance GPT-5／Claude Opus 5実API実験結果

- 実験完了日：2026年9月3日（JST）
- OpenAI Agents SDK：0.22.0
- Claude Agent SDK：0.2.144
- Agent Governance Toolkit：4.1.0
- OpenAIモデル：`gpt-5`
- Claudeモデル：`claude-opus-5`
- 比較元：`cost_governance_experiment_results_2026-09-03.md`

## 1．結論

既存の`gpt-5-nano`／`claude-haiku-4-5-20251001`結果を変更せず，GPT-5／Claude Opus 5で
同じ12ケースを実行した．全ケースについて，期待したAPI呼び出し数と停止task数を確認できた．

SDKおよびAGTのCost Governance機能に関する結論はモデル変更後も同じだった．OpenAI Agents SDKの
`max_turns`，Claude Agent SDKの`max_budget_usd`，AGTのtask／agent／organization上限は，
それぞれ想定した制御フローを実現した．

## 2．全実測結果

| Result | Tasks | API calls | Stopped | Tokens | Effective Cost (USD) |
|---|---:|---:|---:|---:|---:|
| OpenAI SDK baseline | 1 | 1 | 0 | 418 | 0.00084625 |
| OpenAI SDK max-turns stop | 1 | 1 | 1 | 200 | 0.00053875 |
| Claude SDK baseline | 1 | 1 | 0 | 64 | 0.00730200 |
| Claude SDK budget stop | 1 | 1 | 1 | 0 | 0.00615375 |
| AGT＋OpenAI normal | 4 | 4 | 0 | 1,673 | 0.00339500 |
| AGT＋OpenAI task deny | 4 | 0 | 4 | 0 | 0.00000000 |
| AGT＋OpenAI agent deny | 4 | 2 | 2 | 838 | 0.00171250 |
| AGT＋OpenAI organization deny | 4 | 1 | 3 | 419 | 0.00085625 |
| AGT＋Claude normal | 4 | 4 | 0 | 256 | 0.02914800 |
| AGT＋Claude task deny | 4 | 0 | 4 | 0 | 0.00000000 |
| AGT＋Claude agent deny | 4 | 2 | 2 | 128 | 0.00701275 |
| AGT＋Claude organization deny | 4 | 1 | 3 | 64 | 0.00385775 |

12結果のEffective Cost合計は`$0.06082300`である．OpenAIは公式標準処理価格として固定した
input `$1.25 / MTok`，output `$10.00 / MTok`とusageから算出した．ClaudeはSDKが返した
`total_cost_usd`を使用した．いずれもProviderの請求画面をsource of truthとして確認する必要がある．

ClaudeのTokens列はterminal payloadの`input_tokens`と`output_tokens`の和であり，cache creation／
cache read tokensを含まない．したがって，Haiku版との単純な総token比較には使用できない．

## 3．SDK停止結果

GPT-5のbaselineは2 requests，418 tokens，推定`$0.00084625`で完了した．`max_turns=1`では
最初のモデル応答とTool実行後に`MaxTurnsExceeded`となり，1 request，200 tokens，推定
`$0.00053875`だった．

Claude Opus 5のbaselineは2 turns，SDK推定`$0.00730200`で完了した．
`max_budget_usd=0.004`では`budget_exhausted`となり，Toolを1回実行した後，SDK推定
`$0.00615375`で停止した．overshootは`$0.00215375`，設定額に対して約53.8%だった．
Budget停止時のterminal payloadがusageを0として返す挙動はHaiku版と同じだった．

## 4．AGT統合結果

- normal：両Providerとも4 taskを完了した．
- task deny：両ProviderともAPI呼び出し前に4 taskを拒否した．
- agent deny：両Providerとも各Agentの最初のtaskだけを実行し，2 calls／2 stoppedとなった．
- organization deny：両Providerとも最初の1 taskだけを実行し，1 call／3 stoppedとなった．

Opus 5ではprompt cacheによって後続taskのCostがbaselineより低下したため，最初のagent上限候補
`$0.012`では停止しなかった．このrunは`agt-claude-agent-calibration.json`として保存し，上限を
`$0.010`へ調整した本実験で期待結果を確認した．calibration runのCostは`$0.01542600`であり，
上記12結果の合計には含めない．

## 5．保存場所と検証

新しい結果は`demo/cost_governance/results/gpt5-opus5/`に保存した．従来の12 JSONは
`demo/cost_governance/results/`直下にそのまま保持している．

```bash
python demo/cost_governance/validate_results.py \
  demo/cost_governance/results/gpt5-opus5
```

上記検証は全12ケースでPASSした．元実験レポートに記載したovershoot，逐次実行，推定額の精算，
永続化および丸めに関する制約は，本実験にもそのまま適用される．
