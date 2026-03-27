# 代码逻辑流程全图

> **版本**: v2.2 (2345行代码, 61个方法)
> **更新时间**: 2026-02-06
> **适用版本**: monitor.py v2.x

本文档详细描述了WGMM视频监控系统的微观和宏观逻辑结构，包括所有61个方法的执行流程和调用关系。

---

## 目录

1. [程序入口与初始化流程](#1-程序入口与初始化流程)
2. [主监控循环](#2-主监控循环)
3. [三层检测架构](#3-三层检测架构)
4. [WGMM算法核心流程](#4-wgmm算法核心流程)
5. [数据流与文件操作](#5-数据流与文件操作)
6. [通知系统](#6-通知系统)
7. [错误处理机制](#7-错误处理机制)
8. [并发处理机制](#8-并发处理机制)
9. [工具方法与辅助功能](#9-工具方法与辅助功能)
10. [性能与优化](#10-性能与优化)
11. [代码位置快速索引](#11-代码位置快速索引)

---

## 1. 程序入口与初始化流程

```
═══════════════════════════════════════════════════════════════════════
                        程序入口点 (monitor.py:2295)
═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    main()
         │
         ▼
┌─────────────────────────────────────────────────────────────────────┐
│  main() 函数 (monitor.py:2236)                                      │
└─────────────────────────────────────────────────────────────────────┘
    │
    ├─ 1. 加载环境变量
    │   └─> load_env_file() (monitor.py:40)
    │       • 读取 .env 文件
    │       • 设置 GITHUB_TOKEN, GIST_ID, BILIBILI_UID, BARK_DEVICE_KEY
    │
    ├─ 2. 解析命令行参数
    │   └─> parse_arguments() (monitor.py:29)
    │       • --dev / -d: 开发模式标志
    │
    ├─ 3. 创建 VideoMonitor 实例
    │   └─> monitor = VideoMonitor(dev_mode=args.dev)
    │       │
    │       ▼
    │   ┌─────────────────────────────────────────────────────────┐
    │   │  VideoMonitor.__init__() (monitor.py:75)                │
    │   └─────────────────────────────────────────────────────────┘
    │       │
    │       ├─ 环境变量验证
    │       │   • 检查必需的 GITHUB_TOKEN, GIST_ID, BILIBILI_UID, BARK_DEVICE_KEY
    │       │   • 缺失则退出 (sys.exit(1))
    │       │
    │       ├─ 初始化数据结构
    │       │   • memory_urls: list[str] = [] (从 Gist 加载的 URL)
    │       │   • known_urls: set[str] = set() (本地已知 URL)
    │       │   • dev_mode: bool
    │       │
    │       ├─ 开发模式沙盒 (dev_mode=True 时)
    │       │   • sandbox_config: dict
    │       │   • sandbox_known_urls: set[str]
    │       │   • sandbox_miss_history: list[int]
    │       │   • sandbox_next_check_time: int = 0
    │       │   • dev_new_videos: int = 0
    │       │
    │       ├─ 定义文件路径
    │       │   • log_file: "urls.log"
    │       │   • critical_log_file: "critical_errors.log"
    │       │   • wgmm_config_file: "wgmm_config.json"
    │       │   • local_known_file: "local_known.txt"
    │       │   • mtime_file: "mtime.txt"
    │       │   • miss_history_file: "miss_history.txt"
    │       │   • cookies_file: "cookies.txt"
    │       │   • tmp_outputs_dir: "tmp_outputs"
    │       │
    │       ├─ 验证 cookies.txt 文件
    │       │   └─> _validate_cookies_file()
    │       │       • 检查文件存在性和格式
    │       │
    │       ├─ 加载 WGMM 算法配置
    │       │   └─> wgmm_config = _load_wgmm_config()
    │       │       • 读取 wgmm_config.json
    │       │       • 返回配置字典 (维度权重、sigmas、lambda 等)
    │       │
    │       ├─ 配置日志系统
    │       │   └─> setup_logging()
    │       │       • 开发模式: DEBUG 级别
    │       │       • 正常模式: INFO 级别
    │       │
    │       ├─ 加载本地已知 URL
    │       │   └─> load_known_urls()
    │       │       • 读取 local_known.txt
    │       │       • 初始化 known_urls 集合
    │       │
    │       └─ 注册信号处理器
    │           • SIGTERM: signal_handler
    │           • SIGINT: signal_handler
    │
    ├─ 4. 根据模式分支
    │
    │   【开发模式】(args.dev=True)
    │   ├─> 运行单次检查
    │   │   └─> monitor.run_monitor()
    │   │       • 完整的一次检测流程
    │   │       • 使用沙盒变量，不修改配置文件
    │   │
    │   ├─> 等待下次检查 (立即返回)
    │   │   └─> monitor.wait_for_next_check()
    │   │       • dev_mode 下只打印下次检查时间，不等待
    │   │
    │   └─> sys.exit(0)
    │
    │   【正常模式】(args.dev=False)
    │   ├─> 首次运行检查
    │   │   └─> 检查 wgmm_config.json 是否存在
    │   │       • 不存在: 标记首次运行，将自动初始化配置
    │   │       • 存在但缺少 is_manual_run: 设置为 True
    │   │
    │   └─> 进入主循环
    │       └─> while True:
    │           ├─ wait_for_next_check()  ← 等待到下次检查时间
    │           └─ run_monitor()          ← 执行一次完整检查
    │
    └─ 5. 异常处理
        • KeyboardInterrupt: 清理资源，优雅退出
        • OSError/JSONDecodeError/SubprocessError: 记录严重错误，发送通知
```

---

## 2. 主监控循环

```
═══════════════════════════════════════════════════════════════════════
                        主循环 (正常模式)
═══════════════════════════════════════════════════════════════════════

while True:  (monitor.py:2279)
    │
    ├─ 【步骤1】等待到下次检查时间
    │   └─> monitor.wait_for_next_check()  (monitor.py:1690)
    │       │
    │       ├─ 获取下次检查时间戳
    │       │   └─> next_check_timestamp = get_next_check_time()
    │       │       • 从 wgmm_config.json 读取 "next_check_time"
    │       │       • 首次运行返回 0
    │       │
    │       ├─ 计算等待时间
    │       │   • wait_seconds = next_check_timestamp - current_timestamp
    │       │
    │       ├─ 格式化下次检查时间显示
    │       │   • 日期: "2026年01月23日"
    │       │   • 星期: "周四"
    │       │   • 时间: "15:30:00"
    │       │
    │       ├─ 判断等待时间
    │       │   ├─ wait_seconds <= 0: 立即开始检查 (时间已过)
    │       │   ├─ dev_mode: 只打印时间，不等待
    │       │   └─ 正常模式: time.sleep(wait_seconds)
    │       │
    │       └─ 打印日志
    │           └─> "下次检查: 2026年01月23日 周四 15:30:00"
    │
    ├─ 【步骤2】执行完整监控流程
    │   └─> monitor.run_monitor()  (monitor.py:2084)
    │       │
    │       └─> [详见第3节：run_monitor() 详细流程]
    │
    ├─ 【步骤3】循环返回
    │   └─> 返回 while True 开头
    │
    └─ 【异常处理】
        ├─ KeyboardInterrupt (Ctrl+C)
        │   └─> 清理资源，优雅退出 (sys.exit(0))
        │
        └─ 未捕获的严重错误
            └─> 记录到 critical_errors.log
                └─> 发送 Bark 通知
                    └─> sys.exit(1)
```

---

## 3. 三层检测架构

```
═══════════════════════════════════════════════════════════════════════
                        三层检测架构详解
═══════════════════════════════════════════════════════════════════════

┌─────────────────────────────────────────────────────────────────────┐
│ 第一层: 分片预检查 (check_potential_new_parts)                      │
│ monitor.py:1548                                                     │
│                                                                     │
│ 目标: 快速检测是否有视频增加了新分片                                 │
│ 成本: 对已知多P视频预测下一分片是否存在                              │
└─────────────────────────────────────────────────────────────────────┘
    │
    ├─ 提取多P视频的最大分片号
    │   └─> 遍历 memory_urls，提取 "?p=" 后的分片号
    │       • 记录每个 base_url 的最大分片数
    │
    ├─ 预测下一分片是否存在
    │   └─> 对每个多P视频 (max_part > 1):
    │       • next_part = max_part + 1
    │       • next_url = f"{base_url}?p={next_part}"
    │       • run_yt_dlp(["--simulate", next_url])
    │       • 成功 → 发现新分片
    │
    ├─ 继续预测更多分片 (最多额外检查5个)
    │   └─> while check_part <= next_part + 5:
    │       • 检查 check_url 是否存在
    │       • 成功继续，失败停止
    │
    └─ 返回结果
        └─> return has_new_parts

┌─────────────────────────────────────────────────────────────────────┐
│ 第二层: 快速 ID 检查 (quick_precheck)                               │
│ monitor.py:1510                                                     │
│                                                                     │
│ 目标: 检测是否有新视频 (仅检查最新视频ID)                           │
│ 成本: 仅调用一次 yt-dlp 获取第一个视频ID                            │
└─────────────────────────────────────────────────────────────────────┘
    │
    ├─ 判断 memory_urls 是否为空
    │   └─> if not self.memory_urls:
    │       └─> return True  (触发完整检查)
    │
    ├─ 执行 yt-dlp 获取最新视频ID
    │   └─> run_yt_dlp([
    │           "--cookies", self.cookies_file,
    │           "--flat-playlist",
    │           "--print", "%(id)s",
    │           "--playlist-end", "1",  # 只获取第一个视频
    │           f"https://space.bilibili.com/{self.BILIBILI_UID}/video"
    │       ])
    │
    ├─ 解析最新视频ID
    │   └─> latest_id = stdout.strip()
    │
    ├─ 检查最新ID是否在已知URL中
    │   └─> video_exists = any(latest_id in url for url in self.memory_urls)
    │
    └─ 返回结果
        └─> return not video_exists  (ID不存在 → 有新视频)

┌─────────────────────────────────────────────────────────────────────┐
│ 第三层: 完整深度检查 (run_monitor)                                  │
│ monitor.py:2084                                                     │
│                                                                     │
│ 目标: 获取所有视频 URL，进行完整对比                                 │
│ 成本: 调用 yt-dlp 获取完整播放列表 + 并行获取分片                   │
│ 触发条件: 第一层或第二层检测到新内容                                 │
└─────────────────────────────────────────────────────────────────────┘
    │
    ├─ 执行 yt-dlp 获取所有视频 URL
    │   └─> run_yt_dlp([
    │           "--cookies", self.cookies_file,
    │           "--flat-playlist",
    │           "--print", "%(webpage_url)s",
    │           f"https://space.bilibili.com/{self.BILIBILI_UID}/video"
    │       ])
    │       • 无 --playlist-end 限制，获取所有视频
    │
    ├─ 并行获取所有视频的分片信息
    │   └─> get_all_videos_parallel(video_urls)
    │       • ThreadPoolExecutor(max_workers=5)
    │       • 每个视频调用 get_video_parts()
    │       • 返回所有分片 URL 的扁平列表
    │
    ├─ 双层 URL 对比
    │   ├─ gist_missing_urls = current_urls - memory_urls
    │   └─ truly_new_urls = gist_missing_urls - known_urls
    │
    ├─ 保存新视频时间戳
    │   └─> save_real_upload_timestamps(truly_new_urls)
    │       • 追加到 mtime.txt (WGMM 训练数据)
    │
    └─ 发送 Bark 通知
        └─> notify_new_videos(count, has_new_parts)
```

---

## 4. WGMM算法核心流程

```
═══════════════════════════════════════════════════════════════════════
                  adjust_check_frequency() - WGMM 核心算法
═══════════════════════════════════════════════════════════════════════

调用位置: run_monitor() 结束前
参数: found_new_content (bool) - 是否发现新内容

monitor.py:1232

┌─────────────────────────────────────────────────────────────────────┐
│ 【步骤1】加载历史数据和配置                                          │
└─────────────────────────────────────────────────────────────────────┘
    │
    ├─ 加载正向事件 (成功的发布时间)
    │   └─> positive_events = _load_history_file(mtime.txt)
    │       • 格式: 每行一个 Unix 时间戳
    │       • 示例: 1706160000\n1706246400\n...
    │
    ├─ 加载负向事件 (检测失败的空检查时间)
    │   └─> negative_events = _load_miss_history()
    │       • 格式: 每行一个 Unix 时间戳
    │
    ├─ 加载 WGMM 算法配置
    │   └─> config = wgmm_config.json
    │       {
    │         "dimension_weights": { "day": 0.5, "week": 1.0, ... },
    │         "sigmas": { "day": 0.8, "week": 1.0, ... },
    │         "last_lambda": 0.0001,
    │         "last_pos_variance": 0.0,
    │         "last_neg_variance": 0.0,
    │         ...
    │       }
    │
    └─ 首次运行处理
        └─> if not positive_events:
            • 调用 generate_mtime_file() 生成初始历史
            • 从完整扫描获取所有视频的上传时间

┌─────────────────────────────────────────────────────────────────────┐
│ 【步骤2】数据预处理                                                  │
└─────────────────────────────────────────────────────────────────────┘
    │
    ├─ 过滤异常值
    │   └─> filtered_events = _filter_outliers(events, current_time)
    │       • 使用 IQR (四分位距) 方法检测异常
    │       • Q1 = 25th percentile, Q3 = 75th percentile
    │       • IQR = Q3 - Q1
    │       • 移除 [Q1-3×IQR, Q3+3×IQR] 之外的数据
    │
    └─ 剪枝低权重历史数据
        └─> pruned_events = _prune_old_data(
                events,
                last_lambda,
                weight_threshold,
                current_timestamp
            )
            • 计算每个事件的时间衰减权重
            • weight = exp(-lambda × age_hours)
            • 移除权重 < threshold 的事件
            • 保持算法 O(n) 时间复杂度

┌─────────────────────────────────────────────────────────────────────┐
│ 【步骤3】自适应参数学习                                              │
└─────────────────────────────────────────────────────────────────────┘
    │
    ├─ 计算 Lambda (遗忘速度)
    │   └─> pos_lambda, pos_variance = _calculate_adaptive_lambda(
                positive_events,
                last_pos_variance,
                lambda_base
            )
    │       │
    │       ├─ 计算正向事件时间方差
    │       │   └─> intervals = np.diff(sorted(timestamps))
    │       │   └─> current_variance = np.var(intervals)
    │       │
    │       ├─ 计算变异系数 (CV)
    │       │   └─> cv = std(intervals) / mean(intervals)
    │       │
    │       ├─ Lambda 自适应公式
    │       │   └─> lambda_factor = log(1 + variance * 10) / log(11)
    │       │   └─> lambda_min = lambda_base * 0.3
    │       │   └─> lambda_max = lambda_base * (1 + cv * 4)
    │       │   └─> adaptive_lambda = lambda_min + (lambda_max - lambda_min) * lambda_factor
    │       │       • 方差大 → lambda 大 → 快速遗忘 (不稳定模式)
    │       │       • 方差小 → lambda 小 → 长期记忆 (稳定模式)
    │       │
    │       └─ 限制范围
    │           └─> final_lambda = clip(adaptive_lambda, lambda_min, lambda_max)
    │
    ├─ FFT 自动发现附加周期（数据不足时跳过）
    │   └─> discovered = _discover_periods(positive_events)
    │       • 最小样本: 50 条 / 最短跨度: 72 小时
    │       • 构建小时级二值信号 → FFT 频谱分析
    │       • 筛选 > 3× 平均能量的峰值
    │       • 过滤已有4维周期（±20%）及谐波
    │       • 返回最多3个新周期（秒）
    │
    ├─ 同步发现周期到配置
    │   └─> _sync_discovered_periods(discovered)
    │       • ±10% 容忍复用已有 custom_N 索引（保留学习权重）
    │       • 更新 wgmm_config["discovered_periods"]
    │
    ├─ 学习维度权重
    │   └─> dimension_weights = _learn_dimension_weights(
                positive_events,
                old_weights,
                learning_rate
            )
    │       │
    │       ├─ 提取原始时间维度
    │       │   └─> raw_components = _get_raw_time_components(timestamps)
    │       │       • day: 小时 (0-23)
    │       │       • week: 星期 (0-6)
    │       │       • month_week: 月周 (1-6)
    │       │       • year_month: 月份 (1-12)
    │       │
    │       ├─ 计算各维度得分
    │       │   └─> for dim in ["day", "week", "month_week", "year_month"]:
    │       │       • 统计每个值的出现次数
    │       │       • dimension_score = mean(counts) / std(counts)
    │       │       • 标准差越小 → 分布越集中 → 得分越高
    │       │
    │       ├─ 归一化权重
    │       │   └─> normalized_scores = scores / sum(scores) * 2.0
    │       │
    │       └─ 指数平滑更新
    │           └─> smoothed = old_weight * (1 - lr) + new_weight * lr
    │
    └─ 学习时间容忍度 (Sigmas)
        └─> learned_sigmas = _learn_adaptive_sigmas(positive_events, old_sigmas)
            │
            ├─ 提取原始时间维度
            │   └─> raw_components = _get_raw_time_components(timestamps)
            │
            ├─ 计算各维度的标准差
            │   └─> for dim in ["day", "week", "month_week", "year_month"]:
            │       • value_range = max(values) - min(values)
            │       • normalized = (values - min) / range
            │       • std = np.std(normalized)
            │       • adaptive_sigma = max(0.2, min(std * 3.0, 3.0))
            │
            └─ 指数平滑更新
                └─> new_sigma = old_sigma * 0.7 + adaptive_sigma * 0.3

┌─────────────────────────────────────────────────────────────────────┐
│ 【步骤4】计算当前时间发布概率                                        │
└─────────────────────────────────────────────────────────────────────┘
    │
    ├─ 编码当前时间
    │   └─> target_feat = _vectorized_time_features_numpy([current_timestamp])
    │       {
    │         "day_sin": sin(2π × hour / 24),
    │         "day_cos": cos(2π × hour / 24),
    │         "week_sin": sin(2π × weekday / 7),
    │         "week_cos": cos(2π × weekday / 7),
    │         "month_week_sin": sin(2π × week_of_month / 6),
    │         "month_week_cos": cos(2π × week_of_month / 6),
    │         "year_month_sin": sin(2π × month / 12),
    │         "year_month_cos": cos(2π × month / 12)
    │       }
    │
    ├─ 计算正向得分 (成功发布历史的相似性)
    │   └─> pos_score = _calculate_point_score(
    │           current_timestamp,
    │           positive_events,
    │           negative_events,
    │           dimension_weights,
    │           pos_lambda,
    │           neg_lambda,
    │           sigmas,
    │           resistance_coefficient
    │       )
    │       │
    │       ├─ 计算时间年龄并过滤未来事件
    │       │   └─> ages_hours = (current_timestamp - events) / 3600
    │       │   └─> valid_mask = ages_hours >= 0
    │       │
    │       ├─ 计算指数衰减权重
    │       │   └─> weights = exp(-lambda × ages_hours)
    │       │
    │       ├─ 计算四维时间距离 (sin/cos编码的欧氏距离)
    │       │   └─> for dim in ["day", "week", "month_week", "year_month"]:
    │       │       dist_sq = (sin_current - sin_event)² + (cos_current - cos_event)²
    │       │
    │       ├─ 计算高斯核相似性
    │       │   └─> for dim in ["day", "week", "month_week", "year_month"]:
    │       │       gaussian = exp(-dist_sq / (2 × sigma²))
    │       │
    │       ├─ 加权求和
    │       │   └─> combined =
    │       │       day_weight × day_gaussian +
    │       │       week_weight × week_gaussian +
    │       │       month_week_weight × month_week_gaussian +
    │       │       year_month_weight × year_month_gaussian
    │       │
    │       ├─ 时间衰减 × 相似度
    │       │   └─> scores = weights × combined
    │       │
    │       └─ 归一化到 [0, 1]
    │           └─> normalized = (mean - min) / (max - min)
    │
    ├─ 计算负向得分 (失败历史的惩罚)
    │   └─> neg_score = _calculate_point_score(
    │           current_timestamp,
    │           negative_events,
    │           ...  # 相同算法
    │       )
    │
    └─ 计算最终得分
        └─> current_score = pos_score - resistance_coefficient × neg_score
            • 正向得分促进检查
            • 负向得分抑制检查
            • resistance_coefficient = 0.7 + 0.2 / (1 + cv)
            • 结果范围: [0, 1]

┌─────────────────────────────────────────────────────────────────────┐
│ 【步骤5】非线性映射到检查间隔                                        │
└─────────────────────────────────────────────────────────────────────┘
    │
    ├─ 计算间隔统计量
    │   └─> mean_interval, variance, default_interval, max_interval =
            _calculate_interval_stats(positive_events)
    │       • mean_interval: 平均间隔
    │       • default_interval: 中位数 × 0.8
    │       • max_interval: 5th percentile × 0.5
    │
    ├─ 非线性映射
    │   └─> exponential_score = current_score ** mapping_curve  # mapping_curve = 2.0
    │   └─> base_interval_sec = mean_interval - (mean_interval - max_interval) × exponential_score
    │       • score = 1.0 → interval = max_interval (最小间隔)
    │       • score = 0.5 → interval = mean_interval
    │       • score = 0.0 → interval = mean_interval × 2 (最大间隔)
    │
    └─ 限制范围
        └─> base_frequency_sec = clip(base_interval_sec, max_interval, mean_interval × 2)

┌─────────────────────────────────────────────────────────────────────┐
│ 【步骤6】峰值预测 - 扫描未来15天                                    │
└─────────────────────────────────────────────────────────────────────┘
    │
    ├─ 生成扫描时间点
    │   └─> lookahead_seconds = 15 × 86400  # 15天
    │   └─> gaussian_width = (sigmas["day"] × 86400 / 24) × 2
    │   └─> min_step = gaussian_width × 0.25
    │   └─> scan_step = min_step if current_score > 0.5 else min_step × 2
    │   └─> scan_times = np.arange(
    │           scan_start,
    │           lookahead_end + scan_step,
    │           scan_step
    │       )
    │
    ├─ 批量计算得分
    │   └─> scan_scores = _batch_calculate_scores(
    │           scan_times,
    │           positive_events,
    │           negative_events,
    │           dimension_weights,
    │           pos_lambda,
    │           neg_lambda,
    │           sigmas,
    │           resistance_coefficient
    │       )
    │       • NumPy 向量化计算
    │       • 一次性计算数百个时间点
    │       • 避免显式循环，保持 O(n) 复杂度
    │
    ├─ 寻找峰值
    │   └─> if len(scan_scores) > 1:
    │       • 计算梯度: gradients = np.diff(scan_scores)
    │       • 检测峰值: peaks_mask = (gradients[:-1] > 0) & (gradients[1:] < 0)
    │       • 过滤低分峰值: score > 0.7
    │       • 过滤陡峭峰值: abs(gradient) < 0.05
    │       • 选择最佳峰值: argmax(peak_scores)
    │
    └─ 峰值提前量调整
        └─> if best_peak_score > 0.6:
            • peak_interval = best_peak_time - current_timestamp
            • if peak_interval < base_frequency_sec × 1.2:
                • advanced_time = best_peak_time - 5分钟
                • advanced_interval = advanced_time - current_timestamp
                • if advanced_interval > 300秒:
                    • final_frequency_sec = advanced_interval

┌─────────────────────────────────────────────────────────────────────┐
│ 【步骤7】yt-dlp 阻抗因子 (原始机制)                                  │
└─────────────────────────────────────────────────────────────────────┘
    │
    └─> impedance_factor = 1.0
    └─> if last_duration > normal_duration × 2:
        • impedance_ratio = last_duration / normal_duration
        • impedance_factor = 1.0 + min(0.5, (impedance_ratio - 2) × 0.1)
        • yt-dlp 运行时间异常延长
        • 可能是网络问题或 B站响应慢
        • 延长检查间隔，减少请求频率

┌─────────────────────────────────────────────────────────────────────┐
│ 【步骤8】保存配置并设置下次检查                                     │
└─────────────────────────────────────────────────────────────────────┘
    │
    ├─ 应用最终的检查间隔
    │   └─> final_frequency_sec = base_frequency_sec × impedance_factor
    │
    ├─ 记录负向事件
    │   └─> if not found_new_content and not is_manual_run:
    │       • _save_miss_history(current_timestamp, is_manual_run)
    │
    ├─ 计算下次检查时间
    │   └─> next_check_timestamp = current_timestamp + final_frequency_sec
    │
    ├─ 保存配置到文件
    │   └─> wgmm_config["next_check_time"] = next_check_timestamp
    │   └─> wgmm_config["dimension_weights"] = dimension_weights
    │   └─> wgmm_config["sigmas"] = sigmas
    │   └─> wgmm_config["last_lambda"] = pos_lambda
    │   └─> wgmm_config["last_pos_variance"] = pos_current_variance
    │   └─> wgmm_config["last_neg_variance"] = neg_current_variance
    │   └─> wgmm_config["last_update"] = current_timestamp
    │   └─> _save_wgmm_config()
    │
    └─ 打印日志
        └─> polling_interval_str = _format_frequency_interval(final_frequency_sec)
        └─> log_info(f"WGMM调频 - 轮询间隔: {polling_interval_str}")
```

---

## 5. 数据流与文件操作

```
═══════════════════════════════════════════════════════════════════════
                        完整数据流图
═══════════════════════════════════════════════════════════════════════

【持久化存储】

    .env (环境变量)
    │
    ├─ GITHUB_TOKEN
    ├─ GIST_ID
    ├─ BILIBILI_UID
    └─ BARK_DEVICE_KEY
         │
         ▼
    VideoMonitor.__init__()  ← 读取 (load_env_file)

═══════════════════════════════════════════════════════════════════════

    wgmm_config.json (算法状态)
    │
    ├─ dimension_weights (四维时间权重)
    │   ├─ day: 0.3 ~ 0.5
    │   ├─ week: 0.25 ~ 1.0
    │   ├─ month_week: 0.25 ~ 0.3
    │   └─ year_month: 0.2
    │
    ├─ sigmas (时间容忍度)
    │   ├─ day: 0.8 (动态学习)
    │   ├─ week: 1.0 (动态学习)
    │   ├─ month_week: 1.5 (动态学习)
    │   └─ year_month: 2.0 (动态学习)
    │
    ├─ last_lambda (自适应 lambda)
    ├─ last_pos_variance (正向事件方差)
    ├─ last_neg_variance (负向事件方差)
    │
    ├─ next_check_time (下次检查时间戳)
    ├─ last_update (最后更新时间戳)
    └─ is_manual_run (手动运行标志)
         │
         ▼
    _load_wgmm_config()  ← 读取 (monitor.py:208)
    _save_wgmm_config()  ← 保存 (monitor.py:251)

═══════════════════════════════════════════════════════════════════════

    mtime.txt (正向事件 - 成功发布历史)
    │
    ├─ 格式: 每行一个 Unix 时间戳
    ├─ 示例:
    │   1706160000
    │   1706246400
    │   1706332800
    │   ...
    │
    └─> 用途:
        • WGMM 算法的训练数据
        • 计算正向得分 (成功发布的历史模式)
         │
         ▼
    _load_history_file()  ← 读取 (monitor.py:827)
    save_real_upload_timestamps()  ← 追加 (monitor.py:598)
    generate_mtime_file()  ← 首次生成 (monitor.py:747)

═══════════════════════════════════════════════════════════════════════

    miss_history.txt (负向事件 - 检测失败历史)
    │
    ├─ 格式: 每行一个 Unix 时间戳
    ├─ 示例:
    │   1706170000
    │   1706256400
    │   ...
    │
    └─> 用途:
        • WGMM 算法的负向训练数据
        • 计算负向得分 (抑制失败时间点的预测)
         │
         ▼
    _load_miss_history()  ← 读取 (monitor.py:789)
    _save_miss_history()  ← 追加 (monitor.py:806)

═══════════════════════════════════════════════════════════════════════

    local_known.txt (本地已知 URL)
    │
    ├─ 格式: 每行一个 URL
    ├─ 示例:
    │   https://www.bilibili.com/video/BV1xx411c7mD
    │   https://www.bilibili.com/video/BV1yy411c7mE
    │   ...
    │
    └─> 用途:
        • 双层 URL 管理的本地层
        • 与 memory_urls (Gist) 一起防止重复通知
         │
         ▼
    load_known_urls()  ← 读取 (monitor.py:142)
    save_known_urls()  ← 保存 (monitor.py:157)

═══════════════════════════════════════════════════════════════════════

    GitHub Gist (云端备份)
    │
    ├─ GET https://api.github.com/gists/{GIST_ID}
    │   └─> 响应: Gist 文件内容 (memory_urls)
    │
    └─> 用途:
        • 双层 URL 管理的云端层
        • 跨实例/设备同步已知 URL
         │
         ▼
    sync_urls_from_gist()  ← 同步 (monitor.py:501)

═══════════════════════════════════════════════════════════════════════

    urls.log (主运行日志)
    │
    ├─ 格式: 时间戳 - 日志级别 - 消息
    ├─ 示例:
    │   2026-01-23 15:30:00 - INFO - 检查开始                  <--
    │   2026-01-23 15:30:05 - INFO - 预检查完成 - 预测检查: 无新内容 快速检查: 无新内容
    │   2026-01-23 15:30:10 - INFO - WGMM调频 - 轮询间隔: 2 小时 15 分钟 30 秒
    │   ...
    │
    └─> 用途:
        • 记录所有 INFO/WARNING/ERROR 级别日志
        • 自动限制 100000 行
         │
         ▼
    log_message()  ← 写入 (monitor.py:274)

═══════════════════════════════════════════════════════════════════════

    critical_errors.log (严重错误日志)
    │
    ├─ 格式: 时间戳 - CRITICAL - 消息 [上下文]
    ├─ 示例:
    │   2026-01-23 15:30:00 - CRITICAL - 无法获取视频列表 [上下文: 完整检查阶段]
    │   ...
    │
    └─> 用途:
        • 专门记录 CRITICAL 级别错误
        • 自动发送 Bark 通知
        • 自动限制 20000 行
         │
         ▼
    log_critical_error()  ← 写入 (monitor.py:307)
```

---

## 6. 通知系统

```
═══════════════════════════════════════════════════════════════════════
                        Bark 推送通知系统
═══════════════════════════════════════════════════════════════════════

┌─────────────────────────────────────────────────────────────────────┐
│ send_bark_push() - 通用 Bark 推送方法                               │
│ monitor.py:365                                                      │
└─────────────────────────────────────────────────────────────────────┘
    │
    ├─ 参数
    │   ├─ title: 通知标题
    │   ├─ body: 通知内容
    │   ├─ level: 通知级别 ("active", "timeSensitive", "critical")
    │   ├─ sound: 提示音
    │   ├─ group: 分组
    │   ├─ icon: 图标URL
    │   ├─ url: 点击跳转URL
    │   └─ call: 是否来电提醒
    │
    ├─ 构造请求 URL
    │   └─> base_url = f"{bark_base_url}/{bark_device_key}/{title}/{body}"
    │
    ├─ 添加参数
    │   └─> if level != "active": params.append(f"level={level}")
    │   └─> if sound: params.append(f"sound={sound}")
    │   └─> if call: params.append("call=1")
    │   └─> if volume and level == "critical": params.append(f"volume={volume}")
    │   └─> if group: params.append(f"group={group}")
    │   └─> if icon: params.append(f"icon={icon}")
    │   └─> if url: params.append(f"url={url}")
    │   └─> if is_archive: params.append("isArchive=1")
    │
    ├─ 发送 GET 请求
    │   └─> requests.get(full_url, timeout=30)
    │
    └─ 返回结果
        └─> return response.status_code == 200

┌─────────────────────────────────────────────────────────────────────┐
│ notify_new_videos() - 新视频通知                                    │
│ monitor.py:416                                                      │
└─────────────────────────────────────────────────────────────────────┘
    │
    ├─ 参数
    │   ├─ count: 新视频数量
    │   └─ has_new_parts: 是否包含新分片
    │
    ├─ 构造通知内容
    │   └─> body = f"发现 {count} 个新视频{'(含新分片)' if has_new_parts else ''}等待备份"
    │
    └─ 发送 Bark 推送
        └─> send_bark_push(
                title=self.bark_app_title,
                body=body,
                level="timeSensitive",
                sound="minuet",
                group="新视频"
            )

┌─────────────────────────────────────────────────────────────────────┐
│ notify_error() - 普通错误通知                                       │
│ monitor.py:428                                                      │
└─────────────────────────────────────────────────────────────────────┘
    │
    └─> send_bark_push(
            title=f"{self.bark_app_title} - 错误",
            body=message,
            level="active",
            group="错误"
        )

┌─────────────────────────────────────────────────────────────────────┐
│ notify_critical_error() - 严重错误通知                              │
│ monitor.py:437                                                      │
└─────────────────────────────────────────────────────────────────────┘
    │
    └─> send_bark_push(
            title=f"⚠️ {self.bark_app_title} - 严重错误",
            body=message + context,
            level="critical",
            sound="alarm",
            volume=8,
            call=True,
            group="严重错误"
        )

┌─────────────────────────────────────────────────────────────────────┐
│ notify_service_issue() - 服务异常通知                               │
│ monitor.py:451                                                      │
└─────────────────────────────────────────────────────────────────────┘
    │
    └─> send_bark_push(
            title=f"{self.bark_app_title} - 服务异常",
            body=message,
            level="timeSensitive",
            group="服务异常"
        )
```

---

## 7. 错误处理机制

```
═══════════════════════════════════════════════════════════════════════
                        分层错误处理策略
═══════════════════════════════════════════════════════════════════════

┌─────────────────────────────────────────────────────────────────────┐
│ 第一层: 普通错误 (WARNING 级别)                                     │
│                                                                     │
│ 特点: 记录日志，不中断程序，不发送通知                              │
└─────────────────────────────────────────────────────────────────────┘
    │
    ├─ 典型场景
    │   ├─ Bark 通知发送失败
    │   │   └─> log_warning("Bark 通知发送失败")
    │   │
    │   ├─ GitHub Gist 同步失败 (但有内存数据)
    │   │   └─> log_warning("Gist 同步失败")
    │   │
    │   ├─ 配置文件读写失败
    │   │   └─> log_warning("配置文件更新失败")
    │   │
    │   └─ 非关键网络请求失败
    │       └─> log_warning("网络请求失败")
    │
    └─ 处理方式
        ├─ 记录到 urls.log
        ├─ 使用默认值或跳过该操作
        └─ 继续执行后续流程

┌─────────────────────────────────────────────────────────────────────┐
│ 第二层: 严重错误 (CRITICAL 级别)                                    │
│                                                                     │
│ 特点: 记录到专用日志，自动发送 Bark 通知，不影响主循环              │
└─────────────────────────────────────────────────────────────────────┘
    │
    ├─ 典型场景
    │   ├─ 无法获取视频列表
    │   │   └─> log_critical_error("无法获取视频列表", "完整检查阶段")
    │   │
    │   ├─ mtime.txt 生成失败 (3次尝试)
    │   │   └─> log_critical_error("无法生成 mtime.txt", "generate_mtime_file")
    │   │
    │   ├─ cookies.txt 验证失败
    │   │   └─> log_critical_error("cookies.txt 无效", "_validate_cookies_file")
    │   │
    │   └─ yt-dlp 执行失败
    │       └─> log_critical_error("yt-dlp 执行异常", "run_yt_dlp")
    │
    └─ 处理方式
        ├─ 记录到 critical_errors.log (独立文件)
        ├─ 发送 Bark 通知 (实时告警)
        ├─ 记录到 urls.log (主日志)
        ├─ 调用 adjust_check_frequency(found_new_content=False)
        ├─ cleanup() 并 return (跳过本次检查)
        └─ 主循环继续，等待下次检查

┌─────────────────────────────────────────────────────────────────────┐
│ 第三层: 致命错误 (程序退出)                                          │
│                                                                     │
│ 特点: 无法恢复，清理资源后退出程序                                  │
└─────────────────────────────────────────────────────────────────────┘
    │
    ├─ 典型场景
    │   ├─ 缺少必需环境变量
    │   │   └─> print("缺少必要的环境变量", file=sys.stderr)
    │   │   └─> sys.exit(1)
    │   │
    │   ├─ 主循环未捕获的严重异常
    │   │   └─> log_critical_error(...)
    │   │   └─> sys.exit(1)
    │   │
    │   └─ 用户中断 (KeyboardInterrupt)
    │       └─> log_info("程序被用户中断")
    │       └─> cleanup()
    │       └─> sys.exit(0)
    │
    └─ 处理方式
        ├─ 记录最后错误信息
        ├─ cleanup() 清理临时文件
        ├─ sys.exit(0/1)
        └─ systemd 自动重启 (如果使用服务模式)

┌─────────────────────────────────────────────────────────────────────┐
│ 错误恢复机制                                                        │
└─────────────────────────────────────────────────────────────────────┘
    │
    ├─ 网络请求重试
    │   └─> run_yt_dlp() 内部重试 (yt-dlp 自带)
    │
    ├─ 配置文件备份
    │   └─> wgmm_config.json 修改前自动备份
    │
    ├─ 降级策略
    │   ├─ Gist 同步失败 → 使用本地 memory_urls
    │   ├─ 分片获取失败 → 使用原始 video_urls
    │   └─ 并发获取失败 → 降级为串行处理
    │
    └─ 资源清理
        └─> cleanup()
            • 删除 tmp_outputs/ 目录
            • 关闭文件句柄
            • 重置临时状态
```

---

## 8. 并发处理机制

```
═══════════════════════════════════════════════════════════════════════
                    并发获取视频信息
═══════════════════════════════════════════════════════════════════════

┌─────────────────────────────────────────────────────────────────────┐
│ get_all_videos_parallel() - 并发获取所有视频的分片信息              │
│ monitor.py:1641                                                     │
└─────────────────────────────────────────────────────────────────────┘
    │
    ├─ 参数
    │   └─> video_urls: list[str] - 视频 URL 列表
    │
    ├─ 创建临时目录
    │   └─> Path(self.tmp_outputs_dir).mkdir(exist_ok=True)
    │
    ├─ 创建线程池
    │   └─> with ThreadPoolExecutor(max_workers=5) as executor:
    │       • 最多 5 个并发线程
    │       • 自动管理线程生命周期
    │
    ├─ 提交任务
    │   └─> future_to_url = {
    │           executor.submit(self.get_video_parts, url): url
    │           for url in video_urls
    │       }
    │       • 为每个 URL 创建一个异步任务
    │       • 返回 {Future: URL} 映射
    │
    ├─ 收集结果
    │   └─> for future in as_completed(future_to_url):
    │           │
    │           ├─ 获取分片信息
    │           │   └─> parts = future.result()
    │           │       • 等待单个任务完成
    │           │       • 返回该视频的所有分片 URL
    │           │
    │           ├─ 扩展结果列表
    │           │   └─> all_parts.extend(parts)
    │           │
    │           └─ 异常处理
    │               └─> except Exception:
    │                   └─> log_warning(f"处理分片出错: {url}")
    │
    └─ 返回结果
        └─> return all_parts (所有分片的扁平列表)

┌─────────────────────────────────────────────────────────────────────┐
│ get_video_parts() - 获取单个视频的分片信息                          │
│ monitor.py:1614                                                     │
└─────────────────────────────────────────────────────────────────────┘
    │
    ├─ 参数
    │   └─> video_url: str - 视频 URL
    │
    ├─ 执行 yt-dlp 获取分片信息
    │   └─> run_yt_dlp([
    │           "--cookies", self.cookies_file,
    │           "--flat-playlist",
    │           "--print", "%(webpage_url)s",
    │           video_url
    │       ])
    │       • 返回视频的所有分片 URL (如果有)
    │
    ├─ 解析输出
    │   └─> if success and stdout:
    │       • return [line.strip() for line in stdout.split("\n")]
    │
    └─ 返回结果
        └─> return parts (分片 URL 列表)

┌─────────────────────────────────────────────────────────────────────┐
│ 性能优化要点                                                        │
└─────────────────────────────────────────────────────────────────────┘
    │
    ├─ 并发控制
    │   • max_workers=5: 平衡并发度和资源占用
    │   • 避免过多并发导致 B站限流
    │
    ├─ 超时处理
    │   • yt-dlp: 默认 300 秒
    │   • requests: 30 秒
    │
    ├─ 资源管理
    │   • with 语句自动管理线程池
    │   • as_completed() 按完成顺序处理结果
    │
    └─ 错误隔离
        • 单个视频失败不影响其他视频
        • 异常被捕获并记录，不会传播
```

---

## 9. 工具方法与辅助功能

```
═══════════════════════════════════════════════════════════════════════
                        常用工具方法
═══════════════════════════════════════════════════════════════════════

┌─────────────────────────────────────────────────────────────────────┐
│ run_yt_dlp() - 执行 yt-dlp 命令                                     │
│ monitor.py:1469                                                     │
└─────────────────────────────────────────────────────────────────────┘
    │
    ├─ 参数
    │   ├─ command_args: list[str] - yt-dlp 命令行参数
    │   └─ timeout: int - 超时时间 (默认300秒)
    │
    ├─ 查找 yt-dlp 可执行文件
    │   ├─ 首次调用: shutil.which("yt-dlp")
    │   ├─ 缓存路径: self.yt_dlp_path
    │   └─> 重复使用: 直接使用缓存路径
    │
    ├─ 构造完整命令
    │   └─> cmd = [yt_dlp_path, *command_args]
    │
    ├─ 执行命令
    │   └─> subprocess.run(
    │           cmd,
    │           capture_output=True,
    │           text=True,
    │           timeout=timeout,
    │           encoding="utf-8",
    │           check=False
    │       )
    │
    ├─ 记录执行时间
    │   └─> self.last_ytdlp_duration = elapsed_time
    │   └─> if returncode == 0:
    │       • self.normal_ytdlp_duration = 0.9 × normal + 0.1 × elapsed
    │
    └─ 返回结果
        └─> return (success, stdout, stderr)

┌─────────────────────────────────────────────────────────────────────┐
│ save_real_upload_timestamps() - 保存真实上传时间                    │
│ monitor.py:598                                                      │
└─────────────────────────────────────────────────────────────────────┘
    │
    ├─ 参数
    │   └─> urls: set[str] - 新视频 URL 集合
    │
    ├─ 确保 mtime.txt 存在
    │   └─> if not mtime_file_path.exists():
    │       • generate_mtime_file("save_real_upload_timestamps")
    │
    ├─ 遍历每个 URL
    │   └─> for url in urls:
    │       │
    │       ├─ 获取上传时间
    │       │   └─> upload_timestamp = get_video_upload_time(url)
    │       │       • 调用 yt-dlp 的 --print "%(timestamp)s|%(upload_date)s"
    │       │       • 返回 Unix 时间戳
    │       │
    │       ├─ 降级处理
    │       │   └─> if not upload_timestamp:
    │       │       • timestamps.append(current_time)
    │       │
    │       └─ 成功获取
    │           └─> timestamps.append(upload_timestamp)
    │
    ├─ 排序并写入文件
    │   └─> sorted_timestamps = sorted(timestamps)
    │   └─> with mtime_file_path.open("a") as f:
    │       • f.writelines(f"{ts}\n" for ts in sorted_timestamps)
    │
    └─ 限制文件大小
        └─> limit_file_lines(self.mtime_file, 100000)

┌─────────────────────────────────────────────────────────────────────┐
│ generate_mtime_file() - 生成 mtime.txt                              │
│ monitor.py:747                                                      │
└─────────────────────────────────────────────────────────────────────┘
    │
    ├─ 检查文件是否存在
    │   └─> if mtime_file_path.exists() and size > 0:
    │       • return True
    │
    ├─ 最多尝试 3 次
    │   └─> for attempt in range(1, 4):
    │       │
    │       ├─ 记录尝试次数
    │       │   └─> log_info(f"mtime.txt 第 {attempt} 次尝试生成")
    │       │
    │       ├─ 调用创建方法
    │       │   └─> if create_mtime_from_info_json():
    │       │       • return True
    │       │
    │       └─ 继续下一次尝试
    │
    └─ 3次都失败
        └─> log_critical_error("经过 3 次尝试仍无法生成 mtime.txt")
        └─> return False

┌─────────────────────────────────────────────────────────────────────┐
│ create_mtime_from_info_json() - 通过 info.json 创建                │
│ monitor.py:642                                                      │
└─────────────────────────────────────────────────────────────────────┘
    │
    ├─ 创建临时目录
    │   └─> temp_info_dir = Path("temp_info_json")
    │   └─> temp_info_dir.mkdir(exist_ok=True)
    │
    ├─ 获取所有视频的 info.json
    │   └─> run_yt_dlp([
    │           "--write-info-json",
    │           "--skip-download",
    │           "--output", f"{temp_info_dir}/%(id)s.%(ext)s",
    │           ...
    │       ])
    │
    ├─ 提取时间戳
    │   └─> for info_file in temp_info_dir.glob("*.info.json"):
    │       • 读取 JSON 数据
    │       • 提取 timestamp 或 upload_date
    │       • 写入临时文件
    │
    ├─ 排序时间戳
    │   ├─ 优先使用系统 sort 命令
    │   │   └─> subprocess.run(["sort", "-n", temp_file])
    │   │
    │   └─ 降级使用内存排序
    │       └─> timestamps.sort()
    │
    ├─ 写入 mtime.txt
    │   └─> mtime_file_path.write_text(sorted_content)
    │
    └─ 清理临时文件
        └─> shutil.rmtree(temp_info_dir)

┌─────────────────────────────────────────────────────────────────────┐
│ get_video_upload_time() - 获取视频上传时间                          │
│ monitor.py:558                                                      │
└─────────────────────────────────────────────────────────────────────┘
    │
    ├─ 参数
    │   └─> video_url: str - 视频 URL
    │
    ├─ 执行 yt-dlp
    │   └─> run_yt_dlp([
    │           "--print", "%(timestamp)s|%(upload_date)s",
    │           "--no-download",
    │           video_url
    │       ])
    │
    ├─ 解析输出
    │   ├─ 优先使用 timestamp
    │   │   └─> if parts[0] and parts[0] != "NA":
    │   │       • return int(parts[0])
    │   │
    │   └─ 降级使用 upload_date
    │       └─> if parts[1] and parts[1] != "NA":
    │           • parsed_dt = datetime.strptime(parts[1], "%Y%m%d")
    │           • return int(parsed_dt.timestamp())
    │
    └─ 失败返回 None

┌─────────────────────────────────────────────────────────────────────┐
│ cleanup() - 清理临时资源                                            │
│ monitor.py:1668                                                     │
└─────────────────────────────────────────────────────────────────────┘
    │
    ├─ 删除临时输出目录
    │   └─> tmp_outputs_path = Path(self.tmp_outputs_dir)
    │   └─> if tmp_outputs_path.exists():
    │       • shutil.rmtree(tmp_outputs_path)
    │
    └─ 开发模式额外清理
        └─> if self.dev_mode:
            • 删除 temp_info_json 目录

┌─────────────────────────────────────────────────────────────────────┐
│ signal_handler() - 信号处理器                                       │
│ monitor.py:264                                                      │
└─────────────────────────────────────────────────────────────────────┘
    │
    ├─ 注册信号
    │   ├─ SIGTERM: 终止信号 (kill 命令)
    │   └─ SIGINT: 中断信号 (Ctrl+C)
    │
    ├─ 信号处理流程
    │   ├─ 接收信号
    │   ├─ log_message(f"收到信号 {signum}, 正在清理并退出...")
    │   ├─ save_known_urls() 保存状态
    │   ├─ cleanup() 清理资源
    │   └─ sys.exit(0) 优雅退出
    │
    └─ 确保数据完整性
        • 配置文件保存
        • 临时文件删除
        • 日志刷新到磁盘

┌─────────────────────────────────────────────────────────────────────┐
│ get_next_check_time() - 获取下次检查时间                            │
│ monitor.py:460                                                      │
└─────────────────────────────────────────────────────────────────────┘
    │
    ├─ 开发模式
    │   └─> return self.sandbox_next_check_time
    │
    ├─ 正常模式
    │   └─> config_file = Path(self.wgmm_config_file)
    │   └─> if config_file.exists():
    │       • config = json.loads(config_file.read_text())
    │       • return config.get("next_check_time", 0)
    │   └─> else:
    │       • return 0
    │
    └─ 异常处理
        └─> except Exception:
            • log_warning("读取next_check_time失败")
            • return 0

┌─────────────────────────────────────────────────────────────────────┐
│ save_next_check_time() - 保存下次检查时间                           │
│ monitor.py:477                                                      │
└─────────────────────────────────────────────────────────────────────┘
    │
    ├─ 开发模式
    │   └─> self.sandbox_next_check_time = next_check_timestamp
    │
    ├─ 正常模式
    │   └─> config_file = Path(self.wgmm_config_file)
    │   └─> if config_file.exists():
    │       • config = json.loads(config_file.read_text())
    │   └─> config["next_check_time"] = next_check_timestamp
    │   └─> config_file.write_text(json.dumps(config, ...))
    │
    └─ 异常处理
        └─> log_critical_error("保存next_check_time失败")

┌─────────────────────────────────────────────────────────────────────┐
│ _format_frequency_interval() - 格式化时间间隔                       │
│ monitor.py:1106                                                     │
└─────────────────────────────────────────────────────────────────────┘
    │
    ├─ 参数
    │   └─> seconds: float - 间隔秒数
    │
    ├─ 分解时间单位
    │   ├─ polling_days = int(total_seconds // 86400)
    │   ├─ polling_hours = int((total_seconds % 86400) // 3600)
    │   ├─ polling_minutes = int((total_seconds % 3600) // 60)
    │   └─ polling_seconds = int(total_seconds % 60)
    │
    ├─ 构造格式化字符串
    │   └─> parts = []
    │   └─> if polling_days > 0: parts.append(f"{polling_days} 天")
    │   └─> if polling_hours > 0: parts.append(f"{polling_hours} 小时")
    │   └─> if polling_minutes > 0: parts.append(f"{polling_minutes} 分钟")
    │   └─> if polling_seconds > 0 or not parts:
    │       • parts.append(f"{polling_seconds} 秒")
    │
    └─ 返回结果
        └─> return " ".join(parts)
```

---

## 10. 性能与优化

```
═══════════════════════════════════════════════════════════════════════
                        性能优化策略
═══════════════════════════════════════════════════════════════════════

┌─────────────────────────────────────────────────────────────────────┐
│ WGMM 算法性能优化                                                   │
└─────────────────────────────────────────────────────────────────────┘
    │
    ├─ 向量化计算 (monitor.py:1740)
    │   ├─ 使用 NumPy 数组操作
    │   │   • 避免显式 Python 循环
    │   │   • 利用 C 层级的性能
    │   │
    │   └─ _batch_calculate_scores() 批处理 (monitor.py:1969)
    │       • 一次性计算数百个时间点
    │       • 时间复杂度: O(n) = O(历史事件数)
    │       • 典型执行时间: ~10ms
    │
    ├─ 内存管理 (monitor.py:903)
    │   ├─ _prune_old_data() 自动剪枝
    │   │   • 移除权重 < threshold 的历史事件
    │   │   • threshold = max(0.0001, 0.001 × (100 / (total_events + 50)))
    │   │   • 保持算法 O(n) 复杂度
    │   │
    │   └─ 使用生成器而非列表
    │       • _filter_outliers() 返回 NumPy 数组
    │       • 减少内存占用
    │
    └─ 缓存优化
        ├─ yt-dlp 路径缓存
        │   • 首次调用后缓存路径
        │   • 避免重复 shutil.which()
        │
        └─ 配置文件缓存
            • wgmm_config 在内存中维护
            • 仅在修改时写入磁盘

┌─────────────────────────────────────────────────────────────────────┐
│ 网络请求优化                                                        │
└─────────────────────────────────────────────────────────────────────┘
    │
    ├─ 并发控制
    │   • ThreadPoolExecutor(max_workers=5)
    │   • 平衡并发度和 B站限流风险
    │
    ├─ 超时设置
    │   • yt-dlp: 300 秒
    │   • requests: 30 秒
    │   • 避免长时间阻塞
    │
    ├─ 三层检测架构
    │   ├─ 第一层: 仅检查已知多P视频的下一分片
    │   ├─ 第二层: 仅获取第一个视频ID
    │   └─ 第三层: 完整扫描 (仅在前两层触发时执行)
    │
    └─ 请求节省率
        • WGMM 自适应调频: 节省 60-80% 请求
        • 相比固定 1 小时间隔

┌─────────────────────────────────────────────────────────────────────┐
│ I/O 优化                                                            │
└─────────────────────────────────────────────────────────────────────┘
    │
    ├─ 日志文件大小限制
    │   ├─ urls.log: 100000 行
    │   ├─ critical_errors.log: 20000 行
    │   └─ mtime.txt: 100000 行
    │
    ├─ 批量写入
    │   • save_known_urls(): 一次性写入所有 URL
    │   • 减少 I/O 次数
    │
    └─ 临时文件管理
        • tmp_outputs/ 统一管理临时输出
        • cleanup() 自动清理

┌─────────────────────────────────────────────────────────────────────┐
│ 典型性能指标                                                        │
└─────────────────────────────────────────────────────────────────────┘
    │
    ├─ WGMM 算法计算
    │   • 时间: ~10ms (100 个历史事件)
    │   • 内存: <1MB
    │
    ├─ 三层检测
    │   • 第一层: ~1秒 (数个多P视频)
    │   • 第二层: ~1秒 (仅第一个视频ID)
    │   • 第三层: ~10秒 (100 个视频，含分片)
    │
    ├─ 系统资源占用
    │   • CPU: <1% (大部分时间在睡眠)
    │   • 内存: <10MB (常驻内存)
    │   • 网络: 取决于视频数量
    │
    └─ 并发性能
        • 5 个并发线程
        • 单个视频获取: ~1秒
        • 100 个视频总耗时: ~20秒
```

---

## 11. 代码位置快速索引

```
═══════════════════════════════════════════════════════════════════════
                      关键代码位置索引
═══════════════════════════════════════════════════════════════════════

【程序入口与初始化】
monitor.py:29       - parse_arguments() - 命令行参数解析
monitor.py:40       - load_env_file() - 环境变量加载
monitor.py:61       - VideoMonitor 类定义
monitor.py:75       - __init__() - 初始化监控系统
monitor.py:133      - setup_logging() - 配置日志系统
monitor.py:174      - _validate_cookies_file() - 验证cookies文件
monitor.py:2236     - main() - 程序入口点
monitor.py:2295     - if __name__ == "__main__" - 启动

【主监控循环】
monitor.py:2084     - run_monitor() - 主监控流程
monitor.py:1690     - wait_for_next_check() - 等待下次检查

【三层检测架构】
monitor.py:1548     - check_potential_new_parts() - 第一层: 分片预检查
monitor.py:1510     - quick_precheck() - 第二层: 快速 ID 检查
monitor.py:2084     - 第三层: 完整深度扫描 (run_monitor 内)

【WGMM 核心算法】
monitor.py:1326     - adjust_check_frequency() - WGMM 主函数
monitor.py:1225     - _scan_future_peak() - 扫描未来峰值
monitor.py:1898     - _calculate_point_score() - 计算单个时间点得分
monitor.py:2018     - _batch_calculate_scores() - 批量计算得分
monitor.py:1790     - _vectorized_time_features_numpy() - 时间特征编码
monitor.py:1232     - _calculate_adaptive_lambda() - Lambda 自适应
monitor.py:1204     - _discover_periods() - FFT 发现非日历周期
monitor.py:1315     - _sync_discovered_periods() - 同步发现周期到配置
monitor.py:1081     - _learn_dimension_weights() - 维度权重学习（含 custom_N）
monitor.py:1150     - _learn_adaptive_sigmas() - Sigma 学习（含 custom_N）
monitor.py:937      - _filter_outliers() - 过滤异常值
monitor.py:982      - _prune_old_data() - 剪枝旧数据

【数据管理】
monitor.py:501      - sync_urls_from_gist() - 同步 Gist URL
monitor.py:142      - load_known_urls() - 加载本地已知 URL
monitor.py:157      - save_known_urls() - 保存本地已知 URL
monitor.py:598      - save_real_upload_timestamps() - 保存上传时间
monitor.py:208      - _load_wgmm_config() - 加载 WGMM 配置
monitor.py:251      - _save_wgmm_config() - 保存 WGMM 配置
monitor.py:827      - _load_history_file() - 加载历史文件
monitor.py:789      - _load_miss_history() - 加载失败历史
monitor.py:806      - _save_miss_history() - 保存失败历史

【通知系统】
monitor.py:365      - send_bark_push() - Bark 推送通知
monitor.py:416      - notify_new_videos() - 新视频通知
monitor.py:428      - notify_error() - 普通错误通知
monitor.py:437      - notify_critical_error() - 严重错误通知
monitor.py:451      - notify_service_issue() - 服务异常通知

【工具方法】
monitor.py:1469     - run_yt_dlp() - 执行 yt-dlp 命令
monitor.py:1614     - get_video_parts() - 获取视频分片
monitor.py:1641     - get_all_videos_parallel() - 并发获取视频信息
monitor.py:1668     - cleanup() - 清理临时资源
monitor.py:264      - signal_handler() - 信号处理器
monitor.py:460      - get_next_check_time() - 获取下次检查时间
monitor.py:477      - save_next_check_time() - 保存下次检查时间
monitor.py:558      - get_video_upload_time() - 获取视频上传时间
monitor.py:747      - generate_mtime_file() - 生成 mtime.txt
monitor.py:642      - create_mtime_from_info_json() - 通过 info.json 创建
monitor.py:1106     - _format_frequency_interval() - 格式化时间间隔

【日志与错误处理】
monitor.py:274      - log_message() - 统一日志记录
monitor.py:288      - log_info() - INFO 级别日志
monitor.py:292      - log_warning() - WARNING 级别日志
monitor.py:296      - log_error() - ERROR 级别日志
monitor.py:307      - log_critical_error() - CRITICAL 级别日志
monitor.py:337      - _limit_critical_log_lines() - 限制严重错误日志行数
monitor.py:342      - limit_file_lines() - 限制日志文件行数

【配置管理】
monitor.py:1194     - _initialize_wgmm_config() - 初始化 WGMM 配置
monitor.py:956      - _calculate_interval_stats() - 计算间隔统计量

【辅助方法】
monitor.py:1838     - _get_local_timezone_offset() - 获取本地时区偏移
monitor.py:1779     - _get_jst_datetime_str() - 获取JST格式化时间字符串
monitor.py:1947     - _get_raw_time_components() - 提取原始时间维度

【类常量定义】
monitor.py:71       - DEFAULT_CHECK_INTERVAL - 默认检查间隔
monitor.py:72       - FALLBACK_INTERVAL - 降级检查间隔
monitor.py:73       - MAX_RETRY_ATTEMPTS - 最大重试次数

【统计信息】
• 总行数: 2345 行
• 类数量: 1 个 (VideoMonitor)
• 方法数量: 61 个 (包含嵌套函数)
• 函数数量: 3 个 (parse_arguments, load_env_file, main)
```

---

## 版本历史

- **v2.2** (2026-02-06): 更新方法数量统计(61个), 添加新增方法索引(_scan_future_peak, _get_jst_datetime_str等), 更新代码行号
- **v2.1** (2026-01-24): 修正方法数量统计(58个), 添加遗漏的方法索引(_limit_critical_log_lines等)
- **v2.0** (2026-01-24): 基于2296行代码重构，新增11个核心类方法，完整更新文档
- **v1.0** (2026-01-23): 初始版本，基于2439行代码（包含Phase 1实验性功能）

---

**文档维护**: 请在代码重大变更后及时更新本文档
**问题反馈**: 请通过 GitHub Issues 报告文档问题
