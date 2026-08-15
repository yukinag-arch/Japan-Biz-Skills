#!/usr/bin/env python3
"""skills/ 配下の SKILL.md を検証する(依存パッケージなし・Python 3.9+)。

検査項目
  1. frontmatter: name(<=64字・^[a-z0-9][a-z0-9-]*$・ディレクトリ名と一致)/ description(<=1024字・空でない)/ license(Apache-2.0)
     metadata.status(draft | reviewed | released)。released は metadata.reviewed-by が空でないこと
  2. 本文: 500行以内(超過は警告)。必須見出し(概要 / 前提と範囲外 / 段取り / 記録項目の推奨 / 参照 / 更新履歴)
  3. 語彙: scripts/policy.json の forbidden_terms が本文・references に出たらエラー。warn_terms_product_names は警告
  4. 評価: evals/evals.json が存在し、status が reviewed/released なら evals >= 8

終了コード: エラーがあれば 1。--strict で警告もエラー扱い。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"
POLICY = json.loads((ROOT / "scripts" / "policy.json").read_text(encoding="utf-8"))
REQUIRED_HEADINGS = ["概要", "前提と範囲外", "段取り", "記録項目の推奨", "参照", "更新履歴"]
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """最小の YAML 風パーサ(この用途に必要な形だけ扱う: key: value / key: >- 複数行 / metadata: の入れ子1段)。"""
    if not text.startswith("---\n"):
        raise ValueError("frontmatter が無い(先頭が --- ではない)")
    end = text.find("\n---", 4)
    if end < 0:
        raise ValueError("frontmatter の終端 --- が無い")
    fm_text = text[4:end]
    body = text[end + 4 :].lstrip("\n")
    fm: dict = {}
    current_key = None
    block_lines: list[str] = []
    nested: dict | None = None
    for raw in fm_text.split("\n"):
        if current_key and (raw.startswith("  ") or raw.strip() == ""):
            if raw.strip():
                block_lines.append(raw.strip())
            continue
        if current_key:
            fm[current_key] = " ".join(block_lines)
            current_key, block_lines = None, []
        if raw.startswith("  ") and nested is not None:
            k, _, v = raw.strip().partition(":")
            nested[k.strip()] = v.strip().strip('"')
            continue
        nested = None
        if not raw.strip():
            continue
        k, _, v = raw.partition(":")
        k, v = k.strip(), v.strip()
        if v in (">-", ">", "|", "|-"):
            current_key = k
            block_lines = []
        elif v == "":
            fm[k] = {}
            nested = fm[k]
        else:
            fm[k] = v.strip('"')
    if current_key:
        fm[current_key] = " ".join(block_lines)
    return fm, body


def check_skill(skill_dir: Path, errors: list[str], warnings: list[str]) -> None:
    md = skill_dir / "SKILL.md"
    tag = skill_dir.name
    if not md.exists():
        errors.append(f"[{tag}] SKILL.md が無い")
        return
    text = md.read_text(encoding="utf-8")
    try:
        fm, body = parse_frontmatter(text)
    except ValueError as e:
        errors.append(f"[{tag}] {e}")
        return

    name = str(fm.get("name", ""))
    if not name:
        errors.append(f"[{tag}] name が無い")
    elif len(name) > 64 or not NAME_RE.match(name):
        errors.append(f"[{tag}] name が規格外(64字以内・小文字英数とハイフン): {name!r}")
    elif name != skill_dir.name:
        errors.append(f"[{tag}] name({name})とディレクトリ名({skill_dir.name})が一致しない")

    desc = str(fm.get("description", ""))
    if not desc.strip():
        errors.append(f"[{tag}] description が空")
    elif len(desc) > 1024:
        errors.append(f"[{tag}] description が 1024 字を超えている({len(desc)})")
    elif not re.search(r"[A-Za-z]{3,}", desc):
        warnings.append(f"[{tag}] description に英語一行が無い(索引・検索のため推奨)")

    if str(fm.get("license", "")) != "Apache-2.0":
        errors.append(f"[{tag}] license は Apache-2.0 であること(現在: {fm.get('license')!r})")

    meta = fm.get("metadata") if isinstance(fm.get("metadata"), dict) else {}
    status = str(meta.get("status", "draft"))
    if status not in ("draft", "reviewed", "released"):
        errors.append(f"[{tag}] metadata.status が不正: {status!r}")
    if status == "released" and not str(meta.get("reviewed-by", "")).strip():
        errors.append(f"[{tag}] status=released には metadata.reviewed-by(専門家一読の記録)が必要")

    lines = body.split("\n")
    if len(lines) > 500:
        warnings.append(f"[{tag}] 本文が 500 行を超えている({len(lines)})。references/ への切り出しを検討")
    headings = {re.sub(r"^#+\s*", "", l).strip() for l in lines if l.startswith("#")}
    for h in REQUIRED_HEADINGS:
        if not any(x.startswith(h) for x in headings):
            errors.append(f"[{tag}] 必須見出し「{h}」が無い")

    # 語彙検査(本文 + references)
    corpus = [(md, body)]
    for ref in (skill_dir / "references").glob("*.md") if (skill_dir / "references").exists() else []:
        corpus.append((ref, ref.read_text(encoding="utf-8")))
    for path, content in corpus:
        low = content.lower()
        for term in POLICY.get("forbidden_terms", []):
            if term.lower() in low:
                errors.append(f"[{tag}] 対象外の語彙「{term}」が {path.relative_to(ROOT)} に含まれる")
        if path == md:
            for term in POLICY.get("warn_terms_product_names", []):
                if term.lower() in low:
                    warnings.append(f"[{tag}] 製品名「{term}」が本文に含まれる(references の出典としてのみ可)")

    # 評価
    evals = skill_dir / "evals" / "evals.json"
    if not evals.exists():
        (errors if status != "draft" else warnings).append(f"[{tag}] evals/evals.json が無い(status={status})")
    else:
        try:
            data = json.loads(evals.read_text(encoding="utf-8"))
            n = len(data.get("evals", []))
            if data.get("skill_name") != name:
                errors.append(f"[{tag}] evals.json の skill_name({data.get('skill_name')})が name と一致しない")
            if status != "draft" and n < 8:
                errors.append(f"[{tag}] status={status} には評価ケース 8 件以上が必要(現在 {n})")
            elif n < 8:
                warnings.append(f"[{tag}] 評価ケースが {n} 件(確定には 8 件以上)")
        except json.JSONDecodeError as e:
            errors.append(f"[{tag}] evals.json が JSON として読めない: {e}")


def main() -> int:
    strict = "--strict" in sys.argv
    errors: list[str] = []
    warnings: list[str] = []
    dirs = sorted(p for p in SKILLS.iterdir() if p.is_dir()) if SKILLS.exists() else []
    if not dirs:
        print("skills/ にスキルがまだ無い(検査対象なし)")
        return 0
    for d in dirs:
        check_skill(d, errors, warnings)
    for w in warnings:
        print(f"WARN  {w}")
    for e in errors:
        print(f"ERROR {e}")
    print(f"--- {len(dirs)} skills / {len(errors)} errors / {len(warnings)} warnings")
    return 1 if errors or (strict and warnings) else 0


if __name__ == "__main__":
    sys.exit(main())
