"""WGMM 调频服务测试."""

from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from wgmm_monitor.models import WgmmConfig
from wgmm_monitor.runtime_logger import RuntimeLogger
from wgmm_monitor.services.frequency import FrequencyService
from wgmm_monitor.stores.config_store import ConfigStore
from wgmm_monitor.stores.history_store import HistoryStore
from wgmm_monitor.wgmm.constants import FALLBACK_INTERVAL


class FakeHistoryService:
	"""测试用历史服务: 直接控制 mtime 生成结果."""

	def __init__(self, generate_success: bool = True) -> None:
		self.generate_success = generate_success
		self.calls: list[str] = []

	def generate_mtime_file(self, context: str = "") -> bool:
		self.calls.append(context)
		return self.generate_success


def make_service(
	root: Path,
	dev_mode: bool = False,
	generate_success: bool = True,
	config: WgmmConfig | None = None,
) -> tuple[FrequencyService, FakeHistoryService, Path]:
	"""组装调频服务及其真实存储."""
	logger = RuntimeLogger(root / "u.log", root / "c.log", dev_mode=True)
	config = config or WgmmConfig()
	config_store = ConfigStore(root / "wgmm_config.json", logger, dev_mode=dev_mode)
	history_store = HistoryStore(
		root / "mtime.txt",
		root / "miss_history.txt",
		logger,
		dev_mode=dev_mode,
	)
	history_service = FakeHistoryService(generate_success=generate_success)
	service = FrequencyService(
		config,
		config_store,
		history_store,
		history_service,  # type: ignore[arg-type]
		logger,
		dev_mode=dev_mode,
	)
	return service, history_service, root / "wgmm_config.json"


def write_weekly_events(root: Path, count: int = 30) -> None:
	"""写入间隔一周的合成正向事件."""
	now = int(time.time())
	events = sorted(now - i * 604800 for i in range(1, count + 1))
	(root / "mtime.txt").write_text("".join(f"{e}\n" for e in events), encoding="utf-8")


class FrequencyServiceTest(unittest.TestCase):
	"""验证调频服务的数据准备与决策编排."""

	def test_missing_mtime_and_failed_generation_uses_fallback(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			root = Path(tmp)
			service, history, config_path = make_service(root, generate_success=False)

			decision = service.adjust_check_frequency()

			self.assertEqual(decision.final_frequency_sec, float(FALLBACK_INTERVAL))
			self.assertEqual(history.calls, ["adjust_check_frequency"])
			self.assertIn("回退", decision.log_message)
			self.assertTrue(config_path.exists())

	def test_learning_mode_with_few_events(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			root = Path(tmp)
			# 两个事件间隔需大于 600s 聚合阈值, 才会保留为两条正向事件
			(root / "mtime.txt").write_text("100\n1000\n", encoding="utf-8")
			service, _history, config_path = make_service(root)

			decision = service.adjust_check_frequency()

			self.assertTrue(decision.learning_mode)
			self.assertEqual(decision.positive_count, 2)
			self.assertTrue(config_path.exists())

	def test_normal_flow_persists_config_and_miss(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			root = Path(tmp)
			write_weekly_events(root)
			config = WgmmConfig(is_manual_run=False)
			service, _history, config_path = make_service(root, config=config)

			decision = service.adjust_check_frequency(found_new_content=False)

			self.assertFalse(decision.learning_mode)
			self.assertGreater(decision.final_frequency_sec, 0)
			self.assertTrue(decision.should_save_miss)
			self.assertTrue((root / "miss_history.txt").exists())
			self.assertTrue(config_path.exists())
			self.assertEqual(service.get_next_check_time(), decision.next_check_time)

	def test_manual_first_run_does_not_record_miss(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			root = Path(tmp)
			write_weekly_events(root)
			service, _history, _config_path = make_service(root)

			decision = service.adjust_check_frequency(found_new_content=False)

			self.assertFalse(decision.should_save_miss)
			self.assertFalse((root / "miss_history.txt").exists())

	def test_found_new_content_skips_miss(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			root = Path(tmp)
			write_weekly_events(root)
			config = WgmmConfig(is_manual_run=False)
			service, _history, _config_path = make_service(root, config=config)

			decision = service.adjust_check_frequency(found_new_content=True)

			self.assertFalse(decision.should_save_miss)
			self.assertFalse((root / "miss_history.txt").exists())

	def test_dev_mode_does_not_persist(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			root = Path(tmp)
			write_weekly_events(root)
			service, _history, config_path = make_service(root, dev_mode=True)

			decision = service.adjust_check_frequency()

			self.assertFalse(config_path.exists())
			self.assertFalse((root / "miss_history.txt").exists())
			self.assertGreater(decision.final_frequency_sec, 0)

	def test_prune_threshold_triggers_prune_path(self) -> None:
		"""正负事件数达到 PRUNE_THRESHOLD 时走剪枝分支 (近期数据应原样保留)."""
		with tempfile.TemporaryDirectory() as tmp:
			root = Path(tmp)
			now = int(time.time())
			events = sorted(now - i * 3600 for i in range(1, 1001))
			(root / "mtime.txt").write_text(
				"".join(f"{e}\n" for e in events), encoding="utf-8"
			)
			misses = sorted(now - i * 1800 for i in range(1, 1001))
			(root / "miss_history.txt").write_text(
				"".join(f"{m}\n" for m in misses), encoding="utf-8"
			)
			config = WgmmConfig(is_manual_run=False)
			service, _history, _config_path = make_service(root, config=config)

			decision = service.adjust_check_frequency(found_new_content=True)

			self.assertGreaterEqual(decision.positive_count, 1000)
			self.assertGreaterEqual(decision.negative_count, 900)


if __name__ == "__main__":
	unittest.main()
