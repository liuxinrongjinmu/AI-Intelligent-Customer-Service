.PHONY: eval eval-retrieval eval-intent eval-report

# 一键运行所有评估
eval: eval-retrieval eval-intent
	@echo "所有评估完成，生成报告: tests/eval/reports/report.html"

# 检索质量评估（Recall@5 >= 0.80）
eval-retrieval:
	@echo "=== 运行检索评估 ==="
	python -m tests.eval.eval_retrieval --output tests/eval/reports/retrieval_report.html 2>&1 | tee tests/eval/reports/retrieval.log

# 意图分类评估（Accuracy >= 0.85）
eval-intent:
	@echo "=== 运行意图分类评估 ==="
	python -m tests.eval.eval_intent --output tests/eval/reports/intent_report.html 2>&1 | tee tests/eval/reports/intent.log

# 生成综合报告
eval-report:
	python -m tests.eval.eval_report --retrieval tests/eval/reports/retrieval.log --intent tests/eval/reports/intent.log --output tests/eval/reports/report.html
