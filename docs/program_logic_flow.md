# 程序执行逻辑链条全图

## 1. 程序启动与初始化流程

```
═══════════════════════════════════════════════════════════════════════
                        程序入口点 (monitor.py:2438)
═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    main()
         │
         ▼
┌─────────────────────────────────────────────────────────────────────┐
│  main() 函数 (monitor.py:2379)                                      │
└─────────────────────────────────────────────────────────────────────┘
    │
    ├─ 1. 加载环境变量
    │   └─> load_env_file() (monitor.py:37)
    │       • 读取 .env 文件
    │       • 设置 GITHUB_TOKEN, GIST_ID, BILIBILI_UID, BARK_DEVICE_KEY
    │
    ├─ 2. 解析命令行参数
    │   └─> parse_arguments() (monitor.py:26)
    │       • --dev / -d: 开发模式标志
    │
    ├─ 3. 创建 VideoMonitor 实例
    │   └─> monitor = VideoMonitor(dev_mode=args.dev)
    │       │
    │       ▼
    │   ┌─────────────────────────────────────────────────────────┐
    │   │  VideoMonitor.__init__() (monitor.py:74)                │
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

## 2. 主监控循环

```
═══════════════════════════════════════════════════════════════════════
                        主循环 (正常模式)
═══════════════════════════════════════════════════════════════════════

while True:  (monitor.py:2422)
    │
    ├─ 【步骤1】等待到下次检查时间
    │   └─> monitor.wait_for_next_check()  (monitor.py:1658)
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
    │   └─> monitor.run_monitor()  (monitor.py:2052)
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

## 3. run_monitor() 详细流程

```
═══════════════════════════════════════════════════════════════════════
                    run_monitor() - 完整深度检查 (monitor.py:2052)
═══════════════════════════════════════════════════════════════════════

try:
    │
    ├─ 【阶段1】同步已知 URL (monitor.py:2073)
    │   └─> sync_success = sync_urls_from_gist()
    │       │
    │       ├─ GET https://api.github.com/gists/{GIST_ID}
    │       │
    │       ├─ 解析响应，提取 memory_urls
    │       │   • 从 Gist 的文件内容读取已备份的 URL 列表
    │       │
    │       ├─ 处理失败情况
    │       │   └─> if not sync_success and not self.memory_urls:
    │       │           • 无法获取基准数据
    │       │           • 跳过本次检查
    │       │           • cleanup() 并 return
    │       │
    │       └─ 返回同步成功标志
    │
    ├─ 【阶段2】第一层检测 - 分片预检查 (monitor.py:2083)
    │   └─> found_new_parts = check_potential_new_parts()
    │       │
    │       └─> [详见第4节：三层检测架构]
    │
    ├─ 【阶段3】第二层检测 - 快速 ID 检查 (monitor.py:2085)
    │   └─> found_new_videos = quick_precheck()
    │       │
    │       └─> [详见第4节：三层检测架构]
    │
    ├─ 【阶段4】预检查结果判断 (monitor.py:2094)
    │   │
    │   ├─ if not (found_new_parts or found_new_videos):
    │   │   └─> 两层预检查都未发现新内容
    │   │       • adjust_check_frequency(found_new_content=False)
    │   │       • cleanup()
    │   │       • return (跳过完整扫描)
    │   │
    │   └─> 任一预检查发现新内容，继续完整扫描
    │
    ├─ 【阶段5】第三层检测 - 完整深度扫描 (monitor.py:2100)
    │   │
    │   ├─ 执行 yt-dlp 获取所有视频 URL
    │   │   └─> run_yt_dlp([
    │   │           "--cookies", self.cookies_file,
    │   │           "--flat-playlist",
    │   │           "--print", "%(webpage_url)s",
    │   │           f"https://space.bilibili.com/{self.BILIBILI_UID}/video"
    │   │       ])
    │   │
    │   ├─ 处理失败情况
    │   │   ├─ if not success or not stdout:
    │   │   │   • 记录严重错误
    │   │   │   • adjust_check_frequency(found_new_content=False)
    │   │   │   • cleanup() 并 return
    │   │   │
    │   │   └─ if not video_urls (解析为空列表):
    │   │       • 记录严重错误
    │   │       • adjust_check_frequency(found_new_content=False)
    │   │       • cleanup() 并 return
    │   │
    │   ├─ 并行获取所有视频的分片信息
    │   │   └─> all_parts = get_all_videos_parallel(video_urls)
    │   │       • 使用 ThreadPoolExecutor 并发请求
    │   │       • 每个视频调用 get_video_parts()
    │   │       • 返回所有分片 URL 的扁平列表
    │   │
    │   └─ 处理分片获取失败
    │       └─> if not all_parts:
    │           • 使用原始 video_urls 作为后备
    │
    ├─ 【阶段6】双层 URL 对比 (monitor.py:2141)
    │   │
    │   ├─ existing_urls_set = set(memory_urls)
    │   │   • Gist 中已存在的 URL 集合
    │   │
    │   ├─ current_urls_set = set(all_parts)
    │   │   • 当前检测到的所有 URL 集合
    │   │
    │   ├─ gist_missing_urls = current_urls_set - existing_urls_set
    │   │   • Gist 中缺失的 URL (可能已更新，也可能未同步)
    │   │
    │   ├─ truly_new_urls = gist_missing_urls - known_urls
    │   │   • 真正的新 URL (既不在 Gist，也不在本地已知列表)
    │   │   • 只有这些 URL 才会触发通知
    │   │
    │   └─ 判断是否有新内容
    │       └─> if gist_missing_urls:
    │           ├─ 计算新 URL 数量
    │           │   • old_count = len(gist_missing_urls) - len(truly_new_urls)
    │           │   • new_count = len(truly_new_urls)
    │   │
    │           ├─ 保存真正新视频的上传时间戳
    │           │   └─> if truly_new_urls:
    │           │       └─> save_real_upload_timestamps(truly_new_urls)
    │           │           • 调用 yt-dlp 获取每个新视频的上传时间
    │           │           • 追加到 mtime.txt (WGMM 算法的训练数据)
    │           │
    │           ├─ 更新本地已知 URL 列表
    │           │   └─> known_urls.update(gist_missing_urls)
    │           │   └─> save_known_urls()
    │           │       • 保存到 local_known.txt
    │           │
    │           ├─ 开发模式处理
    │           │   └─> if self.dev_mode:
    │           │       └─> dev_new_videos += len(gist_missing_urls)
    │           │
    │           ├─ 发送 Bark 通知
    │           │   └─> notify_new_videos(
    │           │           len(gist_missing_urls),
    │           │           has_new_parts=found_new_parts
    │           │       )
    │           │       • 调用 Bark API 推送通知
    │           │       • 更新 memory_urls 并同步到 Gist
    │           │
    │           └─ 根据是否发现真正的新内容调整检查频率
    │               ├─ if truly_new_urls:
    │               │   └─> adjust_check_frequency(found_new_content=True)
    │               │
    │               └─ else:
    │                   └─> adjust_check_frequency(found_new_content=False)
    │
    ├─ 【阶段7】处理仅发现新分片的情况 (monitor.py:2182)
    │   └─> elif found_new_parts:
    │       • log_info("完整检查未发现新视频 - 但发现新分片, 已处理")
    │       • adjust_check_frequency(found_new_content=True)
    │
    ├─ 【阶段8】处理未发现新内容的情况 (monitor.py:2185)
    │   └─> else:
    │       • log_info("完整检查未发现新内容")
    │       • adjust_check_frequency(found_new_content=False)
    │
    └─ 【阶段9】清理资源 (monitor.py:2189)
        └─> cleanup()
            • 删除临时输出目录 (tmp_outputs/)
```

