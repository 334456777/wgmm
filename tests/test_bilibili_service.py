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


def make_service(client: FakeYtDlpClient, root: Path) -> BilibiliService:
	"""组装测试用 B站服务."""
	config = AppConfig(
		gist_id="",
		github_token="",
		bilibili_uid="1",
		bark_device_key="",
		bark_app_title="",
	)
	logger = RuntimeLogger(root / "urls.log", root / "critical.log", dev_mode=True)
	return BilibiliService(config, client, root / "cookies.txt", logger)


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


if __name__ == "__main__":
	unittest.main()
