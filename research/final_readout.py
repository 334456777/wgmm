"""冻结 k=130 后的一次性验证读出: val 指标 + 配对块 bootstrap + 切点稳定性."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from analyze import delays_in, paired_block_bootstrap  # noqa: E402
from harness import load_events, span_fraction  # noqa: E402

RESEARCH = Path(__file__).resolve().parent


def fmt_slice(s: dict) -> str:
	"""格式化切片指标."""
	return (
		f"{s['checks_per_day']:5.2f}/d mean={s['mean_all']:6.2f} "
		f"med={s['median_all']:5.2f} p90={s['p90_all']:6.2f} "
		f"sess_mean={s['mean_session']:6.2f} undet={s['events_undetected_at_end']}"
	)


def main() -> None:
	"""执行最终读出."""
	scan1 = json.loads((RESEARCH / "sqrtcap_scan.json").read_text())
	scan2 = json.loads((RESEARCH / "sqrtcap_scan2.json").read_text())
	rows = [json.loads(line) for line in (RESEARCH / "sweep3.jsonl").read_text().splitlines()]
	base = next(r for r in rows if r["overrides"] == "production")

	winner = scan1["130"]
	events = load_events()
	t70 = span_fraction(events, 0.70)
	t_end = events[-1] + 1

	print("== 冻结候选: wgmm + sqrt_hazard 上限 (k=130, floor=0.5h) ==")
	print(f"baseline train: {fmt_slice(base['train'])}")
	print(f"k=130    train: {fmt_slice(winner['train'])}")
	print(f"baseline val:   {fmt_slice(base['val'])}")
	print(f"k=130    val:   {fmt_slice(winner['val'])}")
	print(f"baseline full:  {fmt_slice(base['full'])}")
	print(f"k=130    full:  {fmt_slice(winner['full'])}")
	bv = base["val"]["checks_per_day"]
	wv = winner["val"]["checks_per_day"]
	print(f"\nval 预算核查: {wv:.2f} <= {bv:.2f} ? {'PASS' if wv <= bv else 'FAIL'}")

	print("\n敏感性(邻近 k, val):")
	for k, scan in [("110", scan1), ("150", scan2), ("160", scan2)]:
		print(f"  k={k}: {fmt_slice(scan[k]['val'])}")

	print("\n== 配对块 bootstrap (val 切片, 块=发布会话) ==")
	res = paired_block_bootstrap(base["records"], winner["records"], t70, t_end)
	print(json.dumps(res, indent=1))

	print("\n== 切点稳定性 (cut→末尾, 逐事件延迟均值: 基线 vs k=130) ==")
	ts_min, ts_max = events[0], events[-1] + 1
	for frac in [0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85]:
		cut = int(ts_min + (ts_max - ts_min) * frac)
		db = delays_in(base["records"], cut, ts_max)
		dc = delays_in(winner["records"], cut, ts_max)
		print(
			f"  cut={frac:.2f}: baseline {db.mean():6.2f}h (n={len(db):3d})  "
			f"k=130 {dc.mean():6.2f}h  Δ={dc.mean() - db.mean():+7.2f}h"
		)

	print("\n== 全程延迟分布对比 (30%→end) ==")
	t30 = span_fraction(events, 0.30)
	db = delays_in(base["records"], t30, ts_max)
	dc = delays_in(winner["records"], t30, ts_max)
	for name, d in [("baseline", db), ("k=130", dc)]:
		print(
			f"  {name:<9} mean={d.mean():6.2f} med={np.median(d):5.2f} "
			f"p75={np.percentile(d, 75):6.2f} p90={np.percentile(d, 90):6.2f} "
			f"p99={np.percentile(d, 99):7.2f} max={d.max():7.2f}"
		)


if __name__ == "__main__":
	main()
