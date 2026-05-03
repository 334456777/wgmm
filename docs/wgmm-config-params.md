# wgmm_config.json 参数说明

`data/wgmm_config.json` 是 WGMM 调频状态快照，由 `WgmmConfig`、`ConfigStore` 和 `wgmm_monitor/wgmm/scheduler.py` 共同维护。未知字段会保存在 `WgmmConfig.extra`，写回时原样保留，便于兼容旧配置或未来扩展。

## 当前字段

```json
{
  "dimension_weights": {
    "day": 0.5,
    "week": 1.0,
    "month_week": 0.3,
    "year_month": 0.2
  },
  "last_lambda": 0.0001,
  "last_pos_variance": 0.0,
  "last_neg_variance": 0.0,
  "last_update": 0,
  "next_check_time": 0,
  "is_manual_run": true,
  "sigmas": {
    "day": 0.8,
    "week": 1.0,
    "month_week": 1.5,
    "year_month": 2.0
  },
  "discovered_periods": []
}
```

默认值定义在 `wgmm_monitor/wgmm/constants.py`，读写模型定义在 `wgmm_monitor/models.py`。

## `dimension_weights`

时间维度权重，控制各维度在加权高斯相似度中的贡献。

| 键 | 默认值 | 含义 |
|----|--------|------|
| `day` | `0.5` | 日内小时模式 |
| `week` | `1.0` | 一周内时间模式 |
| `month_week` | `0.3` | 月内第几周模式 |
| `year_month` | `0.2` | 年内月份模式 |
| `custom_N` | `0.1` | 自相关发现的附加周期维度 |

`learn_dimension_weights()` 在正向历史不少于 20 条时更新权重。它统计每个维度的离散桶分布，分布越集中，该维度越有预测价值。更新采用平滑学习率，不会一次性大幅跳变。

`custom_N` 只在 `discovered_periods` 非空时出现。`initialize_wgmm_dimensions()` 会补齐缺失的 custom 权重，并删除已经无对应周期的旧 custom 键。

## `sigmas`

各维度高斯核标准差，控制时间相似度的宽松程度。

| 键 | 默认值 | 含义 |
|----|--------|------|
| `day` | `0.8` | 日内时间容忍度 |
| `week` | `1.0` | 周周期容忍度 |
| `month_week` | `1.5` | 月内周容忍度 |
| `year_month` | `2.0` | 月份容忍度 |
| `custom_N` | `1.0` | 附加周期容忍度 |

公式：

```text
similarity = exp(-distance_sq / (2 * sigma^2))
```

sigma 越小，匹配越严格；sigma 越大，匹配越宽松。`learn_adaptive_sigmas()` 根据历史数据在各维度上的离散度自适应更新。

## `last_lambda`

正向事件的最近一次自适应遗忘速度，单位是“每小时”。

公式：

```text
weight = exp(-lambda * age_hours)
```

`calculate_adaptive_lambda()` 根据事件间隔方差和变异系数计算：

- `lambda_min = LAMBDA_BASE * 0.3`
- `lambda_max = LAMBDA_BASE * (1 + cv * 4)`，并限制到 `LAMBDA_BASE * 15`
- 方差越大，lambda 越大，旧数据遗忘越快
- 方差越小，lambda 越小，旧数据保留越久

参考半衰期：

| lambda | 半衰期 |
|--------|--------|
| `0.00005` | 约 578 天 |
| `0.0001` | 约 289 天 |
| `0.0005` | 约 58 天 |
| `0.001` | 约 29 天 |

## `last_pos_variance` / `last_neg_variance`

最近一次正向事件和负向事件间隔方差，单位是秒平方。

- `last_pos_variance`：来自 `data/mtime.txt`。
- `last_neg_variance`：来自 `data/miss_history.txt`。

这两个值作为下一次 `calculate_adaptive_lambda()` 的趋势参考。数值通常很大，直接阅读意义不如观察 `last_lambda` 和日志中的轮询间隔。

## `last_update`

最近一次完整非学习期调频更新时间，Unix 秒时间戳。

数据不足进入学习期时，调频会更新 `next_check_time`，但不会写入完整学习参数。

## `next_check_time`

下一次检查时间，Unix 秒时间戳。

- 生产模式由 `MonitorService.wait_for_next_check()` 读取并等待。
- dev mode 只打印下次检查时间，不 sleep。
- `--wgmm-core-only` 会计算一次该值后退出。

## `is_manual_run`

手动运行保护标记。

- 默认 `true`。
- 生产模式第一次进入调频时，如果为 `true`，会切换为 `false`。
- 手动运行时不保存 miss history，避免把用户临时启动污染为负向样本。
- dev mode 始终按手动运行处理。

## `discovered_periods`

自相关发现的非日历周期，单位是秒，最多 3 个。

示例：

```json
"discovered_periods": [259200.0]
```

表示发现约 3 天周期。发现流程在 `discover_periods()`：

- 至少 50 条正向历史。
- 数据跨度至少 168 小时。
- 构建小时级事件信号。
- 通过 FFT 自相关寻找 2 天到 90 天范围内的局部峰值。
- 过滤日、周、月、年附近的已有周期。
- 过滤整数倍/约数谐波。

`sync_discovered_periods()` 用 10% 容忍度复用已有周期，保持 `custom_N` 索引稳定，避免已经学到的权重频繁漂移。

## 字段关系

```text
data/mtime.txt
data/miss_history.txt
    -> aggregate_publish_events() for positive
    -> filter_outliers() for negative
    -> prune_old_data()
    -> calculate_adaptive_lambda()
        -> last_lambda
        -> last_pos_variance / last_neg_variance
    -> discover_periods()
        -> discovered_periods
        -> custom_N weights/sigmas
    -> learn_dimension_weights()
        -> dimension_weights
    -> learn_adaptive_sigmas()
        -> sigmas
    -> decide_next_frequency()
        -> next_check_time
        -> last_update
        -> is_manual_run
```

## 不存在的旧字段

当前 `WgmmConfig` 不包含 `score_calibration`、固定 `MIN_INTERVAL`、固定 `MAX_INTERVAL` 或独立低活跃度参数。检查间隔边界由历史事件间隔、未来峰值距离和 `FALLBACK_INTERVAL` 动态决定。
