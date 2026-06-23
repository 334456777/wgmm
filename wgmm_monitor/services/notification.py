"""通知业务封装."""

from __future__ import annotations

from wgmm_monitor.clients.bark import BarkClient
from wgmm_monitor.models import AppConfig


class NotificationService:
	"""负责构造监控系统通知内容."""

	def __init__(self, bark_client: BarkClient, config: AppConfig) -> None:
		"""初始化通知客户端."""
		self.bark_client = bark_client
		self.config = config

	def notify_new_videos(self, count: int, has_new_parts: bool = False) -> bool:
		"""发送新视频通知."""
		body = f"发现 {count} 个新视频{'(含新分片)' if has_new_parts else ''}等待备份"
		return self.bark_client.send_push(
			title=self.config.bark_app_title,
			body=body,
			level="timeSensitive",
			sound="minuet",
			group="新视频",
		)

	def notify_cookie_expiry(self, days_left: int, expiry_str: str) -> bool:
		"""发送 cookies(SESSDATA) 临近过期提醒."""
		if days_left < 0:
			body = f"SESSDATA 已于 {expiry_str} 过期, 请立即重新导出 cookies 替换"
		else:
			body = (
				f"SESSDATA 将于 {expiry_str} 过期(剩 {days_left} 天), "
				"请尽快重新导出 cookies 替换"
			)
		return self.bark_client.send_push(
			title=f"⚠️ {self.config.bark_app_title} - Cookies 即将过期",
			body=body,
			level="timeSensitive",
			sound="minuet",
			group="Cookies",
		)

	def notify_error(self, message: str) -> bool:
		"""发送普通错误通知."""
		return self.bark_client.send_push(
			title=f"{self.config.bark_app_title} - 错误",
			body=message,
			level="active",
			group="错误",
		)

	def notify_critical_error(self, message: str, context: str = "") -> bool:
		"""发送严重错误通知."""
		body = message + (f" ({context})" if context else "")
		return self.bark_client.send_push(
			title=f"⚠️ {self.config.bark_app_title} - 严重错误",
			body=body,
			level="critical",
			sound="alarm",
			volume=8,
			call=True,
			group="严重错误",
		)
