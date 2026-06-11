"""候选策略验证: 在指定窗口集合上对比候选与基线."""

from __future__ import annotations

import json
import multiprocessing as mp
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import DEFAULT_PARAMS, load_events, simulate, span_fraction  # noqa: E402


def run_window(job: tuple[dict, float, float]) -> dict:
	"""跑单个 (配置, 窗口) 组合."""
	overrides, fa, fb = job
	events = load_events()
	ta = span_fraction(events, fa)
	tb = span_fraction(events, fb) + (1 if fb >= 1.0 else 0)
	params = dict(DEFAULT_PARAMS)
	params.update(overrides)
	result = simulate(events, ta, tb, params)
	result.pop("check_times")
	result.pop("delays_h")
	return {"overrides": overrides, "window": [fa, fb], **result}


def main() -> None:
	"""CLI: validate.py <configs.json> <fa:fb> [<fa:fb> ...]"""
	configs = json.loads(Path(sys.argv[1]).read_text())
	windows = [tuple(float(x) for x in w.split(":")) for w in sys.argv[2:]]
	jobs = [(c, fa, fb) for c in configs for fa, fb in windows]
	with mp.Pool(processes=max(mp.cpu_count() - 2, 2)) as pool:
		for row in pool.imap(run_window, jobs):
			o = dict(row["overrides"])
			name = o.pop("policy", "wgmm")
			desc = name + "|" + ",".join(f"{k}={v}" for k, v in o.items())
			print(
				f"{row['window'][0]:.2f}-{row['window'][1]:.2f} {desc:<75} "
				f"{row['checks_per_day']:5.2f}/d mean={row['delay_mean_h']:6.2f} "
				f"med={row['delay_median_h']:5.2f} p90={row['delay_p90_h']:6.2f} "
				f"max={row['delay_max_h']:6.1f} undet={row['events_undetected_at_end']}",
				flush=True,
			)


if __name__ == "__main__":
	main()
