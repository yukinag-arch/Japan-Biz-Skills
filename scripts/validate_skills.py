#!/usr/bin/env python3
"""skills/ 配下の SKILL.md を検証する(依存パッケージなし・Python 3.9+)。

検査項目
  1. frontmatter: name(<=64字・^[a-z0-9][a-z0-9-]*$・ディレクトリ名と一致)/ description(<=1024字・空でない)/ license(Apache-2.0)
     metadata.status(draft | reviewed | released)。released は metadata.reviewed-by が空でないこと
  2. 本文: 500行以内(超過は警告)。必須見出し(概要 / 前提と範囲外 / 段取り / 記録項目の推奨 / 参照 / 更新履歴)
  3. 語彙: scripts/policy.json の forbidden_terms が本文・references に出たらエラー。
     ただし範囲外を宣言している行(「◯◯は扱わない」等)は除外する。warn_terms_product_names は警告
  4. 一次情報の鮮度: references/*.md の frontmatter の source-checked(閲覧日)を見る。
     policy.json の freshness_months を超えたもの、unverified: true のものは draft では警告・
     reviewed 以上ではエラー。法改正で内容が腐るのを検知するため
  5. 評価: evals/evals.json が存在すること。各 eval の kind(positive | boundary | out_of_scope)と
     内訳(正例 5+ / 境界 2+ / 範囲外 1+ / 合計 8+)を見る。draft では警告、reviewed 以上ではエラー

終了コード: エラーがあれば 1。--strict で警告もエラー扱い。
"""
from __future__ import annotations

import json
import re
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"
POLICY = json.loads((ROOT / "scripts" / "policy.json").read_text(encoding="utf-8"))
REQUIRED_HEADINGS = ["概要", "前提と範囲外", "段取り", "記録項目の推奨", "参照", "更新履歴"]
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
EVAL_KINDS = ("positive", "boundary", "out_of_scope")
KIND_MINIMUMS = {"positive": 5, "boundary": 2, "out_of_scope": 1}
FRESHNESS_MONTHS = int(POLICY.get("freshness_months", 12))


def parse_frontmatter(text: str) -> tuple:
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
    block_lines: list = []
    nested = None
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


def split_optional_frontmatter(text: str) -> tuple:
    """references 用。frontmatter が無ければ空 dict と全文を返す。"""
    try:
        return parse_frontmatter(text)
    except ValueError:
        return {}, text


def months_since(d: date) -> int:
    today = date.today()
    return (today.year - d.year) * 12 + (today.month - d.month) - (1 if today.day < d.day else 0)


def forbidden_hits(content: str) -> list:
    """対象外語彙のうち、範囲外を宣言している行に出るものは除外して返す。

    「勤怠管理は扱わない」と書けないと範囲外の宣言そのものができなくなるため。
    判定は行単位: その行に allow_context_markers のいずれかがあれば、その行の出現は許す。
    """
    markers = [m.lower() for m in POLICY.get("allow_context_markers", [])]
    hits = []
    for lineno, line in enumerate(content.split("\n"), start=1):
        low = line.lower()
        if any(m in low for m in markers):
            continue
        for term in POLICY.get("forbidden_terms", []):
            if term.lower() in low:
                hits.append((term, lineno))
    return hits


def check_references(skill_dir: Path, tag: str, status: str, errors: list, warnings: list) -> list:
    """references/*.md の鮮度と未確認フラグを見る。戻り値は語彙検査の対象(パス, 本文)。"""
    corpus = []
    ref_dir = skill_dir / "references"
    if not ref_dir.exists():
        return corpus
    hard = status in ("reviewed", "released")
    sink = errors if hard else warnings
    for ref in sorted(ref_dir.glob("*.md")):
        text = ref.read_text(encoding="utf-8")
        fm, _ = split_optional_frontmatter(text)
        corpus.append((ref, text))
        rel = ref.relative_to(ROOT)

        checked = str(fm.get("source-checked", "")).strip()
        if not checked:
            sink.append("[{}] {} に source-checked(一次情報の閲覧日)が無い".format(tag, rel))
        else:
            try:
                age = months_since(datetime.strptime(checked, "%Y-%m-%d").date())
            except ValueError:
                errors.append("[{}] {} の source-checked が YYYY-MM-DD でない: {!r}".format(tag, rel, checked))
            else:
                if age > FRESHNESS_MONTHS:
                    sink.append("[{}] {} の一次情報が {} か月前({})。法改正の反映を確認すること".format(
                        tag, rel, age, checked))

        if str(fm.get("unverified", "")).strip().lower() in ("true", "yes", "1"):
            sink.append("[{}] {} に未確認の記述がある(unverified: true)。reviewed に上げる前に一次情報を確認".format(
                tag, rel))
    return corpus


