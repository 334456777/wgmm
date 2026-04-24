"""时间相关工具."""

from __future__ import annotations

import time
from datetime import datetime as dt
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")


def get_jst_datetime_str() -> str:
	"""获取 JST 时区的日志时间字符串."""
	return dt.now(JST).strftime("%Y-%m-%d %H:%M:%S")


def get_local_timezone_offset() -> float:
	"""获取本地时区偏移量(秒)."""
	if time.localtime().tm_isdst and time.daylight:
		return float(-time.altzone)
	return float(-time.timezone)


def format_frequency_interval(seconds: float) -> str:
	"""格式化轮询间隔."""
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
