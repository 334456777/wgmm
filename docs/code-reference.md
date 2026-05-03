# 代码参考

本文档按当前模块结构说明代码职责。`monitor.py` 只是兼容入口，实际实现位于 `wgmm_monitor/`。

## 总览

```text
monitor.py
    -> wgmm_monitor.cli
    -> wgmm_monitor.app
    -> services
        -> clients
        -> stores
        -> wgmm
        -> utils
        -> models
```

核心边界：

- `clients`：外部系统 I/O。
- `stores`：本地文件读写。
- `services`：业务流程编排。
- `wgmm`：纯算法层。
- `models`：跨模块数据结构。

## 入口与装配

### `monitor.py`

保留历史运行方式：

```bash
python monitor.py
python monitor.py --dev
python monitor.py --wgmm-core-only
```

文件只导入并调用 `wgmm_monitor.cli.main()`。

### `wgmm_monitor/cli.py`

职责：

- 解析 `--dev` 和 `--wgmm-core-only`。
- 调用 `load_env_file("data/.env")`。
- 创建 `Application`。
- 根据模式调用 `run_forever()`、`run_dev_once()` 或 `run_wgmm_core_only()`。

### `wgmm_monitor/app.py`

`Application` 是运行期依赖装配器。

装配对象：

- `RuntimePaths`
- `AppConfig`
- `RuntimeLogger`
- `BarkClient`
- `GistClient`
- `YtDlpClient`
- `ConfigStore`
- `UrlStore`
- `HistoryStore`
- `BilibiliService`
- `HistoryService`
- `FrequencyService`
- `MonitorService`
- `NotificationService`

启动校验：

- 必需环境变量缺失时退出。
- `data/cookies.txt` 缺失、为空或不可读时记录严重错误并退出。
- 注册 `SIGTERM` 和 `SIGINT` 信号处理器。

## 配置与模型

### `wgmm_monitor/config.py`

- `load_env_file()`：读取简单 `KEY=VALUE` 格式的 `data/.env`。
- `load_app_config()`：从环境变量生成 `AppConfig`。

### `wgmm_monitor/models.py`

主要数据模型：

- `RuntimePaths`：所有运行时路径。
- `AppConfig`：Gist、Bark、Bilibili 配置。
- `WgmmConfig`：WGMM 持久化状态，未知字段保存在 `extra` 并写回。
- `YtDlpResult`：`yt-dlp` 执行结果。
- `FrequencyDecision`：一次调频决策结果。

## 外部客户端

### `wgmm_monitor/clients/ytdlp.py`

`YtDlpClient` 只负责执行 `yt-dlp`：

- 首次调用时用 `shutil.which("yt-dlp")` 查找可执行文件并缓存路径。
- 使用 `subprocess.run()` 执行命令。
- 记录 `last_duration`。
- 对成功调用更新 `normal_duration` 指数滑动均值。
- 返回 `YtDlpResult`，不抛出业务异常。

### `wgmm_monitor/clients/gist.py`

`GistClient` 封装 GitHub Gist API：

- `fetch_urls()` 读取 Gist 中的 `urls.txt`。
- `write_new_urls()` 写入 Gist 中的 `new.txt`。
- HTTP 或 JSON 错误以 `(success, data, error)` 形式返回给服务层处理。

### `wgmm_monitor/clients/bark.py`

`BarkClient` 构造 Bark URL 并发送 GET 请求。通知语义不在 client 层处理，由 `NotificationService` 决定。

## 本地存储

### `wgmm_monitor/stores/config_store.py`

管理 `data/wgmm_config.json`：

- 缺失时使用 `WgmmConfig()` 默认值。
- JSON 损坏时记录 warning 并使用默认配置。
- dev mode 下 `save()` 不写磁盘。
- `ensure_manual_flag()` 保证生产模式首次运行时存在 `is_manual_run`。

### `wgmm_monitor/stores/history_store.py`

