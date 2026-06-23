"""主监控服务测试."""

from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from wgmm_monitor.models import RuntimePaths, YtDlpResult
from wgmm_monitor.runtime_logger import RuntimeLogger
from wgmm_monitor.services.monitor import MonitorService


class FakeGistClient:
	"""测试用 Gist 客户端."""

	def __init__(
		self,
		success: bool = True,
		urls: list[str] | None = None,
		write_success: bool = True,
	) -> None:
		self.success = success
		self.urls = urls or []
		self.write_success = write_success
		self.written: list[set[str]] = []

	def fetch_urls(self) -> tuple[bool, list[str], str]:
		if self.success:
			return True, list(self.urls), ""
		return False, [], "Gist 测试失败"

	def write_new_urls(self, urls: set[str]) -> tuple[bool, str]:
		self.written.append(set(urls))
		if self.write_success:
			return True, ""
		return False, "写入失败"


class RaisingGistClient:
	"""测试用 Gist 客户端: fetch 时抛出指定异常."""

	def __init__(self, exc: BaseException) -> None:
		self.exc = exc

	def fetch_urls(self) -> tuple[bool, list[str], str]:
		raise self.exc

	def write_new_urls(self, urls: set[str]) -> tuple[bool, str]:
		_ = urls
		return True, ""


class FakeUrlStore:
	"""测试用 URL 存储."""

	def __init__(self, urls: set[str] | None = None) -> None:
		self.urls = urls or set()
		self.saved: list[set[str]] = []

	def load(self) -> set[str]:
		return set(self.urls)

	def save(self, known_urls: set[str]) -> None:
		self.saved.append(set(known_urls))
		self.urls = set(known_urls)


class FakeYtDlpClient:
	"""测试用 yt-dlp 耗时对象."""

	last_duration = 1.0
	normal_duration = 60.0


class FakeBilibiliService:
	"""测试用 B站服务."""

	def __init__(
		self,
		found_parts: bool = False,
		found_videos: bool = False,
		fetch_results: list[YtDlpResult] | None = None,
		all_parts: list[str] | None = None,
		dynamic_video_urls: list[str] | None = None,
	) -> None:
		self.found_parts = found_parts
		self.found_videos = found_videos
		self.fetch_results = fetch_results or []
		self.all_parts = all_parts or []
		self.dynamic_video_urls = dynamic_video_urls or []
		self.ytdlp_client = FakeYtDlpClient()
		self.fetch_count = 0

	def check_potential_new_parts(
		self,
		memory_urls: list[str],
		known_urls: set[str],
	) -> bool:
		_ = memory_urls
		_ = known_urls
		return self.found_parts

	def quick_precheck(self, memory_urls: list[str], known_urls: set[str]) -> bool:
		_ = memory_urls
		_ = known_urls
		return self.found_videos

	def fetch_video_list(self) -> YtDlpResult:
		result = self.fetch_results[min(self.fetch_count, len(self.fetch_results) - 1)]
		self.fetch_count += 1
		return result

	def fetch_dynamic_video_urls(self, max_pages: int = 6) -> list[str]:
		_ = max_pages
		return list(self.dynamic_video_urls)

	def get_all_videos_parallel(self, video_urls: list[str]) -> list[str]:
		_ = video_urls
		return list(self.all_parts)


class FakeHistoryService:
	"""测试用历史服务."""

	def __init__(self) -> None:
		self.saved_urls: list[set[str]] = []

	def save_real_upload_timestamps(self, new_urls: set[str]) -> None:
		self.saved_urls.append(set(new_urls))


class FakeFrequencyService:
	"""测试用调频服务."""

	def __init__(self, next_check_time: int = 0) -> None:
		self.calls: list[bool] = []
		self.next_check_time = next_check_time

	def get_next_check_time(self) -> int:
		return self.next_check_time

	def adjust_check_frequency(
		self,
		found_new_content: bool = False,
		last_ytdlp_duration: float = 0.0,
		normal_ytdlp_duration: float = 60.0,
	) -> None:
		_ = last_ytdlp_duration
		_ = normal_ytdlp_duration
		self.calls.append(found_new_content)


