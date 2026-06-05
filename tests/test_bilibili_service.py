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


if __name__ == "__main__":
	unittest.main()
