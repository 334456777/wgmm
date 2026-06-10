"""工具函数测试."""

from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from wgmm_monitor.utils.files import limit_file_lines
from wgmm_monitor.utils.time import format_frequency_interval, get_local_timezone_offset


class LimitFileLinesTest(unittest.TestCase):
	"""验证文件截断工具."""

	def test_missing_file_is_noop(self) -> None:
		limit_file_lines(Path("/nonexistent/never/x.log"), 10)

	def test_under_limit_keeps_content(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			path = Path(tmp) / "a.log"
			path.write_text("1\n2\n", encoding="utf-8")

			limit_file_lines(path, 5)

			self.assertEqual(path.read_text(encoding="utf-8"), "1\n2\n")

	def test_over_limit_keeps_tail(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			path = Path(tmp) / "a.log"
			path.write_text("1\n2\n3\n4\n5\n", encoding="utf-8")

			limit_file_lines(path, 2)

			self.assertEqual(path.read_text(encoding="utf-8"), "4\n5\n")

	def test_header_lines_preserved(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			path = Path(tmp) / "a.log"
			path.write_text("h1\nh2\n1\n2\n3\n", encoding="utf-8")

			limit_file_lines(path, 3, header_lines=2)

			self.assertEqual(path.read_text(encoding="utf-8"), "h1\nh2\n3\n")


class FormatFrequencyIntervalTest(unittest.TestCase):
	"""验证轮询间隔格式化."""

	def test_zero_seconds(self) -> None:
		self.assertEqual(format_frequency_interval(0), "0 秒")

	def test_seconds_only(self) -> None:
		self.assertEqual(format_frequency_interval(59), "59 秒")

	def test_exact_minute_omits_seconds(self) -> None:
		self.assertEqual(format_frequency_interval(60), "1 分钟")

	def test_exact_hour(self) -> None:
		self.assertEqual(format_frequency_interval(3600), "1 小时")

	def test_full_combination(self) -> None:
		self.assertEqual(
			format_frequency_interval(86400 + 3600 + 60 + 1),
			"1 天 1 小时 1 分钟 1 秒",
		)


class TimezoneOffsetTest(unittest.TestCase):
	"""验证本地时区偏移读取."""

	def test_offset_matches_time_module(self) -> None:
		offset = get_local_timezone_offset()
		expected = (
			-time.altzone
			if (time.localtime().tm_isdst and time.daylight)
			else -time.timezone
		)

		self.assertIsInstance(offset, float)
		self.assertEqual(offset, float(expected))


if __name__ == "__main__":
	unittest.main()
