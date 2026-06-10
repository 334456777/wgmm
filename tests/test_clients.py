"""外部客户端测试 (Bark / Gist / yt-dlp), 全部网络与子进程调用均被 mock."""

from __future__ import annotations

import contextlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import requests

from wgmm_monitor.clients.bark import BarkClient
from wgmm_monitor.clients.gist import GistClient
from wgmm_monitor.clients.ytdlp import YtDlpClient
from wgmm_monitor.models import AppConfig
from wgmm_monitor.runtime_logger import RuntimeLogger


def make_config(**overrides: str) -> AppConfig:
	"""创建带默认值的测试配置."""
	values = {
		"gist_id": "gid",
		"github_token": "token",
		"bilibili_uid": "1",
		"bark_device_key": "devkey",
		"bark_app_title": "标题",
	}
	values.update(overrides)
	return AppConfig(**values)  # type: ignore[arg-type]


class BarkClientTest(unittest.TestCase):
	"""验证 Bark 推送 URL 组装与异常处理."""

	def test_success_returns_true(self) -> None:
		client = BarkClient(make_config())
		with mock.patch("wgmm_monitor.clients.bark.requests.get") as get:
			get.return_value = SimpleNamespace(ok=True)

			self.assertTrue(client.send_push("标题", "内容"))

			url = get.call_args.args[0]
			self.assertIn("/devkey/", url)
			self.assertIn("isArchive=1", url)
			self.assertNotIn("level=", url)

	def test_critical_push_includes_all_params(self) -> None:
		client = BarkClient(make_config())
		with mock.patch("wgmm_monitor.clients.bark.requests.get") as get:
			get.return_value = SimpleNamespace(ok=True)

			ok = client.send_push(
				"标题",
				"内容",
				level="critical",
				sound="alarm",
				group="严重错误",
				icon="https://i.example/x.png",
				url="https://example.com",
				call=True,
				volume=8,
			)

			self.assertTrue(ok)
			full_url = get.call_args.args[0]
			for fragment in ("level=critical", "sound=alarm", "call=1", "volume=8"):
				self.assertIn(fragment, full_url)

	def test_volume_ignored_for_non_critical(self) -> None:
		client = BarkClient(make_config())
		with mock.patch("wgmm_monitor.clients.bark.requests.get") as get:
			get.return_value = SimpleNamespace(ok=True)

			client.send_push("标题", "内容", level="timeSensitive", volume=8)

			self.assertNotIn("volume=", get.call_args.args[0])

	def test_request_exception_returns_false(self) -> None:
		client = BarkClient(make_config())
		with (
			mock.patch(
				"wgmm_monitor.clients.bark.requests.get",
				side_effect=requests.RequestException("网络断了"),
			),
			contextlib.redirect_stdout(io.StringIO()) as out,
		):
			self.assertFalse(client.send_push("标题", "内容"))
		self.assertIn("Bark推送失败", out.getvalue())


class GistFetchTest(unittest.TestCase):
	"""验证 Gist 读取分支."""

	def test_missing_gist_id_short_circuits(self) -> None:
		client = GistClient(make_config(gist_id=""))

		success, urls, error = client.fetch_urls()

		self.assertFalse(success)
		self.assertEqual(urls, [])
		self.assertIn("GIST_ID", error)

	def test_missing_token_short_circuits(self) -> None:
		client = GistClient(make_config(github_token=""))

		success, _urls, error = client.fetch_urls()

		self.assertFalse(success)
		self.assertIn("GITHUB_TOKEN", error)

	def test_success_parses_urls(self) -> None:
		client = GistClient(make_config())
		response = mock.Mock()
		response.json.return_value = {
			"files": {"urls.txt": {"content": "https://a\n\n https://b \n"}}
		}
		with mock.patch(
			"wgmm_monitor.clients.gist.requests.get", return_value=response
		) as get:
			success, urls, error = client.fetch_urls()

			self.assertTrue(success)
			self.assertEqual(urls, ["https://a", "https://b"])
			self.assertEqual(error, "")
			headers = get.call_args.kwargs["headers"]
			self.assertEqual(headers["Authorization"], "Bearer token")

	def test_missing_urls_txt_reports_error(self) -> None:
		client = GistClient(make_config())
		response = mock.Mock()
		response.json.return_value = {"files": {}}
		with mock.patch("wgmm_monitor.clients.gist.requests.get", return_value=response):
			success, _urls, error = client.fetch_urls()

			self.assertFalse(success)
			self.assertIn("urls.txt", error)

	def test_http_error_includes_status_code(self) -> None:
		client = GistClient(make_config())
		response = mock.Mock()
		response.raise_for_status.side_effect = requests.exceptions.HTTPError(
			response=SimpleNamespace(status_code=404)
		)
		with mock.patch("wgmm_monitor.clients.gist.requests.get", return_value=response):
			success, _urls, error = client.fetch_urls()

			self.assertFalse(success)
			self.assertIn("404", error)

	def test_network_error_reported(self) -> None:
		client = GistClient(make_config())
		with mock.patch(
			"wgmm_monitor.clients.gist.requests.get",
			side_effect=requests.RequestException("超时"),
		):
			success, _urls, error = client.fetch_urls()

			self.assertFalse(success)
			self.assertIn("从 Gist 获取数据失败", error)

	def test_bad_json_reported(self) -> None:
		client = GistClient(make_config())
		response = mock.Mock()
		response.json.side_effect = json.JSONDecodeError("bad", "", 0)
		with mock.patch("wgmm_monitor.clients.gist.requests.get", return_value=response):
			success, _urls, _error = client.fetch_urls()

			self.assertFalse(success)


