"""本地存储测试."""

from __future__ import annotations

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


if __name__ == "__main__":
	unittest.main()
