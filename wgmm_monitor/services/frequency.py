"""WGMM 调频服务."""

from __future__ import annotations

import time

from wgmm_monitor.models import FrequencyDecision, WgmmConfig
from wgmm_monitor.runtime_logger import RuntimeLogger
from wgmm_monitor.services.history import HistoryService
from wgmm_monitor.stores.config_store import ConfigStore
from wgmm_monitor.stores.history_store import HistoryStore
from wgmm_monitor.wgmm.constants import FALLBACK_INTERVAL, LAMBDA_BASE, PRUNE_THRESHOLD
from wgmm_monitor.wgmm.learning import aggregate_publish_events, filter_outliers
from wgmm_monitor.wgmm.scheduler import decide_next_frequency


class FrequencyService:
	"""负责加载历史数据并调用 WGMM 纯算法."""

	def __init__(
		self,
		config: WgmmConfig,
		config_store: ConfigStore,
		history_store: HistoryStore,
		history_service: HistoryService,
		logger: RuntimeLogger,
		dev_mode: bool = False,
	) -> None:
		"""初始化调频服务依赖."""
		self.config = config
		self.config_store = config_store
		self.history_store = history_store
		self.history_service = history_service
		self.logger = logger
		self.dev_mode = dev_mode

	def get_next_check_time(self) -> int:
		"""读取下次检查时间."""
		return self.config.next_check_time

	def adjust_check_frequency(
		self,
		found_new_content: bool = False,
		last_ytdlp_duration: float = 0.0,
		normal_ytdlp_duration: float = 60.0,
	) -> FrequencyDecision:
		"""执行一次 WGMM 调频."""
		current_timestamp = int(time.time())
		mtime_missing = not self.history_store.mtime_file.exists()
		if mtime_missing and not self.history_service.generate_mtime_file(
			"adjust_check_frequency",
		):
			self.config.next_check_time = int(time.time()) + FALLBACK_INTERVAL
			if not self.dev_mode:
				self.config_store.save(self.config)
			return FrequencyDecision(
				config=self.config,
				next_check_time=self.config.next_check_time,
				final_frequency_sec=float(FALLBACK_INTERVAL),
				found_new_content=found_new_content,
				should_save_miss=False,
				miss_timestamp=None,
				log_message="mtime.txt 不可用, 使用回退检查间隔",
				positive_count=0,
				negative_count=0,
			)

		positive_events = self.history_store.load_positive_events()
		negative_events = self.history_store.load_miss_history()
		positive_events = aggregate_publish_events(positive_events, current_timestamp)
		negative_events = filter_outliers(negative_events, current_timestamp)

		total_events = len(positive_events) + len(negative_events)
		weight_threshold = max(0.0001, 0.001 * (100 / (total_events + 50)))
		if len(positive_events) >= PRUNE_THRESHOLD:
			positive_events = self.history_store.prune_old_data(
				positive_events,
				self.config.last_lambda or LAMBDA_BASE,
				weight_threshold,
				current_timestamp,
				self.history_store.mtime_file,
			)
		if len(negative_events) >= PRUNE_THRESHOLD:
			negative_events = self.history_store.prune_old_data(
				negative_events,
				self.config.last_lambda or LAMBDA_BASE,
				weight_threshold,
				current_timestamp,
				self.history_store.miss_history_file,
			)

		decision = decide_next_frequency(
			config=self.config,
			positive_events=positive_events,
			negative_events=negative_events,
			current_timestamp=current_timestamp,
			found_new_content=found_new_content,
			dev_mode=self.dev_mode,
			last_ytdlp_duration=last_ytdlp_duration,
			normal_ytdlp_duration=normal_ytdlp_duration,
		)

		if decision.should_save_miss and decision.miss_timestamp is not None:
			self.history_store.save_miss_history(decision.miss_timestamp, False)

		if not self.dev_mode:
			self.config_store.save(self.config)

		self.logger.log_info(decision.log_message)
		return decision
