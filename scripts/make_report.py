#!/usr/bin/env python3
"""results.json からレビュー用ビューア(review.html)を作る。依存パッケージなし・Python 3.9+。

人間が見るのは「あり/なしの差」であって正答率そのものではない。左右に並べて、
どの判定項目で差がついたかと、スキルが発火したかを一目で分かるようにする。
所見はブラウザに保存され、feedback.json として書き出せる(次の周回の入力)。

    python3 scripts/make_report.py --skill onboarding-offboarding-jp
    python3 scripts/make_report.py --results .evals/<skill>/iteration-2/results.json
"""
from __future__ import annotations

import argparse
import html as html_mod
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVAL_ROOT = ROOT / ".evals"

CSS = """
:root{--bg:#faf9f5;--surface:#fff;--border:#e5e3da;--text:#1a1a18;--muted:#6b6960;
--accent:#c25a3c;--ok:#4b7a3f;--ok-bg:#eef3ea;--ng:#a33a34;--ng-bg:#fbecea;--chip:#efede4;}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#17161a;--surface:#201f24;
--border:#34323a;--text:#eceaf0;--muted:#a3a0ab;--accent:#e08a6c;--ok:#8fbf7c;--ok-bg:#22301f;
--ng:#e08a84;--ng-bg:#33201f;--chip:#2b2a31;}}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--text);font:15px/1.65 -apple-system,"Hiragino Sans",sans-serif;padding:2rem 1.5rem 5rem}
.wrap{max-width:1200px;margin:0 auto}
h1{font-size:1.4rem;margin-bottom:.2rem}
.sub{color:var(--muted);font-size:.85rem;margin-bottom:1.5rem}
table{border-collapse:collapse;width:100%;font-size:.85rem}
th,td{border:1px solid var(--border);padding:.45rem .6rem;text-align:left;vertical-align:top}
th{background:var(--chip);font-weight:600}
.num{text-align:right;font-variant-numeric:tabular-nums}
section{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:1.1rem;margin-bottom:1.1rem}
h2{font-size:1rem;margin-bottom:.7rem}
h3{font-size:.9rem;margin:.9rem 0 .4rem;color:var(--muted)}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:1rem}
@media(max-width:900px){.cols{grid-template-columns:1fr}}
pre{background:var(--bg);border:1px solid var(--border);border-radius:6px;padding:.7rem;
white-space:pre-wrap;word-break:break-word;font:12.5px/1.6 ui-monospace,SFMono-Regular,Menlo,monospace;
max-height:32rem;overflow:auto}
.chip{display:inline-block;padding:.1rem .5rem;border-radius:99px;background:var(--chip);
font-size:.72rem;margin-right:.35rem;color:var(--muted)}
.chip.fire{background:var(--ok-bg);color:var(--ok)}
.chip.nofire{background:var(--ng-bg);color:var(--ng)}
.pass{color:var(--ok);font-weight:600}.fail{color:var(--ng);font-weight:600}
tr.diff td{background:var(--ng-bg)}
.warn{border-left:3px solid var(--accent);padding-left:.8rem;color:var(--accent);font-size:.85rem;margin-top:.6rem}
textarea{width:100%;min-height:5rem;background:var(--bg);color:var(--text);border:1px solid var(--border);
border-radius:6px;padding:.6rem;font:14px/1.6 inherit;resize:vertical}
button{background:var(--accent);color:#fff;border:0;border-radius:6px;padding:.5rem 1rem;
font:600 .85rem inherit;cursor:pointer}
.bar{position:fixed;left:0;right:0;bottom:0;background:var(--surface);border-top:1px solid var(--border);
padding:.7rem 1.5rem;display:flex;gap:1rem;align-items:center;justify-content:flex-end;font-size:.85rem}
.overflow{overflow-x:auto}
"""

