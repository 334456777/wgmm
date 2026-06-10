"""历史发布时间服务测试."""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from wgmm_monitor.models import AppConfig, RuntimePaths, YtDlpResult
from wgmm_monitor.runtime_logger import RuntimeLogger
from wgmm_monitor.services.history import HistoryService
from wgmm_monitor.stores.history_store import HistoryStore


class FakeBilibiliService:
	"""测试用 B站服务: 列表抓取与 view API 都按脚本返回."""

	def __init__(
		self,
		upload_times: dict[str, int | None] | None = None,
		listing_success: bool = True,
		ctimes_by_bvid: dict[str, list[int]] | None = None,
	) -> None:
		self.upload_times = upload_times or {}
		self.listing_success = listing_success
		self.ctimes_by_bvid = ctimes_by_bvid or {}
		self.requested_bvids: list[str] = []

	def get_video_upload_time(self, url: str) -> int | None:
		return self.upload_times.get(url)

	def run_yt_dlp(self, command_args: list[str], timeout: int = 300) -> YtDlpResult:
		_ = command_args
		_ = timeout
		return YtDlpResult(self.listing_success)

	def get_bvid_part_ctimes(self, bvid: str) -> list[int]:
		self.requested_bvids.append(bvid)
		return self.ctimes_by_bvid.get(bvid, [])


