"""Bark 推送客户端."""

from __future__ import annotations

import urllib.parse

import requests

from wgmm_monitor.models import AppConfig
from wgmm_monitor.utils.time import get_jst_datetime_str


class BarkClient:
	"""封装 Bark HTTP 推送."""

	def __init__(self, config: AppConfig) -> None:
		"""保存 Bark 配置."""
		self.config = config

	def send_push(
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
		"""发送 Bark 推送."""
		success = False
		try:
			encoded_title = urllib.parse.quote(title)
			encoded_body = urllib.parse.quote(body)
			base_url = (
				f"{self.config.bark_base_url}/{self.config.bark_device_key}/"
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
			success = response.ok
		except requests.RequestException as exc:
			timestamp = get_jst_datetime_str()
			# Bark 客户端是 RuntimeLogger 的通知出口, 反向调用 logger 会成环
			print(f"{timestamp} - WARNING - Bark推送失败: {exc}")  # noqa: T201
			success = False

		return success