class FakeNotificationService:
	"""测试用通知服务."""

	def __init__(self, success: bool = True) -> None:
		self.success = success
		self.calls: list[tuple[int, bool]] = []

	def notify_new_videos(self, count: int, has_new_parts: bool = False) -> bool:
		self.calls.append((count, has_new_parts))
		return self.success


def make_service(
	root: Path,
	gist: FakeGistClient,
	bilibili: FakeBilibiliService,
	url_store: FakeUrlStore | None = None,
	history: FakeHistoryService | None = None,
	frequency: FakeFrequencyService | None = None,
	notification: FakeNotificationService | None = None,
	dev_mode: bool = False,
	sleep_log: list[float] | None = None,
) -> tuple[MonitorService, FakeHistoryService, FakeFrequencyService]:
	"""组装测试监控服务."""
	paths = RuntimePaths(
		data_dir=root,
		log_file=root / "urls.log",
		critical_log_file=root / "critical.log",
		wgmm_config_file=root / "wgmm_config.json",
		local_known_file=root / "local_known.txt",
		mtime_file=root / "mtime.txt",
		miss_history_file=root / "miss_history.txt",
		cookies_file=root / "cookies.txt",
		temp_info_dir=root / "temp_info_json",
		temp_timestamps_file=root / "temp_timestamps.txt",
	)
	logger = RuntimeLogger(paths.log_file, paths.critical_log_file, dev_mode=True)
	history = history or FakeHistoryService()
	frequency = frequency or FakeFrequencyService()
	monitor = MonitorService(
		paths,
		gist,
		url_store or FakeUrlStore(),
		bilibili,
		history,
		frequency,
		notification or FakeNotificationService(),
		logger,
		dev_mode=dev_mode,
		sleep_func=(sleep_log.append if sleep_log is not None else lambda _seconds: None),
	)
	return monitor, history, frequency


