"""启动配置、CLI 入口与应用装配测试."""

from __future__ import annotations

import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from wgmm_monitor import cli
from wgmm_monitor.app import Application
from wgmm_monitor.config import load_app_config, load_env_file

REQUIRED_ENV = {
	"GIST_ID": "gid",
	"GITHUB_TOKEN": "tok",
	"BILIBILI_UID": "1",
	"BARK_DEVICE_KEY": "key",
	"BARK_APP_TITLE": "标题",
}


class LoadEnvFileTest(unittest.TestCase):
	"""验证 .env 解析."""

	def test_missing_file_is_noop(self) -> None:
		with mock.patch.dict(os.environ, {}, clear=True):
			load_env_file("/nonexistent/.env")

			self.assertEqual(os.environ.get("GIST_ID"), None)

	def test_parses_values_and_strips_quotes(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			env_path = Path(tmp) / ".env"
			env_path.write_text(
				"# 注释\n\nGIST_ID=\"gid\"\nGITHUB_TOKEN='tok'\nBAD_LINE\n",
				encoding="utf-8",
			)
			with mock.patch.dict(os.environ, {}, clear=True):
				load_env_file(str(env_path))

				self.assertEqual(os.environ["GIST_ID"], "gid")
				self.assertEqual(os.environ["GITHUB_TOKEN"], "tok")
				self.assertNotIn("BAD_LINE", os.environ)

	def test_does_not_override_existing_env(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			env_path = Path(tmp) / ".env"
			env_path.write_text("GIST_ID=from_file\n", encoding="utf-8")
			with mock.patch.dict(os.environ, {"GIST_ID": "from_env"}, clear=True):
				load_env_file(str(env_path))

				self.assertEqual(os.environ["GIST_ID"], "from_env")

	def test_oserror_reports_to_stderr(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			env_path = Path(tmp) / ".env"
			env_path.write_text("A=1\n", encoding="utf-8")
			err = io.StringIO()
			with (
				mock.patch("pathlib.Path.open", side_effect=OSError("拒绝访问")),
				contextlib.redirect_stderr(err),
			):
				load_env_file(str(env_path))

			self.assertIn("无法加载 .env 文件", err.getvalue())


class LoadAppConfigTest(unittest.TestCase):
	"""验证环境变量到配置的映射."""

	def test_reads_all_fields(self) -> None:
		with mock.patch.dict(os.environ, REQUIRED_ENV, clear=True):
			config = load_app_config()

			self.assertEqual(config.gist_id, "gid")
			self.assertEqual(config.bark_app_title, "标题")
			self.assertEqual(config.missing_required_keys(), [])

	def test_missing_env_reported(self) -> None:
		with mock.patch.dict(os.environ, {}, clear=True):
			config = load_app_config()

			self.assertEqual(len(config.missing_required_keys()), 5)


class CliDispatchTest(unittest.TestCase):
	"""验证 CLI 参数到运行模式的分发."""

	def run_main(self, argv: list[str]) -> mock.Mock:
		"""以 mock 的 Application 运行 main, 返回应用实例 mock."""
		with (
			mock.patch.object(cli, "Application") as app_cls,
			mock.patch.object(cli, "load_env_file"),
			mock.patch("sys.argv", ["monitor.py", *argv]),
		):
			cli.main()
		return app_cls

	def test_default_runs_forever(self) -> None:
		app_cls = self.run_main([])

		app_cls.assert_called_once_with(dev_mode=False)
		app_cls.return_value.run_forever.assert_called_once()

	def test_dev_flag_runs_once(self) -> None:
		app_cls = self.run_main(["--dev"])

		app_cls.assert_called_once_with(dev_mode=True)
		app_cls.return_value.run_dev_once.assert_called_once()

	def test_wgmm_core_only_flag(self) -> None:
		app_cls = self.run_main(["--wgmm-core-only"])

		app_cls.assert_called_once_with(dev_mode=True)
		app_cls.return_value.run_wgmm_core_only.assert_called_once()


class ApplicationTest(unittest.TestCase):
	"""验证应用装配与启动校验 (全部在临时目录内, 不触网)."""

	def setUp(self) -> None:
		"""切换到临时工作目录."""
		self._tmp = tempfile.TemporaryDirectory()
		self._old_cwd = Path.cwd()
		os.chdir(self._tmp.name)
		self.addCleanup(self._restore)

	def _restore(self) -> None:
		"""恢复工作目录并清理临时目录."""
		os.chdir(self._old_cwd)
		self._tmp.cleanup()

	def make_app(self, dev_mode: bool = True) -> object:
		"""在临时目录内装配应用."""
		Path("data").mkdir(exist_ok=True)
		Path("data/cookies.txt").write_text("# cookies\ncontent\n", encoding="utf-8")
		with mock.patch.dict(os.environ, REQUIRED_ENV, clear=True):
			return Application(dev_mode=dev_mode)

	def test_missing_env_exits(self) -> None:
		err = io.StringIO()
		with (
			mock.patch.dict(os.environ, {}, clear=True),
			contextlib.redirect_stderr(err),
			self.assertRaises(SystemExit) as ctx,
		):
			Application(dev_mode=True)

		self.assertEqual(ctx.exception.code, 1)
		self.assertIn("缺少必要的环境变量", err.getvalue())

	def test_missing_cookies_exits(self) -> None:
		with (
			mock.patch.dict(os.environ, REQUIRED_ENV, clear=True),
			contextlib.redirect_stdout(io.StringIO()),
			self.assertRaises(SystemExit) as ctx,
		):
			Application(dev_mode=True)

		self.assertEqual(ctx.exception.code, 1)

	def test_empty_cookies_exits(self) -> None:
		Path("data").mkdir(exist_ok=True)
		Path("data/cookies.txt").write_text("  \n", encoding="utf-8")
		with (
			mock.patch.dict(os.environ, REQUIRED_ENV, clear=True),
			contextlib.redirect_stdout(io.StringIO()),
			self.assertRaises(SystemExit) as ctx,
		):
			Application(dev_mode=True)

		self.assertEqual(ctx.exception.code, 1)

	def test_successful_assembly_wires_services(self) -> None:
		app = self.make_app()

		self.assertIs(app.frequency_service.config, app.wgmm_config)
		self.assertIs(app.monitor_service.frequency_service, app.frequency_service)
		self.assertIsNotNone(app.logger.error_notifier)

	def test_signal_handler_saves_state_and_exits(self) -> None:
		app = self.make_app()

		with (
			contextlib.redirect_stdout(io.StringIO()),
			self.assertRaises(SystemExit) as ctx,
		):
			app.signal_handler(15, None)

		self.assertEqual(ctx.exception.code, 0)

	def test_run_wgmm_core_only_exits_zero(self) -> None:
		app = self.make_app()

		with (
			mock.patch.object(app.frequency_service, "adjust_check_frequency"),
			self.assertRaises(SystemExit) as ctx,
		):
			app.run_wgmm_core_only()

		self.assertEqual(ctx.exception.code, 0)

	def test_unreadable_cookies_exits(self) -> None:
		Path("data").mkdir(exist_ok=True)
		Path("data/cookies.txt").mkdir()
		with (
			mock.patch.dict(os.environ, REQUIRED_ENV, clear=True),
			contextlib.redirect_stdout(io.StringIO()),
			self.assertRaises(SystemExit) as ctx,
		):
			Application(dev_mode=True)

		self.assertEqual(ctx.exception.code, 1)

	def test_signal_handler_tolerates_save_failure(self) -> None:
		app = self.make_app()

		with (
			mock.patch.object(
				app.monitor_service, "save_known_urls", side_effect=OSError("满")
			),
			contextlib.redirect_stdout(io.StringIO()),
			self.assertRaises(SystemExit) as ctx,
		):
			app.signal_handler(15, None)

		self.assertEqual(ctx.exception.code, 0)

	def test_run_wgmm_core_only_handles_interrupt_and_error(self) -> None:
		app = self.make_app()

		with (
			mock.patch.object(
				app.frequency_service,
				"adjust_check_frequency",
				side_effect=KeyboardInterrupt(),
			),
			contextlib.redirect_stdout(io.StringIO()),
			self.assertRaises(SystemExit) as ctx,
		):
			app.run_wgmm_core_only()
		self.assertEqual(ctx.exception.code, 0)

		with (
			mock.patch.object(
				app.frequency_service,
				"adjust_check_frequency",
				side_effect=OSError("坏了"),
			),
			contextlib.redirect_stdout(io.StringIO()),
			self.assertRaises(SystemExit) as ctx,
		):
			app.run_wgmm_core_only()
		self.assertEqual(ctx.exception.code, 1)

	def test_run_dev_once_paths(self) -> None:
		app = self.make_app()

		with (
			mock.patch.object(app.monitor_service, "run_monitor"),
			mock.patch.object(app.monitor_service, "wait_for_next_check"),
			self.assertRaises(SystemExit) as ctx,
		):
			app.run_dev_once()
		self.assertEqual(ctx.exception.code, 0)

		with (
			mock.patch.object(
				app.monitor_service, "run_monitor", side_effect=KeyboardInterrupt()
			),
			contextlib.redirect_stdout(io.StringIO()),
			self.assertRaises(SystemExit) as ctx,
		):
			app.run_dev_once()
		self.assertEqual(ctx.exception.code, 0)

		with (
			mock.patch.object(
				app.monitor_service, "run_monitor", side_effect=OSError("坏了")
			),
			contextlib.redirect_stdout(io.StringIO()),
			self.assertRaises(SystemExit) as ctx,
		):
			app.run_dev_once()
		self.assertEqual(ctx.exception.code, 1)

	def test_run_forever_paths(self) -> None:
		app = self.make_app()

		with (
			mock.patch.object(
				app.config_store, "ensure_manual_flag", side_effect=OSError("读取失败")
			),
			mock.patch.object(
				app.monitor_service,
				"wait_for_next_check",
				side_effect=KeyboardInterrupt(),
			),
			contextlib.redirect_stdout(io.StringIO()),
			self.assertRaises(SystemExit) as ctx,
		):
			app.run_forever()
		self.assertEqual(ctx.exception.code, 0)

		with (
			mock.patch.object(
				app.monitor_service, "wait_for_next_check", side_effect=OSError("坏了")
			),
			contextlib.redirect_stdout(io.StringIO()),
			self.assertRaises(SystemExit) as ctx,
		):
			app.run_forever()
		self.assertEqual(ctx.exception.code, 1)


if __name__ == "__main__":
	unittest.main()
