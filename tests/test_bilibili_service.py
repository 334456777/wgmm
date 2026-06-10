"""B站检测服务测试."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from wgmm_monitor.models import AppConfig, YtDlpResult
from wgmm_monitor.runtime_logger import RuntimeLogger
from wgmm_monitor.services.bilibili import BilibiliService


class FakeYtDlpClient:
	"""测试用 yt-dlp 客户端."""

	def __init__(self, successful_urls: set[str]) -> None:
		"""保存模拟成功的 URL 集合."""
		self.successful_urls = successful_urls
		self.probed_urls: list[str] = []
		self.last_duration = 0.0
		self.normal_duration = 60.0

	def run(self, command_args: list[str], timeout: int = 300) -> YtDlpResult:
		"""按 URL 返回模拟执行结果."""
		_ = timeout
		url = command_args[-1]
		self.probed_urls.append(url)
		return YtDlpResult(url in self.successful_urls)


class FakeBilibiliApiClient:
	"""测试用 view API 客户端, 按 bvid 返回预设 data 字典."""

	def __init__(self, data_by_bvid: dict[str, dict | None]) -> None:
		"""保存 bvid -> data 映射并记录请求过的 bvid."""
		self.data_by_bvid = data_by_bvid
		self.fetched_bvids: list[str] = []
		self._cache: dict[str, dict | None] = {}

	def fetch_view(self, bvid: str) -> dict | None:
		"""模拟带缓存的 view API 请求."""
		if bvid in self._cache:
			return self._cache[bvid]
		self.fetched_bvids.append(bvid)
		data = self.data_by_bvid.get(bvid)
		self._cache[bvid] = data
		return data

	def get_ctime(self, bvid: str, page: int = 1) -> int | None:
		"""复用真实客户端的分 P 选择逻辑."""
		data = self.fetch_view(bvid)
		if not data:
			return None
		pages = data.get("pages") or []
		if len(pages) > 1:
			for part in pages:
				if part.get("page") == page and part.get("ctime"):
					return int(part["ctime"])
		ctime = data.get("ctime")
		return int(ctime) if ctime else None

	def get_part_ctimes(self, bvid: str) -> list[int]:
		"""返回某 BV 全部真实 ctime."""
		data = self.fetch_view(bvid)
		if not data:
			return []
		pages = data.get("pages") or []
		if len(pages) > 1:
			ctimes = [int(p["ctime"]) for p in pages if p.get("ctime")]
			if ctimes:
				return ctimes
		ctime = data.get("ctime")
		return [int(ctime)] if ctime else []


def make_service(
	client: FakeYtDlpClient,
	root: Path,
	api_client: FakeBilibiliApiClient | None = None,
) -> BilibiliService:
	"""组装测试用 B站服务."""
	config = AppConfig(
		gist_id="",
		github_token="",
		bilibili_uid="1",
		bark_device_key="",
		bark_app_title="",
	)
	logger = RuntimeLogger(root / "urls.log", root / "critical.log", dev_mode=True)
	api_client = api_client or FakeBilibiliApiClient({})
	return BilibiliService(config, client, api_client, root / "cookies.txt", logger)


class BilibiliServiceTest(unittest.TestCase):
	"""验证 B站预检查逻辑."""

	def test_part_precheck_uses_local_known_urls(self) -> None:
		"""Gist 滞后但本地已知时, 不重复预测旧分片."""
		with tempfile.TemporaryDirectory() as tmp:
			base_url = "https://www.bilibili.com/video/BV1test"
			client = FakeYtDlpClient({f"{base_url}?p=3"})
			service = make_service(client, Path(tmp))

			found = service.check_potential_new_parts(
				[f"{base_url}?p=2"],
				{f"{base_url}?p=3"},
			)

			self.assertFalse(found)
			self.assertEqual(client.probed_urls, [f"{base_url}?p=4"])

	def test_part_precheck_detects_next_unknown_part(self) -> None:
		"""完整已知状态之后存在下一分片时, 返回发现新内容."""
		with tempfile.TemporaryDirectory() as tmp:
			base_url = "https://www.bilibili.com/video/BV1test"
			client = FakeYtDlpClient({f"{base_url}?p=4"})
			service = make_service(client, Path(tmp))

			found = service.check_potential_new_parts(
				[f"{base_url}?p=2"],
				{f"{base_url}?p=3"},
			)

			self.assertTrue(found)
			self.assertEqual(client.probed_urls, [f"{base_url}?p=4", f"{base_url}?p=5"])


class UploadTimeTest(unittest.TestCase):
	"""验证基于 view API 的真实投稿时间获取."""

	def test_single_part_uses_data_ctime(self) -> None:
		"""单 P 视频返回 data.ctime."""
		with tempfile.TemporaryDirectory() as tmp:
			api = FakeBilibiliApiClient(
				{"BV1single": {"ctime": 1721363639, "pages": [{"page": 1}]}}
			)
			service = make_service(FakeYtDlpClient(set()), Path(tmp), api)

			ts = service.get_video_upload_time("https://www.bilibili.com/video/BV1single")

			self.assertEqual(ts, 1721363639)

	def test_multi_part_matches_page_ctime(self) -> None:
		"""多 P 视频按 ?p= 匹配对应分 P 的 ctime."""
		with tempfile.TemporaryDirectory() as tmp:
			api = FakeBilibiliApiClient(
				{
					"BV1multi": {
						"ctime": 1000,
						"pages": [
							{"page": 1, "ctime": 1000},
							{"page": 2, "ctime": 2000},
						],
					}
				}
			)
			service = make_service(FakeYtDlpClient(set()), Path(tmp), api)

			ts = service.get_video_upload_time(
				"https://www.bilibili.com/video/BV1multi?p=2"
			)

			self.assertEqual(ts, 2000)

	def test_api_failure_returns_none(self) -> None:
		"""API 返回 None 时上游获取真实时间为 None (上层跳过)."""
		with tempfile.TemporaryDirectory() as tmp:
			api = FakeBilibiliApiClient({"BV1fail": None})
			service = make_service(FakeYtDlpClient(set()), Path(tmp), api)

			ts = service.get_video_upload_time("https://www.bilibili.com/video/BV1fail")

			self.assertIsNone(ts)

	def test_invalid_url_returns_none(self) -> None:
		"""无法解析 bvid 时返回 None."""
		with tempfile.TemporaryDirectory() as tmp:
			service = make_service(FakeYtDlpClient(set()), Path(tmp))

			self.assertIsNone(service.get_video_upload_time("https://example.com/foo"))

	def test_same_bvid_fetched_once(self) -> None:
		"""同一 BV 的多个分 P 只请求一次 view API (缓存生效)."""
		with tempfile.TemporaryDirectory() as tmp:
			api = FakeBilibiliApiClient(
				{
					"BV1dup": {
						"ctime": 1000,
						"pages": [
							{"page": 1, "ctime": 1000},
							{"page": 2, "ctime": 2000},
						],
					}
				}
			)
			service = make_service(FakeYtDlpClient(set()), Path(tmp), api)

			service.get_video_upload_time("https://www.bilibili.com/video/BV1dup?p=1")
			service.get_video_upload_time("https://www.bilibili.com/video/BV1dup?p=2")

			self.assertEqual(api.fetched_bvids, ["BV1dup"])


class ScriptedYtDlpClient:
	"""测试用 yt-dlp 客户端: 按调用顺序返回预设结果."""

	def __init__(self, results: list[YtDlpResult]) -> None:
		"""保存结果队列."""
		self.results = list(results)
		self.commands: list[list[str]] = []
		self.last_duration = 0.0
		self.normal_duration = 60.0

	def run(self, command_args: list[str], timeout: int = 300) -> YtDlpResult:
		"""依次弹出结果, 用尽后重复最后一个."""
		_ = timeout
		self.commands.append(list(command_args))
		if len(self.results) > 1:
			return self.results.pop(0)
		return self.results[0]


class QuickPrecheckTest(unittest.TestCase):
	"""验证第二层快速 ID 检查."""

	def test_empty_memory_urls_triggers_full_check(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			client = ScriptedYtDlpClient([YtDlpResult(True, stdout="BV1x")])
			service = make_service(client, Path(tmp))

			self.assertTrue(service.quick_precheck([], set()))
			self.assertEqual(client.commands, [])

	def test_failed_listing_triggers_full_check(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			client = ScriptedYtDlpClient([YtDlpResult(False)])
			service = make_service(client, Path(tmp))

			self.assertTrue(service.quick_precheck(["https://x/BV1old"], set()))

	def test_known_latest_id_means_no_update(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			client = ScriptedYtDlpClient([YtDlpResult(True, stdout="BV1old")])
			service = make_service(client, Path(tmp))

			found = service.quick_precheck(
				["https://x/BV1old"],
				{"https://x/BV1known"},
			)

			self.assertFalse(found)

	def test_unknown_latest_id_means_update(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			client = ScriptedYtDlpClient([YtDlpResult(True, stdout="BV1brand")])
			service = make_service(client, Path(tmp))

			self.assertTrue(service.quick_precheck(["https://x/BV1old"], set()))


class PartPrecheckEdgeTest(unittest.TestCase):
	"""验证第一层分片预检查的边界分支."""

	def test_empty_known_urls_skips(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			service = make_service(FakeYtDlpClient(set()), Path(tmp))

			self.assertFalse(service.check_potential_new_parts([], set()))

	def test_urls_without_part_param_are_ignored(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			client = FakeYtDlpClient(set())
			service = make_service(client, Path(tmp))

			found = service.check_potential_new_parts(
				["https://x/BV1plain", "https://x/BV1bad?p=abc"],
				set(),
			)

			self.assertFalse(found)
			self.assertEqual(client.probed_urls, [])

	def test_part_one_only_is_not_probed(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			client = FakeYtDlpClient(set())
			service = make_service(client, Path(tmp))

			found = service.check_potential_new_parts(["https://x/BV1a?p=1"], set())

			self.assertFalse(found)
			self.assertEqual(client.probed_urls, [])

	def test_consecutive_new_parts_are_expanded(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			base = "https://x/BV1a"
			client = FakeYtDlpClient({f"{base}?p=3", f"{base}?p=4"})
			service = make_service(client, Path(tmp))

			found = service.check_potential_new_parts([f"{base}?p=2"], set())

			self.assertTrue(found)
			self.assertEqual(
				client.probed_urls,
				[f"{base}?p=3", f"{base}?p=4", f"{base}?p=5"],
			)


class FetchAndExpandTest(unittest.TestCase):
	"""验证完整扫描与分片展开."""

	def test_fetch_video_list_passes_uid(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			client = ScriptedYtDlpClient([YtDlpResult(True, stdout="a\nb")])
			service = make_service(client, Path(tmp))

			result = service.fetch_video_list()

			self.assertTrue(result.success)
			self.assertIn("https://space.bilibili.com/1/video", client.commands[0])

	def test_get_video_parts_splits_lines(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			client = ScriptedYtDlpClient(
				[YtDlpResult(True, stdout="https://x/p1\n\nhttps://x/p2\n")]
			)
			service = make_service(client, Path(tmp))

			self.assertEqual(
				service.get_video_parts("https://x/BV1a"),
				["https://x/p1", "https://x/p2"],
			)

	def test_get_video_parts_failure_returns_empty(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			client = ScriptedYtDlpClient([YtDlpResult(False)])
			service = make_service(client, Path(tmp))

			self.assertEqual(service.get_video_parts("https://x/BV1a"), [])

	def test_parallel_expansion_merges_parts(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			client = ScriptedYtDlpClient([YtDlpResult(True, stdout="part")])
			service = make_service(client, Path(tmp))

			parts = service.get_all_videos_parallel(["u1", "u2", "u3"])

			self.assertEqual(parts, ["part", "part", "part"])


class UploadTimeEdgeTest(unittest.TestCase):
	"""验证投稿时间获取的参数解析边界."""

	def test_invalid_page_param_defaults_to_one(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			api = FakeBilibiliApiClient({"BV1abc": {"ctime": 123, "pages": []}})
			service = make_service(FakeYtDlpClient(set()), Path(tmp), api)

			ts = service.get_video_upload_time("https://x/BV1abc?p=oops")

			self.assertEqual(ts, 123)


if __name__ == "__main__":
	unittest.main()