def make_paths(root: Path) -> RuntimePaths:
	"""创建落在临时目录内的运行时路径."""
	return RuntimePaths(
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


def make_service(
	root: Path,
	bilibili: FakeBilibiliService,
	dev_mode: bool = False,
) -> tuple[HistoryService, HistoryStore]:
	"""组装历史服务及其真实存储."""
	config = AppConfig(
		gist_id="g",
		github_token="t",
		bilibili_uid="1",
		bark_device_key="k",
		bark_app_title="标题",
	)
	paths = make_paths(root)
	logger = RuntimeLogger(paths.log_file, paths.critical_log_file, dev_mode=True)
	store = HistoryStore(paths.mtime_file, paths.miss_history_file, logger, dev_mode)
	service = HistoryService(config, paths, bilibili, store, logger, dev_mode=dev_mode)
	return service, store


def write_info_json(directory: Path, name: str, payload: dict) -> None:
	"""在临时 info 目录写入一个 info.json."""
	directory.mkdir(exist_ok=True)
	(directory / f"{name}.info.json").write_text(json.dumps(payload), encoding="utf-8")


class SaveRealUploadTimestampsTest(unittest.TestCase):
	"""验证新视频真实时间戳保存."""

	def test_empty_urls_is_noop(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			service, _store = make_service(Path(tmp), FakeBilibiliService())

			service.save_real_upload_timestamps(set())

			self.assertFalse((Path(tmp) / "mtime.txt").exists())

	def test_dev_mode_does_not_write(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			bilibili = FakeBilibiliService(upload_times={"u1": 100})
			service, _store = make_service(Path(tmp), bilibili, dev_mode=True)

			with contextlib.redirect_stdout(io.StringIO()):
				service.save_real_upload_timestamps({"u1"})

			self.assertFalse((Path(tmp) / "mtime.txt").exists())

	def test_missing_mtime_with_failed_generation_still_appends(self) -> None:
		"""mtime.txt 无法生成时仍保存时间戳 (告警不阻断)."""
		with tempfile.TemporaryDirectory() as tmp:
			root = Path(tmp)
			bilibili = FakeBilibiliService(
				upload_times={"u1": 100},
				listing_success=False,
			)
			service, _store = make_service(root, bilibili)

			out = io.StringIO()
			with contextlib.redirect_stdout(out):
				service.save_real_upload_timestamps({"u1"})

			self.assertIn("无法创建 mtime.txt", out.getvalue())
			self.assertEqual(
				(root / "mtime.txt").read_text(encoding="utf-8"),
				"100\n",
			)

	def test_appends_resolved_timestamps_and_skips_failures(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			root = Path(tmp)
			(root / "mtime.txt").write_text("50\n", encoding="utf-8")
			bilibili = FakeBilibiliService(upload_times={"u1": 100, "u2": None})
			service, _store = make_service(root, bilibili)

			with contextlib.redirect_stdout(io.StringIO()):
				service.save_real_upload_timestamps({"u1", "u2"})

			self.assertEqual(
				(root / "mtime.txt").read_text(encoding="utf-8"),
				"50\n100\n",
			)


class GenerateMtimeFileTest(unittest.TestCase):
	"""验证 mtime.txt 保障逻辑."""

	def test_dev_mode_without_file_short_circuits(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			service, _store = make_service(Path(tmp), FakeBilibiliService(), dev_mode=True)

			self.assertTrue(service.generate_mtime_file("test"))

	def test_existing_non_empty_file_returns_true(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			root = Path(tmp)
			(root / "mtime.txt").write_text("100\n", encoding="utf-8")
			service, _store = make_service(root, FakeBilibiliService())

			self.assertTrue(service.generate_mtime_file("test"))

	def test_three_failed_attempts_log_critical(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			bilibili = FakeBilibiliService(listing_success=False)
			service, _store = make_service(Path(tmp), bilibili)

			out = io.StringIO()
			with contextlib.redirect_stdout(out):
				self.assertFalse(service.generate_mtime_file("test"))

			self.assertIn("3 次尝试仍无法生成", out.getvalue())


class CreateMtimeFromInfoJsonTest(unittest.TestCase):
	"""验证从 info.json + view API 重建 mtime.txt."""

	def test_success_writes_sorted_unique_bvid_ctimes(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			root = Path(tmp)
			bilibili = FakeBilibiliService(
				ctimes_by_bvid={"BV1abc": [300, 100], "BV1xyz": [200]},
			)
			service, _store = make_service(root, bilibili)
			info_dir = root / "temp_info_json"
			write_info_json(info_dir, "a", {"id": "BV1abc"})
			write_info_json(info_dir, "b", {"webpage_url": "https://x/BV1xyz"})
			# 同一 BV 的重复 info.json 与坏文件都应被跳过
			write_info_json(info_dir, "c", {"id": "BV1abc"})
			info_dir.mkdir(exist_ok=True)
			(info_dir / "bad.info.json").write_text("{broken", encoding="utf-8")

			with (
				mock.patch("wgmm_monitor.services.history.shutil.which", return_value=None),
				contextlib.redirect_stdout(io.StringIO()),
			):
				self.assertTrue(service.create_mtime_from_info_json())

			self.assertEqual(
				(root / "mtime.txt").read_text(encoding="utf-8"),
				"100\n200\n300\n",
			)
			self.assertEqual(sorted(bilibili.requested_bvids), ["BV1abc", "BV1xyz"])
			self.assertFalse(info_dir.exists())
			self.assertFalse((root / "temp_timestamps.txt").exists())

	def test_system_sort_path_writes_sorted_file(self) -> None:
		"""系统 sort 可用时走外部排序分支."""
		with tempfile.TemporaryDirectory() as tmp:
			root = Path(tmp)
			bilibili = FakeBilibiliService(ctimes_by_bvid={"BV1abc": [300, 100]})
			service, _store = make_service(root, bilibili)
			write_info_json(root / "temp_info_json", "a", {"id": "BV1abc"})

			with contextlib.redirect_stdout(io.StringIO()):
				self.assertTrue(service.create_mtime_from_info_json())

			self.assertEqual(
				(root / "mtime.txt").read_text(encoding="utf-8"),
				"100\n300\n",
			)

	def test_system_sort_failure_falls_back_to_memory_sort(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			root = Path(tmp)
			bilibili = FakeBilibiliService(ctimes_by_bvid={"BV1abc": [300, 100]})
			service, _store = make_service(root, bilibili)
			write_info_json(root / "temp_info_json", "a", {"id": "BV1abc"})

			with (
				mock.patch(
					"wgmm_monitor.services.history.subprocess.run",
					side_effect=OSError("sort 不可用"),
				),
				contextlib.redirect_stdout(io.StringIO()),
			):
				self.assertTrue(service.create_mtime_from_info_json())

			self.assertEqual(
				(root / "mtime.txt").read_text(encoding="utf-8"),
				"100\n300\n",
			)

	def test_unwritable_mtime_reports_and_cleans_up(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			root = Path(tmp)
			(root / "mtime.txt").mkdir()
			bilibili = FakeBilibiliService(ctimes_by_bvid={"BV1abc": [100]})
			service, _store = make_service(root, bilibili)
			write_info_json(root / "temp_info_json", "a", {"id": "BV1abc"})

			out = io.StringIO()
			with contextlib.redirect_stdout(out):
				self.assertFalse(service.create_mtime_from_info_json())

			self.assertIn("创建 mtime.txt 时出错", out.getvalue())
			self.assertFalse((root / "temp_info_json").exists())

	def test_listing_failure_returns_false(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			bilibili = FakeBilibiliService(listing_success=False)
			service, _store = make_service(Path(tmp), bilibili)

			with contextlib.redirect_stdout(io.StringIO()):
				self.assertFalse(service.create_mtime_from_info_json())

	def test_no_valid_timestamps_returns_false(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			root = Path(tmp)
			bilibili = FakeBilibiliService(ctimes_by_bvid={"BV1abc": []})
			service, _store = make_service(root, bilibili)
			write_info_json(root / "temp_info_json", "a", {"id": "BV1abc"})

			with contextlib.redirect_stdout(io.StringIO()):
				self.assertFalse(service.create_mtime_from_info_json())

			self.assertFalse((root / "mtime.txt").exists())


if __name__ == "__main__":
	unittest.main()
