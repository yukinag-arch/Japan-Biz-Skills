#!/usr/bin/env python3
"""評価ループの実行系(claude CLI ヘッドレス)。依存パッケージなし・Python 3.9+。

スキル**あり / なし**の2条件で同じ依頼を走らせ、`evals.json` の assertions を
LLM で採点し、`results.json` と `review.html` にまとめる。
CONTRIBUTING 6章「スキルあり/なしを同じ依頼で走らせ、差を人間が見る」の機械化。

使い方:
    python3 scripts/run_evals.py --skill onboarding-offboarding-jp
    python3 scripts/run_evals.py --skill onboarding-offboarding-jp --evals 1-3 --runs 3 --jobs 4
    python3 scripts/run_evals.py --skill onboarding-offboarding-jp --dry-run

前提: `claude` CLI にログイン済みであること(`npm i -g @anthropic-ai/claude-code`)。

設計上の注意(ここを崩すと測定が濁る)
  1. サンドボックスは**リポジトリの外**(一時ディレクトリ)に作る。リポジトリ内で走らせると
     CLAUDE.md が自動探索されて両条件に混ざり、何を測っているのか分からなくなる。
  2. あり/なしの違いは「サンドボックスに `.claude/skills/<name>/` があるか」**だけ**。
     モデル・システムプロンプト・ツール・今日の日付はすべて揃える。
  3. 「今日」は固定する(`--today` / evals の `today`)。相対日付の依頼を再現可能にするため。
  4. 採点はスキルを見せない別プロセスで行う(採点者がスキル本文を読んで補完しないように)。
  5. スキルが実際に発火したかを stream-json の tool_use から記録する。発火しなければ
     差が出ないのは当然で、直すべきは本文ではなく description。
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"
EVAL_ROOT = ROOT / ".evals"

WEEKDAYS = ["月", "火", "水", "木", "金", "土", "日"]

# 両条件で完全に同一。ここに業務の型を書かないこと(それはスキルの仕事)。
FRAMING = """あなたは日本の中小企業のバックオフィス業務(総務・人事事務)を支援するアシスタントです。
相手は人事・総務の担当者で、法令の専門家ではありません。

- 今日は {today}({weekday}) です。日付の計算は必ずこの日を基準にしてください。
- 依頼と同じ言語で回答してください(日本語の依頼には日本語、英語の依頼には英語)。
- Web 検索・メール・ドライブの参照はできません。手元にある情報だけで答えてください。
- 作業ディレクトリやファイル構成の話はせず、依頼への回答そのものを書いてください。
"""

GRADER_PROMPT = """次の「依頼」に対する「回答」を、判定項目ごとに合否で採点してください。

採点の原則:
- 判定は**回答に書かれていること**だけを根拠にする。あなた自身の知識で補わない。
- 記述が無い・曖昧・一般論にとどまるものは**不合格**にする。
- 表現が違っても内容が満たされていれば合格にしてよい。

<依頼>
{prompt}
</依頼>

<この依頼で期待される回答の要件(参考)>
{expected}
</この依頼で期待される回答の要件(参考)>

<回答>
{response}
</回答>

<判定項目>
{assertions}
</判定項目>

