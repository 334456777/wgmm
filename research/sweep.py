"""调度策略参数扫描: 在训练窗上跑网格, 输出每个配置的延迟/请求量指标."""

from __future__ import annotations

import json
import multiprocessing as mp
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import DEFAULT_PARAMS, load_events, simulate, span_fraction  # noqa: E402

TRAIN = (0.30, 0.70)


def build_grid() -> list[dict]:
	"""构建候选配置网格."""
	grid: list[dict] = []
	for h in [3, 4, 5, 6, 7, 8, 10, 12]:
		grid.append({"policy": "fixed", "fixed_interval_sec": h * 3600.0})
	for q in [0.05, 0.08, 0.10, 0.12, 0.15, 0.20, 0.25, 0.30]:
		for floor in [900.0, 1800.0, 3600.0]:
			grid.append({"policy": "hazard", "hazard_q": q, "hazard_floor_sec": floor})
	for curve in [1.0, 1.5, 2.0, 3.0]:
		for pct in [5.0, 10.0, 20.0, 30.0, 40.0]:
			grid.append(
				{"policy": "wgmm", "mapping_curve": curve, "min_interval_pct": pct}
			)
	for mult in [1.0, 1.5]:
		for base in [0.5, 2.0]:
			grid.append(
				{
					"policy": "wgmm",
					"peak_threshold_mult": mult,
					"peak_window_base": base,
				}
			)
	for q in [0.10, 0.15, 0.20, 0.25]:
		for floor in [1800.0, 3600.0]:
			grid.append({"policy": "hybrid", "hazard_q": q, "hazard_floor_sec": floor})
	return grid


def run_one(overrides: dict) -> dict:
	"""跑单个配置并附上指标."""
	events = load_events()
	ta = span_fraction(events, TRAIN[0])
	tb = span_fraction(events, TRAIN[1])
	params = dict(DEFAULT_PARAMS)
	params.update(overrides)
	result = simulate(events, ta, tb, params)
	result.pop("check_times")
	result.pop("delays_h")
	return {"overrides": overrides, **result}


def main() -> None:
	"""并行执行网格扫描."""
	grid = build_grid()
	out_path = Path(__file__).parent / "sweep_train.jsonl"
	with mp.Pool(processes=max(mp.cpu_count() - 2, 2)) as pool, out_path.open("w") as f:
		for i, row in enumerate(pool.imap_unordered(run_one, grid)):
			f.write(json.dumps(row) + "\n")
			f.flush()
			print(f"[{i + 1}/{len(grid)}] {row['overrides']} -> "
				f"{row['checks_per_day']:.2f}/d mean={row['delay_mean_h']:.2f}h", flush=True)


if __name__ == "__main__":
	main()
