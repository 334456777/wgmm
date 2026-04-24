"""yt-dlp 命令客户端."""

from __future__ import annotations

import shutil
import subprocess
import time

from wgmm_monitor.models import YtDlpResult
from wgmm_monitor.runtime_logger import RuntimeLogger


class YtDlpClient:
	"""封装 yt-dlp 可执行文件调用和耗时统计."""

	def __init__(self, logger: RuntimeLogger) -> None:
		"""初始化 yt-dlp 客户端状态."""
		self.logger = logger
		self.yt_dlp_path: str | None = None
		self.last_duration: float = 0.0
		self.normal_duration: float = 60.0

	def run(self, command_args: list[str], timeout: int = 300) -> YtDlpResult:
		"""执行 yt-dlp 命令."""
		if self.yt_dlp_path is None:
			self.yt_dlp_path = shutil.which("yt-dlp")
			if not self.yt_dlp_path:
				self.logger.log_error("未找到 yt-dlp 可执行文件, 请检查是否安装.")
				return YtDlpResult(False, stderr="没有找到 yt-dlp 可执行文件")

		start_time = time.time()
		try:
			result = subprocess.run(
				[self.yt_dlp_path, *command_args],
				capture_output=True,
				text=True,
				timeout=timeout,
				encoding="utf-8",
				check=False,
			)
			elapsed = time.time() - start_time
			self.last_duration = elapsed

			if result.returncode == 0:
				self.normal_duration = 0.9 * self.normal_duration + 0.1 * elapsed

			return YtDlpResult(
				success=result.returncode == 0,
				stdout=result.stdout.strip(),
				stderr=result.stderr.strip(),
				elapsed=elapsed,
			)
		except subprocess.TimeoutExpired:
			elapsed = time.time() - start_time
			self.last_duration = elapsed
			self.logger.log_warning("yt-dlp 命令超时")
			return YtDlpResult(False, stderr="命令超时", elapsed=elapsed)
		except (OSError, ValueError) as exc:
			elapsed = time.time() - start_time
			self.last_duration = elapsed
			self.logger.log_error(
				f"执行 yt-dlp 命令失败: {exc}",
				send_bark_notification=False,
			)
			return YtDlpResult(False, stderr=str(exc), elapsed=elapsed)