各項目について index(1始まり)・passed・evidence(回答中の該当箇所、または何が欠けているか。日本語1〜2文)を返してください。
"""

GRADER_SCHEMA = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "passed": {"type": "boolean"},
                    "evidence": {"type": "string"},
                },
                "required": ["index", "passed", "evidence"],
            },
        }
    },
    "required": ["results"],
}

CONFIGS = ("with_skill", "without_skill")


# --------------------------------------------------------------------------- CLI 呼び出し


def claude_cli_version() -> str:
    try:
        out = subprocess.run(["claude", "--version"], capture_output=True, text=True, timeout=60)
        return out.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _base_cmd(model, tools):
    cmd = ["claude", "-p", "--setting-sources", "project", "--strict-mcp-config",
           "--no-session-persistence", "--tools", tools]
    if model:
        cmd += ["--model", model]
    return cmd


def execute_run(prompt, cwd, *, model, system_append, timeout, max_budget):
    """依頼を1回実行し、応答と使用したツール名を返す。"""
    cmd = _base_cmd(model, "Skill,Read,Glob")
    cmd += ["--output-format", "stream-json", "--verbose", "--append-system-prompt", system_append]
    if max_budget:
        cmd += ["--max-budget-usd", str(max_budget)]
    cmd += [prompt]

    started = time.time()
    proc = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, timeout=timeout)
    elapsed = time.time() - started

    tools_used, result = [], None
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if msg.get("type") == "assistant":
            for block in msg.get("message", {}).get("content", []):
                if block.get("type") == "tool_use":
                    tools_used.append(block.get("name"))
        elif msg.get("type") == "result":
            result = msg

    if result is None:
        raise RuntimeError(f"result メッセージが返らなかった (exit={proc.returncode}): {proc.stderr[:500]}")

    return {
        "response": result.get("result", ""),
        "is_error": bool(result.get("is_error")),
        "tools_used": tools_used,
        "skill_invoked": "Skill" in tools_used,
        "cost_usd": result.get("total_cost_usd", 0.0),
        "duration_s": round(elapsed, 1),
        "turns": result.get("num_turns"),
        "tokens": _total_tokens(result.get("usage", {})),
    }


def _total_tokens(usage):
    return sum(int(usage.get(k, 0) or 0) for k in
               ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))


def grade_run(prompt, expected, response, assertions, cwd, *, model, timeout):
    """回答を assertions で採点する。スキルの見えない空ディレクトリで走らせる。"""
    if not assertions:
        return []
    numbered = "\n".join("{}. {}".format(i + 1, a) for i, a in enumerate(assertions))
    text = GRADER_PROMPT.format(prompt=prompt, expected=expected or "(指定なし)",
                                response=response, assertions=numbered)
    cmd = _base_cmd(model, "")
    cmd += ["--output-format", "json", "--json-schema", json.dumps(GRADER_SCHEMA), text]

    proc = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, timeout=timeout)
    try:
        outer = json.loads(proc.stdout)
        graded = json.loads(outer["result"])["results"]
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        raise RuntimeError("採点結果を読めなかった: {} / {}".format(e, proc.stdout[:300]))

    by_index = {int(g["index"]): g for g in graded}
    out = []
    for i, a in enumerate(assertions, start=1):
        g = by_index.get(i, {})
        out.append({"index": i, "text": a,
                    "passed": bool(g.get("passed")), "evidence": g.get("evidence", "(採点なし)")})
    return out


# --------------------------------------------------------------------------- サンドボックス


def build_sandboxes(skill_dir):
    """リポジトリ外に with/without/grader の3つの作業ディレクトリを作る。"""
    root = Path(tempfile.mkdtemp(prefix="jbs-eval-"))
    with_dir = root / "with_skill"
    (with_dir / ".claude" / "skills").mkdir(parents=True)
    shutil.copytree(skill_dir, with_dir / ".claude" / "skills" / skill_dir.name)
    (root / "without_skill").mkdir()
    (root / "grader").mkdir()
    return root


# --------------------------------------------------------------------------- 実行計画


def parse_eval_selector(spec, available):
    if not spec:
        return list(available)
    picked = []
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            lo, hi = part.split("-", 1)
            picked += [i for i in range(int(lo), int(hi) + 1) if i in available]
        elif part:
            n = int(part)
            if n in available:
                picked.append(n)
    return sorted(set(picked))


def next_iteration_dir(skill_name):
    base = EVAL_ROOT / skill_name
    base.mkdir(parents=True, exist_ok=True)
    used = [int(p.name.split("-")[1]) for p in base.glob("iteration-*") if p.name.split("-")[-1].isdigit()]
    return base / "iteration-{}".format(max(used) + 1 if used else 1)


def summarize(runs):
    out = {}
    for cfg in CONFIGS:
        got = [r for r in runs if r["config"] == cfg and not r.get("error")]
        graded = [r for r in got if r["assertions"]]
        rates = [r["pass_rate"] for r in graded]
        out[cfg] = {
            "runs": len(got),
            "pass_rate_mean": round(sum(rates) / len(rates), 4) if rates else None,
            "pass_rate_min": round(min(rates), 4) if rates else None,
            "pass_rate_max": round(max(rates), 4) if rates else None,
            "cost_usd": round(sum(r["cost_usd"] for r in got), 4),
            "duration_s_mean": round(sum(r["duration_s"] for r in got) / len(got), 1) if got else None,
            "tokens_mean": int(sum(r["tokens"] for r in got) / len(got)) if got else None,
            "skill_invoked_rate": (round(sum(1 for r in got if r["skill_invoked"]) / len(got), 4)
                                   if got else None),
        }
    a, b = out["with_skill"], out["without_skill"]
    out["delta"] = {
        "pass_rate": (round(a["pass_rate_mean"] - b["pass_rate_mean"], 4)
                      if a["pass_rate_mean"] is not None and b["pass_rate_mean"] is not None else None),
        "duration_s": (round(a["duration_s_mean"] - b["duration_s_mean"], 1)
                       if a["duration_s_mean"] is not None and b["duration_s_mean"] is not None else None),
    }
    return out


# --------------------------------------------------------------------------- main


def main() -> int:
    ap = argparse.ArgumentParser(description="スキルあり/なしで評価を走らせ、差を測る")
    ap.add_argument("--skill", required=True, help="skills/ 配下のディレクトリ名")
    ap.add_argument("--evals", default="", help='走らせる eval id。例: "1,2,5" / "1-3"。既定は全件')
    ap.add_argument("--configs", default=",".join(CONFIGS), help="with_skill,without_skill")
    ap.add_argument("--runs", type=int, default=1, help="1条件あたりの実行回数(ばらつきを見るなら3)")
    ap.add_argument("--model", default="sonnet", help="被験モデル(既定 sonnet。再現性のため必ず固定する)")
    ap.add_argument("--grader-model", default="sonnet", help="採点モデル")
    ap.add_argument("--today", default="", help="固定する『今日』 YYYY-MM-DD。既定は eval の today、無ければ実行日")
    ap.add_argument("--jobs", type=int, default=4, help="並列数")
    ap.add_argument("--timeout", type=int, default=1800, help="1実行のタイムアウト秒")
    ap.add_argument("--max-budget-usd", type=float, default=None, help="1実行あたりの上限ドル")
    ap.add_argument("--iteration", type=int, default=None, help="イテレーション番号(既定は自動採番)")
    ap.add_argument("--dry-run", action="store_true", help="実行計画だけ表示する")
    args = ap.parse_args()

    skill_dir = SKILLS / args.skill
    evals_path = skill_dir / "evals" / "evals.json"
    if not evals_path.exists():
        print("ERROR {} が無い".format(evals_path.relative_to(ROOT)), file=sys.stderr)
        return 1
    data = json.loads(evals_path.read_text(encoding="utf-8"))
    all_evals = {int(e["id"]): e for e in data.get("evals", [])}

    picked = parse_eval_selector(args.evals, set(all_evals))
    configs = [c.strip() for c in args.configs.split(",") if c.strip() in CONFIGS]
    plan = [(eid, cfg, n) for eid in picked for cfg in configs for n in range(1, args.runs + 1)]

    print("スキル      : {}".format(args.skill))
    print("eval        : {} 件 {}".format(len(picked), picked))
    print("条件        : {} / 各 {} 回 → 合計 {} 実行".format(", ".join(configs), args.runs, len(plan)))
    print("モデル      : 被験 {} / 採点 {}".format(args.model, args.grader_model))
    no_assert = [e for e in picked if not all_evals[e].get("assertions")]
    if no_assert:
        print("注意        : assertions が空の eval {} は採点されない(応答は残る)".format(no_assert))
    if args.dry_run:
        return 0

    if not shutil.which("claude"):
        print("ERROR claude CLI が無い。`npm i -g @anthropic-ai/claude-code` の後ログインすること",
              file=sys.stderr)
        return 1

    iter_dir = (EVAL_ROOT / args.skill / "iteration-{}".format(args.iteration)
                if args.iteration else next_iteration_dir(args.skill))
    (iter_dir / "runs").mkdir(parents=True, exist_ok=True)
    sandbox_root = build_sandboxes(skill_dir)
    print("作業場所    : {} (サンドボックス {})".format(iter_dir.relative_to(ROOT), sandbox_root))
    print()

    fallback_today = args.today or datetime.now().strftime("%Y-%m-%d")

    def one(item):
        eid, cfg, n = item
        ev = all_evals[eid]
        today = args.today or ev.get("today") or fallback_today
        wd = WEEKDAYS[datetime.strptime(today, "%Y-%m-%d").weekday()]
        run_id = "eval{}-{}-run{}".format(eid, cfg, n)
        rec = {"run_id": run_id, "eval_id": eid, "config": cfg, "run": n,
               "kind": ev.get("kind", ""), "prompt": ev["prompt"],
               "expected_output": ev.get("expected_output", ""), "today": today,
               "assertions": [], "pass_rate": None, "error": None,
               "cost_usd": 0.0, "duration_s": 0.0, "tokens": 0,
               "skill_invoked": False, "tools_used": [], "turns": None, "response": ""}
        try:
            out = execute_run(ev["prompt"], sandbox_root / cfg, model=args.model,
                              system_append=FRAMING.format(today=today, weekday=wd),
                              timeout=args.timeout, max_budget=args.max_budget_usd)
            rec.update(out)
            if ev.get("assertions"):
                graded = grade_run(ev["prompt"], ev.get("expected_output", ""), out["response"],
                                   ev["assertions"], sandbox_root / "grader",
                                   model=args.grader_model, timeout=args.timeout)
                rec["assertions"] = graded
                rec["pass_rate"] = round(sum(1 for g in graded if g["passed"]) / len(graded), 4)
            mark = "skill発火" if rec["skill_invoked"] else "        "
            rate = "{:.0%}".format(rec["pass_rate"]) if rec["pass_rate"] is not None else " 未採点"
            print("  ✓ {:<34} {} {:>6}  {:>5.0f}s  ${:.3f}".format(
                run_id, mark, rate, rec["duration_s"], rec["cost_usd"]), flush=True)
        except Exception as e:  # 1件の失敗で全体を落とさない
            rec["error"] = "{}: {}".format(type(e).__name__, e)
            print("  ✗ {:<34} {}".format(run_id, rec["error"][:90]), flush=True)
        (iter_dir / "runs" / "{}.json".format(run_id)).write_text(
            json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
        return rec

    started = time.time()
    with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        runs = list(pool.map(one, plan))

    results = {
        "skill_name": args.skill,
        "iteration": int(iter_dir.name.split("-")[-1]),
        "created": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "executor": {"cli": claude_cli_version(), "model": args.model,
                     "grader_model": args.grader_model, "runs_per_configuration": args.runs},
        "runs": runs,
        "summary": summarize(runs),
    }
    results_path = iter_dir / "results.json"
    results_path.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    shutil.rmtree(sandbox_root, ignore_errors=True)

    s = results["summary"]
    print("\n--- {} 実行 / {:.0f} 秒 / 合計 ${:.2f}".format(
        len(runs), time.time() - started, sum(r["cost_usd"] for r in runs)))
    for cfg in configs:
        c = s[cfg]
        print("    {:<14} 正答 {} / 発火 {} / {}s / {} tok".format(
            cfg,
            "{:.0%}".format(c["pass_rate_mean"]) if c["pass_rate_mean"] is not None else "-",
            "{:.0%}".format(c["skill_invoked_rate"]) if c["skill_invoked_rate"] is not None else "-",
            c["duration_s_mean"], c["tokens_mean"]))
    if s["delta"]["pass_rate"] is not None:
        d = s["delta"]["pass_rate"]
        print("    差            正答 {:+.1%}".format(d))
        if abs(d) < 0.10:
            print("    ⚠ 差が 10 ポイント未満。CONTRIBUTING 6章「差が説明できないスキルは載せない」に照らし、")
            print("      本文ではなく assertions の設計を疑うこと(素のモデルが落とす項目になっているか)。")

    try:
        from make_report import build_report
    except ImportError:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from make_report import build_report
    html = build_report(results_path)
    print("\nレビュー用ビューア: {}".format(html.relative_to(ROOT)))
    print("  ブラウザで開いて所見を書き、feedback.json として同じ場所に保存すると次の周回で参照できる。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
