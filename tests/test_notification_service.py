"""通知服务测试."""

from __future__ import annotations

import unittest

from wgmm_monitor.models import AppConfig
from wgmm_monitor.services.notification import NotificationService


class FakeBarkClient:
	"""测试用 Bark 客户端, 记录推送参数."""

	def __init__(self, success: bool = True) -> None:
		self.success = success
		self.pushes: list[dict] = []

	def send_push(self, **kwargs: object) -> bool:
		self.pushes.append(kwargs)
		return self.success


def make_service(success: bool = True) -> tuple[NotificationService, FakeBarkClient]:
	"""组装通知服务与捕获用客户端."""
	config = AppConfig(
		gist_id="g",
		github_token="t",
		bilibili_uid="1",
		bark_device_key="k",
		bark_app_title="监控",
	)
	bark = FakeBarkClient(success=success)
	return NotificationService(bark, config), bark


class NotificationServiceTest(unittest.TestCase):
	"""验证三类通知的标题与参数."""

	def test_new_videos_uses_time_sensitive_level(self) -> None:
		service, bark = make_service()

		self.assertTrue(service.notify_new_videos(2))

		push = bark.pushes[0]
		self.assertEqual(push["title"], "监控")
		self.assertEqual(push["level"], "timeSensitive")
		self.assertIn("2 个新视频", push["body"])
		self.assertNotIn("新分片", push["body"])

	def test_new_videos_mentions_new_parts(self) -> None:
		service, bark = make_service()

		service.notify_new_videos(1, has_new_parts=True)

		self.assertIn("含新分片", bark.pushes[0]["body"])

	def test_error_notification_appends_suffix(self) -> None:
		service, bark = make_service(success=False)

		self.assertFalse(service.notify_error("失败"))

		push = bark.pushes[0]
		self.assertEqual(push["title"], "监控 - 错误")
		self.assertEqual(push["body"], "失败")

	def test_critical_notification_is_loud(self) -> None:
		service, bark = make_service()

		service.notify_critical_error("崩了", context="主循环")

		push = bark.pushes[0]
		self.assertIn("严重错误", push["title"])
		self.assertEqual(push["body"], "崩了 (主循环)")
		self.assertEqual(push["level"], "critical")
		self.assertEqual(push["volume"], 8)
		self.assertTrue(push["call"])

	def test_critical_notification_without_context(self) -> None:
		service, bark = make_service()

		service.notify_critical_error("崩了")

		self.assertEqual(bark.pushes[0]["body"], "崩了")


if __name__ == "__main__":
	unittest.main()
