"""B站 view API 客户端测试."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import requests

from wgmm_monitor.clients.bilibili_api import BilibiliApiClient, extract_bvid
from wgmm_monitor.runtime_logger import RuntimeLogger


def make_client() -> tuple[BilibiliApiClient, Path]:
	"""组装测试用 view API 客户端 (无请求间隔)."""
	tmp = Path(tempfile.mkdtemp())
	logger = RuntimeLogger(tmp / "urls.log", tmp / "critical.log", dev_mode=True)
	client = BilibiliApiClient(logger)
	client.REQUEST_INTERVAL = 0
	return client, tmp


class FakeResponse:
	"""模拟 requests 成功响应."""

	def __init__(self, payload: dict) -> None:
		"""保存返回体."""
		self._payload = payload

	def raise_for_status(self) -> None:
		"""成功响应不抛异常."""

	def json(self) -> dict:
		"""返回 JSON 体."""
		return self._payload


class ExtractBvidTest(unittest.TestCase):
	"""验证 bvid 提取."""

	def test_extract_from_plain_url(self) -> None:
		self.assertEqual(
			extract_bvid("https://www.bilibili.com/video/BV1xx411c7mu"),
			"BV1xx411c7mu",
		)

	def test_extract_from_url_with_page(self) -> None:
		self.assertEqual(
			extract_bvid("https://www.bilibili.com/video/BV1GJ411x7h7?p=3"),
			"BV1GJ411x7h7",
		)

	def test_invalid_returns_none(self) -> None:
		self.assertIsNone(extract_bvid("https://example.com/foo"))
		self.assertIsNone(extract_bvid(""))


class FetchViewTest(unittest.TestCase):
	"""验证 view API 请求与缓存."""

	def test_success_returns_data(self) -> None:
		client, _ = make_client()
		payload = {"code": 0, "data": {"ctime": 123}}
		with mock.patch(
			"wgmm_monitor.clients.bilibili_api.requests.get",
			return_value=FakeResponse(payload),
		) as get:
			data = client.fetch_view("BV1abc")
			self.assertEqual(data, {"ctime": 123})
			get.assert_called_once()

	def test_cache_avoids_second_request(self) -> None:
		client, _ = make_client()
		payload = {"code": 0, "data": {"ctime": 123}}
		with mock.patch(
			"wgmm_monitor.clients.bilibili_api.requests.get",
			return_value=FakeResponse(payload),
		) as get:
			client.fetch_view("BV1abc")
			client.fetch_view("BV1abc")
			get.assert_called_once()

	def test_non_zero_code_returns_none(self) -> None:
		client, _ = make_client()
		payload = {"code": -404, "message": "啥都木有"}
		with mock.patch(
			"wgmm_monitor.clients.bilibili_api.requests.get",
			return_value=FakeResponse(payload),
		):
			self.assertIsNone(client.fetch_view("BV1miss"))

	def test_request_exception_returns_none(self) -> None:
		client, _ = make_client()
		with mock.patch(
			"wgmm_monitor.clients.bilibili_api.requests.get",
			side_effect=requests.RequestException("boom"),
		):
			self.assertIsNone(client.fetch_view("BV1err"))


class CtimeSelectionTest(unittest.TestCase):
	"""验证单 P/多 P 的 ctime 选择."""

	def test_single_part_uses_data_ctime(self) -> None:
		client, _ = make_client()
		client._cache["BV1s"] = {"ctime": 555, "pages": [{"page": 1, "ctime": 555}]}
		self.assertEqual(client.get_ctime("BV1s"), 555)
		self.assertEqual(client.get_part_ctimes("BV1s"), [555])

	def test_multi_part_matches_page(self) -> None:
		client, _ = make_client()
		client._cache["BV1m"] = {
			"ctime": 100,
			"pages": [
				{"page": 1, "ctime": 100},
				{"page": 2, "ctime": 200},
			],
		}
		self.assertEqual(client.get_ctime("BV1m", page=2), 200)
		self.assertEqual(client.get_part_ctimes("BV1m"), [100, 200])

	def test_failure_yields_empty(self) -> None:
		client, _ = make_client()
		client._cache["BV1x"] = None
		self.assertIsNone(client.get_ctime("BV1x"))
		self.assertEqual(client.get_part_ctimes("BV1x"), [])


if __name__ == "__main__":
	unittest.main()
