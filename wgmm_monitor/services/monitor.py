"""主监控业务流程."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from contextlib import suppress
from datetime import datetime as dt

from wgmm_monitor.clients.gist import GistClient
from wgmm_monitor.models import RuntimePaths
from wgmm_monitor.runtime_logger import RuntimeLogger
from wgmm_monitor.services.bilibili import BilibiliService
from wgmm_monitor.services.frequency import FrequencyService
from wgmm_monitor.services.history import HistoryService
from wgmm_monitor.services.notification import NotificationService
from wgmm_monitor.stores.url_store import UrlStore
from wgmm_monitor.utils.time import JST


class MonitorService:
	"""三层检测和主循环编排服务."""

	def __init__(
		self,
		paths: RuntimePaths,
		gist_client: GistClient,
		url_store: UrlStore,
		bilibili: BilibiliService,
		history_service: HistoryService,
		frequency_service: FrequencyService,
		notification_service: NotificationService,
		logger: RuntimeLogger,
		dev_mode: bool = False,
		sleep_func: Callable[[float], None] = time.sleep,
	) -> None:
		"""初始化主监控流程依赖."""
		self.paths = paths
		self.gist_client = gist_client
		self.url_store = url_store
		self.bilibili = bilibili
		self.history_service = history_service
		self.frequency_service = frequency_service
		self.notification_service = notification_service
		self.logger = logger
		self.dev_mode = dev_mode
		self.sleep_func = sleep_func
		self.memory_urls: list[str] = []
		self.known_urls: set[str] = self.url_store.load()

	def save_known_urls(self) -> None:
		"""保存已知 URL 集合."""
		self.url_store.save(self.known_urls)

	def sync_urls_from_gist(self) -> bool:
		"""从 Gist 同步已备份 URL."""
		success, urls, error = self.gist_client.fetch_urls()
		if not success:
			self.logger.log_critical_error(error, "Gist 同步", send_notification=True)
			return False

		self.memory_urls = urls
		self.known_urls.update(self.memory_urls)
		if not self.dev_mode:
			self.save_known_urls()
		return True

	def write_new_urls_to_gist(self, urls: set[str]) -> bool:
		"""写入 Gist new.txt."""
		success, error = self.gist_client.write_new_urls(urls)
		if success:
			return True
		self.logger.log_critical_error(error, "Gist new.txt 更新", send_notification=True)
		return False

	def cleanup(self) -> None:
		"""清理开发模式临时文件."""
		if self.dev_mode:
			with suppress(OSError):
				if self.paths.temp_info_dir.exists():
					shutil.rmtree(self.paths.temp_info_dir)

	def wait_for_next_check(self) -> None:
		"""等待到下次检查时间."""
		try:
			next_check_timestamp = self.frequency_service.get_next_check_time()
			if next_check_timestamp > 0:
				current_timestamp = int(time.time())
				wait_seconds = next_check_timestamp - current_timestamp
				next_dt = dt.fromtimestamp(next_check_timestamp, tz=JST)
				weekday_name = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][
					next_dt.weekday()
				]
				date_str = next_dt.strftime("%Y年%m月%d日")
				time_str = next_dt.strftime("%H:%M:%S")
				next_check_time = f"{date_str} {weekday_name} {time_str}"

				if wait_seconds <= 0:
					self.logger.log_info(
						f"距离上次检查时间已过 {abs(wait_seconds)} 秒, 立即开始检查",
					)
					return

				if self.dev_mode:
					self.logger.log_info(f"下次检查: {next_check_time}")
					return

				self.logger.log_info(f"下次检查: {next_check_time}")
				self.sleep_func(wait_seconds)
			else:
				self.logger.log_info("未找到保存的检查时间, 立即开始首次检查")
		except (FileNotFoundError, ValueError) as exc:
			self.logger.log_info(f"配置文件异常 ({exc}), 立即开始检查")
		except OSError as exc:
			self.logger.log_warning(f"等待逻辑异常: {exc}, 使用默认等待")
			if not self.dev_mode:
				self.sleep_func(24000)
			else:
				self.logger.log_info("Dev模式下跳过异常等待")

	def adjust_check_frequency(self, found_new_content: bool = False) -> None:
		"""调频服务兼容入口."""
		self.frequency_service.adjust_check_frequency(
			found_new_content=found_new_content,
			last_ytdlp_duration=self.bilibili.ytdlp_client.last_duration,
			normal_ytdlp_duration=self.bilibili.ytdlp_client.normal_duration,
		)

	def run_monitor(self) -> None:
		"""执行一次完整监控流程."""
		try:
			self.logger.log_message("检查开始                  <--")
			sync_success = self.sync_urls_from_gist()

			if not sync_success and not self.memory_urls:
				self.logger.log_warning(
					"无法获取基准数据 (Gist 失败且内存 urls 为空), 跳过本次检查",
				)
				self.cleanup()
				return

			found_new_parts = self.bilibili.check_potential_new_parts(self.memory_urls)
			found_new_videos = self.bilibili.quick_precheck(
				self.memory_urls,
				self.known_urls,
			)

			parts_result = "发现新内容" if found_new_parts else "无新内容"
			videos_result = "发现新内容" if found_new_videos else "无新内容"
			self.logger.log_info(
				f"预检查完成 - 预测检查: {parts_result} 快速检查: {videos_result}",
			)

			if not (found_new_parts or found_new_videos):
				self.adjust_check_frequency(found_new_content=False)
				self.cleanup()
				return

			result = self.bilibili.fetch_video_list()
			if not result.success or not result.stdout:
				self.logger.log_warning(
					f"完整检查首次尝试失败, 30秒后重试 [stderr: {result.stderr}]",
				)
				self.sleep_func(30)
				result = self.bilibili.fetch_video_list()

			if not result.success or not result.stdout:
				self.logger.log_critical_error(
					"无法获取视频列表",
					"完整检查阶段",
					send_notification=True,
					detail=result.stderr,
				)
				self.adjust_check_frequency(found_new_content=False)
				self.cleanup()
				return

			video_urls = [
				line.strip() for line in result.stdout.split("\n") if line.strip()
			]
			if not video_urls:
				self.logger.log_critical_error(
					"未获取到任何内容",
					"完整检查阶段",
					send_notification=True,
				)
				self.adjust_check_frequency(found_new_content=False)
				self.cleanup()
				return

			all_parts = self.bilibili.get_all_videos_parallel(video_urls)
			if not all_parts:
				self.logger.log_warning("分片扩展失败(可能被限流), 跳过本次检测")
				self.adjust_check_frequency(found_new_content=False)
				self.cleanup()
				return

			existing_urls_set = set(self.memory_urls)
			current_urls_set = set(all_parts)
			gist_missing_urls = current_urls_set - existing_urls_set
			truly_new_urls = gist_missing_urls - self.known_urls

			if truly_new_urls:
				old_count = len(gist_missing_urls) - len(truly_new_urls)
				new_count = len(truly_new_urls)
				separator = " " if old_count > 0 and new_count > 0 else ""
				display = f"{'*' * old_count}{separator}{'*' * new_count}"
				self.logger.log_info(display)

				self.history_service.save_real_upload_timestamps(truly_new_urls)

				self.known_urls.update(gist_missing_urls)
				self.save_known_urls()

				if not self.dev_mode and not self.write_new_urls_to_gist(truly_new_urls):
					self.logger.log_warning("写入 new.txt 失败, 不影响主流程")

				if not self.dev_mode and not self.notification_service.notify_new_videos(
					len(truly_new_urls),
					has_new_parts=found_new_parts,
				):
					self.logger.log_critical_error(
						"通知发送失败 - 无法向用户推送新视频通知",
						"notify_new_videos",
						send_notification=False,
					)

				self.adjust_check_frequency(found_new_content=True)
			elif gist_missing_urls:
				self.logger.log_info(
					f"完整检查发现 {len(gist_missing_urls)} 个URL均已在本地, 跳过通知",
				)
				self.adjust_check_frequency(found_new_content=False)
			elif found_new_parts:
				self.logger.log_info("完整检查未发现新视频 - 但发现新分片, 已处理")
				self.adjust_check_frequency(found_new_content=True)
			else:
				self.logger.log_info("完整检查未发现新内容 - 快速检查结果已确认, 无更新")
				self.adjust_check_frequency(found_new_content=False)

			self.cleanup()
		except KeyboardInterrupt:
			self.logger.log_info("收到中断信号, 正在退出...")
			self.cleanup()
			sys.exit(0)
		except (OSError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
			self.logger.log_critical_error(
				f"监控脚本运行时出现意外错误: {exc}",
				"run_monitor",
				send_notification=True,
			)
			self.cleanup()
