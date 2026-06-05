"""B站视频检测业务."""

from __future__ import annotations

import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from wgmm_monitor.clients.bilibili_api import BilibiliApiClient, extract_bvid
from wgmm_monitor.clients.ytdlp import YtDlpClient
from wgmm_monitor.models import AppConfig, YtDlpResult
from wgmm_monitor.runtime_logger import RuntimeLogger


class BilibiliService:
	"""封装三层检测中与 B站/yt-dlp 有关的逻辑."""

	def __init__(
		self,
		config: AppConfig,
		ytdlp_client: YtDlpClient,
		api_client: BilibiliApiClient,
		cookies_file: Path,
		logger: RuntimeLogger,
	) -> None:
		"""初始化 B站检测所需依赖."""
		self.config = config
		self.ytdlp_client = ytdlp_client
		self.api_client = api_client
		self.cookies_file = cookies_file
		self.logger = logger

	def run_yt_dlp(
		self,
		command_args: list[str],
		timeout: int = 300,
	) -> YtDlpResult:
		"""透传执行 yt-dlp."""
		return self.ytdlp_client.run(command_args, timeout=timeout)

	def quick_precheck(self, memory_urls: list[str], known_urls: set[str]) -> bool:
		"""第二层检测: 快速 ID 检查."""
		if not memory_urls:
			self.logger.log_info("memory_urls 为空, 触发完整检查")
			return True

		result = self.run_yt_dlp(
			[
				"--cookies",
				str(self.cookies_file),
				"--flat-playlist",
				"--print",
				"%(id)s",
				"--playlist-end",
				"1",
				f"https://space.bilibili.com/{self.config.bilibili_uid}/video",
			],
		)

		if not result.success or not result.stdout:
			self.logger.log_info("快速检查失败, 触发完整检查")
			return True

		latest_id = result.stdout.strip()
		all_known = set(memory_urls) | known_urls
		video_exists = any(latest_id in url for url in all_known)
		return not video_exists

	def check_potential_new_parts(
		self,
		memory_urls: list[str],
		known_urls: set[str],
	) -> bool:
		"""第一层检测: 分片预检查."""
		all_known_urls = set(memory_urls) | known_urls
		if not all_known_urls:
			self.logger.log_info("内存数据为空, 跳过分片预检查")
			return False

		has_new_parts = False
		try:
			base_urls = {}
			for url in all_known_urls:
				if "?p=" in url:
					parsed = urllib.parse.urlparse(url)
					base_url = parsed._replace(query="").geturl()
					params = urllib.parse.parse_qs(parsed.query)
					if "p" not in params:
						continue
					try:
						part_num = int(params["p"][0])
						if base_url not in base_urls or part_num > base_urls[base_url]:
							base_urls[base_url] = part_num
					except ValueError:
						continue

			for base_url, max_part in base_urls.items():
				if max_part > 1:
					next_part = max_part + 1
					next_url = f"{base_url}?p={next_part}"
					result = self.run_yt_dlp(
						["--cookies", str(self.cookies_file), "--simulate", next_url],
					)
					if result.success:
						has_new_parts = True
						check_part = next_part + 1
						while check_part <= next_part + 5:
							check_url = f"{base_url}?p={check_part}"
							result = self.run_yt_dlp(
								[
									"--cookies",
									str(self.cookies_file),
									"--simulate",
									check_url,
								],
							)
							if result.success:
								check_part += 1
							else:
								break
		except (ValueError, OSError) as exc:
			self.logger.log_warning(f"预测检查出错: {exc}")
			return False

		return has_new_parts

	def fetch_video_list(self) -> YtDlpResult:
		"""完整扫描获取 UP 主视频 URL 列表."""
		return self.run_yt_dlp(
			[
				"--cookies",
				str(self.cookies_file),
				"--flat-playlist",
				"--print",
				"%(webpage_url)s",
				f"https://space.bilibili.com/{self.config.bilibili_uid}/video",
			],
		)

	def get_video_parts(self, video_url: str) -> list[str]:
		"""获取单个视频的所有分 P URL."""
		result = self.run_yt_dlp(
			[
				"--cookies",
				str(self.cookies_file),
				"--flat-playlist",
				"--print",
				"%(webpage_url)s",
				video_url,
			],
		)
		if result.success and result.stdout:
			return [line.strip() for line in result.stdout.split("\n") if line.strip()]
		return []

	def get_all_videos_parallel(self, video_urls: list[str]) -> list[str]:
		"""并行展开所有视频分片."""
		all_parts = []
		try:
			with ThreadPoolExecutor(max_workers=5) as executor:
				future_to_url = {
					executor.submit(self.get_video_parts, url): url for url in video_urls
				}
				for future in as_completed(future_to_url):
					try:
						parts = future.result()
						all_parts.extend(parts)
					except (ValueError, OSError) as exc:
						self.logger.log_warning(f"处理分片出错: {exc}")
		except (ValueError, OSError) as exc:
			self.logger.log_critical_error(
				f"并行处理时出错: {exc}",
				"get_all_videos_parallel 方法",
				send_notification=True,
			)
		return all_parts

	def get_video_upload_time(self, video_url: str) -> int | None:
		"""获取视频真实投稿时间戳.

		通过 B站 view API 取真实 ``ctime`` (而非可被伪造的 pubdate):
		从 URL 解析 bvid 与分 P 编号, 单 P 用 ``data.ctime``, 多 P 按 ``page``
		匹配 ``data.pages[].ctime``. 获取失败返回 ``None``, 上层会跳过不记录.

		Args:
			video_url: B站视频 URL, 可带 ``?p=N`` 分 P 参数.

		Returns:
			真实投稿时间戳 (Unix 秒), 解析或请求失败时返回 ``None``.
		"""
		bvid = extract_bvid(video_url)
		if not bvid:
			self.logger.log_warning(f"无法从 URL 解析 bvid: {video_url}")
			return None

		page = 1
		parsed = urllib.parse.urlparse(video_url)
		params = urllib.parse.parse_qs(parsed.query)
		if "p" in params:
			try:
				page = int(params["p"][0])
			except ValueError:
				page = 1

		return self.api_client.get_ctime(bvid, page)

	def get_bvid_part_ctimes(self, bvid: str) -> list[int]:
		"""获取某个 BV 的全部真实投稿时间戳 (供批量重建使用)."""
		return self.api_client.get_part_ctimes(bvid)