## 4. 三层检测架构

```
═══════════════════════════════════════════════════════════════════════
                        三层检测架构详解
═══════════════════════════════════════════════════════════════════════

┌─────────────────────────────────────────────────────────────────────┐
│ 第一层: 分片预检查 (check_potential_new_parts)                      │
│ monitor.py:1515                                                     │
│                                                                     │
│ 目标: 快速检测是否有视频增加了新分片                                 │
│ 成本: 仅调用一次 yt-dlp 获取视频列表                                 │
└─────────────────────────────────────────────────────────────────────┘
    │
    ├─ 执行 yt-dlp 获取最新视频列表
    │   └─> run_yt_dlp([
    │           "--cookies", self.cookies_file,
    │           "--flat-playlist",
    │           "--print", "%(webpage_url)s",
    │           "--playlist-end", "10",  # 只检查最新10个视频
    │           f"https://space.bilibili.com/{self.BILIBILI_UID}/video"
    │       ])
    │
    ├─ 解析输出获取最新视频 URL 列表
    │   └─> recent_videos = [line.strip() for line in stdout.split("\n")]
    │
    ├─ 并行获取每个视频的分片信息
    │   └─> get_all_videos_parallel(recent_videos)
    │       • 对每个视频调用 get_video_parts(url)
    │       • get_video_parts() 获取视频的分片数 (p 属性)
    │       • 返回所有分片 URL 的扁平列表
    │
    ├─ 对比本地已知分片
    │   └─> new_parts = [url for url in all_parts if url not in known_urls]
    │
    └─ 返回结果
        └─> return len(new_parts) > 0

┌─────────────────────────────────────────────────────────────────────┐
│ 第二层: 快速 ID 检查 (quick_precheck)                               │
│ monitor.py:1477                                                     │
│                                                                     │
│ 目标: 检测是否有新视频 (仅检查 URL 数量)                             │
│ 成本: 仅调用一次 yt-dlp 获取视频数量                                 │
└─────────────────────────────────────────────────────────────────────┘
    │
    ├─ 执行 yt-dlp 获取视频数量
    │   └─> run_yt_dlp([
    │           "--cookies", self.cookies_file,
    │           "--flat-playlist",
    │           "--print", "playlist_count",
    │           f"https://space.bilibili.com/{self.BILIBILI_UID}/video"
    │       ])
    │
    ├─ 解析输出
    │   └─> current_count = int(stdout.strip())
    │
    ├─ 对比内存中的 URL 数量
    │   └─> memory_count = len(memory_urls)
    │
    ├─ 判断是否有新视频
    │   └─> has_new = current_count > memory_count
    │
    └─ 返回结果
        └─> return has_new

┌─────────────────────────────────────────────────────────────────────┐
│ 第三层: 完整深度检查 (run_monitor 中的扫描)                         │
│ monitor.py:2100                                                     │
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
    │       • ThreadPoolExecutor(max_workers=10)
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

## 5. WGMM 算法完整执行流程

```
═══════════════════════════════════════════════════════════════════════
                  adjust_check_frequency() - WGMM 核心算法
═══════════════════════════════════════════════════════════════════════

调用位置: run_monitor() 结束前
参数: found_new_content (bool) - 是否发现新内容

monitor.py:794

