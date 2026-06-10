# 开发指南

本文档描述当前 `wgmm_monitor/` 模块化实现下的开发、验证和故障排查流程。对外入口仍然是 `python monitor.py`，入口内部调用 `wgmm_monitor.cli.main()`。

## 开发命令

```bash
source .venv/bin/activate
pip install -r requirements-dev.txt  # 开发工具: ruff + coverage

python monitor.py
python monitor.py --dev
python monitor.py --wgmm-core-only

ruff check monitor.py wgmm_monitor tests
ruff format monitor.py wgmm_monitor tests
ruff format --check monitor.py wgmm_monitor tests
python -m unittest discover -s tests

# 测试覆盖率 (配置见 pyproject.toml [tool.coverage])
python -m coverage run -m unittest discover -s tests
python -m coverage report
```

模式说明：

- `python monitor.py`：生产循环，读取 `next_check_time` 并等待。
- `python monitor.py --dev`：执行一次完整监控链，不写 WGMM 配置，不发送新视频通知。
- `python monitor.py --wgmm-core-only`：只执行 WGMM 调频，不执行 B站视频检测。

## 当前架构

```text
monitor.py
    -> wgmm_monitor.cli
    -> wgmm_monitor.app
    -> services
        -> clients / stores / wgmm / utils / models
```

职责边界：

- `cli.py`：参数解析和模式分发。
- `app.py`：装配 `RuntimePaths`、配置、日志、客户端、存储和服务。
- `clients/`：外部系统封装，包括 Bark、Gist、`yt-dlp`。
- `stores/`：本地文件持久化，包括 WGMM 配置、历史事件、URL 状态。
- `services/`：业务编排，包括主监控流程、B站检测、历史维护、调频、通知。
- `wgmm/`：纯算法层，不直接访问网络、日志文件或环境变量。
- `models.py`：跨模块数据结构。
- `runtime_logger.py`：日志和严重错误通知触发。

## 代码质量

修改 Python 代码后必须运行：

```bash
source .venv/bin/activate
ruff check monitor.py wgmm_monitor tests
ruff format monitor.py wgmm_monitor tests
python -m unittest discover -s tests
```

提交前使用只读格式检查：

```bash
ruff format --check monitor.py wgmm_monitor tests
```

要求：

- tab 缩进
- 行长度 92
- Google 风格 docstring
- 不修改 `pyproject.toml` 来绕过 lint
- 外部请求、文件写入、时间相关逻辑应可测试

## 测试策略

测试使用标准库 `unittest`：

```bash
python -m unittest discover -s tests
```

测试覆盖重点：

- `wgmm_monitor/wgmm/`：算法输入输出、学习期、custom period、得分边界、峰值响应与阻抗分支。
- `wgmm_monitor/stores/`：缺失文件、dev mode、未知配置字段保留、剪枝与 OSError 容错。
- `wgmm_monitor/services/`：监控全分支、三层检测、历史重建（mock yt-dlp / view API）、调频编排、通知内容。
- `wgmm_monitor/clients/`：Bark/Gist/yt-dlp 的参数组装与异常路径（mock requests / subprocess）。
- `wgmm_monitor/config.py`、`cli.py`、`app.py`：配置加载、模式分发、装配与启动校验。

测试约束：

- 不触网、不调用真实子进程：requests/subprocess 一律 mock，外部系统用 Fake 类。
- 文件操作全部落在 `tempfile.TemporaryDirectory` 内。
- 整套测试应在 1 秒内完成。

覆盖率基线：整体 ≥ 90%（当前约 96%）。新增代码应附带测试；查看缺失行：

```bash
python -m coverage report --show-missing
```

冒烟测试链：

```bash
python monitor.py --wgmm-core-only
python monitor.py --dev
python -m unittest discover -s tests
```

如果部署为 systemd 服务，再检查：

```bash
sudo systemctl status video-monitor
sudo journalctl -u video-monitor -n 100
```

## 数据文件

```text
data/.env                  # 手动创建，环境变量
data/cookies.txt           # 手动创建，B站登录凭证
data/local_known.txt       # UrlStore 管理
data/wgmm_config.json      # ConfigStore 管理
data/mtime.txt             # HistoryStore 正向事件
data/miss_history.txt      # HistoryStore 负向事件
urls.log                   # RuntimeLogger 主日志
critical_errors.log        # RuntimeLogger 严重错误日志
```

开发模式下：

- `ConfigStore.save()` 不写 `wgmm_config.json`。
- `HistoryStore.save_miss_history()` 写入内存沙盒。
- `UrlStore.save()` 写入内存沙盒。
- `RuntimeLogger` 不写日志文件。
- `MonitorService` 清理 `temp_info_json`。

## 主监控流程

`wgmm_monitor/services/monitor.py` 的一次 `run_monitor()`：

```text
sync_urls_from_gist()
    -> check_potential_new_parts()
    -> quick_precheck()
    -> fetch_video_list() when needed
    -> get_all_videos_parallel()
    -> compare memory_urls / known_urls / current_urls
    -> save_real_upload_timestamps()
    -> write_new_urls_to_gist()
    -> notify_new_videos()
    -> adjust_check_frequency()
```