class GistWriteTest(unittest.TestCase):
	"""验证 new.txt 写入分支."""

	def test_empty_set_skips_request(self) -> None:
		client = GistClient(make_config())
		with mock.patch("wgmm_monitor.clients.gist.requests.patch") as patch_call:
			success, error = client.write_new_urls(set())

			self.assertTrue(success)
			self.assertEqual(error, "")
			patch_call.assert_not_called()

	def test_success_writes_sorted_payload(self) -> None:
		client = GistClient(make_config())
		response = mock.Mock()
		with mock.patch(
			"wgmm_monitor.clients.gist.requests.patch", return_value=response
		) as patch_call:
			success, _error = client.write_new_urls({"b", "a"})

			self.assertTrue(success)
			payload = patch_call.call_args.kwargs["json"]
			self.assertEqual(payload["files"]["new.txt"]["content"], "a\nb\n")

	def test_http_error_includes_status_code(self) -> None:
		client = GistClient(make_config())
		response = mock.Mock()
		response.raise_for_status.side_effect = requests.exceptions.HTTPError(
			response=SimpleNamespace(status_code=403)
		)
		with mock.patch("wgmm_monitor.clients.gist.requests.patch", return_value=response):
			success, error = client.write_new_urls({"a"})

			self.assertFalse(success)
			self.assertIn("403", error)

	def test_network_error_reported(self) -> None:
		client = GistClient(make_config())
		with mock.patch(
			"wgmm_monitor.clients.gist.requests.patch",
			side_effect=requests.RequestException("断开"),
		):
			success, error = client.write_new_urls({"a"})

			self.assertFalse(success)
			self.assertIn("写入 new.txt 请求失败", error)


class YtDlpClientTest(unittest.TestCase):
	"""验证 yt-dlp 调用封装与耗时统计."""

	def make_client(self, root: Path) -> YtDlpClient:
		"""创建带开发模式日志器的客户端."""
		logger = RuntimeLogger(root / "u.log", root / "c.log", dev_mode=True)
		return YtDlpClient(logger)

	def test_missing_executable_fails_fast(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			client = self.make_client(Path(tmp))
			with (
				mock.patch("wgmm_monitor.clients.ytdlp.shutil.which", return_value=None),
				contextlib.redirect_stdout(io.StringIO()),
			):
				result = client.run(["--version"])

			self.assertFalse(result.success)
			self.assertIn("yt-dlp", result.stderr)

	def test_success_updates_duration_ema(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			client = self.make_client(Path(tmp))
			fake_proc = SimpleNamespace(returncode=0, stdout="ok\n", stderr="")
			with (
				mock.patch(
					"wgmm_monitor.clients.ytdlp.shutil.which", return_value="/bin/yt-dlp"
				),
				mock.patch(
					"wgmm_monitor.clients.ytdlp.subprocess.run", return_value=fake_proc
				) as run,
			):
				result = client.run(["--version"], timeout=10)

			self.assertTrue(result.success)
			self.assertEqual(result.stdout, "ok")
			self.assertEqual(run.call_args.args[0][0], "/bin/yt-dlp")
			# 成功执行后正常耗时按 0.9/0.1 EMA 更新, 应低于初始 60 秒
			self.assertLess(client.normal_duration, 60.0)
			self.assertGreater(client.normal_duration, 50.0)

	def test_failure_keeps_normal_duration(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			client = self.make_client(Path(tmp))
			fake_proc = SimpleNamespace(returncode=1, stdout="", stderr="boom")
			with (
				mock.patch(
					"wgmm_monitor.clients.ytdlp.shutil.which", return_value="/bin/yt-dlp"
				),
				mock.patch(
					"wgmm_monitor.clients.ytdlp.subprocess.run", return_value=fake_proc
				),
			):
				result = client.run(["--version"])

			self.assertFalse(result.success)
			self.assertEqual(result.stderr, "boom")
			self.assertEqual(client.normal_duration, 60.0)

	def test_timeout_reports_and_records_duration(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			client = self.make_client(Path(tmp))
			with (
				mock.patch(
					"wgmm_monitor.clients.ytdlp.shutil.which", return_value="/bin/yt-dlp"
				),
				mock.patch(
					"wgmm_monitor.clients.ytdlp.subprocess.run",
					side_effect=subprocess.TimeoutExpired(cmd="yt-dlp", timeout=1),
				),
				contextlib.redirect_stdout(io.StringIO()),
			):
				result = client.run(["--version"], timeout=1)

			self.assertFalse(result.success)
			self.assertEqual(result.stderr, "命令超时")

	def test_oserror_reported(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			client = self.make_client(Path(tmp))
			with (
				mock.patch(
					"wgmm_monitor.clients.ytdlp.shutil.which", return_value="/bin/yt-dlp"
				),
				mock.patch(
					"wgmm_monitor.clients.ytdlp.subprocess.run",
					side_effect=OSError("无法执行"),
				),
				contextlib.redirect_stdout(io.StringIO()),
			):
				result = client.run(["--version"])

			self.assertFalse(result.success)
			self.assertIn("无法执行", result.stderr)


if __name__ == "__main__":
	unittest.main()
