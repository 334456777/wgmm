"""B站 view API 客户端.

通过 ``https://api.bilibili.com/x/web-interface/view`` 获取视频**真实投稿时间**
``ctime``. 注意 yt-dlp/info.json 中的 ``timestamp`` 字段对应的是 ``pubdate``
(发布时间, 可被 UP 主伪造), 与真实投稿时间存在偏差, 不能用于 WGMM 训练数据.

设计约束:
    - **串行调用**: view API 在短时间内并发请求容易触发封控, 因此所有请求串行执行,
      并在两次实际请求之间留出 ``REQUEST_INTERVAL`` 间隔.
    - **按 bvid 缓存**: 同一 BV 的多个分 P 只需请求一次 API, 失败结果 (``None``)
      也写入缓存, 避免在同一次运行内重复打 API.
"""

from __future__ import annotations

import http.cookiejar
import re
import time
from pathlib import Path

import requests

from wgmm_monitor.runtime_logger import RuntimeLogger

# 匹配 B站视频号 (BV 号), 用于从 URL 或 yt-dlp id 中提取 bvid.
_BVID_PATTERN = re.compile(r"BV[0-9A-Za-z]+")


def extract_bvid(text: str) -> str | None:
	"""从 URL 或 yt-dlp id 中提取 bvid.

	Args:
		text: 可能包含 BV 号的字符串, 如视频 URL 或 info.json 的 ``id`` 字段.

	Returns:
		提取到的 bvid (如 ``BV1xx411c7mu``), 未匹配到则返回 ``None``.
	"""
	if not text:
		return None
	match = _BVID_PATTERN.search(text)
	return match.group(0) if match else None


