"""生产实现对账: 集成 hazard cap 后的真实 decide 必须复现冻结候选 k=130."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import DEFAULT_PARAMS, load_events, simulate, span_fraction  # noqa: E402


def main() -> None:
	"""逐检查对账."""
	events = load_events()
	t0 = span_fraction(events, 0.30)
	t_end = events[-1] + 1

	prod = simulate(events, t0, t_end, "production")
	params = dict(DEFAULT_PARAMS)
	params.update({"sqrt_cap_k": 130.0, "hazard_floor_sec": 1800.0})
	frozen = simulate(events, t0, t_end, params)

	same_checks = prod["check_times"] == frozen["check_times"]
	same_records = prod["records"] == frozen["records"]
	print(f"checks: prod={len(prod['check_times'])} frozen={len(frozen['check_times'])}")
	print(f"check sequences identical: {same_checks}")
	print(f"delay records identical: {same_records}")
	if not same_checks:
		for i, (a, b) in enumerate(
			zip(prod["check_times"], frozen["check_times"], strict=False)
		):
			if a != b:
				print(f"first divergence at check #{i}: prod={a} frozen={b}")
				break
		sys.exit(1)


if __name__ == "__main__":
	main()
