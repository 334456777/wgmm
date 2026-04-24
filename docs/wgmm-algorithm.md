# WGMM 算法说明

WGMM 的纯算法实现位于 `wgmm_monitor/wgmm/`。服务层只负责加载历史数据、保存配置和记录日志，算法层不访问网络、环境变量或本地文件。

## 文件分工

| 文件 | 职责 |
|------|------|
| `constants.py` | 默认权重、sigma、lambda、扫描窗口等常量 |
| `features.py` | 时间特征提取和离散维度提取 |
| `learning.py` | 异常值过滤、自适应参数学习、自相关周期发现 |
| `scoring.py` | 单点得分和批量得分 |
| `scheduler.py` | 调频决策、未来峰值扫描、配置更新 |

服务入口是 `wgmm_monitor/services/frequency.py`，核心函数是 `decide_next_frequency()`。

## 核心思想

算法把“某个时间点是否可能发布”建模为历史事件在周期时间特征空间中的加权相似度。

输入：

- 正向事件：`data/mtime.txt` 中的真实上传时间戳。
- 负向事件：`data/miss_history.txt` 中未发现新内容的检查时间。
- 当前时间。
- 上一次持久化的 `WgmmConfig`。

输出：

- 下一次检查时间 `next_check_time`。
- 学到的 `dimension_weights`、`sigmas`、`last_lambda` 等状态。
- 是否需要保存本次 miss history。

## 时间特征

`vectorized_time_features_numpy()` 生成周期特征：

```text
day_sin / day_cos
week_sin / week_cos
month_week_sin / month_week_cos
year_month_sin / year_month_cos
custom_N_sin / custom_N_cos
```

固定维度：

- `day`：一天内的秒数，周期 86400 秒。
- `week`：一周内的秒数，周期 604800 秒。
- `month_week`：月内第几周，按 6 个桶编码。
- `year_month`：月份，周期 12。

附加维度：

- `custom_N`：来自 `discovered_periods` 的任意秒级周期。

sin/cos 编码避免了周期边界问题，例如 23:59 与 00:01 在线性时间上相距很远，但在单位圆上相近。

## 预处理

`FrequencyService.adjust_check_frequency()` 会在进入调度器前做预处理：

1. 如果 `mtime.txt` 不存在，调用 `HistoryService.generate_mtime_file()`。
2. 加载正向和负向事件。
3. 用 `filter_outliers()` 过滤未来时间和异常间隔。
4. 当正向事件数量达到 `PRUNE_THRESHOLD` 时，用 `prune_old_data()` 剪枝低权重历史。

`filter_outliers()` 使用 IQR：

```text
lower = Q1 - 3 * IQR
upper = Q3 + 3 * IQR
```

剪枝使用指数衰减权重：

```text
weight = exp(-last_lambda * age_hours)
```

## 学习期

`MIN_HISTORY_COUNT = 10`。

当正向事件少于 10 条时，调度器进入学习期：

- 如果有正向或负向事件，使用历史间隔中位数作为下一次检查间隔。
- 如果没有任何事件，使用 `FALLBACK_INTERVAL = 3600` 秒。
- 不执行完整权重、sigma、周期发现和峰值扫描。

学习期目标是收集足够历史，而不是做强预测。

## 自适应 lambda

`calculate_adaptive_lambda()` 根据事件间隔方差和变异系数学习遗忘速度。

```text
intervals = diff(sorted(timestamps))
current_variance = var(intervals)
cv = std(intervals) / mean(intervals)
lambda_min = lambda_base * 0.3
lambda_max = min(lambda_base * (1 + cv * 4), lambda_base * 15)
```

方差越大，发布越不稳定，lambda 越高，旧数据越快被遗忘。方差越小，lambda 越低，长期规律保留得更多。

正向事件和负向事件分别计算 lambda，正向 lambda 保存为 `last_lambda`。

## 自相关周期发现

`discover_periods()` 在数据足够时发现非日历周期：

- 最少 50 条正向事件。
- 数据跨度至少 168 小时。
- 构建小时级信号。
- 使用 FFT 计算自相关。
- 在 2 天到 90 天范围内寻找局部峰值。
- 排除日、周、月、年附近的已有周期。
- 排除与已选周期成整数倍或约数关系的谐波。
- 最多返回 3 个周期。

`sync_discovered_periods()` 使用 10% 容忍度复用旧周期，确保 `custom_0`、`custom_1` 等索引稳定。

## 维度权重

`learn_dimension_weights()` 在正向历史不少于 20 条时启用。

流程：

1. `get_raw_time_components()` 提取每个维度的离散桶。
2. 统计每个桶的出现次数。
3. 用 `mean(counts) / std(counts)` 估计集中度。
4. 归一化到总权重约 2.0。
5. 用学习率平滑旧权重和新权重。

分布越集中，说明该维度对发布模式越有解释力。

## 自适应 sigma

`learn_adaptive_sigmas()` 也在正向历史不少于 20 条时启用。

流程：

