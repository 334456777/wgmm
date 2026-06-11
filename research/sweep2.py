"""第二阶段扫描: 间隔上限(cap)与爆发窗口(burst)叠加在基础策略上."""

from __future__ import annotations

import json
import multiprocessing as mp
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sweep import run_one  # noqa: E402

H = 3600.0


def build_grid() -> list[dict]:
	"""cap/burst 组合网格."""
	grid: list[dict] = []
	for cap in [6, 8, 12, 16, 24, 36, 48]:
		grid.append({"policy": "wgmm", "max_interval_cap_sec": cap * H})
	for cap in [12, 24, 48]:
		for bw in [2, 6, 12]:
			for bi in [900.0, 1800.0]:
				grid.append(
					{
						"policy": "wgmm",
						"max_interval_cap_sec": cap * H,
						"burst_window_sec": bw * H,
						"burst_interval_sec": bi,
					}
				)
	for bw in [2, 6, 12]:
		for bi in [900.0, 1800.0]:
			grid.append(
				{
					"policy": "wgmm",
					"burst_window_sec": bw * H,
					"burst_interval_sec": bi,
				}
			)
	for fixed in [6, 8, 10, 12]:
		grid.append(
			{
				"policy": "fixed",
				"fixed_interval_sec": fixed * H,
				"burst_window_sec": 6 * H,
				"burst_interval_sec": 1800.0,
			}
		)
	for q in [0.15, 0.2, 0.25, 0.3]:
		for cap in [24, 48]:
			grid.append(
				{
					"policy": "hybrid",
					"hazard_q": q,
					"hazard_floor_sec": 3600.0,
					"max_interval_cap_sec": cap * H,
				}
			)
	return grid


def main() -> None:
	"""并行执行第二阶段网格."""
	grid = build_grid()
	out_path = Path(__file__).parent / "sweep2_train.jsonl"
	with mp.Pool(processes=max(mp.cpu_count() - 2, 2)) as pool, out_path.open("w") as f:
		for i, row in enumerate(pool.imap_unordered(run_one, grid)):
			f.write(json.dumps(row) + "\n")
			f.flush()
			print(f"[{i + 1}/{len(grid)}] {row['overrides']} -> "
				f"{row['checks_per_day']:.2f}/d mean={row['delay_mean_h']:.2f}h "
				f"med={row['delay_median_h']:.2f}h p90={row['delay_p90_h']:.2f}h", flush=True)


if __name__ == "__main__":
	main()
