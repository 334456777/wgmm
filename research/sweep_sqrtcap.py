"""hybrid_sqrt(wgmm + sqrt_hazard 上限) 的 k 预算校准: 只打印 train, val 落盘不看."""

from __future__ import annotations

import json
import multiprocessing as mp
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import run_protocol  # noqa: E402


def run(k: float) -> tuple[float, dict]:
	"""跑单个 k."""
	result = run_protocol(
		{"policy": "wgmm", "sqrt_cap_k": k, "hazard_floor_sec": 1800.0}
	)
	return k, result


def main() -> None:
	"""并行校准并落盘."""
	ks = [150, 160, 175, 200]
	results: dict = {}
	with mp.Pool(processes=7) as pool:
		for k, r in pool.imap_unordered(run, ks):
			results[k] = r
			t = r["train"]
			print(
				f"k={k:>3} TRAIN {t['checks_per_day']:5.2f}/d "
				f"mean={t['mean_all']:6.2f} med={t['median_all']:5.2f} "
				f"p90={t['p90_all']:6.2f} sess={t['mean_session']:6.2f}",
				flush=True,
			)
	out = Path(__file__).parent / "sqrtcap_scan2.json"
	json.dump({str(k): r for k, r in results.items()}, out.open("w"))
	print("\n(val 切片已落盘 research/sqrtcap_scan2.json, 尚未查看)")


if __name__ == "__main__":
	main()
