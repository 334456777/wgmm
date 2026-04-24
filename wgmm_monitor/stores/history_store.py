"""历史事件文件存储."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from wgmm_monitor.runtime_logger import RuntimeLogger


class HistoryStore:
	"""读写发布时间和负向检测历史."""

	def __init__(
		self,
		mtime_file: Path,
		miss_history_file: Path,
		logger: RuntimeLogger,
		dev_mode: bool = False,
	) -> None:
		"""初始化历史文件路径."""
		self.mtime_file = mtime_file
		self.miss_history_file = miss_history_file
		self.logger = logger
		self.dev_mode = dev_mode
		self.sandbox_miss_history: list[int] = []

	def load_history_file(self, filepath: Path) -> list[int]:
		"""加载历史文件并去重."""
		try:
			raw_data = [
				line.strip()
				for line in filepath.read_text(encoding="utf-8").splitlines()
				if line.strip().isdigit()
			]
			seen_timestamps = set()
			filtered = []
			for timestamp_str in raw_data:
				timestamp = int(timestamp_str)
				if timestamp > 0 and timestamp not in seen_timestamps:
					filtered.append(timestamp)
					seen_timestamps.add(timestamp)
		except OSError as exc:
			self.logger.log_warning(f"读取历史文件失败 {filepath}: {exc}")
			return []
		else:
			return filtered

	def load_positive_events(self) -> list[int]:
		"""加载正向事件."""
		return self.load_history_file(self.mtime_file)

	def load_miss_history(self) -> list[int]:
		"""加载负向事件历史."""
		if not self.miss_history_file.exists():
			return []
		try:
			with self.miss_history_file.open() as f:
				return [int(line.strip()) for line in f if line.strip().isdigit()]
		except OSError as exc:
			self.logger.log_warning(f"读取失败历史记录失败: {exc}")
			return []

	def save_miss_history(self, timestamp: int, is_manual_run: bool) -> None:
		"""保存一次负向事件."""
		if is_manual_run:
			return
		if self.dev_mode:
			self.sandbox_miss_history.append(timestamp)
			return
		try:
			with self.miss_history_file.open("a") as f:
				f.write(f"{timestamp}\n")
			self.logger.limit_file_lines(self.miss_history_file, 100000)
		except OSError as exc:
			self.logger.log_warning(f"写入失败历史记录失败: {exc}")

	def append_upload_timestamps(self, timestamps: list[int]) -> None:
		"""追加真实上传时间戳."""
		if self.dev_mode or not timestamps:
			return
		try:
			with self.mtime_file.open("a") as f:
				f.writelines(f"{ts}\n" for ts in sorted(timestamps))
			self.logger.limit_file_lines(self.mtime_file, 100000)
		except OSError as exc:
			self.logger.log_warning(f"保存时间戳失败: {exc}")

	def prune_old_data(
		self,
		events: list[int],
		last_lambda: float,
		threshold: float,
		current_timestamp: int,
		target_file: Path,
	) -> list[int]:
		"""剪枝权重过低的历史数据并回写文件."""
		if not events or not target_file.exists():
			return events

		events_arr = np.array(events, dtype=np.float64)
		current_ts = float(current_timestamp)
		ages_hours = (current_ts - events_arr) / 3600.0
		weights = np.exp(-last_lambda * ages_hours)
		mask = (ages_hours >= 0) & (weights >= threshold)
		pruned_arr = events_arr[mask]

		if len(pruned_arr) < len(events_arr):
			try:
				pruned_list = pruned_arr.astype(int).tolist()
				if not self.dev_mode:
					target_file.write_text(
						"".join(f"{ts}\n" for ts in pruned_list),
						encoding="utf-8",
					)
			except OSError as exc:
				self.logger.log_warning(f"数据剪枝失败: {exc}")
				return events
			return pruned_list

		return events