JS = """
const KEY = 'jbs-feedback-' + DATA.skill_name + '-' + DATA.iteration;
const saved = JSON.parse(localStorage.getItem(KEY) || '{}');
document.querySelectorAll('textarea[data-eval]').forEach(t => {
  const k = t.dataset.eval;
  if (saved[k]) t.value = saved[k];
  t.addEventListener('input', () => {
    saved[k] = t.value;
    localStorage.setItem(KEY, JSON.stringify(saved));
    document.getElementById('status').textContent = '保存済み(ブラウザ内)';
  });
});
document.getElementById('export').addEventListener('click', () => {
  const out = {
    skill_name: DATA.skill_name, iteration: DATA.iteration,
    reviewed_at: new Date().toISOString().slice(0, 10), feedback: saved
  };
  const text = JSON.stringify(out, null, 1);
  navigator.clipboard.writeText(text).then(
    () => { document.getElementById('status').textContent = 'クリップボードにコピーした。feedback.json として保存する'; },
    () => { document.getElementById('dump').value = text; }
  );
});
"""


def esc(s):
    return html_mod.escape(str(s if s is not None else ""))


def _pct(v):
    return "-" if v is None else "{:.0%}".format(v)


def _pick(runs, eval_id, config):
    got = [r for r in runs if r["eval_id"] == eval_id and r["config"] == config]
    return got[0] if got else None


