"""历史事件存储测试."""

from __future__ import annotations

import contextlib
import io
import math
import tempfile
import unittest
from pathlib import Path

from wgmm_monitor.runtime_logger import RuntimeLogger
from wgmm_monitor.stores.history_store import HistoryStore


def make_store(root: Path, dev_mode: bool = False) -> HistoryStore:
	"""创建写入临时目录的历史存储."""
	logger = RuntimeLogger(root / "u.log", root / "c.log", dev_mode=True)
	return HistoryStore(
		root / "mtime.txt",
		root / "miss_history.txt",
		logger,
		dev_mode=dev_mode,
	)


class LoadHistoryTest(unittest.TestCase):
	"""验证历史文件读取."""

	def test_load_positive_events_deduplicates_and_skips_garbage(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			root = Path(tmp)
			(root / "mtime.txt").write_text(
				"100\nabc\n\n200\n100\n-5\n0\n", encoding="utf-8"
			)
			store = make_store(root)

			self.assertEqual(store.load_positive_events(), [100, 200])

	def test_load_positive_events_missing_file_returns_empty(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			store = make_store(Path(tmp))

			self.assertEqual(store.load_positive_events(), [])

	def test_load_miss_history_missing_file_returns_empty(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			store = make_store(Path(tmp))

			self.assertEqual(store.load_miss_history(), [])

	def test_load_miss_history_skips_garbage_lines(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			root = Path(tmp)
			(root / "miss_history.txt").write_text("100\nxx\n200\n", encoding="utf-8")
			store = make_store(root)

			self.assertEqual(store.load_miss_history(), [100, 200])


class SaveMissHistoryTest(unittest.TestCase):
	"""验证负向事件写入."""

	def test_manual_run_skips_save(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			root = Path(tmp)
			store = make_store(root)

			store.save_miss_history(100, is_manual_run=True)

			self.assertFalse((root / "miss_history.txt").exists())

	def test_dev_mode_uses_sandbox(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			root = Path(tmp)
			store = make_store(root, dev_mode=True)

			store.save_miss_history(100, is_manual_run=False)

			self.assertFalse((root / "miss_history.txt").exists())
			self.assertEqual(store.sandbox_miss_history, [100])

	def test_appends_timestamp(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			root = Path(tmp)
			(root / "miss_history.txt").write_text("100\n", encoding="utf-8")
			store = make_store(root)

			store.save_miss_history(200, is_manual_run=False)

			self.assertEqual(
				(root / "miss_history.txt").read_text(encoding="utf-8"),
				"100\n200\n",
			)


class AppendUploadTimestampsTest(unittest.TestCase):
	"""验证正向事件追加."""

	def test_dev_mode_or_empty_skips_write(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			root = Path(tmp)
			make_store(root, dev_mode=True).append_upload_timestamps([100])
			make_store(root).append_upload_timestamps([])

			self.assertFalse((root / "mtime.txt").exists())

	def test_appends_sorted(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			root = Path(tmp)
			(root / "mtime.txt").write_text("50\n", encoding="utf-8")
			store = make_store(root)

			store.append_upload_timestamps([300, 100])

			self.assertEqual(
				(root / "mtime.txt").read_text(encoding="utf-8"),
				"50\n100\n300\n",
			)


class PruneOldDataTest(unittest.TestCase):
	"""验证按指数权重剪枝."""

	def test_recent_events_are_kept(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			root = Path(tmp)
			now = 1_700_000_000
			events = [now - 3600, now - 7200]
			(root / "mtime.txt").write_text(
				"".join(f"{e}\n" for e in events), encoding="utf-8"
			)
			store = make_store(root)

			result = store.prune_old_data(events, 0.0001, 0.001, now, store.mtime_file)

			self.assertEqual(result, events)

	def test_low_weight_events_are_pruned_and_file_rewritten(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			root = Path(tmp)
			now = 1_700_000_000
			old = now - 3600 * 200_000
			recent = now - 3600
			# 老事件权重 e^{-0.001*200000} 远低于阈值, 新事件接近 1
			self.assertLess(math.exp(-0.001 * 200_000), 0.001)
			(root / "mtime.txt").write_text(f"{old}\n{recent}\n", encoding="utf-8")
			store = make_store(root)

			result = store.prune_old_data(
				[old, recent], 0.001, 0.001, now, store.mtime_file
			)

			self.assertEqual(result, [recent])
			self.assertEqual(
				(root / "mtime.txt").read_text(encoding="utf-8"),
				f"{recent}\n",
			)

	def test_missing_target_file_returns_input(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			store = make_store(Path(tmp))

			self.assertEqual(
				store.prune_old_data([100], 0.001, 0.001, 200, store.mtime_file),
				[100],
			)

	def test_dev_mode_prunes_in_memory_only(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			root = Path(tmp)
			now = 1_700_000_000
			old = now - 3600 * 200_000
			recent = now - 3600
			content = f"{old}\n{recent}\n"
			(root / "mtime.txt").write_text(content, encoding="utf-8")
			store = make_store(root, dev_mode=True)

			result = store.prune_old_data(
				[old, recent], 0.001, 0.001, now, store.mtime_file
			)

			self.assertEqual(result, [recent])
			self.assertEqual(
				(root / "mtime.txt").read_text(encoding="utf-8"),
				content,
			)


class OsErrorPathsTest(unittest.TestCase):
	"""验证各写入路径的 OSError 容错 (目标路径为目录时触发)."""

	def test_load_miss_history_oserror_returns_empty(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			root = Path(tmp)
			(root / "miss_history.txt").mkdir()
			store = make_store(root)

			with contextlib.redirect_stdout(io.StringIO()):
				self.assertEqual(store.load_miss_history(), [])

	def test_save_miss_history_oserror_is_reported(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			root = Path(tmp)
			(root / "miss_history.txt").mkdir()
			store = make_store(root)
			out = io.StringIO()
			with contextlib.redirect_stdout(out):
				store.save_miss_history(100, is_manual_run=False)

			self.assertIn("写入失败历史记录失败", out.getvalue())

	def test_append_timestamps_oserror_is_reported(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			root = Path(tmp)
			(root / "mtime.txt").mkdir()
			store = make_store(root)
			out = io.StringIO()
			with contextlib.redirect_stdout(out):
				store.append_upload_timestamps([100])

			self.assertIn("保存时间戳失败", out.getvalue())

	def test_prune_write_failure_keeps_original_events(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			root = Path(tmp)
			(root / "mtime.txt").mkdir()
			now = 1_700_000_000
			old = now - 3600 * 200_000
			recent = now - 3600
			store = make_store(root)

			out = io.StringIO()
			with contextlib.redirect_stdout(out):
				result = store.prune_old_data(
					[old, recent], 0.001, 0.001, now, store.mtime_file
				)

			self.assertEqual(result, [old, recent])
			self.assertIn("数据剪枝失败", out.getvalue())


if __name__ == "__main__":
	unittest.main()