管理历史事件：

- `load_positive_events()` 读取 `data/mtime.txt`。
- `load_miss_history()` 读取 `data/miss_history.txt`。
- `save_miss_history()` 保存一次负向事件；手动运行和 dev mode 不写真实文件。
- `append_upload_timestamps()` 追加真实上传时间。
- `prune_old_data()` 根据指数衰减权重剪枝低权重历史。

### `wgmm_monitor/stores/url_store.py`

管理 `data/local_known.txt`：

- `load()` 返回本地已知 URL 集合。
- `save()` 写入排序后的 URL。
- dev mode 下写入内存沙盒。

## 业务服务

### `wgmm_monitor/services/monitor.py`

`MonitorService` 编排主监控流程。

关键状态：

- `memory_urls`：从 Gist 读取的云端 URL。
- `known_urls`：本地完整已知 URL 集合。

关键方法：

- `sync_urls_from_gist()`：读取 Gist 并合并本地状态。
- `run_monitor()`：执行一次完整检测和调频。
- `wait_for_next_check()`：根据 `FrequencyService.get_next_check_time()` 等待。
- `adjust_check_frequency()`：兼容入口，传入 `yt-dlp` 耗时给调频服务。
- `cleanup()`：dev mode 下清理临时目录。

`run_monitor()` 的重要分支：

- Gist 失败且没有基准 URL：跳过本轮。
- 两层预检查都无变化：直接按未发现新内容调频。
- 完整视频列表首次失败：等待 30 秒重试一次。
- 分片扩展返回空：跳过本轮检测，避免基础 URL 误判。
- 新 URL 存在：保存真实上传时间、更新本地状态、写 Gist、发送通知、按发现新内容调频。

### `wgmm_monitor/services/bilibili.py`

`BilibiliService` 封装 B站相关业务：

- `check_potential_new_parts()`：第一层，多分片预检查。
- `quick_precheck()`：第二层，获取最新视频 ID，并同时检查 `memory_urls` 与 `known_urls`。
- `fetch_video_list()`：第三层完整扫描入口。
- `get_video_parts()`：获取单个视频的所有分片 URL。
- `get_all_videos_parallel()`：最多 5 个线程并行展开分片。
- `get_video_upload_time()`：获取真实上传时间，优先 `timestamp`，降级 `upload_date`。

### `wgmm_monitor/services/history.py`

`HistoryService` 维护 `mtime.txt`：

- `save_real_upload_timestamps()`：为真正新 URL 获取真实上传时间。获取失败时跳过，不使用当前时间伪造。
- `generate_mtime_file()`：保证 `mtime.txt` 可用，最多尝试 3 次。
- `create_mtime_from_info_json()`：通过 `yt-dlp --write-info-json` 批量提取上传时间。

### `wgmm_monitor/services/frequency.py`

`FrequencyService` 是服务层与纯算法层的边界：

- 读取正向/负向事件。
- 过滤异常值。
- 必要时剪枝旧数据。
- 调用 `decide_next_frequency()`。
- 保存 miss history 和 WGMM 配置。
- dev mode 下不写真实配置。

### `wgmm_monitor/services/notification.py`

负责通知内容：

- `notify_new_videos()`
- `notify_error()`
- `notify_critical_error()`

## WGMM 算法层

### `wgmm_monitor/wgmm/constants.py`

默认值：

- `DEFAULT_DIMENSION_WEIGHTS`
- `DEFAULT_SIGMAS`
- `LAMBDA_BASE`
- `MAPPING_CURVE`
- `MIN_HISTORY_COUNT`
- `PRUNE_THRESHOLD`
- `LOOKAHEAD_DAYS`
- `FALLBACK_INTERVAL`

### `wgmm_monitor/wgmm/features.py`

- `vectorized_time_features_numpy()`：生成 sin/cos 周期特征。
- `get_raw_time_components()`：生成离散维度值，用于权重和 sigma 学习。

