"""
benchmark_runner: 对 agent 跑标准对话集，输出 JSON 报告。
跑前备份 data/agents/<agent_id>/ 到 logs/benchmark/<agent>-<ts>.tar.gz，跑完恢复。

用法：
    python tools/benchmark_runner.py <agent_id> [--run-label baseline]
"""
import argparse
import json
import logging
import shutil
import tarfile
import time
from datetime import datetime
from pathlib import Path

from core.dialogue import chat, end_session

_ROOT          = Path(__file__).parent.parent
_AGENTS_DIR    = _ROOT / "data" / "agents"
_BENCHMARK_DIR = _ROOT / "logs" / "benchmark"
_DEFAULT_DIALOGUES = _ROOT / "tests" / "data" / "benchmark_dialogues.json"

logger = logging.getLogger("benchmark_runner")


def _backup_agent(agent_id: str) -> Path:
    _BENCHMARK_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    tar_path = _BENCHMARK_DIR / f"{agent_id}-snapshot-{ts}.tar.gz"
    target = _AGENTS_DIR / agent_id
    if not target.exists():
        raise FileNotFoundError(f"agent dir not found: {target}")
    with tarfile.open(tar_path, "w:gz") as tar:
        tar.add(target, arcname=agent_id)
    return tar_path


def _restore_agent(agent_id: str, tar_path: Path) -> None:
    target = _AGENTS_DIR / agent_id
    if target.exists():
        shutil.rmtree(target)
    with tarfile.open(tar_path, "r:gz") as tar:
        tar.extractall(_AGENTS_DIR, filter="data")


def run_benchmark(agent_id: str, dialogues_path: Path, run_label: str = "baseline") -> dict:
    with open(dialogues_path, "r", encoding="utf-8") as f:
        dialogues = json.load(f)

    backup = _backup_agent(agent_id)
    logger.info(f"benchmark backup saved: {backup}")

    results = []
    session_history: list = []
    session_surfaced: set = set()
    t_start = time.time()

    try:
        for i, q in enumerate(dialogues):
            t0 = time.monotonic()
            try:
                r = chat(agent_id, q["text"], session_history, session_surfaced)
            except Exception as e:
                logger.error(f"benchmark q{i} error: {e}")
                results.append({
                    "index": i,
                    "category": q.get("category", ""),
                    "question": q["text"],
                    "reply": None,
                    "error": str(e),
                    "elapsed_s": round(time.monotonic() - t0, 2),
                })
                continue
            elapsed = time.monotonic() - t0
            session_history.append({"role": "user", "content": q["text"]})
            session_history.append({"role": "assistant", "content": r["reply"]})
            session_surfaced = r["session_surfaced"]
            results.append({
                "index": i,
                "category": q.get("category", ""),
                "question": q["text"],
                "reply": r["reply"],
                "emotion_intensity": r["emotion_intensity"],
                "surfaced_count": len(r["session_surfaced"]),
                "elapsed_s": round(elapsed, 2),
            })
        try:
            end_session(agent_id, session_history)
        except Exception as e:
            logger.warning(f"benchmark end_session error (non-fatal): {e}")
    finally:
        _restore_agent(agent_id, backup)
        logger.info(f"benchmark restored from: {backup}")

    report = {
        "agent_id":       agent_id,
        "run_label":      run_label,
        "started_at":     datetime.now().isoformat(),
        "total_elapsed_s": round(time.time() - t_start, 2),
        "backup_tar":     str(backup),
        "question_count": len(dialogues),
        "ok_count":       sum(1 for x in results if "error" not in x),
        "results":        results,
    }
    out_path = _BENCHMARK_DIR / f"{agent_id}-{run_label}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    logger.info(f"benchmark report: {out_path}")
    return report


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(description="Run benchmark dialogues against an agent")
    parser.add_argument("agent_id")
    parser.add_argument("--run-label",  default="baseline")
    parser.add_argument("--dialogues",  default=str(_DEFAULT_DIALOGUES))
    args = parser.parse_args()
    run_benchmark(args.agent_id, Path(args.dialogues), args.run_label)


if __name__ == "__main__":
    main()
