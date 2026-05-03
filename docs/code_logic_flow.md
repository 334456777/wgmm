# 代码逻辑流程

本文档描述当前 `wgmm_monitor/` 模块化实现的运行流程、数据流和错误处理。

## 入口流程

```text
monitor.py
    -> wgmm_monitor.cli.main()
        -> load_env_file("data/.env")
        -> parse_arguments()
        -> Application(dev_mode=args.dev or args.wgmm_core_only)
            -> load_app_config()
            -> validate required env keys
            -> RuntimeLogger
            -> NotificationService(BarkClient)
            -> validate data/cookies.txt
            -> ConfigStore.load()
            -> UrlStore.load()
            -> HistoryStore
            -> YtDlpClient
            -> BilibiliService
            -> HistoryService
            -> FrequencyService
            -> MonitorService
            -> register signals
        -> run_wgmm_core_only() / run_dev_once() / run_forever()
```

模式分支：

- `--wgmm-core-only`：调用 `FrequencyService.adjust_check_frequency(found_new_content=False)` 后退出。
- `--dev`：调用 `MonitorService.run_monitor()`，再打印下次检查时间后退出。
- 默认模式：循环执行 `wait_for_next_check()` 和 `run_monitor()`。

## 主循环

```text
Application.run_forever()
    -> ConfigStore.ensure_manual_flag()
    -> while True:
        -> MonitorService.wait_for_next_check()
        -> MonitorService.run_monitor()
```

`wait_for_next_check()` 从内存中的 `WgmmConfig.next_check_time` 读取目标时间。生产模式会 `sleep()`；dev mode 只打印下次检查时间。

## 三层检测流程

一次 `run_monitor()`：

```text
检查开始
    -> sync_urls_from_gist()
        -> GistClient.fetch_urls()
        -> memory_urls = gist urls
        -> known_urls.update(memory_urls)
        -> UrlStore.save(known_urls) outside dev mode

    -> BilibiliService.check_potential_new_parts(memory_urls)
        -> extract max ?p= per base URL
        -> yt-dlp --simulate next part
        -> if found, probe up to five more possible parts

    -> BilibiliService.quick_precheck(memory_urls, known_urls)
        -> yt-dlp --flat-playlist --playlist-end 1 --print "%(id)s"
        -> compare latest id against memory_urls | known_urls

    -> if neither precheck finds changes:
        -> adjust_check_frequency(found_new_content=False)
        -> cleanup()
        -> return

    -> BilibiliService.fetch_video_list()
        -> retry once after 30 seconds if first attempt fails

    -> BilibiliService.get_all_videos_parallel(video_urls)
        -> ThreadPoolExecutor(max_workers=5)
        -> get_video_parts() for each base URL

    -> if all_parts is empty:
        -> log warning
        -> adjust_check_frequency(found_new_content=False)
        -> cleanup()
        -> return

    -> compare URL sets
        -> existing_urls_set = set(memory_urls)
        -> current_urls_set = set(all_parts)
        -> gist_missing_urls = current_urls_set - existing_urls_set
        -> truly_new_urls = gist_missing_urls - known_urls

    -> if truly_new_urls:
        -> save real upload timestamps for truly_new_urls
        -> known_urls.update(gist_missing_urls)
        -> UrlStore.save(known_urls)
        -> write Gist new.txt outside dev mode
        -> notify outside dev mode (count = len(truly_new_urls))
        -> adjust_check_frequency(found_new_content=True)

    -> elif gist_missing_urls:
        -> adjust_check_frequency(found_new_content=False)

    -> elif found_new_parts:
        -> adjust_check_frequency(found_new_content=True)

    -> else:
        -> adjust_check_frequency(found_new_content=False)

    -> cleanup()
```

关键防护：

- Gist 失败且没有基准 URL 时跳过本轮。
- 完整列表获取失败时重试一次。
- 分片扩展失败时跳过本轮，不把基础 URL 当作结果。
- 上传时间获取失败时跳过该时间戳，不写当前时间。

## URL 双层状态

```text
GitHub Gist urls.txt
    -> memory_urls
        + data/local_known.txt
    -> known_urls
        + current scan result
    -> gist_missing_urls
    -> truly_new_urls
```

含义：

- `memory_urls`：云端已备份 URL。
- `known_urls`：本地完整已知集合，包含云端和本地尚未同步状态。
- `gist_missing_urls`：当前扫描中 Gist 还没有的 URL。
- `truly_new_urls`：本地也没见过的 URL，才保存上传时间、写入 Gist new.txt、触发通知和新内容学习。

通知与 Gist new.txt 写入只在 `truly_new_urls` 非空时发生。如果 `gist_missing_urls` 非空但 `truly_new_urls` 为空（云端备份滞后于本地已知），路径会静默走 negative 调频，避免对同一批 URL 重复推送。这个设计容忍 Gist 手动或延迟更新期间的状态不一致。

## WGMM 调频流程

服务层入口：

```text
MonitorService.adjust_check_frequency()
    -> FrequencyService.adjust_check_frequency()
```

详细流程：

