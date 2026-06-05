# WGMM 智能视频监控系统

WGMM 是一个 B站视频监控工具，使用加权高斯混合模型根据历史发布时间自适应调整检查间隔。对外入口仍然是 `python monitor.py`，当前实现已经拆分为 `wgmm_monitor/` 下的小型模块化单体应用。

项目目标是实用监控：及时发现新视频和新分片，同时减少无效网络请求。

## 快速开始

### 运行要求

- Python 3.14+
- 项目自带 `.venv` 虚拟环境
- `yt-dlp` 可执行文件在 `PATH` 中
- B站 cookies 保存到 `data/cookies.txt`
- GitHub Gist 和 Bark 配置写入 `data/.env`

检查 `yt-dlp`：

```bash
which yt-dlp
yt-dlp --version
```

### 配置

```bash
cp data/.env.example data/.env
nano data/.env
```

必需变量：

```bash
GITHUB_TOKEN=your_github_token
BARK_DEVICE_KEY=your_bark_key
GIST_ID=your_gist_id
BILIBILI_UID=your_bilibili_uid
BARK_APP_TITLE=your_app_title
```

手动创建 `data/cookies.txt`，使用 Netscape cookie 格式。程序启动时会检查该文件是否存在且非空。

### 运行

```bash
source .venv/bin/activate

python monitor.py
python monitor.py --dev
python monitor.py --wgmm-core-only
```

模式说明：

- `python monitor.py`：生产循环，等待 `next_check_time`，执行一次监控，再进入下一轮。
- `python monitor.py --dev`：执行一次完整检测链，不写 WGMM 配置，不发送新视频通知。
- `python monitor.py --wgmm-core-only`：只执行一次 WGMM 调频，跳过 B站检测流程。

### systemd

```bash
sudo systemctl status video-monitor
sudo systemctl start video-monitor
sudo systemctl stop video-monitor
sudo systemctl restart video-monitor
sudo journalctl -u video-monitor -f
```

## 文件结构

```text
wgmm/
├── monitor.py                    # 入口壳: wgmm_monitor.cli.main()
├── wgmm_monitor/
│   ├── cli.py                    # 参数解析和模式分发
│   ├── app.py                    # 运行期依赖装配
│   ├── config.py                 # data/.env 加载
│   ├── models.py                 # RuntimePaths/AppConfig/WgmmConfig/结果模型
│   ├── runtime_logger.py         # 控制台、urls.log、critical_errors.log
│   ├── clients/
│   │   ├── bark.py               # Bark HTTP 客户端
│   │   ├── gist.py               # GitHub Gist API 客户端
│   │   ├── ytdlp.py              # yt-dlp 子进程封装
│   │   └── bilibili_api.py       # B站 view API 客户端（真实 ctime）
│   ├── services/
│   │   ├── monitor.py            # 三层检测主流程
│   │   ├── bilibili.py           # B站和 yt-dlp 业务
│   │   ├── frequency.py          # WGMM 调频编排
│   │   ├── history.py            # 投稿时间戳生成与维护（view API 取真实 ctime）
│   │   └── notification.py       # 通知内容封装
│   ├── stores/
│   │   ├── config_store.py       # data/wgmm_config.json
│   │   ├── history_store.py      # data/mtime.txt 与 miss_history.txt
│   │   └── url_store.py          # data/local_known.txt
│   ├── wgmm/
│   │   ├── constants.py          # 算法默认参数
│   │   ├── features.py           # 时间特征提取
│   │   ├── learning.py           # lambda/权重/sigma/周期发现
│   │   ├── scheduler.py          # 下一次检查时间决策
│   │   └── scoring.py            # 单点和批量得分
│   └── utils/
├── tests/                        # unittest 测试
├── docs/
├── requirements.txt
├── pyproject.toml
└── video-monitor.service
```

运行时文件：

```text
data/.env                  # 手动创建，已忽略
data/cookies.txt           # 手动创建，已忽略
data/local_known.txt       # 本地 URL 状态
data/wgmm_config.json      # WGMM 状态
data/mtime.txt             # 正向上传历史
data/miss_history.txt      # 负向检查历史
urls.log                   # 主日志
critical_errors.log        # 严重错误日志
```

## 监控流程

系统维护两层 URL 状态：

