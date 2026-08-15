# CLAUDE.md — このリポジトリで作業する Claude への常設指示

Japan-Biz-Skills は、日本の中小企業のバックオフィス業務(記録と段取り)の知識を Agent Skills 規格(SKILL.md)で書くオープンなスキル集である。**執筆規約は `CONTRIBUTING.md` が正本**。作業前に必ず読む。

## 守ること

1. **製品非依存**。特定の製品・サービスの操作手順を書かない。製品名は `references/` の出典としてのみ。権限・承認・実行の仕組みも書かない(利用側システムの責務)。
2. **士業の線引き**。税務代理・税務書類の作成・税務相談、労働社会保険諸法令に基づく申請書等の作成・提出代行に該当し得る行為をエージェントに行わせる記述をしない。**手前まで行き切る**(必要情報を揃える・期限を知らせる・チェックリストを作る)。
3. **対象外の領域**。勤怠管理・給与計算・税務判断・労務判断は扱わない。`scripts/policy.json` の語彙が本文に出たら検証は落ちる。
4. **一次情報は要約と参照**。公的機関の案内は `references/` に URL・閲覧日・要点を置く。転載しない。
5. **評価が無いスキルは下書き**。`evals/evals.json` に 8 件以上(正例 5+ / 境界 2+ / 範囲外 1+)。作り方・回し方は Anthropic の skill-creator の流儀に従う(スキルあり/なしを同じ依頼で走らせ、人間がレビュー)。
6. **一本ずつ**。並行して複数のスキルを書かない。ドラフト → 評価ケース → 実行 → レビュー → 改訂の一周を終えてから次へ。

## 手順(新しいスキル)

1. `template/SKILL.md` を `skills/<業務名>-jp/SKILL.md` に複製(職種名ではなく業務名で切る)
2. ヒアリングの内容を反映して本文を書く。長くなる部分は `references/` に切り出す。`references/*.md` には `source-checked`(閲覧日)と `unverified` の frontmatter を必ず付ける
3. `evals/evals.json` にテストプロンプトを置く(prompt / expected_output / `kind` / `today`。assertions は実行中に足す)
4. `make check` を通す
5. `make eval SKILL=<name>` でスキルあり/なしを走らせ、`review.html` を人間に見せる。フィードバックで改訂(→ CONTRIBUTING 9章)
6. 士業に隣接する内容は `metadata.status: reviewed` にとどめ、専門家一読の記録が入るまで `released` にしない

**評価で差が出ないときに本文を厚くしないこと。** あり/なしで結果が割れないのは assertions が素のモデルの知識を測っているからで、直すのは評価の設計。発火しないなら直すのは `description`。

## 手順(他のリポジトリからの取り込み)

Apache-2.0 / MIT のみ。丸写しせず翻案。`UPSTREAM.md`(repo / path / commit / license / 翻案の要点)と `THIRD_PARTY_NOTICES.md` を更新。以後は新規スキルと同じ手順。

## 変更しないもの

`LICENSE`(Apache-2.0)/ `scripts/policy.json` の対象外語彙(緩める方向の変更は人間の判断)。
