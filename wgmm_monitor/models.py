"""跨模块共享的数据模型."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from wgmm_monitor.wgmm.constants import DEFAULT_DIMENSION_WEIGHTS, DEFAULT_SIGMAS


@dataclass(slots=True)
class RuntimePaths:
	"""运行时文件路径集合."""

	data_dir: Path = Path("data")
	log_file: Path = Path("urls.log")
	critical_log_file: Path = Path("critical_errors.log")
	wgmm_config_file: Path = Path("data/wgmm_config.json")
	local_known_file: Path = Path("data/local_known.txt")
	mtime_file: Path = Path("data/mtime.txt")
	miss_history_file: Path = Path("data/miss_history.txt")
	cookies_file: Path = Path("data/cookies.txt")
	temp_info_dir: Path = Path("temp_info_json")
	temp_timestamps_file: Path = Path("temp_timestamps.txt")

	def ensure_data_dir(self) -> None:
		"""确保数据目录存在."""
		self.data_dir.mkdir(exist_ok=True)


@dataclass(slots=True)
class AppConfig:
	"""外部服务配置."""

	gist_id: str
	github_token: str
	bilibili_uid: str
	bark_device_key: str
	bark_app_title: str
	gist_base_url: str = "https://api.github.com/gists"
	bark_base_url: str = "https://api.day.app"

	def missing_required_keys(self) -> list[str]:
		"""返回缺失的必填配置名称."""
		required = {
			"GIST_ID": self.gist_id,
			"GITHUB_TOKEN": self.github_token,
			"BILIBILI_UID": self.bilibili_uid,
			"BARK_DEVICE_KEY": self.bark_device_key,
			"BARK_APP_TITLE": self.bark_app_title,
		}
		return [key for key, value in required.items() if not value]


@dataclass(slots=True)
class WgmmConfig:
	"""WGMM 持久化配置.

	未知字段会保存在 ``extra`` 中并在写回时原样保留, 避免破坏已有配置扩展.
	"""

	dimension_weights: dict[str, float] = field(
		default_factory=lambda: dict(DEFAULT_DIMENSION_WEIGHTS)
	)
	sigmas: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_SIGMAS))
	last_lambda: float = 0.0001
	last_pos_variance: float = 0.0
	last_neg_variance: float = 0.0
	last_update: int = 0
	next_check_time: int = 0
	is_manual_run: bool = True
	discovered_periods: list[float] = field(default_factory=list)
	extra: dict[str, Any] = field(default_factory=dict)

	@classmethod
	def from_dict(cls, raw: dict[str, Any] | None) -> WgmmConfig:
		"""从 JSON 字典创建配置, 自动补齐默认值."""
		data = dict(raw or {})
		known_keys = {
			"dimension_weights",
			"sigmas",
			"last_lambda",
			"last_pos_variance",
			"last_neg_variance",
			"last_update",
			"next_check_time",
			"is_manual_run",
			"discovered_periods",
		}
		weights = dict(DEFAULT_DIMENSION_WEIGHTS)
		weights.update(data.get("dimension_weights") or {})
		sigmas = dict(DEFAULT_SIGMAS)
		sigmas.update(data.get("sigmas") or {})
		extra = {key: value for key, value in data.items() if key not in known_keys}
		return cls(
			dimension_weights={key: float(value) for key, value in weights.items()},
			sigmas={key: float(value) for key, value in sigmas.items()},
			last_lambda=float(data.get("last_lambda", 0.0001)),
			last_pos_variance=float(data.get("last_pos_variance", 0.0)),
			last_neg_variance=float(data.get("last_neg_variance", 0.0)),
			last_update=int(data.get("last_update", 0)),
			next_check_time=int(data.get("next_check_time", 0)),
			is_manual_run=bool(data.get("is_manual_run", True)),
			discovered_periods=[
				float(period) for period in data.get("discovered_periods", [])
			],
			extra=extra,
		)

	def to_dict(self) -> dict[str, Any]:
		"""转换为兼容原始 ``wgmm_config.json`` 的字典."""
		data = dict(self.extra)
		data.update(
			{
				"dimension_weights": dict(self.dimension_weights),
				"last_lambda": self.last_lambda,
				"last_pos_variance": self.last_pos_variance,
				"last_neg_variance": self.last_neg_variance,
				"last_update": self.last_update,
				"next_check_time": self.next_check_time,
				"is_manual_run": self.is_manual_run,
				"sigmas": dict(self.sigmas),
				"discovered_periods": list(self.discovered_periods),
			}
		)
		return data


@dataclass(slots=True)
class YtDlpResult:
	"""yt-dlp 执行结果."""

	success: bool
	stdout: str = ""
	stderr: str = ""
	elapsed: float = 0.0


@dataclass(slots=True)
class FrequencyDecision:
	"""WGMM 调频结果."""

	config: WgmmConfig
	next_check_time: int
	final_frequency_sec: float
	found_new_content: bool
	should_save_miss: bool
	miss_timestamp: int | None
	log_message: str
	positive_count: int
	negative_count: int
	learning_mode: bool = False