def check_evals(skill_dir: Path, tag: str, name: str, status: str, errors: list, warnings: list) -> None:
    evals_path = skill_dir / "evals" / "evals.json"
    hard = status in ("reviewed", "released")
    sink = errors if hard else warnings
    if not evals_path.exists():
        (errors if hard else warnings).append("[{}] evals/evals.json が無い(status={})".format(tag, status))
        return
    try:
        data = json.loads(evals_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        errors.append("[{}] evals.json が JSON として読めない: {}".format(tag, e))
        return

    if data.get("skill_name") != name:
        errors.append("[{}] evals.json の skill_name({})が name と一致しない".format(tag, data.get("skill_name")))

    items = data.get("evals", [])
    if len(items) < 8:
        sink.append("[{}] 評価ケースが {} 件(確定には 8 件以上)".format(tag, len(items)))

    counts = dict.fromkeys(EVAL_KINDS, 0)
    missing_kind, no_assertions = [], []
    for e in items:
        kind = str(e.get("kind", "")).strip()
        if kind not in EVAL_KINDS:
            missing_kind.append(e.get("id"))
        else:
            counts[kind] += 1
        if not e.get("assertions"):
            no_assertions.append(e.get("id"))

    if missing_kind:
        sink.append("[{}] eval {} に kind({} のいずれか)が無い".format(
            tag, missing_kind, " | ".join(EVAL_KINDS)))
    for kind, need in KIND_MINIMUMS.items():
        if counts[kind] < need:
            sink.append("[{}] kind={} が {} 件(必要 {} 件以上)".format(tag, kind, counts[kind], need))
    if no_assertions:
        warnings.append("[{}] eval {} に assertions が無い(実行しても採点されない)".format(tag, no_assertions))


def check_skill(skill_dir: Path, errors: list, warnings: list) -> None:
    md = skill_dir / "SKILL.md"
    tag = skill_dir.name
    if not md.exists():
        errors.append("[{}] SKILL.md が無い".format(tag))
        return
    text = md.read_text(encoding="utf-8")
    try:
        fm, body = parse_frontmatter(text)
    except ValueError as e:
        errors.append("[{}] {}".format(tag, e))
        return

    name = str(fm.get("name", ""))
    if not name:
        errors.append("[{}] name が無い".format(tag))
    elif len(name) > 64 or not NAME_RE.match(name):
        errors.append("[{}] name が規格外(64字以内・小文字英数とハイフン): {!r}".format(tag, name))
    elif name != skill_dir.name:
        errors.append("[{}] name({})とディレクトリ名({})が一致しない".format(tag, name, skill_dir.name))

    desc = str(fm.get("description", ""))
    if not desc.strip():
        errors.append("[{}] description が空".format(tag))
    elif len(desc) > 1024:
        errors.append("[{}] description が 1024 字を超えている({})".format(tag, len(desc)))
    elif not re.search(r"[A-Za-z]{3,}", desc):
        warnings.append("[{}] description に英語一行が無い(索引・検索のため推奨)".format(tag))

    if str(fm.get("license", "")) != "Apache-2.0":
        errors.append("[{}] license は Apache-2.0 であること(現在: {!r})".format(tag, fm.get("license")))

    meta = fm.get("metadata") if isinstance(fm.get("metadata"), dict) else {}
    status = str(meta.get("status", "draft"))
    if status not in ("draft", "reviewed", "released"):
        errors.append("[{}] metadata.status が不正: {!r}".format(tag, status))
        status = "draft"
    if status == "released" and not str(meta.get("reviewed-by", "")).strip():
        errors.append("[{}] status=released には metadata.reviewed-by(専門家一読の記録)が必要".format(tag))

    lines = body.split("\n")
    if len(lines) > 500:
        warnings.append("[{}] 本文が 500 行を超えている({})。references/ への切り出しを検討".format(tag, len(lines)))
    headings = {re.sub(r"^#+\s*", "", l).strip() for l in lines if l.startswith("#")}
    for h in REQUIRED_HEADINGS:
        if not any(x.startswith(h) for x in headings):
            errors.append("[{}] 必須見出し「{}」が無い".format(tag, h))

    # 語彙検査(本文 + references)。references の鮮度もここで見る
    corpus = [(md, body)] + check_references(skill_dir, tag, status, errors, warnings)
    for path, content in corpus:
        for term, lineno in forbidden_hits(content):
            errors.append("[{}] 対象外の語彙「{}」が {}:{} に含まれる".format(
                tag, term, path.relative_to(ROOT), lineno))
        if path == md:
            low = content.lower()
            for term in POLICY.get("warn_terms_product_names", []):
                if term.lower() in low:
                    warnings.append("[{}] 製品名「{}」が本文に含まれる(references の出典としてのみ可)".format(tag, term))

    check_evals(skill_dir, tag, name, status, errors, warnings)


def main() -> int:
    strict = "--strict" in sys.argv
    errors: list = []
    warnings: list = []
    dirs = sorted(p for p in SKILLS.iterdir() if p.is_dir()) if SKILLS.exists() else []
    if not dirs:
        print("skills/ にスキルがまだ無い(検査対象なし)")
        return 0
    for d in dirs:
        check_skill(d, errors, warnings)
    for w in warnings:
        print("WARN  {}".format(w))
    for e in errors:
        print("ERROR {}".format(e))
    print("--- {} skills / {} errors / {} warnings".format(len(dirs), len(errors), len(warnings)))
    return 1 if errors or (strict and warnings) else 0


if __name__ == "__main__":
    sys.exit(main())