def build_report(results_path) -> Path:
    results_path = Path(results_path)
    data = json.loads(results_path.read_text(encoding="utf-8"))
    runs, summary, ex = data["runs"], data["summary"], data["executor"]
    eval_ids = sorted({r["eval_id"] for r in runs})

    p = []
    p.append("<div class=wrap>")
    p.append("<h1>{} — iteration {}</h1>".format(esc(data["skill_name"]), data["iteration"]))
    p.append("<div class=sub>{} / 被験 {} · 採点 {} · 各条件 {} 回 / CLI {}</div>".format(
        esc(data["created"]), esc(ex["model"]), esc(ex["grader_model"]),
        ex.get("runs_per_configuration", 1), esc(ex.get("cli", "?"))))

    # ---- サマリ
    p.append("<section><h2>要約</h2><div class=overflow><table>")
    p.append("<tr><th>条件</th><th class=num>正答率</th><th class=num>最小〜最大</th>"
             "<th class=num>スキル発火</th><th class=num>所要秒</th><th class=num>トークン</th>"
             "<th class=num>費用</th></tr>")
    for cfg in ("with_skill", "without_skill"):
        c = summary[cfg]
        p.append("<tr><td>{}</td><td class=num>{}</td><td class=num>{}〜{}</td><td class=num>{}</td>"
                 "<td class=num>{}</td><td class=num>{}</td><td class=num>${:.2f}</td></tr>".format(
                     cfg, _pct(c["pass_rate_mean"]), _pct(c["pass_rate_min"]), _pct(c["pass_rate_max"]),
                     _pct(c["skill_invoked_rate"]), c["duration_s_mean"], c["tokens_mean"], c["cost_usd"]))
    d = summary["delta"]
    p.append("<tr><th>差(あり − なし)</th><th class=num>{}</th><td colspan=2></td>"
             "<th class=num>{}</th><td colspan=2></td></tr>".format(
                 "-" if d["pass_rate"] is None else "{:+.1%}".format(d["pass_rate"]),
                 "-" if d["duration_s"] is None else "{:+.0f}s".format(d["duration_s"])))
    p.append("</table></div>")

    if d["pass_rate"] is not None and abs(d["pass_rate"]) < 0.10:
        p.append("<div class=warn>正答率の差が 10 ポイント未満。CONTRIBUTING 6章は「差が説明できないスキルは"
                 "載せない」と定める。疑うべきは本文ではなく <b>assertions の設計</b> — "
                 "素のモデルが既に知っている知識を測っていないか。</div>")
    fire = summary["with_skill"]["skill_invoked_rate"]
    if fire is not None and fire < 1.0:
        p.append("<div class=warn>スキルの発火率が {} 。発火しない依頼があるなら直すのは本文ではなく "
                 "<b>description</b>(いつ使うかの列挙)。</div>".format(_pct(fire)))
    p.append("</section>")

    # ---- eval ごと
    for eid in eval_ids:
        a, b = _pick(runs, eid, "with_skill"), _pick(runs, eid, "without_skill")
        base = a or b
        p.append("<section>")
        p.append("<h2>eval {} <span class=chip>{}</span></h2>".format(eid, esc(base.get("kind") or "kind未設定")))
        p.append("<pre>{}</pre>".format(esc(base["prompt"])))

        if base.get("assertions"):
            p.append("<h3>判定項目</h3><div class=overflow><table><tr><th>#</th><th>項目</th>"
                     "<th>あり</th><th>なし</th><th>あり側の根拠</th></tr>")
            for i, item in enumerate(base["assertions"]):
                ga = a["assertions"][i] if a and i < len(a["assertions"]) else None
                gb = b["assertions"][i] if b and i < len(b["assertions"]) else None
                pa = ga and ga["passed"]
                pb = gb and gb["passed"]
                cls = " class=diff" if pa != pb else ""
                p.append("<tr{}><td class=num>{}</td><td>{}</td>"
                         "<td class={}>{}</td><td class={}>{}</td><td>{}</td></tr>".format(
                             cls, i + 1, esc(item["text"]),
                             "pass" if pa else "fail", "○" if pa else "×",
                             "pass" if pb else "fail", "○" if pb else "×",
                             esc(ga["evidence"] if ga else "")))
            p.append("</table></div><div class=sub>色の付いた行 = あり/なしで結果が割れた項目。"
                     "ここがこのスキルの効き目。割れた行が無ければ評価が効き目を測れていない。</div>")

        p.append("<div class=cols>")
        for label, r in (("スキルあり", a), ("スキルなし", b)):
            p.append("<div><h3>{}".format(label))
            if r:
                if r["config"] == "with_skill":
                    p.append(" <span class='chip {}'>{}</span>".format(
                        "fire" if r["skill_invoked"] else "nofire",
                        "発火" if r["skill_invoked"] else "未発火"))
                p.append(" <span class=chip>{} · {:.0f}s · ${:.3f}</span>".format(
                    _pct(r["pass_rate"]), r["duration_s"], r["cost_usd"]))
            p.append("</h3><pre>{}</pre></div>".format(
                esc(r["error"] or r["response"]) if r else "(未実行)"))
        p.append("</div>")

        p.append("<h3>所見(次の周回で直すこと)</h3>"
                 "<textarea data-eval='{}' placeholder='例: なし側も期限を日付換算できている → この assertion は差を測れていない。"
                 "「全項目に担当が付いているか」に差し替える'></textarea>".format(eid))
        p.append("</section>")

    p.append("</div>")
    p.append("<div class=bar><span id=status class=sub></span>"
             "<button id=export>所見を JSON でコピー</button></div>")
    p.append("<textarea id=dump style='display:none'></textarea>")

    payload = json.dumps({"skill_name": data["skill_name"], "iteration": data["iteration"]},
                         ensure_ascii=False).replace("</", "<\\/")
    doc = ("<!doctype html><html lang=ja><head><meta charset=utf-8>"
           "<meta name=viewport content='width=device-width,initial-scale=1'>"
           "<title>{} iteration {}</title><style>{}</style></head><body>{}"
           "<script>const DATA={};{}</script></body></html>").format(
               esc(data["skill_name"]), data["iteration"], CSS, "".join(p), payload, JS)

    out = results_path.parent / "review.html"
    out.write_text(doc, encoding="utf-8")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="results.json からレビュー用ビューアを作る")
    ap.add_argument("--skill", default="", help="最新イテレーションを使う")
    ap.add_argument("--results", default="", help="results.json のパスを直接指定")
    args = ap.parse_args()

    if args.results:
        path = Path(args.results)
    elif args.skill:
        base = EVAL_ROOT / args.skill
        iters = sorted(base.glob("iteration-*"), key=lambda p: int(p.name.split("-")[-1]))
        if not iters:
            print("ERROR {} に results が無い。先に run_evals.py を回すこと".format(base), file=sys.stderr)
            return 1
        path = iters[-1] / "results.json"
    else:
        ap.error("--skill か --results のどちらかが要る")

    if not path.exists():
        print("ERROR {} が無い".format(path), file=sys.stderr)
        return 1
    print(build_report(path).relative_to(ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
