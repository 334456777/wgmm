"""sweep3 结果分析: 预注册选择规则 + 配对块 bootstrap + 切点稳定性.

预注册选择规则(在看到 val 之前固定):
  在 train 切片上, 预算约束 checks_per_day <= 同切片基线 cpd × tier
  (tier=1.00 严格档 / 1.10 宽松档), 约束内选 mean_all 最小者.
val 切片一次性报告全部候选, 胜者附配对块 bootstrap CI(块=发布会话).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

RESEARCH = Path(__file__).resolve().parent


def load_rows(path: Path) -> tuple[dict, list[dict]]:
	"""读取 sweep3 行, 分离基线."""
	rows = [json.loads(line) for line in path.read_text().splitlines()]
	baseline = next(r for r in rows if r["overrides"] == "production")
	candidates = [r for r in rows if r["overrides"] != "production"]
	return baseline, candidates


def desc(overrides: dict | str) -> str:
	"""配置的紧凑描述."""
	if overrides == "production":
		return "BASELINE(production)"
	o = dict(overrides)
	p = o.pop("policy")
	parts = []
	for k, v in o.items():
		k = (
			k.replace("max_interval_cap_sec", "cap")
			.replace("burst_window_sec", "bw")
			.replace("burst_interval_sec", "bi")
			.replace("hazard_floor_sec", "floor")
			.replace("hazard_q", "q")
			.replace("fixed_interval_sec", "iv")
			.replace("sqrth_k", "k")
			.replace("nn_m", "m")
		)
		if isinstance(v, float) and v >= 900:
			v = f"{v / 3600:g}h"
		parts.append(f"{k}={v}")
	return p + "(" + ",".join(parts) + ")"


def sessionize(records: list) -> list[list[tuple[int, float]]]:
	"""把逐事件记录按会话分块(块 bootstrap 用)."""
	blocks: list[list[tuple[int, float]]] = []
	for ts, delay, is_start in records:
		if is_start or not blocks:
			blocks.append([])
		blocks[-1].append((ts, delay))
	return blocks


def paired_block_bootstrap(
	base_records: list, cand_records: list, lo: int, hi: int, n_boot: int = 10000
) -> dict:
	"""配对块 bootstrap: 候选与基线对同一组事件的延迟差(块=会话)."""
	base = {r[0]: (r[1], r[2]) for r in base_records if lo <= r[0] < hi}
	cand = {r[0]: r[1] for r in cand_records if lo <= r[0] < hi}
	common = sorted(set(base) & set(cand))
	blocks = sessionize(
		[[ts, cand[ts] - base[ts][0], base[ts][1]] for ts in common]
	)
	diffs_by_block = [np.array([d for _, d in b]) for b in blocks]
	rng = np.random.default_rng(42)
	n = len(diffs_by_block)
	means = np.empty(n_boot)
	for i in range(n_boot):
		idx = rng.integers(0, n, n)
		sample = np.concatenate([diffs_by_block[j] for j in idx])
		means[i] = sample.mean()
	point = float(np.concatenate(diffs_by_block).mean())
	return {
		"paired_mean_diff_h": point,
		"ci95": [float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))],
		"n_events": len(common),
		"n_blocks": n,
		"frac_boot_below_zero": float((means < 0).mean()),
	}


def delays_in(records: list, lo: int, hi: int) -> np.ndarray:
	"""切片内逐事件延迟."""
	return np.array([r[1] for r in records if lo <= r[0] < hi], dtype=np.float64)


def main() -> None:
	"""执行分析."""
	baseline, candidates = load_rows(RESEARCH / "sweep3.jsonl")
	b_train, b_val = baseline["train"], baseline["val"]
	print(
		f"baseline train: {b_train['checks_per_day']:.2f}/d mean={b_train['mean_all']:.2f} "
		f"med={b_train['median_all']:.2f} p90={b_train['p90_all']:.2f}"
	)
	print(
		f"baseline val:   {b_val['checks_per_day']:.2f}/d mean={b_val['mean_all']:.2f} "
		f"med={b_val['median_all']:.2f} p90={b_val['p90_all']:.2f}\n"
	)

	for tier, label in [(1.00, "严格档 cpd<=1.00x"), (1.10, "宽松档 cpd<=1.10x")]:
		ok = [
			r
			for r in candidates
			if r["train"]["checks_per_day"] <= b_train["checks_per_day"] * tier
		]
		ok.sort(key=lambda r: r["train"]["mean_all"])
		print(f"== {label}: {len(ok)} 个候选满足预算, train mean 前 5 ==")
		for r in ok[:5]:
			t, v = r["train"], r["val"]
			print(
				f"  {desc(r['overrides']):<52} train {t['checks_per_day']:5.2f}/d "
				f"mean={t['mean_all']:6.2f} | val {v['checks_per_day']:5.2f}/d "
				f"mean={v['mean_all']:6.2f} med={v['median_all']:5.2f} "
				f"p90={v['p90_all']:6.2f} sess={v['mean_session']:6.2f}"
			)
		print()

	if len(sys.argv) > 1 and sys.argv[1] == "bootstrap":
		winner_desc = sys.argv[2]
		winner = next(r for r in candidates if desc(r["overrides"]) == winner_desc)
		events_all = [r[0] for r in baseline["records"]]
		t70 = sorted(events_all)[0]  # placeholder, replaced below
		# val 切片边界: 取基线 val 切片的实际范围
		lo = min(r[0] for r in baseline["records"])
		hi = max(r[0] for r in baseline["records"]) + 1
		# 主分析: val 边界由 span 70% 定义, 由调用方传入
		lo = int(sys.argv[3])
		hi = int(sys.argv[4])
		res = paired_block_bootstrap(
			baseline["records"], winner["records"], lo, hi
		)
		print("paired block bootstrap (val):", json.dumps(res, indent=1))

		print("\n切点稳定性 (delay mean, 候选 vs 基线):")
		ts_min = min(events_all)
		ts_max = max(events_all) + 1
		for frac in [0.60, 0.70, 0.80]:
			cut = int(ts_min + (ts_max - ts_min) * frac)
			db = delays_in(baseline["records"], cut, ts_max)
			dc = delays_in(winner["records"], cut, ts_max)
			print(
				f"  cut={frac:.2f}: baseline mean={db.mean():6.2f} (n={len(db)}), "
				f"winner mean={dc.mean():6.2f} (n={len(dc)})"
			)


if __name__ == "__main__":
	main()