- `memory_urls`：从 GitHub Gist `urls.txt` 读取的云端已知 URL。
- `known_urls`：从 `data/local_known.txt` 读取并合并 `memory_urls` 后的完整本地状态。

只有不在这两层中的 URL 才会被视为真正的新内容。

```text
GitHub Gist urls.txt
    -> memory_urls
        + data/local_known.txt
    -> known_urls
    -> 与当前 B站扫描结果对比
    -> truly new URLs
    -> Bark 推送 + Gist new.txt 更新
```

主流程位于 `wgmm_monitor/services/monitor.py`：

1. 从 Gist 同步 URL。
2. 执行多分片预检查。
3. 执行最新视频 ID 快速检查。
4. 任一预检查发现变化时，抓取完整视频列表并展开分片。
5. 为真正新增 URL 保存真实投稿时间戳（通过 B站 view API 的 `ctime`，而非可被 UP 主伪造的 `pubdate`）。
6. 发送 Bark 推送并写入 Gist `new.txt`。
7. 调用 WGMM 计算下一次检查时间。

## WGMM 摘要

纯算法层在 `wgmm_monitor/wgmm/`：

- `features.py`：用 sin/cos 编码日、周、月内周、年内月，以及可选 `custom_N` 周期。
- `learning.py`：异常值过滤、自适应 lambda/sigma/权重学习、自相关周期发现。
- `scoring.py`：正向和负向事件的加权高斯得分。
- `scheduler.py`：扫描未来 15 天，将相对得分映射为检查间隔，并根据 `yt-dlp` 实际耗时提前峰值检查。

详见 [docs/wgmm-algorithm.md](docs/wgmm-algorithm.md) 和 [docs/wgmm-config-params.md](docs/wgmm-config-params.md)。

## 开发命令

```bash
source .venv/bin/activate

ruff check monitor.py wgmm_monitor tests
ruff format monitor.py wgmm_monitor tests
python -m unittest discover -s tests
python monitor.py --wgmm-core-only
python monitor.py --dev
```

修改 Python 代码后运行 Ruff 和完整 unittest。`--wgmm-core-only` 用于隔离 WGMM 调频，`--dev` 用于跑完整检测链但避免写 WGMM 配置和发送新视频通知。

## 故障排查

常用检查：

```bash
source .venv/bin/activate
which yt-dlp
yt-dlp --version
ls -l data/cookies.txt
tail -100 urls.log
cat critical_errors.log
sudo journalctl -u video-monitor -n 100
```

常见情况：

- 环境变量缺失：启动时输出 `缺少必要的环境变量` 并退出。
- cookies 缺失或为空：启动时记录严重错误并退出。
- `yt-dlp` 不在 `PATH`：`YtDlpClient` 记录错误并返回失败结果，先检查 `which yt-dlp`。
- Gist 获取失败：本轮记录严重错误；如果没有基准 URL 数据，则跳过本次检查。
- B站限流或分片扩展失败：记录 warning，跳过本次检测，并按“未发现新内容”执行 WGMM 调频。
- 通知失败：记录失败，不阻断 URL 状态和调频流程。

## 文档

- [README.md](README.md)：英文用户说明
- [CONTRIBUTING.md](CONTRIBUTING.md)：贡献流程
- [docs/development-guide.md](docs/development-guide.md)：开发与故障排查
- [docs/code_logic_flow.md](docs/code_logic_flow.md)：当前架构流程
- [docs/code-reference.md](docs/code-reference.md)：模块参考
- [docs/wgmm-algorithm.md](docs/wgmm-algorithm.md)：算法说明
- [docs/wgmm-config-params.md](docs/wgmm-config-params.md)：配置字段说明
- [docs/wgmm-universality-analysis.md](docs/wgmm-universality-analysis.md)：普适性分析
- [docs/adr/002-do-not-adopt-x-algorithm-techniques.md](docs/adr/002-do-not-adopt-x-algorithm-techniques.md)
- [docs/adr/003-avoid-large-refactoring.md](docs/adr/003-avoid-large-refactoring.md)
- [docs/adr/004-fix-cascade-false-detection.md](docs/adr/004-fix-cascade-false-detection.md)

## 安全

- `data/.env` 和 `data/cookies.txt` 不进入版本控制。
- 不要提交 Gist Token、Bark Key、cookies 或包含敏感信息的日志。
- systemd 服务应使用项目提供的路径和沙盒设置。

## 许可证

MIT License
