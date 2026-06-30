"""
评估运行器

统一入口，支持：
  - python -m tests.eval.eval_runner --all      运行所有评估
  - python -m tests.eval.eval_runner --retrieval  仅检索
  - python -m tests.eval.eval_runner --intent     仅意图

退出码规则：
  - 0: 所有指标达标
  - 1: 部分指标不达标（不注册到 Nacos）
  - 2: 运行异常
"""
import sys
import os
import argparse
import subprocess
import datetime

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

EVAL_DIR = os.path.join(PROJECT_ROOT, "tests", "eval")
REPORTS_DIR = os.path.join(EVAL_DIR, "reports")
os.makedirs(REPORTS_DIR, exist_ok=True)

# 指标目标
THRESHOLDS = {
    "retrieval": {"recall_at_5": 0.80, "mrr": 0.60},
    "intent": {"accuracy": 0.85},
}


def run_eval(module: str) -> tuple[bool, str]:
    """运行单个评估模块，返回 (是否达标, 输出)"""
    cmd = [sys.executable, "-m", f"tests.eval.{module}"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=PROJECT_ROOT, timeout=120)
        output = result.stdout + result.stderr
        return result.returncode == 0, output
    except subprocess.TimeoutExpired:
        return False, "评估超时"
    except Exception as e:
        return False, str(e)


def check_thresholds(module: str, output: str) -> dict:
    """从输出中提取指标并与目标比较"""
    checks = {}
    targets = THRESHOLDS.get(module, {})
    for metric, target in targets.items():
        # 查找输出中的指标行，如 "Recall@5: 0.85"
        for line in output.split("\n"):
            key_map = {
                "recall_at_5": "Recall",
                "mrr": "MRR",
                "accuracy": "Accuracy",
            }
            keyword = key_map.get(metric, metric)
            if keyword in line and ":" in line:
                try:
                    value = float(line.split(":")[-1].strip())
                    checks[metric] = {"value": value, "target": target, "pass": value >= target}
                    break
                except ValueError:
                    continue
        if metric not in checks:
            checks[metric] = {"value": None, "target": target, "pass": False, "error": "未找到指标"}
    return checks


def main():
    parser = argparse.ArgumentParser(description="RAG 客服 Agent 评估运行器")
    parser.add_argument("--all", action="store_true", help="运行所有评估")
    parser.add_argument("--retrieval", action="store_true", help="运行检索评估")
    parser.add_argument("--intent", action="store_true", help="运行意图评估")
    args = parser.parse_args()

    if not (args.all or args.retrieval or args.intent):
        parser.print_help()
        sys.exit(0)

    if args.all:
        args.retrieval = True
        args.intent = True

    all_pass = True
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    modules = []
    if args.retrieval:
        modules.append("eval_retrieval")
    if args.intent:
        modules.append("eval_intent")

    for module in modules:
        print(f"\n{'=' * 60}")
        print(f"  评估: {module}")
        print(f"{'=' * 60}")
        ok, output = run_eval(module)
        print(output)
        checks = check_thresholds(module, output)
        for metric, info in checks.items():
            status = "PASS" if info["pass"] else "FAIL"
            print(f"  [{status}] {metric}: {info.get('value', 'N/A')} (target: {info['target']})")
            if not info["pass"]:
                all_pass = False

    # 生成汇总报告
    report_path = os.path.join(REPORTS_DIR, "summary.txt")
    with open(report_path, "w") as f:
        f.write(f"评估时间: {timestamp}\n")
        f.write(f"结果: {'PASS' if all_pass else 'FAIL'}\n")

    print(f"\n汇总报告: {report_path}")
    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
