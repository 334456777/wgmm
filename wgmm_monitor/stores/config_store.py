"""WGMM 配置持久化."""

from __future__ import annotations

import json
from pathlib import Path

from wgmm_monitor.models import WgmmConfig
from wgmm_monitor.runtime_logger import RuntimeLogger


class ConfigStore:
	"""读写 ``wgmm_config.json``."""

	def __init__(self, path: Path, logger: RuntimeLogger, dev_mode: bool = False) -> None:
		"""初始化配置文件路径."""
		self.path = path
		self.logger = logger
		self.dev_mode = dev_mode

	def load(self) -> WgmmConfig:
		"""加载配置, 缺失字段自动补齐."""
		try:
			if self.path.exists():
				raw = json.loads(self.path.read_text(encoding="utf-8"))
				return WgmmConfig.from_dict(raw)
			config = WgmmConfig()
			if not self.dev_mode:
				self.save(config)
			return config
		except (OSError, json.JSONDecodeError) as exc:
			self.logger.log_warning(f"加载WGMM配置文件失败, 使用默认配置: {exc}")
			return WgmmConfig()

	def save(self, config: WgmmConfig) -> None:
		"""保存配置; 开发模式不写入磁盘."""
		if self.dev_mode:
			return
		try:
			self.path.write_text(
				json.dumps(config.to_dict(), indent=2, ensure_ascii=False),
				encoding="utf-8",
			)
		except OSError as exc:
			self.logger.log_warning(f"保存WGMM配置失败: {exc}")

	def ensure_manual_flag(self, config: WgmmConfig) -> None:
		"""首次运行时保证存在手动运行标志."""
		if self.path.exists():
			try:
				raw = json.loads(self.path.read_text(encoding="utf-8"))
				if "is_manual_run" not in raw:
					config.is_manual_run = True
					self.save(config)
					self.logger.log_info("首次运行, 已设置 is_manual_run = True")
			except (OSError, json.JSONDecodeError) as exc:
				self.logger.log_warning(f"初始化运行标志失败: {exc}")
		else:
			self.logger.log_info("首次运行, 将自动初始化配置")
