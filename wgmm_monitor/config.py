"""启动配置加载."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from wgmm_monitor.models import AppConfig


def load_env_file(env_path: str = "data/.env") -> None:
	"""加载简单 ``KEY=VALUE`` 格式的环境变量文件."""
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
					value = value.strip().strip('"').strip("'")
					if key and not os.getenv(key):
						os.environ[key] = value
	except OSError as exc:
		print(f"无法加载 .env 文件: {exc}", file=sys.stderr)


def load_app_config() -> AppConfig:
	"""从环境变量读取应用配置."""
	return AppConfig(
		gist_id=os.getenv("GIST_ID", ""),
		github_token=os.getenv("GITHUB_TOKEN", ""),
		bilibili_uid=os.getenv("BILIBILI_UID", ""),
		bark_device_key=os.getenv("BARK_DEVICE_KEY", ""),
		bark_app_title=os.getenv("BARK_APP_TITLE", ""),
	)
