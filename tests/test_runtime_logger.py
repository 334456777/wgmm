"""运行期日志器测试."""

from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from wgmm_monitor.runtime_logger import RuntimeLogger


def make_logger(root: Path, dev_mode: bool = False, **kwargs: object) -> RuntimeLogger:
	"""创建写入临时目录的日志器."""
	return RuntimeLogger(
		root / "urls.log",
		root / "critical.log",
		dev_mode=dev_mode,
		**kwargs,  # type: ignore[arg-type]
	)


def capture_stdout() -> contextlib.redirect_stdout:
	"""静默并捕获控制台输出."""
	return contextlib.redirect_stdout(io.StringIO())


class LogMessageTest(unittest.TestCase):
	"""验证基础日志写入."""

	def test_writes_file_with_level(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			logger = make_logger(Path(tmp))

			with capture_stdout():
				logger.log_warning("注意")

			content = (Path(tmp) / "urls.log").read_text(encoding="utf-8")
			self.assertIn("- WARNING - 注意", content)

	def test_dev_mode_does_not_write_file(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			logger = make_logger(Path(tmp), dev_mode=True)

			with capture_stdout():
				logger.log_info("hello")

			self.assertFalse((Path(tmp) / "urls.log").exists())

	def test_rotation_counter_triggers_limit(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			logger = make_logger(Path(tmp))
			logger._log_write_count = 999

			with capture_stdout():
				logger.log_info("第1000条")

			self.assertEqual(logger._log_write_count, 1000)


class LogErrorTest(unittest.TestCase):
	"""验证错误日志与通知回调."""

	def test_notifier_success_logged(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			calls: list[str] = []

			def notifier(message: str) -> bool:
				calls.append(message)
				return True

			logger = make_logger(Path(tmp), error_notifier=notifier)
			out = io.StringIO()
			with contextlib.redirect_stdout(out):
				logger.log_error("出错了")

			self.assertEqual(calls, ["出错了"])
			self.assertIn("错误通知已发送", out.getvalue())

	def test_notifier_failure_logged(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			logger = make_logger(Path(tmp), error_notifier=lambda _m: False)
			out = io.StringIO()
			with contextlib.redirect_stdout(out):
				logger.log_error("出错了")

			self.assertIn("错误通知发送失败", out.getvalue())

	def test_notification_can_be_skipped(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			calls: list[str] = []
			logger = make_logger(
				Path(tmp),
				error_notifier=lambda m: calls.append(m) is None,
			)

			with capture_stdout():
				logger.log_error("出错了", send_bark_notification=False)

			self.assertEqual(calls, [])


class LogCriticalErrorTest(unittest.TestCase):
	"""验证严重错误日志."""

	def test_writes_critical_file_with_context_and_detail(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			logger = make_logger(Path(tmp))

			with capture_stdout():
				logger.log_critical_error(
					"崩了",
					context="单元测试",
					send_notification=False,
					detail="栈",
				)

			content = (Path(tmp) / "critical.log").read_text(encoding="utf-8")
			self.assertIn("崩了 [上下文: 单元测试] [详情: 栈]", content)

	def test_notifier_called_when_enabled(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			calls: list[tuple[str, str]] = []

			def notifier(message: str, context: str) -> bool:
				calls.append((message, context))
				return False

			logger = make_logger(Path(tmp), critical_notifier=notifier)
			out = io.StringIO()
			with contextlib.redirect_stdout(out):
				logger.log_critical_error("崩了", context="ctx")

			self.assertEqual(calls, [("崩了", "ctx")])
			self.assertIn("重大错误通知发送失败", out.getvalue())

	def test_dev_mode_skips_file_and_notification(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			calls: list[tuple[str, str]] = []
			logger = make_logger(
				Path(tmp),
				dev_mode=True,
				critical_notifier=lambda m, c: calls.append((m, c)) is None,
			)

			with capture_stdout():
				logger.log_critical_error("崩了")

			self.assertFalse((Path(tmp) / "critical.log").exists())
			self.assertEqual(calls, [])

	def test_unwritable_critical_file_falls_back_to_console(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			root = Path(tmp)
			(root / "critical.log").mkdir()
			logger = make_logger(root)
			out = io.StringIO()
			with contextlib.redirect_stdout(out):
				logger.log_critical_error("崩了", send_notification=False)

			self.assertIn("无法写入重大错误日志", out.getvalue())
			self.assertIn("原始错误: 崩了", out.getvalue())


class LimitFileLinesWrapperTest(unittest.TestCase):
	"""验证按文件类型保留头部的截断封装."""

	def test_main_log_keeps_two_header_lines(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			logger = make_logger(Path(tmp))
			logger.log_file.write_text("h1\nh2\n1\n2\n3\n", encoding="utf-8")

			logger.limit_file_lines(logger.log_file, 3)

			self.assertEqual(
				logger.log_file.read_text(encoding="utf-8"),
				"h1\nh2\n3\n",
			)

	def test_critical_log_keeps_one_header_line(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			logger = make_logger(Path(tmp))
			logger.critical_log_file.write_text("h\n1\n2\n3\n", encoding="utf-8")

			logger.limit_file_lines(logger.critical_log_file, 3)

			self.assertEqual(
				logger.critical_log_file.read_text(encoding="utf-8"),
				"h\n2\n3\n",
			)

	def test_other_file_keeps_no_header(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			logger = make_logger(Path(tmp))
			other = Path(tmp) / "mtime.txt"
			other.write_text("1\n2\n3\n", encoding="utf-8")

			logger.limit_file_lines(other, 2)

			self.assertEqual(other.read_text(encoding="utf-8"), "2\n3\n")

	def test_oserror_is_reported_not_raised(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			root = Path(tmp)
			logger = make_logger(root)
			directory = root / "somedir"
			directory.mkdir()

			with capture_stdout():
				logger.limit_file_lines(directory, 2)

			content = (root / "critical.log").read_text(encoding="utf-8")
			self.assertIn("限制文件行数时出错", content)


class ContextManagerTest(unittest.TestCase):
	"""验证上下文管理器协议."""

	def test_enter_returns_logger(self) -> None:
		with (
			tempfile.TemporaryDirectory() as tmp,
			make_logger(Path(tmp), dev_mode=True) as logger,
		):
			self.assertIsInstance(logger, RuntimeLogger)


if __name__ == "__main__":
	unittest.main()
