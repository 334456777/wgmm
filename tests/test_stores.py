"""本地存储测试."""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from wgmm_monitor.models import WgmmConfig
from wgmm_monitor.runtime_logger import RuntimeLogger
from wgmm_monitor.stores.config_store import ConfigStore
from wgmm_monitor.stores.url_store import UrlStore


def make_logger(root: Path) -> RuntimeLogger:
	"""创建测试日志器."""
	return RuntimeLogger(root / "urls.log", root / "critical.log", dev_mode=True)


class StoreTest(unittest.TestCase):
	"""验证本地存储行为."""

	def test_config_store_dev_mode_does_not_write_file(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			root = Path(tmp)
			store = ConfigStore(root / "wgmm_config.json", make_logger(root), dev_mode=True)

			config = store.load()
			config.next_check_time = 99
			store.save(config)

			self.assertFalse((root / "wgmm_config.json").exists())

	def test_config_store_preserves_unknown_fields(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			root = Path(tmp)
			path = root / "wgmm_config.json"
			path.write_text('{"custom_flag": "keep"}', encoding="utf-8")
			store = ConfigStore(path, make_logger(root), dev_mode=False)

			config = store.load()
			config.next_check_time = 88
			store.save(config)
			reloaded = WgmmConfig.from_dict(json.loads(path.read_text()))

			self.assertEqual(reloaded.extra["custom_flag"], "keep")
			self.assertEqual(reloaded.next_check_time, 88)

	def test_url_store_deduplicates_and_sorts_on_write(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			root = Path(tmp)
			path = root / "local_known.txt"
			store = UrlStore(path, make_logger(root), dev_mode=False)

			store.save({"https://b.example/2", "https://a.example/1"})

			self.assertEqual(
				path.read_text(encoding="utf-8"),
				"https://a.example/1\nhttps://b.example/2",
			)

	def test_url_store_dev_mode_keeps_sandbox_only(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			root = Path(tmp)
			path = root / "local_known.txt"
			store = UrlStore(path, make_logger(root), dev_mode=True)

			store.save({"b", "a"})

			self.assertFalse(path.exists())
			self.assertEqual(store.sandbox_known_urls, {"a", "b"})

	def test_url_store_load_deduplicates_lines(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			root = Path(tmp)
			path = root / "local_known.txt"
			path.write_text("b\na\nb\n", encoding="utf-8")
			store = UrlStore(path, make_logger(root), dev_mode=False)

			self.assertEqual(store.load(), {"a", "b"})

	def test_url_store_load_initializes_missing_file(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			root = Path(tmp)
			path = root / "local_known.txt"
			store = UrlStore(path, make_logger(root), dev_mode=False)

			self.assertEqual(store.load(), set())
			self.assertTrue(path.exists())

	def test_config_store_corrupted_json_returns_defaults(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			root = Path(tmp)
			path = root / "wgmm_config.json"
			path.write_text("{broken", encoding="utf-8")
			store = ConfigStore(path, make_logger(root), dev_mode=False)

			with contextlib.redirect_stdout(io.StringIO()):
				config = store.load()

			self.assertTrue(config.is_manual_run)

	def test_config_store_load_creates_default_file(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			root = Path(tmp)
			path = root / "wgmm_config.json"
			store = ConfigStore(path, make_logger(root), dev_mode=False)

			store.load()

			self.assertTrue(path.exists())

	def test_ensure_manual_flag_sets_when_key_missing(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			root = Path(tmp)
			path = root / "wgmm_config.json"
			path.write_text("{}", encoding="utf-8")
			store = ConfigStore(path, make_logger(root), dev_mode=False)
			config = WgmmConfig(is_manual_run=False)

			with contextlib.redirect_stdout(io.StringIO()):
				store.ensure_manual_flag(config)

			self.assertTrue(config.is_manual_run)
			self.assertIn("is_manual_run", path.read_text(encoding="utf-8"))

	def test_ensure_manual_flag_noop_when_key_present(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			root = Path(tmp)
			path = root / "wgmm_config.json"
			path.write_text('{"is_manual_run": false}', encoding="utf-8")
			store = ConfigStore(path, make_logger(root), dev_mode=False)
			config = WgmmConfig(is_manual_run=False)

			store.ensure_manual_flag(config)

			self.assertFalse(config.is_manual_run)

	def test_url_store_load_oserror_returns_empty(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			root = Path(tmp)
			path = root / "local_known.txt"
			path.mkdir()
			store = UrlStore(path, make_logger(root), dev_mode=False)

			with contextlib.redirect_stdout(io.StringIO()):
				self.assertEqual(store.load(), set())

	def test_url_store_save_oserror_is_reported(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			root = Path(tmp)
			path = root / "local_known.txt"
			path.mkdir()
			store = UrlStore(path, make_logger(root), dev_mode=False)
			out = io.StringIO()
			with contextlib.redirect_stdout(out):
				store.save({"a"})

			self.assertIn("保存本地已知 URL 失败", out.getvalue())

	def test_ensure_manual_flag_missing_file_logs_first_run(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			root = Path(tmp)
			store = ConfigStore(
				root / "wgmm_config.json", make_logger(root), dev_mode=False
			)
			out = io.StringIO()
			with contextlib.redirect_stdout(out):
				store.ensure_manual_flag(WgmmConfig())

			self.assertIn("首次运行", out.getvalue())


if __name__ == "__main__":
	unittest.main()
