"""配置模型测试."""

from __future__ import annotations

import unittest

from wgmm_monitor.models import AppConfig, WgmmConfig


class ConfigModelTest(unittest.TestCase):
	"""验证配置模型兼容性."""

	def test_app_config_reports_missing_required_keys(self) -> None:
		config = AppConfig(
			gist_id="",
			github_token="token",
			bilibili_uid="",
			bark_device_key="key",
			bark_app_title="title",
		)
		self.assertEqual(config.missing_required_keys(), ["GIST_ID", "BILIBILI_UID"])

	def test_wgmm_config_fills_defaults_and_preserves_unknown_fields(self) -> None:
		config = WgmmConfig.from_dict(
			{
				"dimension_weights": {"day": 0.9, "custom_0": 0.2},
				"sigmas": {"custom_0": 1.3},
				"next_check_time": 123,
				"future_field": {"enabled": True},
			}
		)

		self.assertEqual(config.dimension_weights["day"], 0.9)
		self.assertIn("week", config.dimension_weights)
		self.assertEqual(config.sigmas["custom_0"], 1.3)
		self.assertIn("day", config.sigmas)

		serialized = config.to_dict()
		self.assertEqual(serialized["future_field"], {"enabled": True})
		self.assertEqual(serialized["next_check_time"], 123)


if __name__ == "__main__":
	unittest.main()