class BilibiliApiClient:
	"""封装 B站 view API 调用, 串行执行并按 bvid 缓存."""

	VIEW_URL = "https://api.bilibili.com/x/web-interface/view"
	DYNAMIC_URL = "https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/space"
	REQUEST_INTERVAL = 0.5

	def __init__(self, logger: RuntimeLogger) -> None:
		"""初始化客户端, 准备缓存与串行控制状态."""
		self.logger = logger
		# bvid -> data 字典; 失败缓存为 None, 保证同 BV 只请求一次.
		self._cache: dict[str, dict | None] = {}
		self._last_request_ts = 0.0

	def _headers(self) -> dict[str, str]:
		"""构造 view API 请求头.

		view API 为公开接口, 无需 cookies, 但需带 User-Agent 与 Referer
		以降低被风控拦截的概率.
		"""
		return {
			"User-Agent": (
				"Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
				"AppleWebKit/537.36 (KHTML, like Gecko) "
				"Chrome/120.0.0.0 Safari/537.36"
			),
			"Referer": "https://www.bilibili.com",
		}

	def fetch_view(self, bvid: str) -> dict | None:
		"""获取指定 bvid 的 ``data`` 字段 (含 ctime/pages).

		命中缓存直接返回; 否则串行请求 API. 任何失败 (网络异常/HTTP 错误/
		``code != 0``) 均记 warning, 缓存 ``None`` 并返回 ``None``.

		Args:
			bvid: B站视频号.

		Returns:
			API 返回的 ``data`` 字典, 失败时返回 ``None``.
		"""
		if bvid in self._cache:
			return self._cache[bvid]

		data = self._request_view(bvid)
		self._cache[bvid] = data
		return data

	def _request_view(self, bvid: str) -> dict | None:
		"""实际发起一次 view API 请求 (串行 + 间隔)."""
		elapsed = time.time() - self._last_request_ts
		if elapsed < self.REQUEST_INTERVAL:
			time.sleep(self.REQUEST_INTERVAL - elapsed)

		try:
			response = requests.get(
				self.VIEW_URL,
				params={"bvid": bvid},
				headers=self._headers(),
				timeout=30,
			)
			self._last_request_ts = time.time()
			response.raise_for_status()
			payload = response.json()
		except requests.exceptions.HTTPError as exc:
			self._last_request_ts = time.time()
			status_code = exc.response.status_code if exc.response is not None else "未知"
			self.logger.log_warning(f"view API 请求失败 {bvid}: HTTP {status_code}")
			return None
		except (requests.RequestException, ValueError) as exc:
			self._last_request_ts = time.time()
			self.logger.log_warning(f"view API 请求异常 {bvid}: {exc!s}")
			return None

		if payload.get("code") != 0:
			self.logger.log_warning(
				f"view API 返回非 0 {bvid}: code={payload.get('code')} "
				f"msg={payload.get('message')}"
			)
			return None
		return payload.get("data")

	def get_ctime(self, bvid: str, page: int = 1) -> int | None:
		"""获取某一分 P 的真实投稿时间戳.

		单 P 视频或未匹配到分 P 时返回 ``data.ctime``; 多 P 视频按 ``page``
		字段匹配 ``data.pages[]`` 中对应分 P 的 ``ctime``.

		Args:
			bvid: B站视频号.
			page: 分 P 编号 (从 1 开始), 默认 1.

		Returns:
			真实投稿时间戳 (Unix 秒), 失败时返回 ``None``.
		"""
		data = self.fetch_view(bvid)
		if not data:
			return None

		pages = data.get("pages") or []
		if len(pages) > 1:
			for part in pages:
				if part.get("page") == page:
					ctime = part.get("ctime")
					if ctime:
						return int(ctime)
					break

		ctime = data.get("ctime")
		return int(ctime) if ctime else None

	def get_part_ctimes(self, bvid: str) -> list[int]:
		"""获取某个 BV 的全部真实投稿时间戳.

		多 P 视频收集每个 ``pages[].ctime``; 单 P 视频返回 ``[data.ctime]``.
		用于批量重建 mtime.txt 时按分 P 粒度采集.

		Args:
			bvid: B站视频号.

		Returns:
			该 BV 全部分 P 的真实投稿时间戳列表 (已过滤无效值), 失败时为空列表.
		"""
		data = self.fetch_view(bvid)
		if not data:
			return []

		pages = data.get("pages") or []
		if len(pages) > 1:
			ctimes = [int(p["ctime"]) for p in pages if p.get("ctime")]
			if ctimes:
				return ctimes

		ctime = data.get("ctime")
		return [int(ctime)] if ctime else []

	@staticmethod
	def _dynamic_archive_bvid(item: dict) -> str | None:
		"""从单条动态提取**本人投稿**视频的 bvid.

		仅取 ``module_dynamic.major`` 为 ``MAJOR_TYPE_ARCHIVE`` 的归档视频;
		转发动态 (``DYNAMIC_TYPE_FORWARD``) 的 ``major`` 为空, 自动跳过,
		避免把他人视频 bvid 误纳入.
		"""
		modules = item.get("modules") or {}
		major = (modules.get("module_dynamic") or {}).get("major") or {}
		if major.get("type") == "MAJOR_TYPE_ARCHIVE":
			return (major.get("archive") or {}).get("bvid")
		return None

	def fetch_space_dynamic_bvids(
		self,
		mid: str,
		cookies_file: Path,
		max_pages: int = 6,
	) -> list[str]:
		"""分页拉取 UP 空间动态, 提取本人投稿视频 (含充电专属) 的 bvid.

		充电专属视频不出现在 ``space/arc/search`` 投稿列表中, 但会作为普通
		``DYNAMIC_TYPE_AV`` 动态出现在 UP 的动态流里. 该接口需登录态 cookies,
		按 ``offset`` 游标翻页. 任意一页失败即停止并返回已收集结果.

		Args:
			mid: UP 主 mid.
			cookies_file: Netscape 格式 cookies 文件 (登录态).
			max_pages: 最多翻页数 (每页约 12 条动态).

		Returns:
			去重后的 bvid 列表, 按动态时间倒序 (最新在前); 失败返回已收集部分.
		"""
		try:
			jar = http.cookiejar.MozillaCookieJar(str(cookies_file))
			jar.load(ignore_discard=True, ignore_expires=True)
		except OSError as exc:
			self.logger.log_warning(f"动态枚举无法加载 cookies: {exc}")
			return []

		session = requests.Session()
		session.cookies = jar
		headers = {
			**self._headers(),
			"Referer": f"https://space.bilibili.com/{mid}/dynamic",
		}
		bvids: list[str] = []
		seen: set[str] = set()
		offset = ""
		for _ in range(max_pages):
			elapsed = time.time() - self._last_request_ts
			if elapsed < self.REQUEST_INTERVAL:
				time.sleep(self.REQUEST_INTERVAL - elapsed)
			params = {
				"offset": offset,
				"host_mid": mid,
				"timezone_offset": -480,
				"features": "itemOpusStyle",
			}
			try:
				response = session.get(
					self.DYNAMIC_URL,
					params=params,
					headers=headers,
					timeout=30,
				)
				self._last_request_ts = time.time()
				response.raise_for_status()
				payload = response.json()
			except (requests.RequestException, ValueError) as exc:
				self._last_request_ts = time.time()
				self.logger.log_warning(f"动态feed请求异常 mid={mid}: {exc!s}")
				break

			if payload.get("code") != 0:
				self.logger.log_warning(
					f"动态feed返回非0 mid={mid}: code={payload.get('code')} "
					f"msg={payload.get('message')}"
				)
				break

			data = payload.get("data") or {}
			for item in data.get("items") or []:
				bvid = self._dynamic_archive_bvid(item)
				if bvid and bvid not in seen:
					seen.add(bvid)
					bvids.append(bvid)

			if not data.get("has_more"):
				break
			offset = data.get("offset") or ""
			if not offset:
				break

		return bvids