class MonitorServiceTest(unittest.TestCase):
	"""验证主监控流程分支."""

	def test_no_update_adjusts_frequency_without_full_scan(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			bilibili = FakeBilibiliService(found_parts=False, found_videos=False)
			_monitor, _history, frequency = make_service(
				Path(tmp),
				FakeGistClient(urls=["old"]),
				bilibili,
			)

			_monitor.run_monitor()

			self.assertEqual(frequency.calls, [False])
			self.assertEqual(bilibili.fetch_count, 0)

	def test_new_video_updates_state_and_notifies(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			notification = FakeNotificationService()
			gist = FakeGistClient(urls=["old"])
			bilibili = FakeBilibiliService(
				found_videos=True,
				fetch_results=[YtDlpResult(True, stdout="base")],
				all_parts=["old", "new"],
			)
			_monitor, history, frequency = make_service(
				Path(tmp),
				gist,
				bilibili,
				notification=notification,
			)

			_monitor.run_monitor()

			self.assertEqual(history.saved_urls, [{"new"}])
			self.assertEqual(gist.written, [{"new"}])
			self.assertEqual(notification.calls, [(1, False)])
			self.assertEqual(frequency.calls, [True])

	def test_new_part_without_missing_url_marks_new_content(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			bilibili = FakeBilibiliService(
				found_parts=True,
				found_videos=False,
				fetch_results=[YtDlpResult(True, stdout="base")],
				all_parts=["old"],
			)
			_monitor, _history, frequency = make_service(
				Path(tmp),
				FakeGistClient(urls=["old"]),
				bilibili,
			)

			_monitor.run_monitor()

			self.assertEqual(frequency.calls, [True])

	def test_gist_failure_without_memory_skips_check(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			bilibili = FakeBilibiliService(found_videos=True)
			_monitor, _history, frequency = make_service(
				Path(tmp),
				FakeGistClient(success=False),
				bilibili,
			)

			_monitor.run_monitor()

			self.assertEqual(frequency.calls, [])
			self.assertEqual(bilibili.fetch_count, 0)

	def test_full_scan_retries_after_first_failure(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			bilibili = FakeBilibiliService(
				found_videos=True,
				fetch_results=[
					YtDlpResult(False, stderr="失败"),
					YtDlpResult(True, stdout="base"),
				],
				all_parts=["old", "new"],
			)
			_monitor, _history, frequency = make_service(
				Path(tmp),
				FakeGistClient(urls=["old"]),
				bilibili,
			)

			_monitor.run_monitor()

			self.assertEqual(bilibili.fetch_count, 2)
			self.assertEqual(frequency.calls, [True])

	def test_locally_known_url_is_not_renotified(self) -> None:
		"""Gist backup 滞后但本地已知时, 不重复通知, 调频走 negative."""
		with tempfile.TemporaryDirectory() as tmp:
			notification = FakeNotificationService()
			gist = FakeGistClient(urls=["old"])
			bilibili = FakeBilibiliService(
				found_videos=True,
				fetch_results=[YtDlpResult(True, stdout="base")],
				all_parts=["old", "new"],
			)
			history = FakeHistoryService()
			frequency = FakeFrequencyService()
			_monitor, _history, _frequency = make_service(
				Path(tmp),
				gist,
				bilibili,
				url_store=FakeUrlStore({"old", "new"}),
				history=history,
				frequency=frequency,
				notification=notification,
			)

			_monitor.run_monitor()

			self.assertEqual(notification.calls, [])
			self.assertEqual(gist.written, [])
			self.assertEqual(history.saved_urls, [])
			self.assertEqual(frequency.calls, [False])

	def test_notification_failure_does_not_block_frequency_update(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			bilibili = FakeBilibiliService(
				found_parts=True,
				found_videos=True,
				fetch_results=[YtDlpResult(True, stdout="base")],
				all_parts=["old", "new"],
			)
			_monitor, _history, frequency = make_service(
				Path(tmp),
				FakeGistClient(urls=["old"]),
				bilibili,
				notification=FakeNotificationService(success=False),
			)

			_monitor.run_monitor()

			self.assertEqual(frequency.calls, [True])


class MonitorBranchesTest(unittest.TestCase):
	"""验证主流程的失败与确认分支."""

	def test_full_scan_failure_after_retry_logs_critical(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			bilibili = FakeBilibiliService(
				found_videos=True,
				fetch_results=[YtDlpResult(False, stderr="一直失败")],
			)
			monitor, _history, frequency = make_service(
				Path(tmp),
				FakeGistClient(urls=["old"]),
				bilibili,
				dev_mode=True,
			)

			monitor.run_monitor()

			self.assertEqual(bilibili.fetch_count, 2)
			self.assertEqual(frequency.calls, [False])

	def test_whitespace_video_list_treated_as_empty(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			bilibili = FakeBilibiliService(
				found_videos=True,
				fetch_results=[YtDlpResult(True, stdout="   ")],
			)
			monitor, _history, frequency = make_service(
				Path(tmp),
				FakeGistClient(urls=["old"]),
				bilibili,
				dev_mode=True,
			)

			monitor.run_monitor()

			self.assertEqual(frequency.calls, [False])

	def test_empty_part_expansion_skips_detection(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			bilibili = FakeBilibiliService(
				found_videos=True,
				fetch_results=[YtDlpResult(True, stdout="base")],
				all_parts=[],
			)
			monitor, _history, frequency = make_service(
				Path(tmp),
				FakeGistClient(urls=["old"]),
				bilibili,
			)

			monitor.run_monitor()

			self.assertEqual(frequency.calls, [False])

	def test_quick_check_false_alarm_confirms_no_update(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			bilibili = FakeBilibiliService(
				found_videos=True,
				fetch_results=[YtDlpResult(True, stdout="base")],
				all_parts=["old"],
			)
			monitor, _history, frequency = make_service(
				Path(tmp),
				FakeGistClient(urls=["old"]),
				bilibili,
			)

			monitor.run_monitor()

			self.assertEqual(frequency.calls, [False])

	def test_gist_write_failure_does_not_block_flow(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			gist = FakeGistClient(urls=["old"], write_success=False)
			bilibili = FakeBilibiliService(
				found_videos=True,
				fetch_results=[YtDlpResult(True, stdout="base")],
				all_parts=["old", "new"],
			)
			monitor, history, frequency = make_service(Path(tmp), gist, bilibili)

			monitor.run_monitor()

			self.assertEqual(history.saved_urls, [{"new"}])
			self.assertEqual(frequency.calls, [True])

	def test_keyboard_interrupt_exits_cleanly(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			monitor, _history, _frequency = make_service(
				Path(tmp),
				RaisingGistClient(KeyboardInterrupt()),  # type: ignore[arg-type]
				FakeBilibiliService(),
				dev_mode=True,
			)

			with self.assertRaises(SystemExit) as ctx:
				monitor.run_monitor()

			self.assertEqual(ctx.exception.code, 0)

	def test_oserror_is_caught_and_reported(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			monitor, _history, frequency = make_service(
				Path(tmp),
				RaisingGistClient(OSError("磁盘错误")),  # type: ignore[arg-type]
				FakeBilibiliService(),
				dev_mode=True,
			)

			monitor.run_monitor()

			self.assertEqual(frequency.calls, [])


class WaitForNextCheckTest(unittest.TestCase):
	"""验证等待逻辑分支."""

	def make_waiting_service(
		self,
		root: Path,
		next_check_time: int,
		dev_mode: bool = False,
	) -> tuple[MonitorService, list[float]]:
		"""组装带睡眠记录的监控服务."""
		sleep_log: list[float] = []
		frequency = FakeFrequencyService(next_check_time=next_check_time)
		monitor, _history, _frequency = make_service(
			root,
			FakeGistClient(),
			FakeBilibiliService(),
			frequency=frequency,
			dev_mode=dev_mode,
			sleep_log=sleep_log,
		)
		return monitor, sleep_log

	def test_zero_next_check_starts_immediately(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			monitor, sleep_log = self.make_waiting_service(Path(tmp), 0)

			monitor.wait_for_next_check()

			self.assertEqual(sleep_log, [])

	def test_past_due_returns_without_sleep(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			monitor, sleep_log = self.make_waiting_service(Path(tmp), 1)

			monitor.wait_for_next_check()

			self.assertEqual(sleep_log, [])

	def test_dev_mode_does_not_sleep(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			future = int(time.time()) + 3600
			monitor, sleep_log = self.make_waiting_service(Path(tmp), future, dev_mode=True)

			monitor.wait_for_next_check()

			self.assertEqual(sleep_log, [])

	def test_future_check_sleeps_for_wait_seconds(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			future = int(time.time()) + 3600
			monitor, sleep_log = self.make_waiting_service(Path(tmp), future)

			monitor.wait_for_next_check()

			self.assertEqual(len(sleep_log), 1)
			self.assertGreater(sleep_log[0], 3590)


class CleanupTest(unittest.TestCase):
	"""验证开发模式临时目录清理."""

	def test_dev_mode_removes_temp_dir(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			root = Path(tmp)
			(root / "temp_info_json").mkdir()
			monitor, _history, _frequency = make_service(
				root,
				FakeGistClient(),
				FakeBilibiliService(),
				dev_mode=True,
			)

			monitor.cleanup()

			self.assertFalse((root / "temp_info_json").exists())

	def test_production_mode_keeps_temp_dir(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			root = Path(tmp)
			(root / "temp_info_json").mkdir()
			monitor, _history, _frequency = make_service(
				root,
				FakeGistClient(),
				FakeBilibiliService(),
			)

			monitor.cleanup()

			self.assertTrue((root / "temp_info_json").exists())


if __name__ == "__main__":
	unittest.main()
