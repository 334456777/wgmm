"""应用装配与运行入口."""

from __future__ import annotations

import json
import signal
import subprocess
import sys
from pathlib import Path
from types import FrameType

from wgmm_monitor.clients.bark import BarkClient
from wgmm_monitor.clients.gist import GistClient
from wgmm_monitor.clients.ytdlp import YtDlpClient
from wgmm_monitor.config import load_app_config
from wgmm_monitor.models import RuntimePaths
from wgmm_monitor.runtime_logger import RuntimeLogger
from wgmm_monitor.services.bilibili import BilibiliService
from wgmm_monitor.services.frequency import FrequencyService
from wgmm_monitor.services.history import HistoryService
from wgmm_monitor.services.monitor import MonitorService
from wgmm_monitor.services.notification import NotificationService
from wgmm_monitor.stores.config_store import ConfigStore
from wgmm_monitor.stores.history_store import HistoryStore
from wgmm_monitor.stores.url_store import UrlStore


class Application:
	"""运行期对象装配器."""

	def __init__(self, dev_mode: bool = False) -> None:
		"""装配全部运行期依赖."""
		self.dev_mode = dev_mode
		self.paths = RuntimePaths()
		self.paths.ensure_data_dir()

		self.config = load_app_config()
		if self.config.missing_required_keys():
			print("缺少必要的环境变量", file=sys.stderr)
			sys.exit(1)

		self.logger = RuntimeLogger(
			self.paths.log_file,
			self.paths.critical_log_file,
			dev_mode=dev_mode,
		)
		self.notification_service = NotificationService(
			BarkClient(self.config),
			self.config,
		)
		self.logger.set_notifiers(
			self.notification_service.notify_error,
			self.notification_service.notify_critical_error,
		)

		self._validate_cookies_file(self.paths.cookies_file)

		self.config_store = ConfigStore(
			self.paths.wgmm_config_file,
			self.logger,
			dev_mode=dev_mode,
		)
		self.wgmm_config = self.config_store.load()
		self.url_store = UrlStore(
			self.paths.local_known_file,
			self.logger,
			dev_mode=dev_mode,
		)
		self.history_store = HistoryStore(
			self.paths.mtime_file,
			self.paths.miss_history_file,
			self.logger,
			dev_mode=dev_mode,
		)
		self.ytdlp_client = YtDlpClient(self.logger)
		self.bilibili = BilibiliService(
			self.config,
			self.ytdlp_client,
			self.paths.cookies_file,
			self.logger,
		)
		self.history_service = HistoryService(
			self.config,
			self.paths,
			self.bilibili,
			self.history_store,
			self.logger,
			dev_mode=dev_mode,
		)
		self.frequency_service = FrequencyService(
			self.wgmm_config,
			self.config_store,
			self.history_store,
			self.history_service,
			self.logger,
			dev_mode=dev_mode,
		)
		self.monitor_service = MonitorService(
			self.paths,
			GistClient(self.config),
			self.url_store,
			self.bilibili,
			self.history_service,
			self.frequency_service,
			self.notification_service,
			self.logger,
			dev_mode=dev_mode,
		)
		signal.signal(signal.SIGTERM, self.signal_handler)
		signal.signal(signal.SIGINT, self.signal_handler)

	def _validate_cookies_file(self, cookies_file: Path) -> None:
		"""验证 cookies 文件存在且非空."""
		if not cookies_file.exists():
			self.logger.log_critical_error(
				f"cookies文件不存在: {cookies_file}",
				"cookies_validation",
				send_notification=True,
			)
			sys.exit(1)

		try:
			content = cookies_file.read_text(encoding="utf-8").strip()
			if not content:
				self.logger.log_critical_error(
					f"cookies文件内容为空: {cookies_file}",
					"cookies_validation",
					send_notification=True,
				)
				sys.exit(1)
		except OSError as exc:
			self.logger.log_critical_error(
				f"无法读取cookies文件 {cookies_file}: {exc}",
				"cookies_validation",
				send_notification=True,
			)
			sys.exit(1)

	def signal_handler(self, signum: int, frame: FrameType | None) -> None:
		"""处理退出信号."""
		_ = frame
		self.logger.log_message(f"收到信号 {signum}, 正在清理并退出...")
		try:
			self.monitor_service.save_known_urls()
		except OSError as exc:
			self.logger.log_message(f"保存 URL 状态失败: {exc}")
		self.monitor_service.cleanup()
		sys.exit(0)

	def run_wgmm_core_only(self) -> None:
		"""仅执行一次 WGMM 调频."""
		try:
			self.frequency_service.adjust_check_frequency(found_new_content=False)
			sys.exit(0)
		except KeyboardInterrupt:
			self.logger.log_info("程序被用户中断")
			self.monitor_service.cleanup()
			sys.exit(0)
		except (OSError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
			self.logger.log_critical_error(
				f"WGMM核心模式运行出错: {exc}",
				"main(wgmm_core_only)",
				send_notification=False,
			)
			sys.exit(1)

	def run_dev_once(self) -> None:
		"""开发模式执行一次检查."""
		try:
			self.monitor_service.run_monitor()
			self.monitor_service.wait_for_next_check()
			sys.exit(0)
		except KeyboardInterrupt:
			self.logger.log_info("程序被用户中断")
			self.monitor_service.cleanup()
			sys.exit(0)
		except (OSError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
			self.logger.log_critical_error(
				f"运行出错: {exc}",
				"main(dev)",
				send_notification=False,
			)
			sys.exit(1)

	def run_forever(self) -> None:
		"""生产模式常驻运行."""
		try:
			self.config_store.ensure_manual_flag(self.wgmm_config)
		except OSError as exc:
			self.logger.log_warning(f"初始化检查失败: {exc}")

		try:
			while True:
				self.monitor_service.wait_for_next_check()
				self.monitor_service.run_monitor()
		except KeyboardInterrupt:
			self.logger.log_info("程序被用户中断")
			self.monitor_service.cleanup()
			sys.exit(0)
		except (OSError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
			self.logger.log_critical_error(
				f"主循环出现严重错误: {exc}",
				"main",
				send_notification=True,
			)
			sys.exit(1)
