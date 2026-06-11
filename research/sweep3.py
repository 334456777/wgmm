"""第三阶段扫描(审计修正后): 暖启动切片协议, 全候选族统一网格."""

from __future__ import annotations

import json
import multiprocessing as mp
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import run_protocol  # noqa: E402

H = 3600.0


def build_grid() -> list[dict | str]:
	"""聚焦网格: 上一轮 Pareto 前沿附近 + sqrt_hazard + 参照."""
	grid: list[dict | str] = ["production"]
	for cap in [12, 16, 24, 36, 48, 72]:
		grid.append({"policy": "wgmm", "max_interval_cap_sec": cap * H})
	for cap in [24, 48]:
		for bw in [2, 6]:
			grid.append(
				{
					"policy": "wgmm",
					"max_interval_cap_sec": cap * H,
					"burst_window_sec": bw * H,
					"burst_interval_sec": 1800.0,
				}
			)
	for q in [0.15, 0.2, 0.25, 0.3, 0.4]:
		for cap in [24 * H, 48 * H, None]:
			grid.append(
				{
					"policy": "hybrid",
					"hazard_q": q,
					"hazard_floor_sec": 3600.0,
					"max_interval_cap_sec": cap,
				}
			)
	for q in [0.08, 0.12]:
		grid.append({"policy": "hazard", "hazard_q": q, "hazard_floor_sec": 3600.0})
	for k in [40, 60, 90, 130, 180]:
		grid.append({"policy": "sqrt_hazard", "sqrth_k": k, "hazard_floor_sec": 1800.0})
	for m in [3, 8]:
		grid.append(
			{
				"policy": "sqrt_hazard",
				"sqrth_k": 90,
				"nn_m": m,
				"hazard_floor_sec": 1800.0,
			}
		)
	for iv in [7, 8, 10]:
		grid.append({"policy": "fixed", "fixed_interval_sec": iv * H})
	return grid


def run_one(overrides: dict | str) -> dict:
	"""跑单个配置."""
	result = run_protocol(overrides)
	return {"overrides": overrides, **result}


def fmt(row: dict, sl: str) -> str:
	"""格式化一个切片的指标."""
	s = row[sl]
	return (
		f"{s['checks_per_day']:5.2f}/d mean={s['mean_all']:6.2f} "
		f"med={s['median_all']:5.2f} p90={s['p90_all']:6.2f} "
		f"sess_mean={s['mean_session']:6.2f}"
	)


def main() -> None:
	"""并行执行."""
	grid = build_grid()
	out_path = Path(__file__).parent / "sweep3.jsonl"
	with mp.Pool(processes=max(mp.cpu_count() - 2, 2)) as pool, out_path.open("w") as f:
		for i, row in enumerate(pool.imap_unordered(run_one, grid)):
			f.write(json.dumps(row) + "\n")
			f.flush()
			print(
				f"[{i + 1}/{len(grid)}] {row['overrides']}\n"
				f"    train {fmt(row, 'train')}\n"
				f"    val   {fmt(row, 'val')}",
				flush=True,
			)


if __name__ == "__main__":
	main()
