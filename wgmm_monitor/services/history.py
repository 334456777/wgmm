"""历史发布时间生成与维护."""

from __future__ import annotations

import json
import shutil
import subprocess
from contextlib import suppress

from wgmm_monitor.clients.bilibili_api import extract_bvid
from wgmm_monitor.models import AppConfig, RuntimePaths
from wgmm_monitor.runtime_logger import RuntimeLogger
from wgmm_monitor.services.bilibili import BilibiliService
from wgmm_monitor.stores.history_store import HistoryStore


class HistoryService:
	"""负责 mtime.txt 和上传时间戳维护."""

	def __init__(
		self,
		config: AppConfig,
		paths: RuntimePaths,
		bilibili: BilibiliService,
		history_store: HistoryStore,
		logger: RuntimeLogger,
		dev_mode: bool = False,
	) -> None:
		"""初始化历史服务依赖."""
		self.config = config
		self.paths = paths
		self.bilibili = bilibili
		self.history_store = history_store
		self.logger = logger
		self.dev_mode = dev_mode

	def save_real_upload_timestamps(self, new_urls: set[str]) -> None:
		"""获取并保存新视频真实上传时间戳."""
		if not new_urls:
			return

		timestamps = []
		for url in new_urls:
			upload_time = self.bilibili.get_video_upload_time(url)
			if upload_time:
				timestamps.append(upload_time)
			else:
				self.logger.log_warning(f"跳过时间戳保存(获取失败): {url}")

		if self.dev_mode:
			return

		if not self.paths.mtime_file.exists() and not self.generate_mtime_file(
			"save_real_upload_timestamps"
		):
			self.logger.log_warning("无法创建 mtime.txt, 仍然保存时间戳")

		self.history_store.append_upload_timestamps(timestamps)

	def create_mtime_from_info_json(self) -> bool:
		"""通过 yt-dlp info.json 生成 mtime.txt."""
		temp_info_dir = self.paths.temp_info_dir
		temp_timestamps_file = self.paths.temp_timestamps_file
		temp_info_dir.mkdir(exist_ok=True)

		try:
			result = self.bilibili.run_yt_dlp(
				[
					"--cookies",
					str(self.paths.cookies_file),
					"--write-info-json",
					"--skip-download",
					"--restrict-filenames",
					"--output",
					f"{temp_info_dir}/%(id)s.%(ext)s",
					f"https://space.bilibili.com/{self.config.bilibili_uid}/video",
				],
				timeout=600,
			)
			if not result.success:
				self.logger.log_warning("获取元信息失败")
				return False

			# 先从 info.json 收集去重后的 bvid, 再按 bvid 串行调 view API 取真实 ctime.
			# info.json 的 timestamp/upload_date 对应可被伪造的 pubdate, 不能直接使用.
			bvids: list[str] = []
			seen_bvids: set[str] = set()
			for info_file in temp_info_dir.glob("*.info.json"):
				try:
					with info_file.open(encoding="utf-8") as f:
						info_data = json.load(f)

					bvid = extract_bvid(
						info_data.get("id") or info_data.get("webpage_url", "")
					)
					if bvid and bvid not in seen_bvids:
						seen_bvids.add(bvid)
						bvids.append(bvid)
				except (OSError, json.JSONDecodeError) as exc:
					self.logger.log_warning(f"解析 info.json 文件失败: {info_file} - {exc}")

			timestamp_count = 0
			collected_timestamps: list[int] = []
			for bvid in bvids:
				ctimes = [ts for ts in self.bilibili.get_bvid_part_ctimes(bvid) if ts > 0]
				if ctimes:
					collected_timestamps.extend(ctimes)
					timestamp_count += len(ctimes)
				else:
					self.logger.log_warning(f"跳过时间戳采集(view API 失败): {bvid}")

			if collected_timestamps:
				with temp_timestamps_file.open("w", encoding="utf-8") as tf:
					tf.writelines(f"{ts}\n" for ts in collected_timestamps)

			with suppress(OSError):
				shutil.rmtree(temp_info_dir)

			if timestamp_count == 0:
				self.logger.log_warning("未能从任何 info.json 文件中提取到有效时间戳")
				with suppress(OSError):
					temp_timestamps_file.unlink()
				return False

			sort_path = shutil.which("sort")
			sorted_content = None
			sort_method = ""
			if sort_path and temp_timestamps_file.exists():
				try:
					sort_result = subprocess.run(
						[sort_path, "-n", str(temp_timestamps_file)],
						capture_output=True,
						text=True,
						check=True,
					)
					sorted_content = sort_result.stdout
					sort_method = "系统排序"
				except (OSError, subprocess.CalledProcessError) as exc:
					self.logger.log_warning(f"系统排序失败: {exc}, 使用内存排序")
					sort_path = None

			if not sort_path and temp_timestamps_file.exists():
				with temp_timestamps_file.open(encoding="utf-8") as tf:
					timestamps = [int(line.strip()) for line in tf if line.strip()]
				timestamps.sort()
				sorted_content = "".join(f"{ts}\n" for ts in timestamps)
				sort_method = "内存排序"

			if sorted_content and temp_timestamps_file.exists():
				self.paths.mtime_file.write_text(sorted_content, encoding="utf-8")
				temp_timestamps_file.unlink()
				self.logger.log_info(
					f"成功创建 mtime.txt ({sort_method}), 包含 {timestamp_count} 个时间戳"
				)
				return True
			return False
		except (OSError, json.JSONDecodeError) as exc:
			self.logger.log_warning(f"创建 mtime.txt 时出错: {exc}")
			with suppress(OSError):
				shutil.rmtree(temp_info_dir)
			return False

	def generate_mtime_file(self, context: str = "") -> bool:
		"""保证 mtime.txt 可用, 最多尝试生成三次."""
		mtime_file_path = self.paths.mtime_file
		if self.dev_mode and not (
			mtime_file_path.exists() and mtime_file_path.stat().st_size > 0
		):
			return True

		max_attempts = 3
		attempt = 0
		while attempt < max_attempts:
			if mtime_file_path.exists() and mtime_file_path.stat().st_size > 0:
				return True

			attempt += 1
			if attempt == 1:
				self.logger.log_info(
					f"mtime.txt 不可用, 第 {attempt} 次尝试生成 [{context}]"
				)
			else:
				self.logger.log_warning(
					f"mtime.txt 仍不可用, 第 {attempt} 次尝试生成 [{context}]",
				)

			if self.create_mtime_from_info_json():
				if mtime_file_path.exists() and mtime_file_path.stat().st_size > 0:
					self.logger.log_info(f"mtime.txt 第 {attempt} 次生成成功 [{context}]")
					return True
				self.logger.log_warning(
					f"mtime.txt 第 {attempt} 次生成后仍不可用 [{context}]",
				)
			else:
				self.logger.log_warning(f"mtime.txt 第 {attempt} 次生成失败 [{context}]")

		error_msg = f"经过 {max_attempts} 次尝试仍无法生成可用的 mtime.txt"
		if context:
			error_msg += f" [上下文: {context}]"
		self.logger.log_critical_error(
			error_msg,
			"generate_mtime_file 方法",
			send_notification=True,
		)
		return False
