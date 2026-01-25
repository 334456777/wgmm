#!/usr/bin/env python3

import argparse
import json
import logging
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import suppress
from datetime import UTC, timedelta, timezone
from datetime import datetime as dt
from pathlib import Path
from types import FrameType
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import requests

# 日本时区 (JST, UTC+9)
JST = timezone(timedelta(hours=9))


def parse_arguments():
	parser = argparse.ArgumentParser(description="视频监控器")
	parser.add_argument(
		"-d",
		"--dev",
		action="store_true",
		help="开发模式: 运行检查后立即退出, 不等待下次检查时间",
	)
	return parser.parse_args()


def load_env_file(env_path: str = ".env") -> None:
	env_file = Path(env_path)
	if not env_file.exists():
		return

	try:
		with env_file.open(encoding="utf-8") as f:
			for raw_line in f:
				line = raw_line.strip()
				if not line or line.startswith("#"):
					continue
				if "=" in line:
					key, value = line.split("=", 1)
					key = key.strip()
					value = value.strip()
					if key and not os.getenv(key):
						os.environ[key] = value
	except OSError as e:
		print(f"无法加载 .env 文件: {e}", file=sys.stderr)


class VideoMonitor:
	"""B站视频监控器 - 基于WGMM算法的自适应监控系统.

	核心功能:
	1. 三层检测架构(分片预检查 → 快速ID检查 → 完整深度检查)
	2. WGMM算法自适应调整检查频率, 节省60-80%网络请求
	3. Bark推送通知新视频
	4. GitHub Gist + 本地文件双层URL管理
	"""

	DEFAULT_CHECK_INTERVAL: int = 24000  # 默认检查间隔(秒)
	FALLBACK_INTERVAL: int = 7200  # 降级检查间隔(秒)
	MAX_RETRY_ATTEMPTS: int = 3  # 最大重试次数

	def __init__(self, dev_mode: bool = False) -> None:
		"""初始化监控系统.

		Args:
			dev_mode: 开发模式标志, True时运行单次检查后退出, 不修改配置文件

		"""
		self.dev_mode: bool = dev_mode

		self.GIST_ID: str = os.getenv("GIST_ID", "")
		self.GITHUB_TOKEN: str = os.getenv("GITHUB_TOKEN", "")
		self.GIST_BASE_URL: str = "https://api.github.com/gists"
		self.BILIBILI_UID: str = os.getenv("BILIBILI_UID", "")

		self.bark_device_key: str = os.getenv("BARK_DEVICE_KEY", "")
		self.bark_base_url: str = "https://api.day.app"
		self.bark_app_title: str = os.getenv("BARK_APP_TITLE", "")

		if not all(
			[
				self.GIST_ID,
				self.GITHUB_TOKEN,
				self.BILIBILI_UID,
				self.bark_device_key,
				self.bark_app_title,
			],
		):
			print("缺少必要的环境变量", file=sys.stderr)
			sys.exit(1)

		self.memory_urls: list[str] = []
		self.known_urls: set[str] = set()

		if self.dev_mode:
			self.sandbox_config: dict = {}
			self.sandbox_known_urls: set[str] = set()
			self.sandbox_miss_history: list[int] = []
			self.sandbox_next_check_time: int = 0
			self.dev_new_videos: int = 0

		self.log_file: str = "urls.log"
		self.critical_log_file: str = "critical_errors.log"
		self.wgmm_config_file: str = "wgmm_config.json"
		self.local_known_file: str = "local_known.txt"
		self.mtime_file: str = "mtime.txt"
		self.miss_history_file: str = "miss_history.txt"
		self.cookies_file: str = "cookies.txt"
		self.tmp_outputs_dir: str = "tmp_outputs"

		self._validate_cookies_file()

		self.last_ytdlp_duration: float = 0.0
		self.normal_ytdlp_duration: float = 60.0

		self.yt_dlp_path: str | None = None

		self.wgmm_config: dict = self._load_wgmm_config()

		self.setup_logging()
		self.load_known_urls()

		signal.signal(signal.SIGTERM, self.signal_handler)
		signal.signal(signal.SIGINT, self.signal_handler)

	def setup_logging(self) -> None:
		"""配置日志系统格式和输出."""
		logging.basicConfig(
			level=logging.INFO,
			format="%(asctime)s - %(message)s",
			datefmt="%Y-%m-%d %H:%M:%S",
		)
		self.logger: logging.Logger = logging.getLogger(__name__)

	def load_known_urls(self) -> None:
		"""从本地文件加载已知URL集合."""
		known_file = Path(self.local_known_file)
		try:
			if known_file.exists():
				with known_file.open(encoding="utf-8") as f:
					self.known_urls = {line.strip() for line in f if line.strip()}
			else:
				self.known_urls = set()
				if not self.dev_mode:
					self.save_known_urls()
		except OSError as e:
			self.log_warning(f"加载本地已知 URL 失败: {e}, 将使用空集合")
			self.known_urls = set()

	def save_known_urls(self) -> None:
		"""保存已知URL集合到本地文件."""
		if self.dev_mode:
			self.sandbox_known_urls = self.known_urls.copy()
			return

		try:
			known_file = Path(self.local_known_file)
			with known_file.open("w", encoding="utf-8") as f:
				f.write("\n".join(sorted(self.known_urls)))
		except OSError as e:
			self.log_critical_error(
				f"保存本地已知 URL 失败: {e}",
				"save_known_urls",
				send_notification=False,
			)

	def _validate_cookies_file(self) -> None:
		"""验证cookies文件存在且非空."""
		cookies_path = Path(self.cookies_file)

		if not cookies_path.exists():
			error_msg = f"cookies文件不存在: {cookies_path}"
			self.log_critical_error(
				error_msg,
				"cookies_validation",
				send_notification=True,
			)
			sys.exit(1)

		try:
			content = cookies_path.read_text(encoding="utf-8").strip()

			if not content:
				error_msg = f"cookies文件内容为空: {cookies_path}"
				self.log_critical_error(
					error_msg,
					"cookies_validation",
					send_notification=True,
				)
				sys.exit(1)

		except OSError as e:
			error_msg = f"无法读取cookies文件 {cookies_path}: {e}"
			self.log_critical_error(
				error_msg,
				"cookies_validation",
				send_notification=True,
			)
			sys.exit(1)

	def _load_wgmm_config(self) -> dict:
		default_config = {
			"dimension_weights": {
				"day": 0.3,
				"week": 0.25,
				"month_week": 0.25,
				"year_month": 0.2,
			},
			"sigmas": {
				"day": 0.8,
				"week": 1.0,
				"month_week": 1.5,
				"year_month": 2.0,
			},
			"last_lambda": 0.0001,
			"last_pos_variance": 0.0,
			"last_neg_variance": 0.0,
			"last_update": 0,
			"next_check_time": 0,
			"is_manual_run": True,
		}
		config_file = Path(self.wgmm_config_file)
		try:
			if config_file.exists():
				config = json.loads(config_file.read_text(encoding="utf-8"))
				for key, value in default_config.items():
					if key not in config:
						config[key] = value
					elif isinstance(value, dict):
						for sub_key, sub_value in value.items():
							if sub_key not in config[key]:
								config[key][sub_key] = sub_value
				return config
			else:
				config_file.write_text(
					json.dumps(default_config, indent=2, ensure_ascii=False),
					encoding="utf-8",
				)
				return default_config
		except (OSError, json.JSONDecodeError) as e:
			self.log_warning(f"加载WGMM配置文件失败, 使用默认配置: {e}")
			return default_config

	def _save_wgmm_config(self) -> None:
		"""保存WGMM算法配置到JSON文件."""
		if self.dev_mode:
			return
		config_file = Path(self.wgmm_config_file)
		try:
			config_file.write_text(
				json.dumps(self.wgmm_config, indent=2, ensure_ascii=False),
				encoding="utf-8",
			)
		except OSError as e:
			self.log_warning(f"保存WGMM配置失败: {e}")

	def signal_handler(self, signum: int, frame: FrameType | None) -> None:
		self.log_message(f"收到信号 {signum}, 正在清理并退出...")
		try:
			self.save_known_urls()
		except OSError as e:
			self.log_message(f"保存 URL 状态失败: {e}")
		with suppress(Exception):
			self.cleanup()
		sys.exit(0)

	def log_message(self, message: str, level: str = "INFO") -> None:
		timestamp = dt.now(ZoneInfo("Asia/Tokyo")).strftime("%Y-%m-%d %H:%M:%S")
		log_entry = f"{timestamp} - {level} - {message}\n"

		if self.dev_mode:
			pass
		else:
			log_file_path = Path(self.log_file)
			with log_file_path.open("a", encoding="utf-8") as f:
				f.write(log_entry)
			self.limit_file_lines(self.log_file, 100000)

		print(f"{timestamp} - {level} - {message}")

	def log_info(self, message: str) -> None:
		"""记录INFO级别日志."""
		self.log_message(message, "INFO")

	def log_warning(self, message: str) -> None:
		"""记录WARNING级别日志."""
		self.log_message(message, "WARNING")

	def log_error(self, message: str, send_bark_notification: bool = True) -> None:
		self.log_message(message, "ERROR")

		if send_bark_notification:
			if self.notify_error(message):
				timestamp = dt.now(ZoneInfo("Asia/Tokyo")).strftime("%Y-%m-%d %H:%M:%S")
				print(f"{timestamp} - INFO - 错误通知已发送")
			else:
				timestamp = dt.now(ZoneInfo("Asia/Tokyo")).strftime("%Y-%m-%d %H:%M:%S")
				print(f"{timestamp} - WARNING - 错误通知发送失败")

	def log_critical_error(
		self,
		message: str,
		context: str = "",
		send_notification: bool = True,
	) -> None:
		timestamp = dt.now(ZoneInfo("Asia/Tokyo")).strftime("%Y-%m-%d %H:%M:%S")
		full_message = f"{message}"
		if context:
			full_message += f" [上下文: {context}]"

		if not self.dev_mode:
			try:
				critical_log_entry = f"{timestamp} - CRITICAL - {full_message}\n"
				critical_log_path = Path(self.critical_log_file)
				with critical_log_path.open("a", encoding="utf-8") as f:
					f.write(critical_log_entry)
				self._limit_critical_log_lines()
			except OSError as e:
				print(f"{timestamp} - CRITICAL - 无法写入重大错误日志: {e}")
				print(f"{timestamp} - CRITICAL - 原始错误: {full_message}")

		print(f"{timestamp} - CRITICAL - {full_message}")

		if send_notification and not self.dev_mode:
			if self.notify_critical_error(message, context):
				print(f"{timestamp} - INFO - 重大错误通知已发送")
			else:
				print(f"{timestamp} - WARNING - 重大错误通知发送失败")

	def _limit_critical_log_lines(self, max_lines: int = 20000) -> None:
		"""限制严重错误日志文件的最大行数."""
		with suppress(Exception):
			self.limit_file_lines(self.critical_log_file, max_lines)

	def limit_file_lines(self, filepath: str, max_lines: int) -> None:
		"""限制日志文件的最大行数, 保留最新的内容."""
		file_path = Path(filepath)
		try:
			if file_path.exists():
				lines = file_path.read_text(encoding="utf-8").splitlines(keepends=True)

				if len(lines) > max_lines:
					if filepath == self.log_file:
						keep_lines = lines[:2] + lines[-(max_lines - 2) :]
					elif filepath == self.critical_log_file:
						keep_lines = lines[:1] + lines[-(max_lines - 1) :]
					else:
						keep_lines = lines[-max_lines:]

					file_path.write_text("".join(keep_lines), encoding="utf-8")
		except OSError as e:
			self.log_critical_error(
				f"限制文件行数时出错: {e}",
				f"文件: {filepath}",
				send_notification=False,
			)

	def send_bark_push(
		self,
		title: str,
		body: str,
		level: str = "active",
		sound: str | None = None,
		group: str | None = None,
		icon: str | None = None,
		url: str | None = None,
		is_archive: bool = True,
		call: bool = False,
		volume: int | None = None,
	) -> bool:
		http_ok = 200
		success = False
		try:
			encoded_title = urllib.parse.quote(title)
			encoded_body = urllib.parse.quote(body)
			base_url = (
				f"{self.bark_base_url}/{self.bark_device_key}/"
				f"{encoded_title}/{encoded_body}"
			)

			params = []
			if level and level != "active":
				params.append(f"level={level}")
			if sound:
				params.append(f"sound={urllib.parse.quote(sound)}")
			if call:
				params.append("call=1")
			if volume is not None and level == "critical":
				params.append(f"volume={volume}")
			if group:
				params.append(f"group={urllib.parse.quote(group)}")
			if icon:
				params.append(f"icon={urllib.parse.quote(icon)}")
			if url:
				params.append(f"url={urllib.parse.quote(url)}")
			if is_archive:
				params.append("isArchive=1")

			full_url = f"{base_url}?{'&'.join(params)}" if params else base_url
			response = requests.get(full_url, timeout=30)
			success = response.status_code == http_ok
		except requests.RequestException as e:
			timestamp = dt.now(ZoneInfo("Asia/Tokyo")).strftime("%Y-%m-%d %H:%M:%S")
			print(f"{timestamp} - WARNING - Bark推送失败: {e}")
			success = False

		return success

	def notify_new_videos(self, count: int, has_new_parts: bool = False) -> bool:
		"""发送新视频通知到Bark."""
		body = f"发现 {count} 个新视频{'(含新分片)' if has_new_parts else ''}等待备份"

		return self.send_bark_push(
			title=self.bark_app_title,
			body=body,
			level="timeSensitive",
			sound="minuet",
			group="新视频",
		)

	def notify_error(self, message: str) -> bool:
		"""发送普通错误通知到Bark."""
		return self.send_bark_push(
			title=f"{self.bark_app_title} - 错误",
			body=message,
			level="active",
			group="错误",
		)

	def notify_critical_error(self, message: str, context: str = "") -> bool:
		"""发送严重错误通知到Bark(带铃声和来电提醒)."""
		body = message + (f" ({context})" if context else "")

		return self.send_bark_push(
			title=f"⚠️ {self.bark_app_title} - 严重错误",
			body=body,
			level="critical",
			sound="alarm",
			volume=8,
			call=True,
			group="严重错误",
		)

	def notify_service_issue(self, message: str) -> bool:
		"""发送服务异常通知到Bark."""
		return self.send_bark_push(
			title=f"{self.bark_app_title} - 服务异常",
			body=message,
			level="timeSensitive",
			group="服务异常",
		)

	def get_next_check_time(self) -> int:
		"""从配置文件读取下次检查时间戳."""
		if self.dev_mode:
			return self.sandbox_next_check_time

		config_file = Path(self.wgmm_config_file)
		try:
			if config_file.exists():
				file_content = config_file.read_text(encoding="utf-8")
				config: dict[str, Any] = json.loads(file_content)
				return config.get("next_check_time", 0)
			else:
				return 0
		except (OSError, json.JSONDecodeError) as e:
			self.log_warning(f"读取next_check_time失败: {e}")
			return 0

	def save_next_check_time(self, next_check_timestamp: int) -> None:
		"""保存下次检查时间戳到配置文件."""
		if self.dev_mode:
			self.sandbox_next_check_time = next_check_timestamp
			return

		config_file = Path(self.wgmm_config_file)
		try:
			config: dict[str, Any] = {}
			if config_file.exists():
				config = json.loads(config_file.read_text(encoding="utf-8"))

			config["next_check_time"] = next_check_timestamp
			config_file.write_text(
				json.dumps(config, indent=2, ensure_ascii=False),
				encoding="utf-8",
			)
		except (OSError, json.JSONDecodeError) as e:
			self.log_critical_error(
				f"保存next_check_time失败: {e}",
				"save_next_check_time 方法",
				send_notification=False,
			)

	def sync_urls_from_gist(self) -> bool:
		success = False

		if not self.GIST_ID or not self.GITHUB_TOKEN:
			error_msg = "GIST_ID 未配置" if not self.GIST_ID else "GITHUB_TOKEN 未配置"
			self.log_critical_error(
				error_msg,
				"Gist 同步",
				send_notification=True,
			)
			return success

		headers = {
			"Authorization": f"Bearer {self.GITHUB_TOKEN}",
			"Accept": "application/vnd.github.v3+json",
		}
		url = f"{self.GIST_BASE_URL}/{self.GIST_ID}"

		try:
			response = requests.get(url, headers=headers, timeout=30)
			response.raise_for_status()
			data = response.json()
			files = data.get("files", {})

			if len(files) != 1:
				self.log_critical_error(
					f"Gist 文件数量错误: 期望 1 个, 实际 {len(files)} 个",
					"Gist 同步验证",
					send_notification=True,
				)
				return success

			content = next(iter(files.values())).get("content", "")
			self.memory_urls = [
				line.strip() for line in content.splitlines() if line.strip()
			]
			self.known_urls.update(self.memory_urls)

			if not self.dev_mode:
				self.save_known_urls()
			success = True

		except requests.exceptions.HTTPError as e:
			self.log_critical_error(
				f"Gist API 请求失败: HTTP {e.response.status_code}",
				"Gist 同步",
				send_notification=True,
			)
		except (requests.RequestException, json.JSONDecodeError) as e:
			self.log_critical_error(
				f"从 Gist 获取数据失败: {e!s}",
				"Gist 同步",
				send_notification=True,
			)

		return success

	def get_video_upload_time(self, video_url: str) -> int | None:
		"""获取视频的上传时间戳."""
		try:
			success, stdout, _stderr = self.run_yt_dlp(
				[
					"--cookies",
					self.cookies_file,
					"--print",
					"%(timestamp)s|%(upload_date)s",
					"--no-download",
					video_url,
				],
				timeout=60,
			)

			if not success or not stdout:
				self.log_warning(f"获取视频上传时间失败: {video_url[:50]}...")
				return None

			parts = stdout.strip().split("|")
			min_parts_for_date = 2

			if len(parts) >= 1 and parts[0] and parts[0] != "NA":
				try:
					return int(parts[0])
				except ValueError:
					pass
			if len(parts) >= min_parts_for_date and parts[1] and parts[1] != "NA":
				try:
					parsed_dt = dt.strptime(parts[1], "%Y%m%d").replace(tzinfo=UTC)
					return int(parsed_dt.timestamp())
				except ValueError:
					pass

			self.log_warning(f"无法解析视频上传时间: {stdout[:50]}")
		except (ValueError, subprocess.SubprocessError) as e:
			self.log_warning(f"获取视频上传时间异常: {e}")
		else:
			return None

	def save_real_upload_timestamps(self, new_urls: set[str]) -> None:
		"""获取并保存新视频的真实上传时间戳到mtime.txt."""
		if not new_urls:
			return

		if self.dev_mode:
			timestamps = []
			current_time = int(time.time())

			for url in new_urls:
				upload_time = self.get_video_upload_time(url)
				if upload_time:
					timestamps.append(upload_time)
				else:
					timestamps.append(current_time)

			if timestamps:
				self.dev_new_videos += len(new_urls)

			return

		mtime_file_path = Path(self.mtime_file)
		if not mtime_file_path.exists() and not self.generate_mtime_file(
			"save_real_upload_timestamps"
		):
			self.log_warning("无法创建 mtime.txt, 仍然保存时间戳")

		timestamps = []
		current_time = int(time.time())

		for url in new_urls:
			upload_time = self.get_video_upload_time(url)
			if upload_time:
				timestamps.append(upload_time)
			else:
				self.log_warning(f"降级使用当前时间: {url[:50]}...")
				timestamps.append(current_time)

		if timestamps:
			sorted_timestamps = sorted(timestamps)
			with mtime_file_path.open("a") as f:
				f.writelines(f"{ts}\n" for ts in sorted_timestamps)
			self.limit_file_lines(self.mtime_file, 100000)

	def create_mtime_from_info_json(self) -> bool:
		"""通过yt-dlp获取所有视频的info.json, 提取上传时间戳生成mtime.txt."""
		temp_info_dir = Path("temp_info_json")
		temp_info_dir.mkdir(exist_ok=True)

		try:
			success, _stdout, stderr = self.run_yt_dlp(
				[
					"--cookies",
					self.cookies_file,
					"--write-info-json",
					"--skip-download",
					"--restrict-filenames",
					"--output",
					f"{temp_info_dir}/%(id)s.%(ext)s",
					f"https://space.bilibili.com/{self.BILIBILI_UID}/video",
				],
				timeout=600,
			)

			if not success:
				self.log_warning(f"获取元信息失败: {stderr[:100]}")
				return False

			temp_timestamps_file = Path("temp_timestamps.txt")
			timestamp_count = 0

			for info_file in temp_info_dir.glob("*.info.json"):
				try:
					with info_file.open(encoding="utf-8") as f:
						info_data = json.load(f)

					upload_timestamp = None
					if info_data.get("timestamp"):
						upload_timestamp = int(info_data["timestamp"])
					elif info_data.get("upload_date"):
						try:
							parsed_dt = dt.strptime(
								info_data["upload_date"], "%Y%m%d"
							).replace(tzinfo=UTC)
							upload_timestamp = int(parsed_dt.timestamp())
						except ValueError:
							pass

					if upload_timestamp and upload_timestamp > 0:
						with temp_timestamps_file.open("a", encoding="utf-8") as tf:
							tf.write(f"{upload_timestamp}\n")
						timestamp_count += 1

				except (OSError, json.JSONDecodeError) as e:
					self.log_warning(f"解析 info.json 文件失败: {info_file} - {e}")

			try:
				shutil.rmtree(temp_info_dir)
			except OSError as e:
				self.log_warning(f"清理临时目录失败: {e}")

			if timestamp_count == 0:
				self.log_warning("未能从任何 info.json 文件中提取到有效时间戳")
				with suppress(OSError):
					temp_timestamps_file.unlink()
				return False

			sort_path = shutil.which("sort")
			sorted_content = None
			sort_method = ""

			if sort_path and temp_timestamps_file.exists():
				try:
					result = subprocess.run(
						[sort_path, "-n", str(temp_timestamps_file)],
						capture_output=True,
						text=True,
						check=True,
					)
					sorted_content = result.stdout
					sort_method = "系统排序"
				except (OSError, subprocess.CalledProcessError) as e:
					self.log_warning(f"系统排序失败: {e}, 使用内存排序")
					sort_path = None

			if not sort_path and temp_timestamps_file.exists():
				with temp_timestamps_file.open(encoding="utf-8") as tf:
					timestamps = [int(line.strip()) for line in tf if line.strip()]
				timestamps.sort()
				sorted_content = "".join(f"{ts}\n" for ts in timestamps)
				sort_method = "内存排序"

			if sorted_content and temp_timestamps_file.exists():
				mtime_file_path = Path(self.mtime_file)
				mtime_file_path.write_text(sorted_content, encoding="utf-8")
				temp_timestamps_file.unlink()
				self.log_info(
					f"成功创建 mtime.txt ({sort_method}), 包含 {timestamp_count} 个时间戳"
				)
				return True
			else:
				return False

		except (OSError, json.JSONDecodeError) as e:
			self.log_warning(f"创建 mtime.txt 时出错: {e}")
			with suppress(OSError):
				shutil.rmtree(temp_info_dir)
			return False

	def generate_mtime_file(self, context: str = "") -> bool:
		mtime_file_path = Path(self.mtime_file)
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
				self.log_info(f"mtime.txt 不可用, 第 {attempt} 次尝试生成 [{context}]")
			else:
				self.log_warning(
					f"mtime.txt 仍不可用, 第 {attempt} 次尝试生成 [{context}]",
				)

			if self.create_mtime_from_info_json():
				if mtime_file_path.exists() and mtime_file_path.stat().st_size > 0:
					self.log_info(f"mtime.txt 第 {attempt} 次生成成功 [{context}]")
					return True
				self.log_warning(
					f"mtime.txt 第 {attempt} 次生成后仍不可用 [{context}]",
				)
			else:
				self.log_warning(f"mtime.txt 第 {attempt} 次生成失败 [{context}]")

		error_msg = f"经过 {max_attempts} 次尝试仍无法生成可用的 mtime.txt"
		if context:
			error_msg += f" [上下文: {context}]"
		self.log_critical_error(
			error_msg,
			"generate_mtime_file 方法",
			send_notification=True,
		)
		return False

	def _load_miss_history(self) -> list[int]:
		"""加载负向事件历史(检测未发现新内容的时间).

		Returns:
			负向事件时间戳列表, 如果文件不存在或读取失败则返回空列表

		"""
		miss_history_path = Path(self.miss_history_file)
		if not miss_history_path.exists():
			return []
		try:
			with miss_history_path.open() as f:
				return [int(line.strip()) for line in f if line.strip().isdigit()]
		except OSError as e:
			self.log_warning(f"读取失败历史记录失败: {e}")
			return []

	def _save_miss_history(self, timestamp: int, is_manual_run: bool) -> None:
		"""保存负向事件到历史文件.

		Args:
			timestamp: 要保存的时间戳
			is_manual_run: 是否为手动运行(手动运行时不保存)

		"""
		if is_manual_run:
			return
		if self.dev_mode:
			self.sandbox_miss_history.append(timestamp)
			return
		miss_history_path = Path(self.miss_history_file)
		try:
			with miss_history_path.open("a") as f:
				f.write(f"{timestamp}\n")
			self.limit_file_lines(self.miss_history_file, 100000)
		except OSError as e:
			self.log_warning(f"写入失败历史记录失败: {e}")

	def _load_history_file(self, filepath: str) -> list[int]:
		"""加载历史文件并去重.

		Args:
			filepath: 历史文件路径

		Returns:
			去重后的时间戳列表, 如果读取失败则返回空列表

		"""
		file_path = Path(filepath)

		try:
			raw_data = [
				line.strip()
				for line in file_path.read_text(encoding="utf-8").splitlines()
				if line.strip().isdigit()
			]
			seen_timestamps = set()
			filtered = []
			for timestamp_str in raw_data:
				timestamp = int(timestamp_str)
				if timestamp > 0 and timestamp not in seen_timestamps:
					filtered.append(timestamp)
					seen_timestamps.add(timestamp)
		except OSError as e:
			self.log_warning(f"读取历史文件失败 {filepath}: {e}")
			return []
		else:
			return filtered

	def _filter_outliers(self, timestamps: list, current_time: int) -> list:
		"""过滤异常值时间戳.

		使用IQR(四分位距)方法检测并移除异常的时间间隔.
		异常值定义: 间隔 < Q1 - 3*IQR 或 > Q3 + 3*IQR

		Args:
			timestamps: 历史时间戳列表
			current_time: 当前时间戳

		Returns:
			过滤后的时间戳列表

		"""
		min_count_for_filter = 3  # 最小样本数才进行过滤
		min_count_for_variance = 2  # 最小样本数才计算方差

		if len(timestamps) < min_count_for_filter:
			return [ts for ts in timestamps if ts <= current_time]

		sorted_ts = np.array(sorted(timestamps), dtype=np.float64)
		if len(sorted_ts) < min_count_for_variance:
			return timestamps

		intervals = np.diff(sorted_ts)
		if len(intervals) == 0:
			return timestamps

		q1 = np.percentile(intervals, 25)
		q3 = np.percentile(intervals, 75)

		iqr = q3 - q1
		lower_bound = q1 - 3.0 * iqr
		upper_bound = q3 + 3.0 * iqr

		mask = (intervals >= lower_bound) & (intervals <= upper_bound)

		filtered_indices = np.concatenate(([0], np.where(mask)[0] + 1))
		filtered_ts = sorted_ts[filtered_indices]

		current_mask = filtered_ts <= current_time
		final_ts = filtered_ts[current_mask]

		return final_ts.tolist()

	def _prune_old_data(
		self,
		events: list,
		last_lambda: float,
		threshold: float,
		current_timestamp: int,
	) -> list:
		"""剪枝权重过低的历史数据.

		根据指数衰减权重移除过时的历史记录, 保持算法对最新模式的敏感度.
		权重公式: w = exp(-lambda * age_hours)

		Args:
			events: 正向或负向事件列表
			last_lambda: 上次计算的lambda参数
			threshold: 权重阈值, 低于此值的数据会被移除
			current_timestamp: 当前时间戳

		Returns:
			剪枝后的事件列表

		"""
		target_file = self.mtime_file if events is not None else self.miss_history_file
		if not events or not Path(target_file).exists():
			return events

		events_arr = np.array(events, dtype=np.float64)
		current_ts = float(current_timestamp)

		# 计算每个事件的年龄(小时)和权重
		ages_hours = (current_ts - events_arr) / 3600.0
		weights = np.exp(-last_lambda * ages_hours)

		# 保留权重 >= threshold 的数据
		mask = (ages_hours >= 0) & (weights >= threshold)

		pruned_arr = events_arr[mask]

		if len(pruned_arr) < len(events_arr):
			filepath = Path(target_file)
			try:
				pruned_list = pruned_arr.astype(int).tolist()
				filepath.write_text(
					"".join(f"{ts}\n" for ts in pruned_list),
					encoding="utf-8",
				)
			except OSError as e:
				self.log_warning(f"数据剪枝失败: {e}")
				return events
			return pruned_list

		return events

	def _calculate_interval_stats(self, timestamps: list) -> tuple[float, float, int, int]:
		"""计算历史间隔统计量并动态设置间隔边界.

		Args:
			timestamps: 历史时间戳列表

		Returns:
			(mean_interval, variance, default_interval, max_interval)

		"""
		min_interval_samples = 5
		min_count_for_stats = 2

		if len(timestamps) < min_count_for_stats:
			return 3600.0, 0.0, 3600, 300

		timestamps_arr = np.array(sorted(timestamps), dtype=np.float64)
		intervals = np.diff(timestamps_arr)
		mean_interval = np.mean(intervals, dtype=np.float64)
		variance = np.var(intervals, dtype=np.float64)

		if len(timestamps) >= min_interval_samples:
			default_interval = float(np.median(intervals) * 0.8)
			min_5th = float(np.percentile(intervals, 5))
			max_interval = max(300, min_5th * 0.5)
			max_interval = min(max_interval, 3600)
		else:
			default_interval = 3600
			max_interval = 300

		return (
			float(mean_interval),
			float(variance),
			int(default_interval),
			int(max_interval),
		)

	def _learn_dimension_weights(
		self, timestamps: list, old_weights: dict, learning_rate: float
	) -> dict:
		"""动态学习各时间维度的权重.

		原理:统计各维度值的分布, 离散度(标准差)越小说明该维度越重要.
		得分 = mean(counts) / std(counts), 得分越高权重越大.

		Args:
			timestamps: 历史时间戳列表
			old_weights: 当前维度权重字典
			learning_rate: 学习率(控制新旧权重的混合比例)

		Returns:
			平滑后的新权重字典

		"""
		min_count_for_learning = 20  # 最小样本数才开始学习
		if len(timestamps) < min_count_for_learning:
			return old_weights

		# 提取原始时间维度值(小时、星期几、第几周、月份)
		raw_components = self._get_raw_time_components(
			np.array(timestamps, dtype=np.float64),
		)

		# 计算各维度得分:均值/标准差(反映分布集中度)
		dimension_scores = {}
		for dim in ["day", "week", "month_week", "year_month"]:
			keys = raw_components.get(dim, np.array([], dtype=np.int64))
			if len(keys) == 0:
				dimension_scores[dim] = 0.0
				continue

			# 统计每个维度值的出现次数
			_, counts = np.unique(keys, return_counts=True)
			counts_arr = counts.astype(np.float64)
			mean_val = np.mean(counts_arr)

			if mean_val == 0:
				dimension_scores[dim] = 0.0
			else:
				# 标准差越小, 分布越集中, 该维度越重要
				std_dev = np.std(counts_arr)
				if std_dev > 0:
					dimension_scores[dim] = float(mean_val / std_dev)
				else:
					dimension_scores[dim] = float(mean_val)

		# 归一化得分, 使总权重约为2
		scores_array = np.array(list(dimension_scores.values()), dtype=np.float64)
		total_score = np.sum(scores_array, dtype=np.float64)

		if total_score > 0:
			normalized_scores = scores_array / total_score * 2.0
			new_weights = dict(zip(dimension_scores.keys(), normalized_scores, strict=True))
		else:
			new_weights = old_weights

		# 指数平滑更新权重:新权重 * 学习率 + 旧权重 * (1 - 学习率)
		smoothed_weights = {}
		for key in dimension_scores:
			old_weight = old_weights[key]
			new_weight = new_weights[key]
			smoothed = old_weight * (1 - learning_rate) + new_weight * learning_rate
			smoothed_weights[key] = float(smoothed)

		return smoothed_weights

	def _learn_adaptive_sigmas(self, timestamps: list, old_sigmas: dict) -> dict:
		"""根据数据离散度动态学习 Sigma 参数.

		数学原理:
		- Sigma 应该反映数据的不确定性
		- 标准差小 -> 规律性强 -> Sigma 小 (精确匹配)
		- 标准差大 -> 规律性弱 -> Sigma 大 (宽松匹配)

		Args:
			timestamps: 历史时间戳列表
			old_sigmas: 当前的 sigma 字典

		Returns:
			学习后的 sigma 字典

		"""
		min_learn_count = 20
		min_sigma_samples = 3
		if len(timestamps) < min_learn_count:
			return old_sigmas

		raw_components = self._get_raw_time_components(
			np.array(timestamps, dtype=np.float64)
		)

		new_sigmas = {}
		for dim in ["day", "week", "month_week", "year_month"]:
			values = raw_components.get(dim, np.array([], dtype=np.int64))
			if len(values) >= min_sigma_samples:
				value_range = float(np.max(values) - np.min(values))
				if value_range > 0:
					normalized = (values.astype(np.float64) - np.min(values)) / value_range
					std = float(np.std(normalized))
					adaptive_sigma = max(0.2, min(std * 3.0, 3.0))

					old_sigma = old_sigmas.get(dim, 1.0)
					new_sigmas[dim] = old_sigma * 0.7 + adaptive_sigma * 0.3
				else:
					new_sigmas[dim] = old_sigmas.get(dim, 1.0)
			else:
				new_sigmas[dim] = old_sigmas.get(dim, 1.0)

		return new_sigmas

	def _format_frequency_interval(self, seconds: float) -> str:
		"""格式化频率间隔为人类可读字符串.

		Args:
			seconds: 间隔秒数

		Returns:
			格式化后的字符串, 如 "1 天 2 小时 30 秒"

		"""
		total_seconds = float(seconds)
		polling_days_float = total_seconds / 86400.0
		polling_hours_float = (total_seconds % 86400.0) / 3600.0
		polling_minutes_float = (total_seconds % 3600.0) / 60.0
		polling_seconds_float = total_seconds % 60.0

		polling_days = int(polling_days_float)
		polling_hours = int(polling_hours_float)
		polling_minutes = int(polling_minutes_float)
		polling_seconds = int(polling_seconds_float)

		polling_interval_parts = []
		if polling_days > 0:
			polling_interval_parts.append(f"{polling_days} 天")
		if polling_hours > 0:
			polling_interval_parts.append(f"{polling_hours} 小时")
		if polling_minutes > 0:
			polling_interval_parts.append(f"{polling_minutes} 分钟")
		if polling_seconds > 0 or not polling_interval_parts:
			polling_interval_parts.append(f"{polling_seconds} 秒")
		return " ".join(polling_interval_parts)

	def _calculate_adaptive_lambda(
		self, timestamps: list, last_variance: float, lambda_base: float
	) -> tuple[float, float]:
		"""自适应计算lambda参数(遗忘速度).

		策略:
		- 方差大 → 发布不规律 → 增大lambda(快速遗忘旧模式)
		- 方差小 → 发布规律 → 减小lambda(保留历史模式)
		- 方差增大 → 趋向不稳定 → 进一步增大lambda
		- 根据CV(变异系数)动态调整lambda范围

		Args:
			timestamps: 历史时间戳列表
			last_variance: 上次计算的方差
			lambda_base: lambda基础值

		Returns:
			(adaptive_lambda, current_variance)

		"""
		min_count_for_lambda = 2  # 最小样本数
		if len(timestamps) < min_count_for_lambda:
			return float(lambda_base), 0.0

		timestamps_arr = np.array(sorted(timestamps), dtype=np.float64)
		intervals = np.diff(timestamps_arr)
		current_variance = np.var(intervals, dtype=np.float64)

		mean_interval = np.mean(intervals)
		cv = np.std(intervals) / mean_interval if mean_interval > 0 else 1.0

		lambda_min = lambda_base * 0.3
		lambda_max = lambda_base * (1.0 + cv * 4.0)
		lambda_max = min(lambda_max, lambda_base * 15.0)

		if last_variance > 0:
			variance_trend_normalized = (current_variance - last_variance) / last_variance
		else:
			variance_trend_normalized = 0.0

		seconds_in_day_sq = 86400**2
		normalized_variance = current_variance / seconds_in_day_sq

		if normalized_variance > 0:
			lambda_factor = np.log(1 + normalized_variance * 10) / np.log(11)
		else:
			lambda_factor = 0

		base_adaptive_lambda = lambda_min + (lambda_max - lambda_min) * lambda_factor
		trend_correction = variance_trend_normalized * 0.3 * base_adaptive_lambda
		adaptive_lambda = base_adaptive_lambda + trend_correction

		final_lambda = np.clip(adaptive_lambda, lambda_min, lambda_max)

		return float(final_lambda), float(current_variance)

	def _initialize_wgmm_config(self) -> tuple[dict, dict, bool]:
		"""初始化 WGMM 配置参数.

		Returns:
			(dimension_weights, sigmas, is_manual_run)

		"""
		config = self.wgmm_config

		if "dimension_weights" not in config:
			config["dimension_weights"] = {
				"day": 0.5,
				"week": 1.0,
				"month_week": 0.3,
				"year_month": 0.2,
			}

		dimension_weights = config["dimension_weights"]

		if "sigmas" not in config:
			config["sigmas"] = {
				"day": 0.8,
				"week": 1.0,
				"month_week": 1.5,
				"year_month": 2.0,
			}

		sigmas = config["sigmas"]

		if self.dev_mode:
			is_manual_run = True
		else:
			is_manual_run = self.wgmm_config.get("is_manual_run", True)
			if is_manual_run:
				self.wgmm_config["is_manual_run"] = False

		return dimension_weights, sigmas, is_manual_run

	def _scan_future_peak(
		self,
		current_timestamp: int,
		base_frequency_sec: float,
		lookahead_days: int,
		gaussian_width: float,
		current_score: float,
		positive_events: list,
		negative_events: list,
		dimension_weights: dict,
		pos_lambda: float,
		neg_lambda: float,
		sigmas: dict,
		resistance_coefficient: float,
	) -> tuple[float | None, float]:
		"""扫描未来时间段寻找最佳发布峰值.

		策略:
		1. 在未来15天内按步长扫描时间点
		2. 使用 WGMM 算法批量计算每个时间点的得分
		3. 通过梯度检测找到局部峰值点
		4. 过滤低得分和高梯度的峰值, 确保找到可靠的高峰

		Args:
			current_timestamp: 当前时间戳
			base_frequency_sec: 基础检查间隔(秒)
			lookahead_days: 向前预测天数
			gaussian_width: 高斯核宽度(秒)
			current_score: 当前时间点的得分
			positive_events: 正向事件列表
			negative_events: 负向事件列表
			dimension_weights: 维度权重字典
			pos_lambda: 正向事件衰减率
			neg_lambda: 负向事件衰减率
			sigmas: Sigma 参数字典
			resistance_coefficient: 负向事件抑制系数

		Returns:
			(best_peak_time, best_peak_score) - 最佳峰值时间和得分, 无峰值则返回 (None, 0.0)

		"""
		seconds_in_day = 86400
		lookahead_seconds = lookahead_days * seconds_in_day
		lookahead_start = current_timestamp + base_frequency_sec
		lookahead_end = current_timestamp + lookahead_seconds

		min_step = float(gaussian_width * 0.25)
		scan_start = float(np.maximum(lookahead_start, current_timestamp + 600.0))

		best_peak_time = None
		best_peak_score = 0.0

		score_threshold = 0.5
		if lookahead_end > scan_start:
			scan_step = min_step if current_score > score_threshold else min_step * 2

			scan_times = np.arange(
				scan_start,
				lookahead_end + scan_step,
				scan_step,
				dtype=np.float64,
			)

			scan_scores = self._batch_calculate_scores(
				scan_times,
				positive_events,
				negative_events,
				dimension_weights,
				pos_lambda,
				neg_lambda,
				sigmas,
				resistance_coefficient,
			)

			if len(scan_scores) > 1:
				gradients = np.diff(scan_scores)
				peaks_mask = (gradients[:-1] > 0) & (gradients[1:] < 0)

				peak_score_threshold = 0.7
				gradient_threshold = 0.05
				for i in range(len(peaks_mask)):
					if peaks_mask[i]:
						scan_idx = i + 1
						score_condition = scan_scores[scan_idx] > peak_score_threshold
						gradient_condition = abs(gradients[i]) < gradient_threshold
						if score_condition and gradient_condition:
							peaks_mask[i] = True

				peak_indices = np.where(peaks_mask)[0]

				if len(peak_indices) > 0:
					peak_scores = scan_scores[peak_indices]
					best_idx_in_peaks = np.argmax(peak_scores)
					best_peak_idx = peak_indices[best_idx_in_peaks]

					if peak_scores[best_idx_in_peaks] > best_peak_score:
						best_peak_score = float(peak_scores[best_idx_in_peaks])
						best_peak_time = float(scan_times[best_peak_idx])

		return best_peak_time, best_peak_score

	def adjust_check_frequency(self, found_new_content: bool = False) -> None:
		"""WGMM算法核心函数 - 根据历史数据自适应调整检查间隔.

		算法流程:
		1. 加载正向事件(视频发布)和负向事件(检测未发现)历史数据
		2. 使用四维时间特征(日/周/月周/年月)计算时间相似性
		3. 高斯核函数评估当前时间点的发布概率
		4. 指数衰减权重赋予新数据更高优先级
		5. 预测未来15天内的发布峰值, 提前5分钟检查
		6. 根据yt-dlp执行时间动态调整检查间隔

		Args:
			found_new_content: 本次检查是否发现新内容(影响负向事件记录)

		"""
		# Lambda参数基础值:指数衰减率, 控制历史记忆的遗忘速度
		lambda_base = 0.0001  # 基础衰减率

		# 固定参数(不随数据变化)
		mapping_curve = 2.0  # 映射曲线指数, 控制得分对间隔的影响
		min_history_count = 10  # 最小历史数据量, 少于此时进入学习期模式
		prune_threshold = 1000  # 数据剪枝阈值, 超过此数量才进行剪枝
		lookahead_days = 15  # 峰值预测窗口(天)
		peak_advance_minutes = 5  # 峰值提前检查时间(分钟)
		seconds_in_day = 86400  # 一天的秒数

		# 初始化配置
		dimension_weights_from_config, sigmas_from_config, is_manual_run = (
			self._initialize_wgmm_config()
		)

		current_timestamp = int(time.time())

		# 确保 mtime.txt 文件存在
		mtime_file_path = Path(self.mtime_file)
		if not mtime_file_path.exists() and not self.generate_mtime_file(
			"adjust_check_frequency"
		):
			if not self.dev_mode:
				self.save_next_check_time(int(time.time()) + 7200)
			return

		# 加载正向和负向事件历史
		positive_events = self._load_history_file(self.mtime_file)
		negative_events = self._load_miss_history()

		# 过滤异常值
		positive_events = self._filter_outliers(positive_events, current_timestamp)
		negative_events = self._filter_outliers(negative_events, current_timestamp)

		total_events = len(positive_events) + len(negative_events)
		weight_threshold = max(0.0001, 0.001 * (100 / (total_events + 50)))
		learning_rate = max(0.02, min(0.2, 0.3 - len(positive_events) * 0.001))

		# 剪枝旧数据
		last_lambda = self.wgmm_config.get("last_lambda", lambda_base)
		# 只有当历史数据超过阈值时才进行剪枝, 避免数据量过小时丢失重要信息
		if len(positive_events) >= prune_threshold:
			positive_events = self._prune_old_data(
				positive_events, last_lambda, weight_threshold, current_timestamp
			)
			negative_events = self._prune_old_data(
				negative_events, last_lambda, weight_threshold, current_timestamp
			)

		# 检查正向数据是否充足
		pos_sufficient = len(positive_events) >= min_history_count

		if not pos_sufficient:
			self.log_info(f"正向数据不足({len(positive_events)}条), 进入学习期模式")
			mtime_file_path = Path(self.mtime_file)
			if not mtime_file_path.exists():
				self.generate_mtime_file("学习期数据不足")
			if not self.dev_mode:
				self.save_next_check_time(int(time.time()) + 3600)
			if is_manual_run:
				self.wgmm_config["is_manual_run"] = False
				self._save_wgmm_config()
			return

		# 计算间隔统计量
		base_interval, _, _default_interval, max_interval = self._calculate_interval_stats(
			positive_events
		)

		# 自适应计算 Lambda 参数
		last_pos_variance = self.wgmm_config.get("last_pos_variance", 0.0)
		pos_lambda, pos_current_variance = self._calculate_adaptive_lambda(
			positive_events,
			last_pos_variance,
			lambda_base,
		)
		last_neg_variance = self.wgmm_config.get("last_neg_variance", 0.0)

		neg_lambda, neg_current_variance = self._calculate_adaptive_lambda(
			negative_events,
			last_neg_variance,
			lambda_base,
		)

		# 学习维度权重和 Sigma 参数
		dimension_weights = self._learn_dimension_weights(
			positive_events,
			dimension_weights_from_config,
			learning_rate,
		)

		learned_sigmas = self._learn_adaptive_sigmas(positive_events, sigmas_from_config)
		sigmas = {
			"day": float(learned_sigmas["day"]),
			"week": float(learned_sigmas["week"]),
			"month_week": float(learned_sigmas["month_week"]),
			"year_month": float(learned_sigmas["year_month"]),
		}

		intervals = np.diff(np.array(sorted(positive_events), dtype=np.float64))
		cv = float(np.std(intervals) / np.mean(intervals)) if len(intervals) > 0 else 1.0
		resistance_coefficient = 0.7 + 0.2 / (1.0 + cv)
		resistance_coefficient = float(np.clip(resistance_coefficient, 0.5, 0.95))

		current_score = self._calculate_point_score(
			current_timestamp,
			positive_events,
			negative_events,
			dimension_weights,
			pos_lambda,
			neg_lambda,
			sigmas,
			resistance_coefficient,
		)

		exponential_score = current_score**mapping_curve
		base_interval_sec = (
			base_interval - (base_interval - max_interval) * exponential_score
		)

		base_frequency_sec = np.clip(base_interval_sec, max_interval, base_interval * 2)

		gaussian_width = (sigmas["day"] * seconds_in_day / 24.0) * 2.0
		best_peak_time, best_peak_score = self._scan_future_peak(
			current_timestamp=current_timestamp,
			base_frequency_sec=base_frequency_sec,
			lookahead_days=lookahead_days,
			gaussian_width=gaussian_width,
			current_score=current_score,
			positive_events=positive_events,
			negative_events=negative_events,
			dimension_weights=dimension_weights,
			pos_lambda=pos_lambda,
			neg_lambda=neg_lambda,
			sigmas=sigmas,
			resistance_coefficient=resistance_coefficient,
		)

		final_frequency_sec = base_frequency_sec
		best_peak_threshold = 0.6
		if best_peak_time and best_peak_score > best_peak_threshold:
			peak_interval = best_peak_time - current_timestamp
			if peak_interval < base_frequency_sec * 1.2:
				advanced_time = best_peak_time - (peak_advance_minutes * 60.0)
				advanced_interval = advanced_time - current_timestamp
				min_advanced_interval = 300
				if advanced_interval > min_advanced_interval:
					final_frequency_sec = float(advanced_interval)

		impedance_factor = 1.0
		last_duration = self.last_ytdlp_duration
		normal_duration = self.normal_ytdlp_duration

		if last_duration > normal_duration * 2.0:
			impedance_ratio = last_duration / max(normal_duration, 1.0)
			impedance_factor = 1.0 + min(0.5, (impedance_ratio - 2.0) * 0.1)

		final_frequency_sec = float(final_frequency_sec * impedance_factor)
		if not found_new_content and not is_manual_run:
			self._save_miss_history(current_timestamp, is_manual_run)

		next_check_timestamp = int(time.time()) + int(final_frequency_sec)
		self.save_next_check_time(next_check_timestamp)

		self.wgmm_config["last_update"] = current_timestamp
		self.wgmm_config["next_check_time"] = next_check_timestamp
		self.wgmm_config["dimension_weights"] = dimension_weights
		self.wgmm_config["sigmas"] = sigmas
		self.wgmm_config["last_lambda"] = pos_lambda
		self.wgmm_config["last_pos_variance"] = pos_current_variance
		self.wgmm_config["last_neg_variance"] = neg_current_variance

		if not self.dev_mode:
			self._save_wgmm_config()

		polling_interval_str = self._format_frequency_interval(final_frequency_sec)
		self.log_info(f"WGMM调频 - 轮询间隔: {polling_interval_str}")

	def run_yt_dlp(
		self,
		command_args: list[str],
		timeout: int = 300,
	) -> tuple[bool, str, str]:
		if self.yt_dlp_path is None:
			self.yt_dlp_path = shutil.which("yt-dlp")
			if not self.yt_dlp_path:
				self.log_error("未找到 yt-dlp 可执行文件, 请检查是否安装.")
				return False, "", "没有找到 yt-dlp 可执行文件"

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
			self.last_ytdlp_duration = elapsed

			if result.returncode == 0:
				self.normal_ytdlp_duration = (
					0.9 * self.normal_ytdlp_duration + 0.1 * elapsed
				)

			return result.returncode == 0, result.stdout.strip(), result.stderr.strip()
		except subprocess.TimeoutExpired:
			elapsed = time.time() - start_time
			self.last_ytdlp_duration = elapsed
			self.log_warning(f"yt-dlp 命令超时: {' '.join(command_args[:3])}...")
			return False, "", "命令超时"
		except (OSError, ValueError) as e:
			elapsed = time.time() - start_time
			self.last_ytdlp_duration = elapsed
			self.log_error(f"执行 yt-dlp 命令失败: {e}", send_bark_notification=False)
			return False, "", str(e)

	def quick_precheck(self) -> bool:
		"""第二层检测:快速ID检查(轻量级检查).

		策略:只获取最新视频的ID, 与已知URL对比, 判断是否需要完整扫描.
		优势:相比完整扫描节省90%以上的流量和时间.

		Returns:
			bool: True表示需要完整检查, False表示可以跳过

		"""
		if not self.memory_urls:
			self.log_info("memory_urls 为空, 触发完整检查")
			return True

		# 只获取第一个视频的ID(--playlist-end 1)
		success, stdout, _stderr = self.run_yt_dlp(
			[
				"--cookies",
				self.cookies_file,
				"--flat-playlist",
				"--print",
				"%(id)s",
				"--playlist-end",
				"1",
				f"https://space.bilibili.com/{self.BILIBILI_UID}/video",
			],
		)

		if not success or not stdout:
			self.log_info("快速检查失败, 触发完整检查")
			return True

		latest_id = stdout.strip()
		# 检查最新ID是否在已知URL中
		video_exists = any(latest_id in url for url in self.memory_urls)

		return not video_exists

	def check_potential_new_parts(self) -> bool:
		"""第一层检测:分片预检查(预测性检查).

		策略:从已知视频URL中提取分片信息, 预测是否存在下一分片.
		例如:已知视频A有分片1-3, 尝试访问分片4, 成功则说明有新分片.

		Returns:
			bool: 是否发现新分片

		"""
		if not self.memory_urls:
			self.log_info("内存数据为空, 跳过分片预检查")
			return False

		has_new_parts = False

		try:
			# 提取所有分P视频的最大分片号
			base_urls = {}
			for url in self.memory_urls:
				if "?p=" in url:
					base_url = url.split("?p=")[0]
					part_str = url.split("?p=")[1]
					try:
						part_num = int(part_str)
						if base_url not in base_urls or part_num > base_urls[base_url]:
							base_urls[base_url] = part_num
					except ValueError:
						continue

			# 对每个多P视频, 预测下一分片是否存在
			for base_url, max_part in base_urls.items():
				if max_part > 1:
					next_part = max_part + 1
					next_url = f"{base_url}?p={next_part}"

					success, _, _ = self.run_yt_dlp(
						["--cookies", self.cookies_file, "--simulate", next_url],
					)

					if success:
						has_new_parts = True

						# 继续预测更多分片(最多额外检查5个)
						check_part = next_part + 1
						while check_part <= next_part + 5:
							check_url = f"{base_url}?p={check_part}"
							success, _, _ = self.run_yt_dlp(
								[
									"--cookies",
									self.cookies_file,
									"--simulate",
									check_url,
								],
							)
							if success:
								check_part += 1
							else:
								break

		except (ValueError, OSError) as e:
			self.log_warning(f"预测检查出错: {e}")
			return False

		return has_new_parts

	def get_video_parts(self, video_url: str) -> list[str]:
		"""获取单个视频的所有分P URL."""
		success, stdout, _stderr = self.run_yt_dlp(
			[
				"--cookies",
				self.cookies_file,
				"--flat-playlist",
				"--print",
				"%(webpage_url)s",
				video_url,
			],
		)

		if success and stdout:
			return [line.strip() for line in stdout.split("\n") if line.strip()]
		_success, _stdout, _stderr = self.run_yt_dlp(
			[
				"--cookies",
				self.cookies_file,
				"--flat-playlist",
				"--print",
				"%(webpage_url)s",
				video_url,
			],
		)
		return []

	def get_all_videos_parallel(self, video_urls: list[str]) -> list[str]:
		all_parts = []
		Path(self.tmp_outputs_dir).mkdir(exist_ok=True)

		try:
			with ThreadPoolExecutor(max_workers=5) as executor:
				future_to_url = {
					executor.submit(self.get_video_parts, url): url for url in video_urls
				}

				for future in as_completed(future_to_url):
					url = future_to_url[future]
					try:
						parts = future.result()
						all_parts.extend(parts)
					except (ValueError, OSError) as e:
						self.log_warning(f"处理分片出错: {str(url)[:50]}... {e}")

		except (ValueError, OSError) as e:
			self.log_critical_error(
				f"并行处理时出错: {e}",
				"get_all_videos_parallel 方法",
				send_notification=True,
			)

		return all_parts

	def cleanup(self) -> None:
		tmp_outputs_path = Path(self.tmp_outputs_dir)
		try:
			if tmp_outputs_path.exists():
				shutil.rmtree(tmp_outputs_path)
		except OSError as e:
			self.log_critical_error(
				f"清理临时文件失败: {e}",
				"cleanup 方法",
				send_notification=False,
			)

		if self.dev_mode:
			try:
				temp_dirs = ["temp_info_json"]
				for temp_dir in temp_dirs:
					temp_path = Path(temp_dir)
					if temp_path.exists():
						shutil.rmtree(temp_path)
			except OSError:
				pass

	def wait_for_next_check(self) -> None:
		"""等待到下次检查时间."""
		try:
			next_check_timestamp = self.get_next_check_time()

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
					self.log_info(
						f"距离上次检查时间已过 {abs(wait_seconds)} 秒, 立即开始检查",
					)
					return

				if self.dev_mode:
					self.log_info(f"下次检查: {next_check_time}")
					return

				self.log_info(f"下次检查: {next_check_time}")
				time.sleep(wait_seconds)
			else:
				self.log_info("未找到保存的检查时间, 立即开始首次检查")
				return

		except (FileNotFoundError, ValueError) as e:
			self.log_info(f"配置文件异常 ({e}), 立即开始检查")
			return
		except OSError as e:
			self.log_warning(f"等待逻辑异常: {e}, 使用默认等待")
			if not self.dev_mode:
				frequency_sec = 24000
				time.sleep(frequency_sec)
			else:
				self.log_info("Dev模式下跳过异常等待")

	def _get_local_timezone_offset(self) -> float:
		"""获取本地时区偏移量(秒)."""
		if time.localtime().tm_isdst and time.daylight:
			return -time.altzone
		return -time.timezone

	def _vectorized_time_features_numpy(self, timestamps_array: np.ndarray) -> dict:
		"""向量化提取时间特征(NumPy优化版).

		使用sin/cos编码将周期性时间转换为连续特征, 解决23:00和00:00距离远的问题.
		编码公式:value = [sin(2π*t/period), cos(2π*t/period)]

		Args:
			timestamps_array: Unix时间戳数组

		Returns:
			包含8个特征的字典:day/cos, week/cos, month_week/cos, year_month/cos

		"""
		if len(timestamps_array) == 0:
			return {
				"day_sin": np.array([], dtype=np.float64),
				"day_cos": np.array([], dtype=np.float64),
				"week_sin": np.array([], dtype=np.float64),
				"week_cos": np.array([], dtype=np.float64),
				"month_week_sin": np.array([], dtype=np.float64),
				"month_week_cos": np.array([], dtype=np.float64),
				"year_month_sin": np.array([], dtype=np.float64),
				"year_month_cos": np.array([], dtype=np.float64),
			}

		ts_arr = np.array(timestamps_array, dtype=np.float64)
		offset = self._get_local_timezone_offset()
		dt64_local = (ts_arr + offset).astype("datetime64[s]")

		# 提取各时间维度
		seconds_in_day = (dt64_local.astype("int64") % 86400).astype(np.float64)
		days_since_epoch = dt64_local.astype("datetime64[D]").astype("int64")
		weekday = (days_since_epoch + 3) % 7  # 0=周一, 6=周日
		dates_m = dt64_local.astype("datetime64[M]")
		months = (dates_m - dates_m.astype("datetime64[Y]")).astype(int) + 1

		# 计算月中的第几周(1-6)
		day_of_month = (
			dt64_local.astype("datetime64[D]") - dates_m.astype("datetime64[D]")
		).astype(int) + 1
		first_day_epoch = dates_m.astype("datetime64[D]").astype("int64")
		first_weekday = (first_day_epoch + 3) % 7
		current_week_of_month = (day_of_month - 1 + first_weekday) // 7 + 1

		# 周内秒数(用于周周期编码)
		current_second_of_week = weekday * 86400.0 + seconds_in_day

		# sin/cos编码各维度
		features = {}
		const_2pi = 2 * np.pi

		features["day_sin"] = np.sin(const_2pi * seconds_in_day / 86400.0)
		features["day_cos"] = np.cos(const_2pi * seconds_in_day / 86400.0)
		features["week_sin"] = np.sin(const_2pi * current_second_of_week / 604800.0)
		features["week_cos"] = np.cos(const_2pi * current_second_of_week / 604800.0)
		features["month_week_sin"] = np.sin(const_2pi * current_week_of_month / 6.0)
		features["month_week_cos"] = np.cos(const_2pi * current_week_of_month / 6.0)
		features["year_month_sin"] = np.sin(const_2pi * months / 12.0)
		features["year_month_cos"] = np.cos(const_2pi * months / 12.0)

		return features

	def _get_raw_time_components(self, timestamps_array: np.ndarray) -> dict:
		"""提取原始时间维度值(用于权重学习).

		返回离散的整数值, 用于统计各维度的分布集中度.

		Args:
			timestamps_array: Unix时间戳数组

		Returns:
			包含4个维度的字典:day(0-23), week(0-6), month_week(1-6), year_month(1-12)

		"""
		if len(timestamps_array) == 0:
			return {
				"day": np.array([], dtype=np.int64),
				"week": np.array([], dtype=np.int64),
				"month_week": np.array([], dtype=np.int64),
				"year_month": np.array([], dtype=np.int64),
			}

		ts_arr = np.array(timestamps_array, dtype=np.float64)
		offset = self._get_local_timezone_offset()
		dt64_local = (ts_arr + offset).astype("datetime64[s]")

		seconds_in_day = dt64_local.astype("int64") % 86400
		days_since_epoch = dt64_local.astype("datetime64[D]").astype("int64")
		dates_m = dt64_local.astype("datetime64[M]")

		# 提取各维度的整数值
		hours = (seconds_in_day // 3600).astype(np.int64)  # 0-23
		weekday = (days_since_epoch + 3) % 7  # 0=周一, 6=周日
		months = (dates_m - dates_m.astype("datetime64[Y]")).astype(int) + 1  # 1-12

		day_of_month = (
			dt64_local.astype("datetime64[D]") - dates_m.astype("datetime64[D]")
		).astype(int) + 1
		first_day_epoch = dates_m.astype("datetime64[D]").astype("int64")
		first_weekday = (first_day_epoch + 3) % 7
		month_week = (day_of_month - 1 + first_weekday) // 7 + 1  # 1-6

		return {
			"day": hours,
			"week": weekday,
			"month_week": month_week,
			"year_month": months,
		}

	def _calculate_point_score(
		self,
		target_timestamp: float,
		pos_events: list,
		neg_events: list,
		dimension_weights: dict,
		pos_lambda: float,
		neg_lambda: float,
		sigmas: dict,
		resistance_coefficient: float,
	) -> float:
		"""计算单个时间点的发布概率得分(WGMM核心).

		算法步骤:
		1. 计算目标时间与历史事件的四维时间距离(sin/cos编码的欧氏距离)
		2. 各维度距离经高斯核转换: exp(-dist² / (2*sigma²))
		3. 加权求和得到相似度得分
		4. 应用指数时间衰减: exp(-lambda * age_hours)
		5. 归一化到[0, 1], 用负向事件抑制正向得分

		Args:
			target_timestamp: 目标时间戳
			pos_events: 正向事件列表(历史发布时间)
			neg_events: 负向事件列表(历史检测失败时间)
			dimension_weights: 四个维度的权重字典
			pos_lambda: 正向事件的衰减率
			neg_lambda: 负向事件的衰减率
			sigmas: 各维度的高斯核标准差
			resistance_coefficient: 负向事件抑制系数

		Returns:
			0-1之间的概率得分, 越高越可能发布新内容

		"""
		target_feat = self._vectorized_time_features_numpy(np.array([target_timestamp]))
		current_features = {k: v[0] for k, v in target_feat.items()}

		def calculate_source_score_vectorized(events_array, lambda_decay):
			"""计算事件数组的得分(向量化实现).

			Args:
				events_array: 历史事件时间戳列表
				lambda_decay: 指数衰减率

			Returns:
				归一化后的得分(0-1)

			"""
			if not events_array:
				return 0.0

			events_arr = np.array(events_array, dtype=np.float64)
			events_feat = self._vectorized_time_features_numpy(events_arr)

			# 计算时间年龄并过滤未来事件
			ages_hours = (target_timestamp - events_arr) / 3600.0
			valid_mask = ages_hours >= 0
			if not np.any(valid_mask):
				return 0.0

			# 指数衰减权重:越新的事件权重越大
			valid_ages = ages_hours[valid_mask]
			weights = np.exp(-lambda_decay * valid_ages, dtype=np.float64)

			# 计算各维度在sin/cos空间中的欧氏距离平方
			def dist_sq(key):
				return (
					current_features[f"{key}_sin"] - events_feat[f"{key}_sin"][valid_mask]
				) ** 2 + (
					current_features[f"{key}_cos"] - events_feat[f"{key}_cos"][valid_mask]
				) ** 2

			# 多维高斯核加权求和: 相似度 = sum(weight * exp(-dist² / (2*sigma²)))
			combined = (
				dimension_weights["day"]
				* np.exp(-dist_sq("day") / (2 * sigmas["day"] ** 2), dtype=np.float64)
				+ dimension_weights["week"]
				* np.exp(-dist_sq("week") / (2 * sigmas["week"] ** 2), dtype=np.float64)
				+ dimension_weights["month_week"]
				* np.exp(
					-dist_sq("month_week") / (2 * sigmas["month_week"] ** 2),
					dtype=np.float64,
				)
				+ dimension_weights["year_month"]
				* np.exp(
					-dist_sq("year_month") / (2 * sigmas["year_month"] ** 2),
					dtype=np.float64,
				)
			)

			# 时间衰减权重 * 相似度
			scores = weights * combined
			if len(scores) == 0:
				return 0.0

			total = np.sum(scores, dtype=np.float64)
			count = len(scores)

			if count == 1:
				return float(np.clip(scores[0], 0.0, 1.0))

			# 归一化到[0, 1]:(均值 - 最小值) / (最大值 - 最小值)
			min_val, max_val = np.min(scores), np.max(scores)
			if max_val > min_val:
				return float(
					np.clip((total / count - min_val) / (max_val - min_val), 0.0, 1.0),
				)
			return 0.5

		# 计算正向和负向得分
		pos_score = calculate_source_score_vectorized(pos_events, pos_lambda)
		neg_score = (
			calculate_source_score_vectorized(neg_events, neg_lambda) if neg_events else 0.0
		)

		# 最终得分 = 正向得分 - 抑制系数 * 负向得分
		return float(
			np.clip(pos_score - (resistance_coefficient * neg_score), 0.0, 1.0),
		)

	def _batch_calculate_scores(
		self,
		scan_times: np.ndarray,
		pos_events: list,
		neg_events: list,
		dimension_weights: dict,
		pos_lambda: float,
		neg_lambda: float,
		sigmas: dict,
		resistance_coefficient: float,
	) -> np.ndarray:
		"""批量计算多个时间点的得分(向量化实现).

		用于峰值预测扫描, 一次性计算未来数百个时间点的得分.
		优化策略:使用广播机制避免显式循环.

		Args:
			scan_times: 要扫描的时间点数组
			其他参数同 _calculate_point_score

		Returns:
			与scan_times等长的得分数组

		"""
		if len(scan_times) == 0:
			return np.array([], dtype=np.float64)

		targets_feat = self._vectorized_time_features_numpy(scan_times)

		def get_source_scores_vectorized(events, lambda_decay):
			"""向量化计算事件集对所有扫描点的得分矩阵.

			返回形状: (len(scan_times),)
			"""
			if not events:
				return np.zeros(len(scan_times), dtype=np.float64)

			events_arr = np.array(events, dtype=np.float64)
			events_feat = self._vectorized_time_features_numpy(events_arr)

			# 广播计算:ages[scan_count, event_count]
			ages = (scan_times[:, np.newaxis] - events_arr[np.newaxis, :]) / 3600.0
			valid_mask = ages >= 0
			weights = np.zeros_like(ages, dtype=np.float64)
			weights[valid_mask] = np.exp(-lambda_decay * ages[valid_mask])

			# 计算各维度距离矩阵(广播机制)
			day_dist_sq = (
				targets_feat["day_sin"][:, np.newaxis]
				- events_feat["day_sin"][np.newaxis, :]
			) ** 2 + (
				targets_feat["day_cos"][:, np.newaxis]
				- events_feat["day_cos"][np.newaxis, :]
			) ** 2
			week_dist_sq = (
				targets_feat["week_sin"][:, np.newaxis]
				- events_feat["week_sin"][np.newaxis, :]
			) ** 2 + (
				targets_feat["week_cos"][:, np.newaxis]
				- events_feat["week_cos"][np.newaxis, :]
			) ** 2
			month_week_dist_sq = (
				targets_feat["month_week_sin"][:, np.newaxis]
				- events_feat["month_week_sin"][np.newaxis, :]
			) ** 2 + (
				targets_feat["month_week_cos"][:, np.newaxis]
				- events_feat["month_week_cos"][np.newaxis, :]
			) ** 2
			year_month_dist_sq = (
				targets_feat["year_month_sin"][:, np.newaxis]
				- events_feat["year_month_sin"][np.newaxis, :]
			) ** 2 + (
				targets_feat["year_month_cos"][:, np.newaxis]
				- events_feat["year_month_cos"][np.newaxis, :]
			) ** 2

			combined_gaussian = np.zeros_like(day_dist_sq, dtype=np.float64)

			dist_sq_dict = {
				"day": day_dist_sq,
				"week": week_dist_sq,
				"month_week": month_week_dist_sq,
				"year_month": year_month_dist_sq,
			}

			# 加权求和各维度的高斯核得分
			for dim, dist_sq in dist_sq_dict.items():
				weight = dimension_weights[dim]
				sigma = sigmas[dim]

				coeff = -0.5 / (sigma**2)

				combined_gaussian += weight * np.exp(dist_sq * coeff, dtype=np.float64)

			# 最终得分 = 时间衰减 * 高斯相似度
			raw_scores = weights * combined_gaussian * valid_mask

			total_scores = np.sum(raw_scores, axis=1, dtype=np.float64)
			valid_counts = np.sum(valid_mask, axis=1)

			# 按行归一化到[0, 1]
			with np.errstate(divide="ignore", invalid="ignore"):
				row_mins = np.min(np.where(valid_mask, raw_scores, np.inf), axis=1)
				row_maxs = np.max(np.where(valid_mask, raw_scores, -np.inf), axis=1)
				normalized_scores = (
					total_scores / np.maximum(valid_counts, 1.0) - row_mins
				) / (row_maxs - row_mins + 1e-9)
				result = np.where(valid_counts > 0, normalized_scores, 0.0)

			return np.clip(result, 0.0, 1.0)

		pos_scores = get_source_scores_vectorized(pos_events, pos_lambda)
		neg_scores = get_source_scores_vectorized(neg_events, neg_lambda)
		return np.clip(pos_scores - (resistance_coefficient * neg_scores), 0.0, 1.0)

	def run_monitor(self) -> None:
		"""第三层检测:完整深度检查(主监控流程).

		执行流程:
		1. 从 GitHub Gist 同步已知URL
		2. 执行分片预检查(第一层)
		3. 执行快速ID检查(第二层)
		4. 如果预检查通过, 执行完整扫描(第三层)
		5. 对比URL, 识别新视频
		6. 保存新视频的上传时间戳
		7. 调用 WGMM 算法调整下次检查间隔
		8. 发送 Bark 通知

		双层URL管理:
		- memory_urls: 从 Gist 同步的已备份URL
		- known_urls: 本地已知URL(memory + 未同步的新URL)
		- truly_new_urls: 既不在 memory 也不在 known 中的URL(才触发通知)

		"""
		try:
			self.log_message("检查开始                  <--")
			sync_success = self.sync_urls_from_gist()

			if not sync_success and not self.memory_urls:
				self.log_warning(
					"无法获取基准数据 (Gist 失败且内存 urls 为空), 跳过本次检查",
				)
				self.cleanup()
				return

			# 第一层:分片预检查
			found_new_parts = self.check_potential_new_parts()
			# 第二层:快速ID检查
			found_new_videos = self.quick_precheck()

			parts_result = "发现新内容" if found_new_parts else "无新内容"
			videos_result = "发现新内容" if found_new_videos else "无新内容"
			self.log_info(
				f"预检查完成 - 预测检查: {parts_result} 快速检查: {videos_result}",
			)

			# 如果两层预检查都未发现新内容, 直接调整频率并退出
			if not (found_new_parts or found_new_videos):
				self.adjust_check_frequency(found_new_content=False)
				self.cleanup()
				return

			# 第三层:完整深度检查(获取所有视频URL)
			success, stdout, _stderr = self.run_yt_dlp(
				[
					"--cookies",
					self.cookies_file,
					"--flat-playlist",
					"--print",
					"%(webpage_url)s",
					f"https://space.bilibili.com/{self.BILIBILI_UID}/video",
				],
			)

			if not success or not stdout:
				self.log_critical_error(
					"无法获取视频列表",
					"完整检查阶段",
					send_notification=True,
				)
				self.adjust_check_frequency(found_new_content=False)
				self.cleanup()
				return

			video_urls = [line.strip() for line in stdout.split("\n") if line.strip()]

			if not video_urls:
				self.log_critical_error(
					"未获取到任何内容",
					"完整检查阶段",
					send_notification=True,
				)
				self.adjust_check_frequency(found_new_content=False)
				self.cleanup()
				return

			# 并行获取所有视频的分片信息
			all_parts = self.get_all_videos_parallel(video_urls)

			if not all_parts:
				self.log_info("处理分片时出错, 错误已处理")
				all_parts = video_urls

			# 双层URL对比逻辑
			existing_urls_set = set(self.memory_urls)
			current_urls_set = set(all_parts)

			# Gist中缺失的URL(可能已更新, 也可能未同步)
			gist_missing_urls = current_urls_set - existing_urls_set
			# 真正的新URL(既不在Gist, 也不在本地已知列表)
			truly_new_urls = gist_missing_urls - self.known_urls

			if gist_missing_urls:
				old_count = len(gist_missing_urls) - len(truly_new_urls)
				new_count = len(truly_new_urls)

				separator = " " if old_count > 0 and new_count > 0 else ""
				display = f"{'*' * old_count}{separator}{'*' * new_count}"
				self.log_info(display)

				# 保存真正的新视频的上传时间戳(用于WGMM算法学习)
				if truly_new_urls:
					self.save_real_upload_timestamps(truly_new_urls)

				# 更新已知URL列表
				self.known_urls.update(gist_missing_urls)
				self.save_known_urls()

				if self.dev_mode:
					self.dev_new_videos += len(gist_missing_urls)
				elif not self.notify_new_videos(
					len(gist_missing_urls),
					has_new_parts=found_new_parts,
				):
					self.log_critical_error(
						"通知发送失败 - 无法向用户推送新视频通知",
						"notify_new_videos",
						send_notification=False,
					)

				# 根据是否发现真正的新内容调整检查频率
				if truly_new_urls:
					self.adjust_check_frequency(found_new_content=True)
				else:
					self.adjust_check_frequency(found_new_content=False)
			elif found_new_parts:
				self.log_info("完整检查未发现新视频 - 但发现新分片, 已处理")
				self.adjust_check_frequency(found_new_content=True)
			else:
				self.log_info("完整检查未发现新内容 - 快速检查结果已确认, 无更新")
				self.adjust_check_frequency(found_new_content=False)

			self.cleanup()

		except KeyboardInterrupt:
			self.log_info("收到中断信号, 正在退出...")
			self.cleanup()
			sys.exit(0)
		except (OSError, json.JSONDecodeError, subprocess.SubprocessError) as e:
			self.log_critical_error(
				f"监控脚本运行时出现意外错误: {e}",
				"run_monitor",
				send_notification=True,
			)
			self.cleanup()


def main() -> None:
	load_env_file()
	args = parse_arguments()
	monitor = VideoMonitor(dev_mode=args.dev)

	if args.dev:
		try:
			monitor.run_monitor()
			monitor.wait_for_next_check()
			sys.exit(0)
		except KeyboardInterrupt:
			monitor.log_info("程序被用户中断")
			monitor.cleanup()
			sys.exit(0)
		except (OSError, json.JSONDecodeError, subprocess.SubprocessError) as e:
			monitor.log_critical_error(
				f"运行出错: {e}",
				"main(dev)",
				send_notification=False,
			)
			sys.exit(1)

	else:
		try:
			config_file = Path(monitor.wgmm_config_file)
			if config_file.exists():
				try:
					config = json.loads(config_file.read_text(encoding="utf-8"))
					if "is_manual_run" not in config:
						config["is_manual_run"] = True
						config_file.write_text(
							json.dumps(config, indent=2, ensure_ascii=False),
							encoding="utf-8",
						)
						monitor.log_info("首次运行, 已设置 is_manual_run = True")
				except (OSError, json.JSONDecodeError) as e:
					monitor.log_warning(f"初始化运行标志失败: {e}")
			else:
				monitor.log_info("首次运行, 将自动初始化配置")
		except OSError as e:
			monitor.log_warning(f"初始化检查失败: {e}")

		try:
			while True:
				monitor.wait_for_next_check()
				monitor.run_monitor()
		except KeyboardInterrupt:
			monitor.log_info("程序被用户中断")
			monitor.cleanup()
			sys.exit(0)
		except (OSError, json.JSONDecodeError, subprocess.SubprocessError) as e:
			monitor.log_critical_error(
				f"主循环出现严重错误: {e}",
				"main",
				send_notification=True,
			)
			sys.exit(1)


if __name__ == "__main__":
	main()
