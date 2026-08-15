# skills/

1ディレクトリ=1スキル。ディレクトリ名 = frontmatter の `name`(業務名で切る・`-jp` 接尾)。

```
<name>/
  SKILL.md
  references/
  evals/evals.json
  UPSTREAM.md   # 取り込みの場合のみ
```

新しいスキルは `../template/SKILL.md` から。検証は `python3 ../scripts/validate_skills.py`。