┌─────────────────────────────────────────────────────────────────────┐
│ 【步骤1】加载历史数据和配置                                          │
└─────────────────────────────────────────────────────────────────────┘
    │
    ├─ 加载正向事件 (成功的发布时间)
    │   └─> positive_events = 读取 mtime.txt
    │       • 格式: 每行一个 Unix 时间戳
    │       • 示例: 1706160000\n1706246400\n...
    │
    ├─ 加载负向事件 (检测失败的空检查时间)
    │   └─> negative_events = 读取 miss_history.txt
    │       • 格式: 每行一个 Unix 时间戳
    │
    ├─ 加载 WGMM 算法配置
    │   └─> config = wgmm_config.json
    │       {
    │         "dimension_weights": { "day": 0.5, "week": 1.0, ... },
    │         "sigmas": { "day": 0.8, "week": 1.0, ... },
    │         "last_lambda": 0.0001,
    │         "online_lambda": 0.0001,
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
    │   └─> filter_outliers(events)
    │       • 使用 IQR (四分位距) 方法检测异常
    │       • Q1 = 25th percentile, Q3 = 75th percentile
    │       • IQR = Q3 - Q1
    │       • 移除 [Q1-1.5×IQR, Q3+1.5×IQR] 之外的数据
    │
    └─ 剪枝低权重历史数据
        └─> prune_old_data(events, lambda)
            • 计算每个事件的时间衰减权重
            • weight = exp(-lambda × age_hours)
            • 移除权重 < threshold 的事件 (默认 0.01)
            • 保持算法 O(n) 时间复杂度

┌─────────────────────────────────────────────────────────────────────┐
│ 【步骤3】自适应参数学习                                              │
└─────────────────────────────────────────────────────────────────────┘
    │
    ├─ 计算 Lambda (遗忘速度)
    │   └─> lambda = _calculate_adaptive_lambda(positive_events, negative_events)
    │       │
    │       ├─ 计算正向事件时间方差
    │       │   └─> pos_variance = var(positive_events)
    │       │
    │       ├─ 计算负向事件时间方差
    │       │   └─> neg_variance = var(negative_events)
    │       │
    │       ├─ Lambda 自适应公式
    │       │   └─> lambda = base_lambda × (1 + variance_factor)
    │       │       • variance_factor = (pos_variance + neg_variance) / scale
    │       │       • 方差大 → lambda 大 → 快速遗忘 (不稳定模式)
    │       │       • 方差小 → lambda 小 → 长期记忆 (稳定模式)
    │       │
    │       └─ 限制范围 [0.00005, 0.0002]
    │
    ├─ 学习维度权重
    │   └─> dimension_weights = learn_dimension_weights(events)
    │       │
    │       ├─ 计算每个维度的时间分布方差
    │       │   • hour_var (日周期)
    │       │   • weekday_var (周周期)
    │       │   • month_week_var (月周周期)
    │       │   • month_var (年月周期)
    │       │
    │       ├─ 归一化权重
    │       │   └─> weight_i = variance_i / sum(variances)
    │       │       • 方差大 → 权重大 (该维度信息丰富)
    │       │
    │       └─ 保存到 config["dimension_weights"]
    │
    └─ 学习时间容忍度 (Sigmas)
        └─> sigmas = learn_adaptive_sigmas(events)
            │
            ├─ 计算每个维度的时间离散度
            │   • day_std, week_std, month_week_std, year_month_std
            │
            ├─ Sigma 自适应公式
            │   └─> sigma = base_sigma × (1 + std_factor)
            │       • std_factor = std / scale
            │       • 离散度大 → sigma 大 (更宽松的匹配)
            │
            └─ 保存到 config["sigmas"]

┌─────────────────────────────────────────────────────────────────────┐
│ 【步骤4】计算当前时间发布概率                                        │
└─────────────────────────────────────────────────────────────────────┘
    │
    ├─ 编码当前时间
    │   └─> current_components = _get_time_components(now)
    │       {
    │         "day_sin": sin(2π × hour / 24),
    │         "day_cos": cos(2π × hour / 24),
    │         "week_sin": sin(2π × weekday / 7),
    │         "week_cos": cos(2π × weekday / 7),
    │         "month_week_sin": sin(2π × week_of_month / 4),
    │         "month_week_cos": cos(2π × week_of_month / 4),
    │         "year_month_sin": sin(2π × month / 12),
    │         "year_month_cos": cos(2π × month / 12)
    │       }
    │
    ├─ 计算正向得分 (成功发布历史的相似性)
    │   └─> positive_score = _calculate_point_score(
    │           current_components,
    │           positive_events,
    │           dimension_weights,
    │           sigmas,
    │           lambda
    │       )
    │       │
    │       ├─ 对每个历史事件:
    │       │   └─> 计算四维时间距离
    │       │       • day_dist = sqrt((sin1-sin2)² + (cos1-cos2)²)
    │       │       • week_dist, month_week_dist, year_month_dist
    │       │
    │       │   └─> 计算高斯核相似性
    │       │       • similarity = exp(-dist² / (2×sigma²))
    │       │
    │       │   └─> 计算指数衰减权重
    │       │       • weight = exp(-lambda × age_hours)
    │       │
    │       │   └─> 加权求和
    │       │       • event_score = similarity × weight
    │       │
    │       ├─ 维度加权求和
    │       │   └─> total_score =
    │       │           day_weight × day_score +
    │       │           week_weight × week_score +
    │       │           month_week_weight × month_week_score +
    │       │           year_month_weight × year_month_score
    │       │
    │       └─ 归一化到 [0, 1]
    │           └─> positive_score = total_score / len(positive_events)
    │
    ├─ 计算负向得分 (失败历史的惩罚)
    │   └─> negative_score = _calculate_point_score(
    │           current_components,
    │           negative_events,
    │           dimension_weights,
    │           sigmas,
    │           lambda
    │       )
    │       • 使用相同算法计算负向事件的相似性
    │
    └─ 计算最终得分
        └─> current_score = positive_score - 0.3 × negative_score
            • 正向得分促进检查
            • 负向得分抑制检查 (0.3 是惩罚系数)
            • 结果范围: [-0.3, 1.0]

┌─────────────────────────────────────────────────────────────────────┐
│ 【步骤5】峰值预测 - 扫描未来15天                                    │
└─────────────────────────────────────────────────────────────────────┘
    │
    ├─ 生成未来时间点
    │   └─> future_timestamps = [now + i×3600 for i in range(360)]  # 15天
    │
    ├─ 批量计算得分
    │   └─> scores = _batch_calculate_scores(
    │           future_timestamps,
    │           positive_events,
    │           negative_events,
    │           dimension_weights,
    │           sigmas,
    │           lambda
    │       )
    │       • NumPy 向量化计算
    │       • 一次性计算 360 个时间点的得分
    │       • 避免显式循环，保持 O(n) 复杂度
    │
    ├─ 找到峰值
    │   ├─ peak_score = max(scores)
    │   ├─ peak_time = future_timestamps[argmax(scores)]
    │   └─> distance_to_peak = peak_time - now
    │
    └─ 映射得分到检查间隔
        └─> base_frequency = map_score_to_interval(current_score)
            │
            ├─ 非线性映射公式
            │   └─> interval = DEFAULT × (1 - score)^curve
            │       • score=1.0 → interval=0 (最高频)
            │       • score=0.5 → interval=DEFAULT/2
            │       • score=0.0 → interval=DEFAULT
            │       • curve=2.0 (控制映射激进程度)
            │
            ├─ 峰值提前量调整
            │   └─> if distance_to_peak < peak_advance_minutes:
            │       interval = min(interval, 300秒)  # 加快检查
            │
            └─ 低活跃期调整
                └─> if activity_score < 0.2:
                    interval = interval × 4  # 延长间隔 (最大30天)

┌─────────────────────────────────────────────────────────────────────┐
│ 【步骤6】EWMA 异常检测 (Phase 1 新增)                               │
└─────────────────────────────────────────────────────────────────────┘
    │
    ├─ 初始化 EWMA 检测器
    │   └─> ewma_detector = EWMAAnomalyDetector(config)
    │       {
    │         "ewma_lambda": 0.3,        # EWMA 平滑系数
    │         "control_limit_k": 3.0,    # 控制限倍数 (±3σ)
    │         "min_history": 10          # 最小历史数据量
    │       }
    │
    ├─ 检查当前得分是否异常
    │   └─> is_anomaly, reason = ewma_detector.check_anomaly(current_score)
    │       │
    │       ├─ 更新 EWMA 统计量
    │       │   └─> ewma_mean = alpha × score + (1-alpha) × old_mean
    │       │   └─> ewma_std = sqrt(alpha × variance + (1-alpha) × old_variance)
    │       │
    │       ├─ 计算控制限
    │       │   └─> UCL = ewma_mean + k × ewma_std
    │       │   └─> LCL = ewma_mean - k × ewma_std
    │       │
    │       ├─ 判断异常
    │       │   └─> is_anomaly = (score < LCL) or (score > UCL)
    │       │
    │       ├─ 连续异常计数
    │       │   └─> if is_anomaly:
    │       │       consecutive_anomalies++
    │       │   else:
    │       │       consecutive_anomalies = 0
    │       │
    │       └─ 保存状态到 config
    │           • ewma_mean, ewma_std
    │           • score_history (最近100次)
    │           • consecutive_anomalies
    │
    └─ 触发强制快速检查
        └─> if is_anomaly and consecutive_anomalies >= 2:
            └─> final_frequency_sec = 300秒  # 覆盖其他计算

┌─────────────────────────────────────────────────────────────────────┐
│ 【步骤7】yt-dlp 阻抗因子 (原始机制)                                  │
└─────────────────────────────────────────────────────────────────────┘
    │
    └─> if last_duration > normal_duration × 2:
        └─> impedance_factor = 1.0 ~ 1.5
            • yt-dlp 运行时间异常延长
            • 可能是网络问题或 B站响应慢
            • 延长检查间隔，减少请求频率

┌─────────────────────────────────────────────────────────────────────┐
│ 【步骤8】负向事件记录                                                │
└─────────────────────────────────────────────────────────────────────┘
    │
    └─> if not found_new_content:
        └─> miss_history.append(now)
            • 记录本次空检查的时间戳
            • 保存到 miss_history.txt
            • 下次计算时作为负向事件抑制得分

┌─────────────────────────────────────────────────────────────────────┐
│ 【步骤9】在线反馈学习 (Phase 1 新增)                                │
└─────────────────────────────────────────────────────────────────────┘
    │
    ├─ 初始化在线学习器
    │   └─> online_learner = OnlineFeedbackLearner(config)
    │       {
    │         "lambda_learning_rate": 0.05,  # Lambda 学习率
    │         "sigma_step": 0.05,            # Sigma 调整步长
    │         "REWARD_HISTORY_MAXLEN": 50    # 奖励历史长度
    │       }
    │
    ├─ 根据反馈更新参数
    │   └─> updated_lambda, updated_sigmas = online_learner.update_from_feedback(
    │           found_new_content,
    │           current_score,
    │           current_sigmas
    │       )
    │       │
    │       ├─ 计算奖励
    │       │   └─> if found_new_content:
    │       │       reward = 1.0 + current_score  # 正奖励
    │       │   else:
    │       │       reward = -1.0 × current_score  # 负奖励 ⚠️
    │       │
    │       ├─ Lambda 自适应调整 (惩罚机制B)
    │       │   └─> lambda_factor = 1.05 (默认)
    │       │   └─> if found_new_content:
    │       │       lambda_factor = 1/1.05  # 成功时减小 lambda (保持记忆)
    │       │   else:
    │       │       lambda_factor = 1.05   # 失败时增大 lambda (快速遗忘) ⚠️
    │       │   └─> updated_lambda = online_lambda × lambda_factor
    │       │
    │       ├─ Sigma 动态调整 (奖励机制C)
    │       │   └─> if current_score > 0.7:
    │       │       sigmas *= 0.975  # 高分时收紧 (更严格匹配)
    │       │   elif current_score < 0.3:
    │       │       sigmas *= 1.025  # 低分时放松 (更宽松匹配)
    │       │
    │       └─ 保存学习状态
    │           • online_lambda
    │           • total_reward += reward
    │           • detection_count++
    │           • if found_new_content: success_count++
    │           • reward_history.append(reward)
    │
    └─ 更新配置中的 lambda 和 sigmas
        └─> config["online_lambda"] = updated_lambda
        └─> config["sigmas"] = updated_sigmas

┌─────────────────────────────────────────────────────────────────────┐
│ 【步骤10】保存配置并设置下次检查                                     │
└─────────────────────────────────────────────────────────────────────┘
    │
    ├─ 应用最终的检查间隔
    │   └─> if anomaly_detected and consecutive_anomalies >= 2:
    │       final_frequency_sec = 300秒  # EWMA 触发的快速检查
    │   else:
    │       final_frequency_sec = base_frequency × impedance_factor
    │
    ├─ 限制间隔范围
    │   └─> final_frequency_sec = max(min(final_frequency, MAX_INTERVAL), MIN_INTERVAL)
    │       • MIN_INTERVAL = 300秒 (5分钟)
    │       • MAX_INTERVAL = 2592000秒 (30天)
    │
    ├─ 计算下次检查时间
    │   └─> next_check_time = now + final_frequency_sec
    │
    ├─ 保存配置到文件
    │   └─> _save_wgmm_config()
    │       {
    │         "dimension_weights": {...},
    │         "sigmas": {...},
    │         "last_lambda": lambda,
    │         "online_lambda": updated_lambda,
    │         "ewma_mean": ewma_mean,
    │         "ewma_std": ewma_std,
    │         "consecutive_anomalies": consecutive_anomalies,
    │         "total_reward": total_reward,
    │         "success_count": success_count,
    │         "next_check_time": next_check_time,
    │         "last_update": now
    │       }
    │
    └─ 打印日志
        └─> log_info(
            f"WGMM调频 - 轮询间隔: {final_frequency_sec}秒 " +
            f"(得分: {current_score:.3f}, " +
            f"Lambda: {updated_lambda:.5f}, " +
            f"下次检查: {next_check_time})"
        )
```

## 6. 数据流与文件操作

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
    VideoMonitor.__init__()  ← 读取

═══════════════════════════════════════════════════════════════════════

    wgmm_config.json (算法状态)
    │
    ├─ dimension_weights (四维时间权重)
    │   ├─ day: 0.5
    │   ├─ week: 1.0
    │   ├─ month_week: 0.3
    │   └─ year_month: 0.2
    │
    ├─ sigmas (时间容忍度)
    │   ├─ day: 0.8
    │   ├─ week: 1.0
    │   ├─ month_week: 1.5
    │   └─ year_month: 2.0
    │
    ├─ last_lambda (自适应 lambda)
    ├─ online_lambda (在线学习 lambda) ⚠️ Phase 1
    ├─ lambda_learning_rate ⚠️ Phase 1
    ├─ sigma_step ⚠️ Phase 1
    │
    ├─ ewma_mean ⚠️ Phase 1
    ├─ ewma_std ⚠️ Phase 1
    ├─ consecutive_anomalies ⚠️ Phase 1
    │
    ├─ total_reward ⚠️ Phase 1
    ├─ detection_count ⚠️ Phase 1
    ├─ success_count ⚠️ Phase 1
    ├─ reward_history ⚠️ Phase 1
    │
    ├─ next_check_time (下次检查时间戳)
    └─ last_update (最后更新时间戳)
         │
         ▼
    _load_wgmm_config()  ← 读取
    _save_wgmm_config()  ← 保存

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
    save_real_upload_timestamps()  ← 追加
    generate_mtime_file()  ← 首次生成

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
    adjust_check_frequency()  ← 追加 (当 found_new_content=False)

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
    load_known_urls()  ← 读取
    save_known_urls()  ← 保存

═══════════════════════════════════════════════════════════════════════

    GitHub Gist (云端备份)
    │
    ├─ GET https://api.github.com/gists/{GIST_ID}
    │   └─> 响应: Gist 文件内容 (memory_urls)
    │
    ├─ PATCH https://api.github.com/gists/{GIST_ID}
    │   └─> 请求: 更新 Gist 文件内容
    │
    └─> 用途:
        • 双层 URL 管理的云端层
        • 跨实例/设备同步已知 URL
         │
         ▼
    sync_urls_from_gist()  ← 同步
    notify_new_videos()    ← 更新

═══════════════════════════════════════════════════════════════════════

    urls.log (主运行日志)
    │
    ├─ 格式: 时间戳 - 日志级别 - 消息
    ├─ 示例:
    │   2026-01-23 15:30:00 - INFO - 检查开始                  <--
    │   2026-01-23 15:30:05 - INFO - 预检查完成 - 预测检查: 无新内容 快速检查: 无新内容
    │   2026-01-23 15:30:10 - INFO - WGMM调频 - 轮询间隔: 7200秒
    │   ...
    │
    └─> 用途:
        • 记录所有 INFO/WARNING/ERROR 级别日志
        • 自动限制 1000 行
         │
         ▼
    log_message()  ← 写入

═══════════════════════════════════════════════════════════════════════

    critical_errors.log (严重错误日志)
    │
    ├─ 格式: 时间戳 - [位置] - 错误消息
    ├─ 示例:
    │   2026-01-23 15:30:00 - [run_monitor] - 无法获取视频列表
    │   ...
    │
    └─> 用途:
        • 专门记录 CRITICAL 级别错误
        • 自动发送 Bark 通知
        • 自动限制 500 行
         │
         ▼
    log_critical_error()  ← 写入
```

## 7. 通知系统

```
═══════════════════════════════════════════════════════════════════════
                        Bark 推送通知系统
═══════════════════════════════════════════════════════════════════════

┌─────────────────────────────────────────────────────────────────────┐
│ send_bark_push() - 通用 Bark 推送方法                               │
│ monitor.py:308                                                      │
└─────────────────────────────────────────────────────────────────────┘
    │
    ├─ 构造请求 URL
    │   └─> url = f"{bark_base_url}/{bark_device_key}/{title}/{body}"
    │       • base_url: "https://api.day.app"
    │       • device_key: 从环境变量读取
    │       • title: 通知标题 (URL 编码)
    │       • body: 通知内容 (URL 编码)
    │
    ├─ 发送 GET 请求
    │   └─> requests.get(url, timeout=10)
    │
    ├─ 处理响应
    │   ├─ 成功: status_code == 200
    │   │   └─> log_info("Bark 通知已发送")
    │   │
    │   └─ 失败: status_code != 200
    │       └─> log_warning(f"Bark 通知发送失败: {status_code}")
    │
    └─ 异常处理
        └─> except requests.RequestException:
            └─> log_warning(f"Bark 通知发送异常: {e}")

┌─────────────────────────────────────────────────────────────────────┐
│ notify_new_videos() - 新视频通知                                    │
│ monitor.py:421                                                      │
└─────────────────────────────────────────────────────────────────────┘
    │
    ├─ 参数
    │   ├─ count: 新视频数量
    │   └─ has_new_parts: 是否包含新分片
    │
    ├─ 构造通知标题
    │   └─> title = f"{self.bark_app_title} - 发现 {count} 个新视频"
    │
    ├─ 构造通知内容
    │   └─> body = "B站有新视频发布！"
    │       if has_new_parts:
    │           body += " (包含新分片)"
    │
    ├─ 发送 Bark 推送
    │   └─> send_bark_push(title, body)
    │
    ├─ 更新 memory_urls
    │   └─> memory_urls.extend(gist_missing_urls)
    │
    └─ 同步到 GitHub Gist
        └─> sync_to_gist()
            ├─ 构造 Gist 更新请求
            │   {
            │     "files": {
            │       "bilibili_videos.txt": {
            │         "content": "\n".join(memory_urls)
            │       }
            │     }
            │   }
            │
            ├─ PATCH https://api.github.com/gists/{GIST_ID}
            │
            └─ 处理响应
                ├─ 成功: log_info("已同步到 Gist")
                └─ 失败: log_warning("Gist 同步失败")

┌─────────────────────────────────────────────────────────────────────┐
│ log_critical_error() - 严重错误通知                                  │
│ monitor.py:366                                                      │
└─────────────────────────────────────────────────────────────────────┘
    │
    ├─ 参数
    │   ├─ message: 错误消息
    │   ├─ location: 错误位置 (函数名)
    │   └─ send_notification: 是否发送 Bark 通知
    │
    ├─ 写入 critical_errors.log
    │   └─> with open(critical_log_file, "a", encoding="utf-8") as f:
    │           f.write(f"{timestamp} - [{location}] - {message}\n")
    │
    ├─ 限制日志文件大小 (500 行)
    │   └─> 读取所有行，保留最后 500 行
    │
    ├─ 发送 Bark 通知 (如果 send_notification=True)
    │   └─> title = "⚠️ 监控脚本严重错误"
    │   └─> body = f"[{location}] {message}"
    │   └─> send_bark_push(title, body)
    │
    └─ 记录到主日志
        └─> log_error(f"严重错误: {message}")
```

## 8. 错误处理机制

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
    │   ├─ GitHub Gist 同步失败
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

## 9. 并发处理机制

```
═══════════════════════════════════════════════════════════════════════
                    并发获取视频信息
═══════════════════════════════════════════════════════════════════════

┌─────────────────────────────────────────────────────────────────────┐
│ get_all_videos_parallel() - 并发获取所有视频的分片信息              │
│ monitor.py:1609                                                     │
└─────────────────────────────────────────────────────────────────────┘
    │
    ├─ 参数
    │   └─> video_urls: list[str] - 视频 URL 列表
    │
    ├─ 创建线程池
    │   └─> with ThreadPoolExecutor(max_workers=10) as executor:
    │       • 最多 10 个并发线程
    │       • 自动管理线程生命周期
    │
    ├─ 提交任务
    │   └─> futures = {
    │           executor.submit(get_video_parts, url): url
    │           for url in video_urls
    │       }
    │       • 为每个 URL 创建一个异步任务
    │       • 返回 {Future: URL} 映射
    │
    ├─ 收集结果
    │   └─> for future in as_completed(futures):
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
    │                   └─> log_warning(f"获取视频分片失败: {url}")
    │
    └─ 返回结果
        └─> return all_parts (所有分片的扁平列表)

┌─────────────────────────────────────────────────────────────────────┐
│ get_video_parts() - 获取单个视频的分片信息                          │
│ monitor.py:1572                                                     │
└─────────────────────────────────────────────────────────────────────┘
    │
    ├─ 参数
    │   └─> video_url: str - 视频 URL
    │
    ├─ 执行 yt-dlp 获取分片信息
    │   └─> run_yt_dlp([
    │           "--cookies", self.cookies_file,
    │           "--print", "playlist_count",
    │           video_url
    │       ])
    │       • playlist_count: 视频的分片数量
    │
    ├─ 解析分片数
    │   └─> part_count = int(stdout.strip()) if stdout else 0
    │
    ├─ 生成分片 URL
    │   └─> if part_count > 1:
    │           parts = []
    │           for i in range(1, part_count + 1):
    │               # B站分片 URL 格式: ?p=1, ?p=2, ...
    │               part_url = f"{video_url}?p={i}"
    │               parts.append(part_url)
    │           return parts
    │       else:
    │           return [video_url]  # 无分片，返回原 URL
    │
    └─ 返回结果
        └─> return parts (分片 URL 列表)

┌─────────────────────────────────────────────────────────────────────┐
│ 性能优化要点                                                        │
└─────────────────────────────────────────────────────────────────────┘
    │
    ├─ 并发控制
    │   • max_workers=10: 平衡并发度和资源占用
    │   • 避免过多并发导致 B站限流
    │
    ├─ 超时处理
    │   • yt-dlp 默认超时: 60 秒
    │   • requests 超时: 10 秒
    │
    ├─ 资源管理
    │   • with 语句自动管理线程池
    │   • as_completed() 按完成顺序处理结果
    │
    └─ 错误隔离
        • 单个视频失败不影响其他视频
        • 异常被捕获并记录，不会传播
```

## 10. 工具方法与辅助功能

```
═══════════════════════════════════════════════════════════════════════
                        常用工具方法
═══════════════════════════════════════════════════════════════════════

┌─────────────────────────────────────────────────────────────────────┐
│ run_yt_dlp() - 执行 yt-dlp 命令                                     │
│ monitor.py:272                                                      │
└─────────────────────────────────────────────────────────────────────┘
    │
    ├─ 参数
    │   └─> args: list[str] - yt-dlp 命令行参数
    │
    ├─ 查找 yt-dlp 可执行文件
    │   ├─ 首次调用: shutil.which("yt-dlp")
    │   ├─ 缓存路径: self.yt_dlp_path
    │   └─> 重复使用: 直接使用缓存路径
    │
    ├─ 构造完整命令
    │   └─> cmd = [yt_dlp_path] + args
    │       • 例如: ["yt-dlp", "--cookies", "cookies.txt", ...]
    │
    ├─ 执行命令
    │   └─> subprocess.run(
    │           cmd,
    │           capture_output=True,
    │           text=True,
    │           check=False,
    │           timeout=120
    │       )
    │       • capture_output=True: 捕获 stdout 和 stderr
    │       • timeout=120: 2 分钟超时
    │
    ├─ 记录执行时间
    │   └─> last_ytdlp_duration = elapsed_time
    │       • 用于 yt-dlp 阻抗因子计算
    │
    └─ 返回结果
        └─> return (success, stdout, stderr)
            • success: returncode == 0
            • stdout: 标准输出内容
            • stderr: 标准错误内容

┌─────────────────────────────────────────────────────────────────────┐
│ save_real_upload_timestamps() - 保存真实上传时间                    │
│ monitor.py:1541                                                     │
└─────────────────────────────────────────────────────────────────────┘
    │
    ├─ 参数
    │   └─> urls: list[str] - 新视频 URL 列表
    │
    ├─ 遍历每个 URL
    │   └─> for url in urls:
    │       │
    │       ├─ 获取上传时间
    │       │   └─> upload_timestamp = get_video_upload_time(url)
    │       │       • 调用 yt-dlp 的 --print "%(timestamp)" 选项
    │       │       • 返回 Unix 时间戳
    │       │
    │       ├─ 写入 mtime.txt
    │       │   └─> with open(mtime_file, "a", encoding="utf-8") as f:
    │       │           f.write(f"{upload_timestamp}\n")
    │       │
    │       └─ 异常处理
    │           └─> except Exception:
    │               └─> log_warning(f"无法获取视频上传时间: {url}")
    │
    └─ 开发模式处理
        └─> if dev_mode:
            • 不写入文件，仅记录到 sandbox_miss_history

┌─────────────────────────────────────────────────────────────────────┐
│ cleanup() - 清理临时资源                                            │
│ monitor.py:1636                                                     │
└─────────────────────────────────────────────────────────────────────┘
    │
    ├─ 删除临时输出目录
    │   └─> tmp_dir = Path(self.tmp_outputs_dir)
    │   └─> if tmp_dir.exists():
    │       └─> shutil.rmtree(tmp_dir)
    │           • 递归删除整个目录
    │
    └─ 其他清理操作 (可扩展)
        • 关闭文件句柄
        • 重置临时状态

┌─────────────────────────────────────────────────────────────────────┐
│ signal_handler() - 信号处理器                                       │
│ monitor.py:1453                                                     │
└─────────────────────────────────────────────────────────────────────┘
    │
    ├─ 注册信号
    │   ├─ SIGTERM: 终止信号 (kill 命令)
    │   └─ SIGINT: 中断信号 (Ctrl+C)
    │
    ├─ 信号处理流程
    │   ├─ 接收信号
    │   ├─ log_info("收到中断信号, 正在退出...")
    │   ├─ cleanup() 清理资源
    │   └─ sys.exit(0) 优雅退出
    │
    └─ 确保数据完整性
        • 配置文件保存
        • 临时文件删除
        • 日志刷新到磁盘

┌─────────────────────────────────────────────────────────────────────┐
│ get_next_check_time() - 获取下次检查时间                            │
│ monitor.py:1627                                                     │
└─────────────────────────────────────────────────────────────────────┘
    │
    ├─ 读取配置
    │   └─> config = _load_wgmm_config()
    │
    ├─ 获取时间戳
    │   └─> next_check_time = config.get("next_check_time", 0)
    │
    └─ 返回结果
        └─> return next_check_time
            • 0: 未设置，立即检查
            • >0: 等待到该时间戳
```

## 11. 性能与优化

```
═══════════════════════════════════════════════════════════════════════
                        性能优化策略
═══════════════════════════════════════════════════════════════════════

┌─────────────────────────────────────────────────────────────────────┐
│ WGMM 算法性能优化                                                   │
└─────────────────────────────────────────────────────────────────────┘
    │
    ├─ 向量化计算 (monitor.py:1932)
    │   ├─ 使用 NumPy 数组操作
    │   │   • 避免显式 Python 循环
    │   │   • 利用 C 层级的性能
    │   │
    │   └─ _batch_calculate_scores() 批处理
    │       • 一次性计算 360 个时间点
    │       • 时间复杂度: O(n) = O(历史事件数)
    │       • 典型执行时间: ~10ms
    │
    ├─ 内存管理 (monitor.py:952)
    │   ├─ prune_old_data() 自动剪枝
    │   │   • 移除权重 < 0.01 的历史事件
    │   │   • 保持算法 O(n) 复杂度
    │   │
    │   └─ 使用生成器而非列表
    │       • filter_outliers() 返回迭代器
    │       • 按需计算，减少内存占用
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
    │   • ThreadPoolExecutor(max_workers=10)
    │   • 平衡并发度和 B站限流风险
    │
    ├─ 超时设置
    │   • yt-dlp: 120 秒
    │   • requests: 10 秒
    │   • 避免长时间阻塞
    │
    ├─ 三层检测架构
    │   ├─ 第一层: 仅检查最新 10 个视频
    │   ├─ 第二层: 仅获取视频数量
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
    │   ├─ urls.log: 1000 行
    │   ├─ critical_errors.log: 500 行
    │   └─ 防止磁盘空间耗尽
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
    │   • 第一层: ~2秒 (10 个视频)
    │   • 第二层: ~1秒 (仅数量)
    │   • 第三层: ~10秒 (100 个视频，含分片)
    │
    ├─ 系统资源占用
    │   • CPU: <1% (大部分时间在睡眠)
    │   • 内存: <10MB (常驻内存)
    │   • 网络: 取决于视频数量
    │
    └─ 并发性能
        • 10 个并发线程
        • 单个视频获取: ~1秒
        • 100 个视频总耗时: ~10秒
```

## 12. 代码位置快速索引

```
═══════════════════════════════════════════════════════════════════════
                      关键代码位置索引
═══════════════════════════════════════════════════════════════════════

【程序入口与初始化】
monitor.py:26      - parse_arguments() - 命令行参数解析
monitor.py:37      - load_env_file() - 环境变量加载
monitor.py:58      - VideoMonitor 类定义
monitor.py:74      - __init__() - 初始化监控系统
monitor.py:2379    - main() - 程序入口点
monitor.py:2438    - if __name__ == "__main__" - 启动

【主监控循环】
monitor.py:2052    - run_monitor() - 主监控流程
monitor.py:1658    - wait_for_next_check() - 等待下次检查

【三层检测架构】
monitor.py:1515    - check_potential_new_parts() - 第一层: 分片预检查
monitor.py:1477    - quick_precheck() - 第二层: 快速 ID 检查
monitor.py:2100    - 第三层: 完整深度扫描 (run_monitor 内)

【WGMM 核心算法】
monitor.py:794     - adjust_check_frequency() - WGMM 主函数
monitor.py:1827    - _calculate_point_score() - 计算单个时间点得分
monitor.py:1932    - 最终得分 = 正向 - 0.3 × 负向
monitor.py:1958    - _batch_calculate_scores() - 批量计算得分
monitor.py:1667    - _get_time_components() - 时间特征编码
monitor.py:1053    - _calculate_adaptive_lambda() - Lambda 自适应
monitor.py:1127    - learn_dimension_weights() - 维度权重学习
monitor.py:1195    - learn_adaptive_sigmas() - Sigma 学习

【Phase 1 在线学习】
monitor.py:2204    - OnlineFeedbackLearner 类定义
monitor.py:2223    - update_from_feedback() - 在线反馈学习
monitor.py:2290    - EWMAAnomalyDetector 类定义
monitor.py:2314    - check_anomaly() - EWMA 异常检测

【数据管理】
monitor.py:129     - sync_urls_from_gist() - 同步 Gist URL
monitor.py:142     - load_known_urls() - 加载本地已知 URL
monitor.py:157     - save_known_urls() - 保存本地已知 URL
monitor.py:1541    - save_real_upload_timestamps() - 保存上传时间
monitor.py:233     - _load_wgmm_config() - 加载 WGMM 配置
monitor.py:244     - _save_wgmm_config() - 保存 WGMM 配置

【通知系统】
monitor.py:308     - send_bark_push() - Bark 推送通知
monitor.py:421     - notify_new_videos() - 新视频通知
monitor.py:366     - log_critical_error() - 严重错误通知

【工具方法】
monitor.py:272     - run_yt_dlp() - 执行 yt-dlp 命令
monitor.py:1572    - get_video_parts() - 获取视频分片
monitor.py:1609    - get_all_videos_parallel() - 并发获取视频信息
monitor.py:1636    - cleanup() - 清理临时资源
monitor.py:1453    - signal_handler() - 信号处理器
monitor.py:1627    - get_next_check_time() - 获取下次检查时间

【日志与错误处理】
monitor.py:385     - log_message() - 统一日志记录
monitor.py:342     - log_info() - INFO 级别日志
monitor.py:349     - log_warning() - WARNING 级别日志
monitor.py:356     - log_error() - ERROR 级别日志
```

---

**文档生成时间**: 2026-01-23
**对应代码版本**: monitor.py (2439 行)
**适用版本**: v1.x - WGMM Phase 1 完整实现
