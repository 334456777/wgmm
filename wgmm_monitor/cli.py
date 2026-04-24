"""命令行入口."""

from __future__ import annotations

import argparse

from wgmm_monitor.app import Application
from wgmm_monitor.config import load_env_file


def parse_arguments() -> argparse.Namespace:
	"""解析命令行参数."""
	parser = argparse.ArgumentParser(description="视频监控器")
	parser.add_argument(
		"-d",
		"--dev",
		action="store_true",
		help="开发模式: 运行检查后立即退出, 不等待下次检查时间",
	)
	parser.add_argument(
		"--wgmm-core-only",
		action="store_true",
		help="仅运行WGMM调频核心, 跳过视频检测流程, 执行一次后退出",
	)
	return parser.parse_args()


def main() -> None:
	"""程序主入口."""
	load_env_file("data/.env")
	args = parse_arguments()
	app = Application(dev_mode=args.dev or args.wgmm_core_only)

	if args.wgmm_core_only:
		app.run_wgmm_core_only()
	elif args.dev:
		app.run_dev_once()
	else:
		app.run_forever()