```text
FrequencyService.adjust_check_frequency()
    -> if data/mtime.txt missing:
        -> HistoryService.generate_mtime_file()
        -> if still unavailable:
            -> next_check_time = now + FALLBACK_INTERVAL
            -> save config outside dev mode
            -> return fallback FrequencyDecision

    -> positive_events = HistoryStore.load_positive_events()
    -> negative_events = HistoryStore.load_miss_history()
    -> aggregate_publish_events(positive_events, gap_threshold_sec=600)
    -> filter_outliers(negative_events)

    -> if positive event count >= PRUNE_THRESHOLD:
        -> HistoryStore.prune_old_data() for positive and negative files

    -> decide_next_frequency(...)

    -> if decision.should_save_miss:
        -> HistoryStore.save_miss_history()

    -> ConfigStore.save() outside dev mode
    -> RuntimeLogger.log_info(decision.log_message)
```

纯算法决策：

```text
decide_next_frequency()
    -> initialize_wgmm_dimensions()
    -> handle manual/dev mode
    -> if positive events < MIN_HISTORY_COUNT:
        -> learning interval = median historical interval or FALLBACK_INTERVAL
        -> update next_check_time
        -> return learning decision

    -> calculate_adaptive_lambda() for positive events
    -> calculate_adaptive_lambda() for negative events
    -> discover_periods()
    -> sync_discovered_periods()
    -> initialize_wgmm_dimensions()
    -> learn_dimension_weights()
    -> learn_adaptive_sigmas()
    -> calculate_point_score()
    -> scan_future_peak()
        -> batch_calculate_scores()
        -> detect local peaks
        -> fallback to global best when needed
    -> map relative current score to interval
    -> optionally advance strong peak by observed yt-dlp duration
    -> apply yt-dlp impedance when recent duration is abnormal
    -> update WgmmConfig
    -> return FrequencyDecision
```

## 历史数据生成

```text
HistoryService.generate_mtime_file(context)
    -> if data/mtime.txt exists and non-empty:
        -> return True
    -> try up to 3 times:
        -> create_mtime_from_info_json()
    -> on repeated failure:
        -> RuntimeLogger.log_critical_error()
        -> return False
```

`create_mtime_from_info_json()`：

```text
yt-dlp --write-info-json --skip-download
    -> temp_info_json/*.info.json
    -> parse timestamp or upload_date
    -> write temp_timestamps.txt
    -> sort with system sort when available
    -> write data/mtime.txt
    -> cleanup temp files
```

## 通知流程

```text
MonitorService.run_monitor()
    -> NotificationService.notify_new_videos()
        -> BarkClient.send_push()
```

通知类型：

- 新视频：`timeSensitive`，分组 `新视频`。
- 普通错误：`active`，分组 `错误`。
- 严重错误：`critical`，带 alarm/call/volume 参数，分组 `严重错误`。

dev mode 下主流程不发送新视频通知，严重错误通知也由 `RuntimeLogger` 的 dev mode 保护。

## 日志流程

```text
RuntimeLogger.log_message()
    -> print to console
    -> write urls.log outside dev mode
    -> limit urls.log every 1000 writes

RuntimeLogger.log_critical_error()
    -> print CRITICAL
    -> write critical_errors.log outside dev mode
    -> send critical Bark notification outside dev mode when enabled
```

日志文件行数限制：

- `urls.log`：100000 行
- `critical_errors.log`：20000 行
- 历史文件由 `HistoryStore` 调用 `limit_file_lines()` 限制到 100000 行

## 错误处理

### 启动阶段

- 环境变量缺失：打印错误并退出。
- cookies 文件缺失、为空或不可读：记录严重错误并退出。

### 外部请求

- Gist 读取失败：记录严重错误，返回失败状态。
- Gist 写入失败：记录严重错误，主流程继续。
- Bark 失败：返回 `False`，服务层记录失败。
- `yt-dlp` 缺失：记录错误并返回失败结果。
- `yt-dlp` 超时：记录 warning 并返回失败结果。

### 检测阶段

- 快速检查失败：触发完整检查。
- 完整列表失败：30 秒后重试一次。
- 完整列表仍失败：记录严重错误，按未发现新内容调频。
- 分片扩展为空：记录 warning，跳过本轮检测。

### 调频阶段

- `mtime.txt` 不可用且生成失败：使用 1 小时回退间隔。
- 配置 JSON 损坏：使用默认 `WgmmConfig`。
- dev mode：不写真实 WGMM 配置和负向历史。

## 并发

唯一显式并发点在 `BilibiliService.get_all_videos_parallel()`：

```text
ThreadPoolExecutor(max_workers=5)
    -> submit get_video_parts(url)
    -> as_completed()
    -> collect parts
```

单个视频失败只记录 warning，不中断其他视频的处理。

## 验证路径

```bash
source .venv/bin/activate
ruff check monitor.py wgmm_monitor tests
ruff format --check monitor.py wgmm_monitor tests
python -m unittest discover -s tests
python monitor.py --wgmm-core-only
python monitor.py --dev
```
