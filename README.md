# Japan-Biz-Skills

日本の中小企業のバックオフィス業務(総務・人事事務・営業事務・経理事務の「記録と段取り」)の知識を、[Agent Skills](https://agentskills.io) 規格(`SKILL.md`)で書いたオープンな業務スキル集です。Claude Code / Cowork / Claude Agent SDK をはじめ、Agent Skills を読める AI エージェントならそのまま使えます。

- **書いてあるもの**: 業務の型と段取り — 何を・どの順で・誰が確認するか、状態と遷移、漏れやすい項目、期限の考え方、記録しておくべき項目、公的機関の一次情報への参照
- **書いていないもの**: 特定製品への依存、権限や承認の仕組み、法令の解釈や判断の代行(→ [CONTRIBUTING.md](CONTRIBUTING.md) の執筆規約)
- **対象外**: 勤怠管理・給与計算・税務判断・労務判断(専門 SaaS と士業の領域。本リポジトリは「その手前の記録と段取り」まで)

## 使い方

Claude Code の場合、リポジトリを clone してプロジェクトの `.claude/skills/` にコピーするか、[`skills` CLI](https://github.com/vercel-labs/skills) で追加します:

```bash
npx skills add <owner>/Japan-Biz-Skills --skill onboarding-offboarding-jp
```

Cowork では `.skill` として保存できます(各スキルの `dist/` を参照 — 準備中)。

## 収録スキル

| スキル | 一言 | 状態 |
|---|---|---|
| (準備中) `onboarding-offboarding-jp` | 入社・退社手続きの段取り(チェックリスト・担当・期限・記録項目) | 下書き |
| (予定) `ringi-approval-flow-jp` | 稟議・申請の受付と回覧(状態・差戻し・回覧順・振り返り) | — |

状態の意味: **下書き** = 評価ケースが揃っていない / **確定** = 評価ケース ≥8 を通し、実務での検証を経たもの。詳細は各スキルの `SKILL.md` と `evals/` を参照。

## 構成

```
skills/<skill-name>/
  SKILL.md          # 規格準拠(name / description / license)。本文は日本語
  references/       # 一次情報の要約・URL・閲覧日(本文への転載はしない)
  evals/evals.json  # 評価ケース(発話 → 期待される結果 → 判定基準)
template/           # 新しいスキルの雛形
scripts/            # 検証スクリプト(frontmatter・語彙・評価の有無)
.github/workflows/  # CI: 検証 + セキュリティスキャン(skill-scanner / agent-scan)
```

## 品質と安全

- すべてのスキルは `scripts/validate_skills.py` を通ります(frontmatter・文字数・対象外語彙・評価ケースの有無)。
- CI で [cisco-ai-defense/skill-scanner](https://github.com/cisco-ai-defense/skill-scanner) と [snyk/agent-scan](https://github.com/snyk/agent-scan) を実行します(いずれも「ベストエフォートの検出」であり、清浄の証明ではありません)。
- スキルは知識であって法的助言ではありません。士業の独占業務(税務代理・社会保険手続きの代行など)に隣接する内容は、公開前に専門家の一読を経る運用にしています(→ CONTRIBUTING)。

## ライセンス

Apache License 2.0(→ [LICENSE](LICENSE))。第三者由来の内容は [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) に記載します。

---

## English

**Japan-Biz-Skills** is an open collection of business-domain skills in the [Agent Skills](https://agentskills.io) format (`SKILL.md`), covering back-office work at Japanese small and mid-sized companies: general affairs, HR administration, sales administration, and accounting administration — specifically the *record-keeping and coordination* side of those jobs.

Each skill captures the shape of a task (steps, actors, states and transitions, deadlines, commonly-missed items, what to record) with pointers to primary sources from Japanese public agencies. Skills are product-neutral, contain no permission or approval logic, and never substitute for professional (tax/labor) advice. Out of scope by design: attendance management, payroll, tax and labor-law judgment.

Skills are written in Japanese; every `description` carries a one-line English summary so registries can index them. Licensed under Apache-2.0. See [CONTRIBUTING.md](CONTRIBUTING.md) for the authoring rules and evaluation requirements.
