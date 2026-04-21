"""benchmark_runner: 对 agent 跑标准对话集，输出 JSON 报告。

两种模式：
  1. 副本模式（推荐）：先把源 agent 拷贝到一个新的测试 agent，对副本跑，
     副本保留下来便于事后查看。
        python tools/benchmark_runner.py jobs_v1 --copy-to jobs_v1_test_benchmark

  2. 原位模式（兼容）：跑前 tar.gz 备份源 agent，跑完恢复，不留现场。
        python tools/benchmark_runner.py jobs_v1 --run-label baseline
"""
import argparse
import json
import logging
import shutil
import sys
import tarfile
import time
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.dialogue import chat, end_session

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
    try:
        with tarfile.open(tar_path, "w:gz") as tar:
            tar.add(target, arcname=agent_id)
    except Exception:
        tar_path.unlink(missing_ok=True)
        raise
    return tar_path


def _restore_agent(agent_id: str, tar_path: Path) -> None:
    target = _AGENTS_DIR / agent_id
    if target.exists():
        shutil.rmtree(target)
    with tarfile.open(tar_path, "r:gz") as tar:
        tar.extractall(_AGENTS_DIR, filter="data")


def _copy_agent(source_id: str, dest_id: str) -> Path:
    """从源 agent 目录拷贝到目标目录。目标若已存在则先删除（每次 benchmark 从干净副本开始）。"""
    src = _AGENTS_DIR / source_id
    dst = _AGENTS_DIR / dest_id
    if not src.exists():
        raise FileNotFoundError(f"source agent dir not found: {src}")
    if src.resolve() == dst.resolve():
        raise ValueError(f"source and dest are the same: {src}")
    if dst.exists():
        logger.info(f"overwriting existing test agent dir: {dst}")
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    return dst


def run_benchmark(
    agent_id: str,
    dialogues_path: Path,
    run_label: str = "baseline",
    copy_to: str | None = None,
) -> dict:
    """
    对 agent_id 跑 dialogues_path 里的对话集。

    copy_to=None     ：原位模式，tar 备份 + 恢复
    copy_to="xxx"    ：副本模式，先 copytree(agent_id → xxx)，跑 xxx，跑完保留
    """
    with open(dialogues_path, "r", encoding="utf-8") as f:
        dialogues = json.load(f)

    if copy_to:
        test_agent = copy_to
        copied_dir = _copy_agent(agent_id, copy_to)
        logger.info(f"benchmark running on copy: {copied_dir}")
        backup = None
    else:
        test_agent = agent_id
        backup = _backup_agent(agent_id)
        copied_dir = None
        logger.info(f"benchmark backup saved: {backup}")

    results = []
    session_history: list = []
    t_start = time.time()
    started_at = datetime.now().isoformat()

    try:
        for i, q in enumerate(dialogues):
            t0 = time.monotonic()
            try:
                r = chat(test_agent, q["text"], session_history)
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
            results.append({
                "index": i,
                "category": q.get("category", ""),
                "question": q["text"],
                "reply": r["reply"],
                "emotion_intensity": r["emotion_intensity"],
                "elapsed_s": round(elapsed, 2),
            })
        try:
            # wait_async=True：benchmark 里必须等 L2 / soul_update 走完再退主进程，
            # 否则 daemon 异步线程会被 kill，l2_patterns 不会更新。
            end_session(test_agent, session_history, wait_async=True)
        except Exception as e:
            logger.warning(f"benchmark end_session error (non-fatal): {e}")
    finally:
        if backup is not None:
            try:
                _restore_agent(agent_id, backup)
                logger.info(f"benchmark restored from: {backup}")
            except Exception as restore_exc:
                logger.critical(
                    f"RESTORE FAILED — agent '{agent_id}' may be in inconsistent state. "
                    f"Manual restore from {backup}. Error: {restore_exc}"
                )

    report = {
        "agent_id":        agent_id,
        "test_agent":      test_agent,
        "copy_mode":       copy_to is not None,
        "kept_copy_dir":   str(copied_dir) if copied_dir else None,
        "run_label":       run_label,
        "started_at":      started_at,
        "total_elapsed_s": round(time.time() - t_start, 2),
        "backup_tar":      str(backup) if backup else None,
        "question_count":  len(dialogues),
        "ok_count":        sum(1 for x in results if "error" not in x),
        "results":         results,
    }
    _BENCHMARK_DIR.mkdir(parents=True, exist_ok=True)
    out_path = _BENCHMARK_DIR / f"{test_agent}-{run_label}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    logger.info(f"benchmark report: {out_path}")
    return report


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(description="Run benchmark dialogues against an agent")
    parser.add_argument("agent_id", help="source agent id (will be copied if --copy-to given)")
    parser.add_argument("--run-label", default="baseline")
    parser.add_argument("--dialogues", default=str(_DEFAULT_DIALOGUES))
    parser.add_argument(
        "--copy-to",
        default=None,
        help="copy agent_id to this new agent_id first, run benchmark on the copy, keep the copy",
    )
    args = parser.parse_args()
    run_benchmark(
        args.agent_id,
        Path(args.dialogues),
        run_label=args.run_label,
        copy_to=args.copy_to,
    )


if __name__ == "__main__":
    main()
