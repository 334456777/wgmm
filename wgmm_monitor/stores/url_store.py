"""本地 URL 状态存储."""

from __future__ import annotations

from pathlib import Path

from wgmm_monitor.runtime_logger import RuntimeLogger


class UrlStore:
	"""管理本地已知 URL 文件."""

	def __init__(self, path: Path, logger: RuntimeLogger, dev_mode: bool = False) -> None:
		"""初始化 URL 文件路径."""
		self.path = path
		self.logger = logger
		self.dev_mode = dev_mode
		self.sandbox_known_urls: set[str] = set()

	def load(self) -> set[str]:
		"""加载本地已知 URL 集合."""
		try:
			if self.path.exists():
				with self.path.open(encoding="utf-8") as f:
					return {line.strip() for line in f if line.strip()}
			if not self.dev_mode:
				self.save(set())
		except OSError as exc:
			self.logger.log_warning(f"加载本地已知 URL 失败: {exc}, 将使用空集合")
		return set()

	def save(self, known_urls: set[str]) -> None:
		"""保存本地已知 URL 集合."""
		if self.dev_mode:
			self.sandbox_known_urls = set(known_urls)
			return

		try:
			self.path.write_text("\n".join(sorted(set(known_urls))), encoding="utf-8")
		except OSError as exc:
			self.logger.log_critical_error(
				f"保存本地已知 URL 失败: {exc}",
				"save_known_urls",
				send_notification=False,
			)