如果 Gist 同步失败且没有基准 URL 数据，本轮检查会跳过。如果分片扩展失败，系统不会降级使用基础 URL，而是跳过本轮检测，避免污染 URL 和历史数据。

## WGMM 调频流程

`wgmm_monitor/services/frequency.py` 负责读取历史数据并调用 `wgmm_monitor/wgmm/scheduler.py`：

```text
load_positive_events()
load_miss_history()
aggregate_publish_events()  # 正向：近邻聚合 600 秒
filter_outliers()           # 负向：IQR 过滤
prune_old_data()
decide_next_frequency()
    -> calculate_adaptive_lambda()
    -> discover_periods()
    -> sync_discovered_periods()
    -> learn_dimension_weights()
    -> learn_adaptive_sigmas()
    -> calculate_point_score()
    -> scan_future_peak()
    -> batch_calculate_scores()
save miss history when needed
save config outside dev mode
```

当 `mtime.txt` 缺失时，`HistoryService.generate_mtime_file()` 会通过 `yt-dlp --write-info-json` 生成历史上传时间戳。失败时使用 1 小时回退间隔。

## 故障排查

### 基础检查

```bash
source .venv/bin/activate
which yt-dlp
yt-dlp --version
ls -la data/.env data/cookies.txt
tail -100 urls.log
cat critical_errors.log
```

### 环境变量缺失

`Application` 调用 `AppConfig.missing_required_keys()`。缺少任一必填项时输出 `缺少必要的环境变量` 并退出。

检查：

```bash
cat data/.env
source .venv/bin/activate
python -c "from wgmm_monitor.config import load_env_file, load_app_config; load_env_file('data/.env'); print(load_app_config().missing_required_keys())"
```

### cookies 缺失或为空

`Application._validate_cookies_file()` 会在启动时验证 `data/cookies.txt`。缺失、为空或不可读都会记录 CRITICAL 并退出。

检查：

```bash
ls -l data/cookies.txt
head -5 data/cookies.txt
```

### yt-dlp 不存在或 PATH 错误

`YtDlpClient` 首次调用时使用 `shutil.which("yt-dlp")`。找不到时记录错误并返回失败结果。

检查：

```bash
which yt-dlp
yt-dlp --version
```

### Gist 失败

`GistClient.fetch_urls()` 失败时返回错误文本，`MonitorService.sync_urls_from_gist()` 记录严重错误。如果没有已有 `memory_urls`，本轮跳过。

检查：

```bash
curl -I https://api.github.com
```

确认 `GITHUB_TOKEN` 有 gist 权限，`GIST_ID` 指向包含 `urls.txt` 的 Gist。

### B站限流或分片扩展失败

`BilibiliService.get_all_videos_parallel()` 如果返回空列表，主流程记录 `分片扩展失败(可能被限流), 跳过本次检测`，然后按未发现新内容调频。

处理：

- 等下一个检查周期。
- 查看 `yt-dlp` stderr。
- 检查 cookies 是否过期。
- 降低手动重试频率，避免继续触发限流。

### 通知失败

`NotificationService.notify_new_videos()` 返回 `False` 时主流程记录严重错误，但不会回滚 URL 状态或 WGMM 决策。

检查：

- `BARK_DEVICE_KEY`
- `BARK_APP_TITLE`
- Bark 服务可达性

## 调试命令

```bash
# 查看 WGMM 配置
cat data/wgmm_config.json | python -m json.tool

# 查看调频日志
grep "WGMM调频" urls.log | tail -20

# 查看历史数据量
wc -l data/mtime.txt data/miss_history.txt

# 只验证 WGMM 调频
python monitor.py --wgmm-core-only

# 跑完整检测链但不写 WGMM 配置和不推送新视频通知
python monitor.py --dev
```

## 常见修改位置

- 调整默认权重或 sigma：`wgmm_monitor/wgmm/constants.py`
- 修改时间特征：`wgmm_monitor/wgmm/features.py`
- 修改学习逻辑：`wgmm_monitor/wgmm/learning.py`
- 修改得分计算：`wgmm_monitor/wgmm/scoring.py`
- 修改调频决策：`wgmm_monitor/wgmm/scheduler.py`
- 修改检测流程：`wgmm_monitor/services/monitor.py`
- 修改 `yt-dlp` 参数：`wgmm_monitor/services/bilibili.py`
- 修改持久化格式：`wgmm_monitor/stores/`

## 提交流程

```bash
source .venv/bin/activate
ruff check monitor.py wgmm_monitor tests
ruff format --check monitor.py wgmm_monitor tests
python -m unittest discover -s tests
python -m coverage run -m unittest discover -s tests && python -m coverage report
git status
git diff
git add <files>
git commit -m "docs: sync architecture docs with modules"
```

提交消息使用 Conventional Commits，description 使用英文。

## 相关文档

- [README.md](../README.md)
- [README_CN.md](../README_CN.md)
- [CONTRIBUTING.md](../CONTRIBUTING.md)
- [docs/code_logic_flow.md](code_logic_flow.md)
- [docs/code-reference.md](code-reference.md)
- [docs/wgmm-algorithm.md](wgmm-algorithm.md)
- [docs/wgmm-config-params.md](wgmm-config-params.md)