1. 提取原始维度值。
2. 将维度值归一化到 `[0, 1]`。
3. 计算标准差。
4. `adaptive_sigma = max(0.2, min(std * 3.0, 3.0))`。
5. 用 `old_sigma * 0.7 + adaptive_sigma * 0.3` 平滑更新。

sigma 越小，匹配越严格；sigma 越大，匹配越宽松。

## 得分计算

`calculate_point_score()` 计算一个时间点的得分。

对每个事件：

```text
age_hours = (target_timestamp - event_timestamp) / 3600
time_weight = exp(-lambda_decay * age_hours)
distance_sq = (target_sin - event_sin)^2 + (target_cos - event_cos)^2
dimension_similarity = exp(-distance_sq / (2 * sigma^2))
combined = sum(dimension_weight * dimension_similarity)
```

正向得分提高检查概率，负向得分抑制检查概率：

```text
score = clip(pos_score - resistance_coefficient * neg_score, 0, 1)
```

`batch_calculate_scores()` 用 NumPy 广播一次性计算未来扫描窗口的多个时间点。

## 未来峰值扫描

`scan_future_peak()` 默认扫描未来 15 天。

扫描步长由 day sigma 推导：

```text
gaussian_width = (sigmas["day"] * 86400 / 24) * 2
min_step = gaussian_width * 0.25
scan_step = min_step if current_score > 0.5 else min_step * 2
```

峰值选择：

1. 批量计算所有扫描点得分。
2. 计算均值和标准差。
3. 用梯度变化寻找局部峰值。
4. 优先选择高于 `mean + 1.5 * std` 且梯度较平缓的峰。
5. 没有合格局部峰时，退回原始局部峰。
6. 仍没有局部峰时，使用全局最高分。

## 间隔映射

调频决策使用数据驱动的边界：

```text
min_check_interval = percentile(positive_intervals, 20)
peak_distance = max(best_peak_time - current_timestamp, 0)
max_check_interval = max(peak_distance, min_check_interval)
```

如果没有正向间隔，则使用 `FALLBACK_INTERVAL`。

当前得分会相对未来扫描窗口归一化：

```text
relative_score = (current_score - scan_min) / (scan_max - scan_min)
exponential_score = relative_score ** MAPPING_CURVE
check_interval = max_interval - (max_interval - min_interval) * exponential_score
```

得分越高，间隔越接近 `min_check_interval`；得分越低，间隔越接近预测峰值距离。

## 峰值提前与阻抗

如果未来最佳峰值明显高于当前得分：

```text
best_peak_score > current_score * 1.2
```

并且峰值足够近，算法会用 `max(last_ytdlp_duration, normal_ytdlp_duration)` 提前检查，避免刚好错过发布峰值。

如果最近一次 `yt-dlp` 耗时超过正常耗时两倍，调度器会增加最多 50% 的阻抗因子，降低请求压力。

## miss history

当一次自动调频未发现新内容，且不是手动运行时：

```text
should_save_miss = True
miss_timestamp = current_timestamp
```

服务层随后写入 `data/miss_history.txt`。dev mode 和手动运行不会写真实负向历史。

## 数据流图

```text
data/mtime.txt
data/miss_history.txt
    -> FrequencyService
    -> filter_outliers()
    -> prune_old_data()
    -> decide_next_frequency()
        -> adaptive lambda
        -> period discovery
        -> weights/sigmas
        -> current score
        -> future peak scan
        -> interval mapping
    -> FrequencyDecision
    -> data/wgmm_config.json
    -> optional data/miss_history.txt append
```

## 调优位置

默认参数：

```text
wgmm_monitor/wgmm/constants.py
```

常用参数：

- `DEFAULT_DIMENSION_WEIGHTS`
- `DEFAULT_SIGMAS`
- `LAMBDA_BASE`
- `MAPPING_CURVE`
- `MIN_HISTORY_COUNT`
- `LOOKAHEAD_DAYS`
- `FALLBACK_INTERVAL`

调优后运行：

```bash
source .venv/bin/activate
ruff check monitor.py wgmm_monitor tests
ruff format --check monitor.py wgmm_monitor tests
python -m unittest discover -s tests
python monitor.py --wgmm-core-only
```

## 常见问题

### 算法是否硬编码固定检查间隔？

不是。当前实现没有固定 5 分钟或 30 天边界。检查间隔来自历史正向间隔、未来峰值距离、当前相对得分和 1 小时回退间隔。

### 为什么数据少时看起来不智能？

少于 10 条正向事件时处于学习期，调度器只使用历史间隔中位数或 1 小时回退。权重和 sigma 学习需要至少 20 条正向历史，附加周期发现需要至少 50 条。

### custom_N 是什么？

`custom_N` 是自相关发现的非日历周期维度。例如一个 UP 主接近每 3 天发布，算法可能把 259200 秒加入 `discovered_periods`，并创建 `custom_0` 的 sin/cos 特征、权重和 sigma。

### 如何只验证 WGMM？

```bash
source .venv/bin/activate
python monitor.py --wgmm-core-only
```

该模式跳过 B站检测流程，只运行一次调频。
