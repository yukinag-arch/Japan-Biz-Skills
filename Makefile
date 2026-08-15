# ループ開発の入口。詳しくは CONTRIBUTING.md 9章。
#
#   make check                     検証(frontmatter・語彙・鮮度・評価の内訳)
#   make eval SKILL=<name>         スキルあり/なしで評価を回し、review.html まで作る
#   make eval SKILL=<name> EVALS=1-3 RUNS=3
#   make report SKILL=<name>       直近の results.json からビューアを作り直す
#   make plan SKILL=<name>         実行計画だけ表示(費用の見積り前に)
#   make setup                     claude CLI の有無を確認

SKILL ?= onboarding-offboarding-jp
RUNS  ?= 1
JOBS  ?= 4
MODEL ?= sonnet
EVALS ?=
BUDGET ?=

EVAL_ARGS = --skill $(SKILL) --runs $(RUNS) --jobs $(JOBS) --model $(MODEL) \
            $(if $(EVALS),--evals $(EVALS),) $(if $(BUDGET),--max-budget-usd $(BUDGET),)

.PHONY: check validate strict eval plan report setup clean-evals

check: validate

validate:
	python3 scripts/validate_skills.py

strict:
	python3 scripts/validate_skills.py --strict

eval: validate
	python3 scripts/run_evals.py $(EVAL_ARGS)

plan:
	python3 scripts/run_evals.py $(EVAL_ARGS) --dry-run

report:
	python3 scripts/make_report.py --skill $(SKILL)

setup:
	@command -v claude >/dev/null 2>&1 \
	  && echo "claude CLI: $$(claude --version)" \
	  || (echo "claude CLI が無い。npm i -g @anthropic-ai/claude-code の後にログインすること"; exit 1)
	@python3 -c "import sys; assert sys.version_info >= (3,9)" && echo "python3: $$(python3 -V)"

clean-evals:
	rm -rf .evals
