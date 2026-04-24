"""运行期日志封装."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from types import TracebackType
from typing import Self

from wgmm_monitor.utils.files import limit_file_lines
from wgmm_monitor.utils.time import get_jst_datetime_str


class RuntimeLogger:
	"""负责控制台日志和本地日志文件写入."""

	def __init__(
		self,
		log_file: Path,
		critical_log_file: Path,
		dev_mode: bool = False,
		error_notifier: Callable[[str], bool] | None = None,
		critical_notifier: Callable[[str, str], bool] | None = None,
	) -> None:
		"""初始化日志文件路径和通知回调."""
		self.log_file = log_file
		self.critical_log_file = critical_log_file
		self.dev_mode = dev_mode
		self.error_notifier = error_notifier
		self.critical_notifier = critical_notifier
		self._log_write_count = 0

	def set_notifiers(
		self,
		error_notifier: Callable[[str], bool],
		critical_notifier: Callable[[str, str], bool],
	) -> None:
		"""设置通知回调."""
		self.error_notifier = error_notifier
		self.critical_notifier = critical_notifier

	def log_message(self, message: str, level: str = "INFO") -> None:
		"""记录一条日志."""
		timestamp = get_jst_datetime_str()
		log_entry = f"{timestamp} - {level} - {message}\n"

		if not self.dev_mode:
			with self.log_file.open("a", encoding="utf-8") as f:
				f.write(log_entry)
			self._log_write_count += 1
			if self._log_write_count % 1000 == 0:
				self.limit_file_lines(self.log_file, 100000)

		print(f"{timestamp} - {level} - {message}")

	def log_info(self, message: str) -> None:
		"""记录 INFO 日志."""
		self.log_message(message, "INFO")

	def log_warning(self, message: str) -> None:
		"""记录 WARNING 日志."""
		self.log_message(message, "WARNING")

	def log_error(self, message: str, send_bark_notification: bool = True) -> None:
		"""记录 ERROR 日志, 可选发送普通错误通知."""
		self.log_message(message, "ERROR")

		if send_bark_notification and self.error_notifier is not None:
			timestamp = get_jst_datetime_str()
			if self.error_notifier(message):
				print(f"{timestamp} - INFO - 错误通知已发送")
			else:
				print(f"{timestamp} - WARNING - 错误通知发送失败")

	def log_critical_error(
		self,
		message: str,
		context: str = "",
		send_notification: bool = True,
		detail: str = "",
	) -> None:
		"""记录 CRITICAL 日志, 可选发送严重错误通知."""
		timestamp = get_jst_datetime_str()
		full_message = f"{message}"
		if context:
			full_message += f" [上下文: {context}]"
		if detail:
			full_message += f" [详情: {detail}]"

		if not self.dev_mode:
			try:
				critical_log_entry = f"{timestamp} - CRITICAL - {full_message}\n"
				with self.critical_log_file.open("a", encoding="utf-8") as f:
					f.write(critical_log_entry)
				self._limit_critical_log_lines()
			except OSError as exc:
				print(f"{timestamp} - CRITICAL - 无法写入重大错误日志: {exc}")
				print(f"{timestamp} - CRITICAL - 原始错误: {full_message}")

		print(f"{timestamp} - CRITICAL - {full_message}")

		if send_notification and not self.dev_mode and self.critical_notifier is not None:
			if self.critical_notifier(message, context):
				print(f"{timestamp} - INFO - 重大错误通知已发送")
			else:
				print(f"{timestamp} - WARNING - 重大错误通知发送失败")

	def _limit_critical_log_lines(self, max_lines: int = 20000) -> None:
		"""限制严重错误日志长度."""
		self.limit_file_lines(self.critical_log_file, max_lines)

	def limit_file_lines(self, filepath: Path, max_lines: int) -> None:
		"""限制日志文件行数."""
		try:
			if filepath == self.log_file:
				header_lines = 2
			elif filepath == self.critical_log_file:
				header_lines = 1
			else:
				header_lines = 0
			limit_file_lines(filepath, max_lines, header_lines)
		except OSError as exc:
			self.log_critical_error(
				f"限制文件行数时出错: {exc}",
				f"文件: {filepath}",
				send_notification=False,
			)

	def __enter__(self) -> Self:
		"""进入上下文管理器."""
		return self

	def __exit__(
		self,
		exc_type: type[BaseException] | None,
		exc_value: BaseException | None,
		traceback: TracebackType | None,
	) -> None:
		"""退出上下文管理器."""
		return None