固定维度：

- `day`
- `week`
- `month_week`
- `year_month`

附加维度：

- `custom_0`、`custom_1`、`custom_2`，来自 `discovered_periods`。

### `wgmm_monitor/wgmm/learning.py`

- `aggregate_publish_events()`：链式合并 600 秒内的连续时间戳，把视频粒度折成 UP 主行为粒度。仅用于正向事件。
- `filter_outliers()`：IQR 过滤异常间隔。仅用于负向事件（正向数据有批量发布，IQR 短端失效）。
- `calculate_adaptive_lambda()`：根据间隔方差和变异系数学习遗忘速度。
- `discover_periods()`：自相关发现非日历周期。
- `sync_discovered_periods()`：稳定 `custom_N` 映射，避免索引漂移。
- `initialize_wgmm_dimensions()`：同步 custom 权重和 sigma。
- `learn_dimension_weights()`：按维度分布集中度学习权重。
- `learn_adaptive_sigmas()`：按离散度学习 sigma。

### `wgmm_monitor/wgmm/scoring.py`

- `calculate_point_score()`：计算单个时间点得分。
- `batch_calculate_scores()`：批量计算扫描窗口得分。

得分由正向事件贡献减去负向事件惩罚，并裁剪到 `[0, 1]`。

### `wgmm_monitor/wgmm/scheduler.py`

- `scan_future_peak()`：扫描未来 `LOOKAHEAD_DAYS` 天并寻找峰值。
- `decide_next_frequency()`：完整调频决策。

决策步骤：

1. 初始化固定维度和 custom 维度。
2. 数据不足时进入学习期，使用历史间隔中位数或 1 小时回退。
3. 学习 lambda、周期、维度权重和 sigma。
4. 计算当前得分。
5. 扫描未来峰值。
6. 将相对得分映射为检查间隔。
7. 如果峰值足够强，根据 `yt-dlp` 正常耗时提前检查。
8. 当最近 `yt-dlp` 耗时异常增大时加入阻抗因子。
9. 更新 `WgmmConfig` 并返回 `FrequencyDecision`。

## 日志与错误

### `wgmm_monitor/runtime_logger.py`

- `log_message()`：控制台输出；非 dev mode 写 `urls.log`。
- `log_error()`：可选普通错误通知。
- `log_critical_error()`：写 `critical_errors.log`，非 dev mode 可发送严重通知。
- `limit_file_lines()`：限制日志和历史文件行数。

严重错误不会自动代表程序退出，是否退出由 `Application` 或服务层决定。

## 常见修改

### 调整预测激进程度

修改 `wgmm_monitor/wgmm/constants.py`：

```python
MAPPING_CURVE = 2.0
```

值越大，高分时越容易靠近最小检查间隔；值越小，检查间隔更保守。

### 调整默认时间容忍度

修改 `DEFAULT_SIGMAS`：

```python
DEFAULT_SIGMAS = {
	"day": 0.8,
	"week": 1.0,
	"month_week": 1.5,
	"year_month": 2.0,
}
```

运行后 sigma 会随历史数据自适应更新。

### 调整记忆速度

修改 `LAMBDA_BASE`：

```python
LAMBDA_BASE = 0.0001
```

实际 lambda 会由 `calculate_adaptive_lambda()` 根据间隔方差动态计算。

### 修改检测策略

- 预检查和完整扫描：`wgmm_monitor/services/bilibili.py`
- 主分支和降级行为：`wgmm_monitor/services/monitor.py`
- 上传时间保存策略：`wgmm_monitor/services/history.py`

## 验证命令

```bash
source .venv/bin/activate
ruff check monitor.py wgmm_monitor tests
ruff format --check monitor.py wgmm_monitor tests
python -m unittest discover -s tests
python monitor.py --wgmm-core-only
python monitor.py --dev
```
