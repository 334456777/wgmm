# 代码参考

本文档提供代码库的结构化参考,从 CLAUDE.md 中提取,供 WGMM 视频监控系统的开发者使用。

## 目录

- [VideoMonitor 类](#videomonitor-类)
  - [初始化与配置](#初始化与配置)
  - [WGMM 核心算法](#wgmm-核心算法)
  - [三层检测架构](#三层检测架构)
  - [数据管理](#数据管理)
  - [日志与通知](#日志与通知)
  - [工具方法](#工具方法)
- [WGMM 算法数学核心](#wgmm-算法数学核心)
  - [时间特征周期性编码](#时间特征周期性编码)
  - [高斯核相似性](#高斯核相似性)
  - [指数时间衰减](#指数时间衰减)
  - [自适应学习机制](#自适应学习机制)
- [常见代码修改场景](#常见代码修改场景)
  - [调整预测激进程度](#调整预测激进程度)
  - [修改时间容忍度](#修改时间容忍度)
  - [调整记忆速度](#调整记忆速度)
- [性能优化要点](#性能优化要点)
  - [向量化计算](#向量化计算)
  - [批处理优化](#批处理优化)
  - [内存管理](#内存管理)

---

## VideoMonitor 类

`monitor.py` (约 2345 行,61 个方法) 是整个系统的核心,包含完整的监控逻辑和 WGMM 算法实现。

### 初始化与配置

#### `__init__()`
**用途**: 初始化监控系统,加载环境变量和配置

**主要职责**:
- 从 `.env` 文件加载环境变量
- 初始化 WGMM 算法参数
- 设置日志和通知系统
- 从本地和远程源加载已知 URL

**另见**: `load_env_file()`, `_load_wgmm_config()`

---

#### `load_env_file()`
**用途**: 从 `.env` 文件加载环境变量

**必需变量**:
- `GITHUB_TOKEN`: 用于 Gist 操作的 GitHub API 令牌
- `BARK_DEVICE_KEY`: Bark 通知设备密钥
- `GIST_ID`: 用于 URL 备份的 GitHub Gist ID
- `BILIBILI_UID`: 要监控的 Bilibili 用户 ID

---

#### `_load_wgmm_config()`
**用途**: 从 `wgmm_config.json` 加载 WGMM 算法配置

**加载的参数**:
- 维度权重 (day, week, month_week, year_month, 以及 custom_N 附加维度)
- 自适应 lambda 值
- 每个维度的 Sigma 值
- `discovered_periods`：自相关自动发现的附加周期列表（秒）
- 历史统计数据

---

#### `_save_wgmm_config()`
**用途**: 将当前 WGMM 算法状态保存到 `wgmm_config.json`

**保存的数据**:
- 学习到的维度权重
- 自适应 lambda 值
- 学习到的 sigma 值
- 算法统计信息

---

### WGMM 核心算法

#### `adjust_check_frequency()`
**用途**: WGMM 算法主函数,根据历史数据计算下次检查间隔

**算法步骤**:
1. 加载正向事件 (mtime.txt) 和负向事件 (miss_history.txt)
2. 使用 IQR 方法过滤异常值
3. 剪枝低权重的旧数据
4. 根据发布方差计算自适应 lambda
5. 自相关自动发现附加周期（`_discover_periods` + `_sync_discovered_periods`），更新 `discovered_periods`
6. 为每个时间维度学习维度权重（含 custom_N 附加维度）
7. 调用 `_scan_future_peak()` 扫描未来 15 天找峰值
8. 将得分映射到检查间隔

**另见**: `_scan_future_peak()`

**关键特性**:
- 多维度时间特征编码 (日、周、月周、年月)
- 高斯核相似性计算
- 指数时间衰减权重
- 自适应 lambda 调整 (遗忘速度)
- 动态维度权重学习

**返回值**: `int` - 下次检查间隔(秒)

**另见**: `_calculate_adaptive_lambda()`, `learn_dimension_weights()`, `_calculate_point_score()`

---

#### `generate_mtime_file()`
**用途**: 生成历史发布时间戳文件(仅首次运行)

**处理过程**:
- 使用 yt-dlp 获取所有视频上传时间
- 将 Unix 时间戳保存到 `mtime.txt`
- 作为 WGMM 算法的训练数据

**注意**: 仅在 `mtime.txt` 不存在时运行

---

#### `create_mtime_from_info_json()`
**用途**: 通过 yt-dlp 获取所有视频的 info.json, 提取上传时间戳生成 mtime.txt

**处理过程**:
- 创建临时目录存储 info.json 文件
- 使用 yt-dlp --write-info-json 下载所有视频的元数据
- 解析 upload_date 字段提取时间戳
- 清理临时文件

**优势**: 比 generate_mtime_file 更可靠,直接使用元数据中的上传日期

---

#### `_calculate_adaptive_lambda()`
**用途**: 根据发布方差自适应计算 lambda 参数

**算法**:
- 计算发布时间戳的方差
- 较高方差 → 更快遗忘 (更高的 lambda)
- 较低方差 → 更慢遗忘 (更低的 lambda)
- 基础 lambda: 0.0001/小时

**返回值**: `float` - 自适应 lambda 值

---

#### `_discover_periods(timestamps)`
**用途**: 自相关分析，从历史时间戳中发现非日历周期，作为附加维度候选

**算法**:
1. 数据不足（< 50 条或跨度 < 168 小时）时返回空列表
2. 将时间戳投影到小时级信号（每桶计事件数）
3. Wiener-Khinchin 定理计算自相关：FFT → |FFT|² → IFFT，归一化到 [0,1]
4. 在 2天~90天 范围内找自相关局部极大值（阈值 0.02）
5. 过滤已有 4 维覆盖的周期（±20% 容忍）
6. 过滤与已选周期成整数倍/约数关系的谐波伪峰（±20% 容忍）
7. 按自相关强度降序选取最多 3 个新周期

**返回值**: `list[float]` - 发现的新周期（秒），数据不足时返回 `[]`

**注意**: 返回空列表时对算法完全无影响（向后兼容）

---

#### `_sync_discovered_periods(new_periods)`
**用途**: 将本次自相关发现的周期与配置中已存储的周期对比，稳定映射到 `custom_N` 索引

**算法**: 对每个新发现周期，在已存储周期中寻找 ±10% 内的匹配。匹配成功则复用已有条目（保留学习到的权重），否则使用新周期值（权重重置为 0.1）

**副作用**: 更新 `self.wgmm_config["discovered_periods"]`

---

#### `learn_dimension_weights()`
**用途**: 为每个时间维度学习重要性权重

**维度**:
- `day`: 一天中的小时 (24 小时周期)
- `week`: 一周中的天数 (7 天周期)
- `month_week`: 月中的周
- `year_month`: 年中的月份
- `custom_0` ~ `custom_2`: 自相关自动发现的非日历周期（可选，最多 3 个）

**方法**:
- 计算每个维度的得分方差
- 更高的方差表示更强的预测能力
- 将权重归一化到总和为 1.0

**返回值**: `dict` - 维度权重

---

#### `_scan_future_peak()`
**用途**: 扫描未来时间窗口, 找到发布概率峰值

**处理过程**:
1. 批量生成未来时间点 (默认 15 天, 每 30 分钟一个点)
2. 使用 `_batch_calculate_scores()` 计算每个时间点的发布概率
3. 应用高斯模糊平滑得分曲线
4. 找到最高得分对应的时间
5. 计算提前检查时间 (峰值前几分钟)

**返回值**: `tuple[int, int]` - (峰值时间戳, 提前检查时间戳)

**参数**:
- `lookahead_days`: 扫描未来天数 (默认 15)
- `gaussian_width`: 高斯模糊宽度 (默认 2.0)

---

### 三层检测架构

#### `check_potential_new_parts()`
**用途**: 第一层 - 分片预检查

**处理过程**:
- 快速检查新的视频分片
- 轻量级验证
- 仅在发现潜在新分片时触发更深层检查

**性能**: 最小的网络开销

---

#### `quick_precheck()`
**用途**: 第二层 - 快速 ID 检查

**处理过程**:
- 将视频 ID 与已知 URL 比较
- 快速识别变化
- 如果检测到变化则触发第三层

**性能**: < 1 秒

**另见**: `run_monitor()`, `get_all_videos_parallel()`

---

#### `run_monitor()`
**用途**: 第三层 - 完整深度检查 (主监控循环)

**主循环流程**:
```
run_monitor()
├── sync_urls_from_gist()       # 从 GitHub Gist 同步已知 URL
├── check_potential_new_parts() # 第一层: 分片预检查
├── quick_precheck()            # 第二层: 快速 ID 检查
│   └── 如果有变化 → 触发完整检查
├── get_all_videos_parallel()   # 第三层: 完整深度检查
├── notify_new_videos()         # 发送通知
└── adjust_check_frequency()    # WGMM 计算下次检查时间
```

**性能**: 约 2 秒 (主要是 yt-dlp I/O)

---

### 数据管理

#### `sync_urls_from_gist()`
**用途**: 从 GitHub Gist 同步已备份的 URL 列表

**处理过程**:
- 从 GitHub Gist 获取最新内容
- 更新 `memory_urls` 集合
- 防止因同步延迟导致的重复通知

**API**: GitHub Gist API v3

---

#### `load_known_urls()`
**用途**: 从 `local_known.txt` 加载本地已知 URL

**数据流向**:
```
local_known.txt (本地状态)
    +
memory_urls (来自 Gist)
    ↓
known_urls (完整已知集合)
```

---

#### `save_known_urls()`
**用途**: 将本地已知 URL 保存到 `local_known.txt`

**注意**: 仅保存尚未同步到 Gist 的 URL

---

#### `get_video_upload_time()`
**用途**: 获取视频上传时间戳

**返回值**: `int` - Unix 时间戳

**工具**: yt-dlp

---

### 日志与通知

#### `send_bark_push()`
**用途**: 发送 Bark 推送通知

**参数**:
- `title`: 通知标题
- `body`: 通知正文
- `sound`: 通知声音 (可选)
- `badge`: 角标数字 (可选)

**API**: Bark 推送 API

---

#### `notify_new_videos()`
**用途**: 通知新发现的视频

**处理过程**:
1. 过滤真正的新 URL (不在 known_urls 中)
2. 发送 Bark 推送通知
3. 用新 URL 更新 GitHub Gist
4. 保存到 local_known.txt

---

#### `notify_critical_error()`
**用途**: 通知严重错误

**特性**:
- 发送 Bark 推送通知
- 记录到 `critical_errors.log`
- 用于系统级故障

---

#### `notify_error()`
**用途**: 发送普通错误通知到 Bark

**特性**:
- 推送级别: `active`
- 标题格式: "{BARK_APP_TITLE} - 错误"

---

#### `notify_service_issue()`
**用途**: 发送服务异常通知到 Bark

**特性**:
- 推送级别: `timeSensitive` (最高优先级)
- 标题格式: "{BARK_APP_TITLE} - 服务异常"
- 用于检测服务异常 (如 cookies 过期、API 限流)

---

#### `log_message()`
**用途**: 统一日志记录接口

**级别**: INFO, WARNING, ERROR, CRITICAL

**输出**: `urls.log`

**日志轮转**: 最多 1000 行

---

#### `log_info()`
**用途**: 记录 INFO 级别日志的快捷方法

---

#### `log_warning()`
**用途**: 记录 WARNING 级别日志的快捷方法

---

#### `log_error()`
**用途**: 记录 ERROR 级别日志

**参数**:
- `send_bark_notification`: 是否发送 Bark 通知 (默认 True)

---

#### `log_critical_error()`
**用途**: 将严重错误记录到 `critical_errors.log`

**特性**:
- 严重错误专用日志文件
- 自动 Bark 通知
- 最多 500 行

---

### 工具方法

#### `run_yt_dlp()`
**用途**: 执行 yt-dlp 命令并处理输出

**参数**:
- `args`: 命令参数
- `timeout`: 命令超时 (默认: 30 秒)

**返回值**: `str` - 命令输出

**错误处理**: 失败时重试,记录错误

---

#### `get_video_parts()`
**用途**: 获取视频分片信息

**返回值**: `list` - 视频分片

**工具**: yt-dlp

---

#### `get_all_videos_parallel()`
**用途**: 并行获取视频信息

**方法**: ThreadPoolExecutor

**性能**: 显著快于顺序请求

---

#### `cleanup()`
**用途**: 清理临时文件

**清理的文件**:
- 临时 yt-dlp 输出文件
- 日志文件 (当达到大小限制时)

---

#### `get_next_check_time()`
**用途**: 获取下次检查时间戳

**返回值**: `int` - 下次检查的 Unix 时间戳

---

#### `save_next_check_time()`
**用途**: 保存下次检查时间戳到配置文件

**参数**:
- `next_check_timestamp`: 下次检查的 Unix 时间戳

**注意**: 开发模式下保存到 `sandbox_next_check_time`, 不写入文件

---

#### `_get_jst_datetime_str()`
**用途**: 获取 JST 时区的格式化日期时间字符串

**返回值**: `str` - 格式为 "YYYY-MM-DD HH:MM:SS" 的字符串

---

#### `_get_local_timezone_offset()`
**用途**: 获取本地时区偏移量 (秒)

**返回值**: `float` - 本地时区相对于 UTC 的偏移秒数

**注意**: 自动处理夏令时

---

## WGMM 算法数学核心

理解这些数学原理对修改算法至关重要。

### 时间特征周期性编码

**位置**: monitor.py:1667-1727

**问题**: 线性时间无法表示周期性模式 (23:59 和 00:01 在线性上相距很远)

**解决**: 使用 sin/cos 编码将时间映射到单位圆

```python
# 日周期 (24 小时)
day_sin = sin(2π × seconds_in_day / 86400)
day_cos = cos(2π × seconds_in_day / 86400)

# 周周期 (7 天)
week_sin = sin(2π × day_of_week / 7)
week_cos = cos(2π × day_of_week / 7)

# 月周周期
month_week_sin = sin(2π × week_of_month / 4)
month_week_cos = cos(2π × week_of_month / 4)

# 年月周期
year_month_sin = sin(2π × month / 12)
year_month_cos = cos(2π × month / 12)
```

**四个维度**:
- **日**: 一天中的小时 (24 小时周期)
- **周**: 一周中的天数 (7 天周期)
- **月周**: 月中的周
- **年月**: 年中的月份

---

### 高斯核相似性

**位置**: monitor.py:1849-1864

**用途**: 将时间距离转换为 0-1 的相似度得分

**公式**:
```
similarity = exp(-dist² / (2σ²))
```

**参数**:
- `σ` (sigma): 控制时间容忍度,越小越严格
- `dist`: 特征空间中的欧几里得距离

**特性**:
- 得分范围从 0 到 1
- 更高的得分 = 更相似
- 衰减速率由 sigma 控制

---

### 指数时间衰减

**位置**: monitor.py:1838

**用途**: 近期事件权重更大,远期事件逐渐"遗忘"

**公式**:
```
weight = exp(-λ × age_hours)
```

**参数**:
- `λ` (lambda): 0.0001/小时 (控制遗忘速度)
- `age_hours`: 事件发生后的小时数

**特性**:
- 近期事件: 权重 ≈ 1.0
- 远期事件: 权重 → 0
- 半衰期: ln(2) / λ ≈ 6931 小时 (约 289 天)

---

### 自适应学习机制

#### 动态维度权重
**位置**: monitor.py:1127-1193

**用途**: 算法学习哪些时间维度重要

**方法**:
- 计算每个维度的得分方差
- 更高的方差 = 更强的预测能力
- 将权重归一化到总和为 1.0

**示例**:
```python
weights = {
    "day": 0.4,        # 最重要
    "week": 0.35,      # 其次
    "month_week": 0.15,
    "year_month": 0.1  # 最不重要
}
```

---

#### 自适应 Lambda
**位置**: monitor.py:1053-1111

**用途**: 根据发布方差调整遗忘速度

**逻辑**:
- 高方差 → UP主发布不规律 → 更快遗忘
- 低方差 → UP主有稳定时间表 → 更慢遗忘

**公式**:
```
lambda = base_lambda × (1 + variance_factor)
```

---

#### 自适应 Sigma
**位置**: monitor.py:1195-1238

**用途**: 根据数据离散度调整时间容忍度

**逻辑**:
- 高离散度 → 更宽松的容忍度 (更高的 sigma)
- 低离散度 → 更严格的容忍度 (更低的 sigma)

**公式**:
```
sigma = base_sigma × (1 + dispersion_factor)
```

---

## 常见代码修改场景

### 调整预测激进程度

#### 更激进 (热门 UP主)
```python
# 更频繁检查
mapping_curve = 2.0  # → 改为 3.0 或更高
peak_advance_minutes = 5  # → 改为 10 (更早检查)
```

**效果**:
- 更短的检查间隔
- 更早的峰值检测
- 更多的网络请求

---

#### 更保守 (冷门 UP主)
```python
# 减少请求
mapping_curve = 2.0  # → 改为 1.5
```

**效果**:
- 更长的检查间隔
- 更少的网络请求
- 可能错过一些更新

---

### 修改时间容忍度

#### 更严格 (仅匹配极相似时间)
```python
sigmas["day"] = 0.8  # → 改为 0.5
```

**效果**:
- 仅匹配与历史模式非常接近的时间
- 减少误报
- 可能错过合法更新

---

#### 更宽松 (容忍更大时间差异)
```python
sigmas["week"] = 1.0  # → 改为 1.5
```

**效果**:
- 匹配更宽的时间窗口
- 增加检测覆盖范围
- 可能增加误报

---

### 调整记忆速度

#### 快速适应 (UP主 经常改变习惯)
```python
lambda_base = 0.0001  # → 改为 0.0002
```

**效果**:
- 更快遗忘旧模式
- 更快适应新模式
- 预测不太稳定

---

#### 长期记忆 (UP主 有稳定习惯)
```python
lambda_base = 0.0001  # → 改为 0.00005
```

**效果**:
- 更长时间记住旧模式
- 预测更稳定
- 对变化的适应更慢

---

## 性能优化要点

代码已经高度优化,修改时需保持这些模式。

### 向量化计算

**位置**: monitor.py:1810-1894

**关键原则**:
- 使用 NumPy 向量操作,避免 Python 循环
- `_batch_calculate_scores()` 可一次计算数百个时间点
- 保持向量化风格,避免引入显式循环

**示例**:
```python
# 好: 向量化
scores = np.exp(-distances**2 / (2 * sigma**2))

# 差: 循环
scores = []
for d in distances:
    scores.append(np.exp(-d**2 / (2 * sigma**2)))
```

---

### 批处理优化

**位置**: monitor.py:1896-1975

**关键原则**:
- 峰值预测使用广播机制避免重复计算
- 所有历史事件一次性计算相似性
- 不要将批处理改为循环调用

**示例**:
```python
# 好: 广播
similarities = np.exp(-np.sum((features - target)**2, axis=1) / (2 * sigma**2))

# 差: 循环
similarities = []
for feature in features:
    sim = np.exp(-np.sum((feature - target)**2) / (2 * sigma**2))
    similarities.append(sim)
```

---

### 内存管理

**位置**: monitor.py:952-998

**关键原则**:
- `prune_old_data()` 自动删除低权重历史数据
- 保持 O(n) 时间复杂度,n 为历史事件数
- 典型内存占用 < 1MB

**剪枝策略**:
```python
# 剪枝权重低于阈值的事件
if weight < 0.01:
    remove_event(event)
```

**数据保留**:
- 最少 1000 个事件 (剪枝前)
- 剪枝权重 < 0.01 的事件
- 每次预测后自动清理

---

## 系统架构关键流程

### 主监控循环

**位置**: monitor.py:500-700

```
run_monitor() 主循环
├── sync_urls_from_gist()       # 从 GitHub Gist 同步已知 URL
├── check_potential_new_parts() # 第一层: 分片预检查
├── quick_precheck()            # 第二层: 快速 ID 检查
│   └── 如果有变化 → 触发完整检查
├── get_all_videos_parallel()   # 第三层: 完整深度检查
├── notify_new_videos()         # 发送通知
└── adjust_check_frequency()    # WGMM 计算下次检查时间
```

---

### WGMM 预测流程

**位置**: monitor.py:786-1400

```
adjust_check_frequency()
├── 加载正向事件 (mtime.txt) 和负向事件 (miss_history.txt)
├── filter_outliers()              # 过滤异常值
├── prune_old_data()               # 剪枝低权重历史数据
├── _calculate_adaptive_lambda()   # 自适应计算遗忘速度
├── _discover_periods()            # 自相关发现非日历周期（数据不足时跳过）
├── _sync_discovered_periods()     # 与配置已有周期对比，稳定 custom_N 映射
├── learn_dimension_weights()      # 学习所有维度权重（固定4维 + custom_N）
├── learn_adaptive_sigmas()        # 学习所有维度容忍度
├── _calculate_point_score()       # 计算当前时间发布概率
├── _batch_calculate_scores()      # 扫描未来 15 天找峰值
└── 映射得分 → 检查间隔
```

---

### 数据流向

```
GitHub Gist (云端备份)
    ↓ sync_urls_from_gist()
memory_urls (已备份视频)
    + local_known.txt (本地状态)
    ↓
known_urls (完整已知集合)
    ↓ 对比检测结果
truly_new_urls (真正的新视频)
    ↓ notify_new_videos()
Bark 推送 + GitHub Gist 更新
```

---

## 代码理解提示

**重要**: `monitor.py` 中的所有函数和类都包含详细的中文注释 (docstring 和行内注释)。

当你需要理解某个函数或变量的用途时:

1. **使用 Grep 工具搜索**函数名或关键词,快速定位相关代码
2. **阅读函数的 docstring**,其中包含算法原理、参数说明和返回值描述
3. **查看行内注释**,了解复杂逻辑的实现细节
4. **参考本文档的"关键方法分类"**,快速了解函数的整体功能

**示例**: 搜索 `def adjust_check_frequency` 可以找到 WGMM 算法的主函数,其 docstring 详细说明了算法的 6 个步骤。

---

## 代码质量标准

**重要**: 每次修改 Python 代码后必须运行以下命令,确保代码质量符合规范。

```bash
# 激活虚拟环境
source .venv/bin/activate

# 1. 使用 ruff 检查 Python 代码质量
ruff check monitor.py

# 2. 使用 ruff 格式化 Python 代码
ruff format monitor.py

# 3. 如果 ruff check 发现问题,尝试自动修复
ruff check --fix monitor.py
```

**代码质量标准**:
- `ruff check` 必须通过 (All checks passed!)
- `ruff format` 必须通过 (already formatted 或格式化成功)
- 任何检查失败都不应该提交代码

**代码风格规范 (强制)**:
- 使用 **tab 缩进** (而非空格)
- 行长度限制: **92 字符**
- docstring 和注释使用英文标点符号 (避免全角符号)
- 遵循 Google 风格的 docstring
- 所有函数必须包含 docstring 说明功能、参数和返回值

**配置管理**:
- **禁止**: 修改 `pyproject.toml` 中的 ruff 配置
- ruff 配置 (包括 ignore 规则、line-length、缩进风格等) 是项目强制标准
- 如需调整代码风格,必须修改代码以符合现有配置,而非修改配置文件

**适用范围**:
- ruff 只检查和格式化 `.py` 文件 (Python 代码)
- Markdown 文档 (如 CLAUDE.md、README.md) 不需要 ruff 检查

---

## 相关文档

- **README.md**: 用户文档、算法原理、FAQ、使用指南
- **CONTRIBUTING.md**: 贡献指南、开发流程、代码质量标准
- **CLAUDE.md**: 面向 AI 助手的开发指南
- **docs/adr/**: 架构决策记录
  - `001-keep-python-implementation.md`: 保持 Python 实现的决策
  - `002-do-not-adopt-x-algorithm-techniques.md`: 不引入推荐系统技术的决策
  - `003-keep-monolithic-architecture.md`: 保持单体架构的决策

---

## 文件位置

- **核心代码**: `/home/user/wgmm/monitor.py`
- **配置文件**: `/home/user/wgmm/.env`
- **WGMM 配置**: `/home/user/wgmm/wgmm_config.json`
- **已知 URL**: `/home/user/wgmm/local_known.txt`
- **发布历史**: `/home/user/wgmm/mtime.txt`
- **失误历史**: `/home/user/wgmm/miss_history.txt`
- **主日志**: `/home/user/wgmm/urls.log`
- **严重错误**: `/home/user/wgmm/critical_errors.log`
