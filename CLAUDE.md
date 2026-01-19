# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

这是一个基于加权高斯混合模型（WGMM）的B站视频智能监控系统，使用机器学习算法自适应调整监控频率，在保证及时性的同时节省 60-80% 的网络请求。

## 开发命令

### 基本运行

```bash
# 正常运行（生产环境）
python3 monitor.py

# 开发模式：运行单次检查后立即退出，不修改配置文件
python3 monitor.py --dev
# 或
python3 monitor.py -d

# 虚拟环境中运行
source .venv/bin/activate
python monitor.py
```

### 代码质量

```bash
# 使用 ruff 进行代码格式化
ruff format monitor.py

# 使用 ruff 进行 linting
ruff check monitor.py

# 自动修复 ruff 发现的问题
ruff check --fix monitor.py
```

### systemd 服务管理

```bash
# 查看服务状态
sudo systemctl status video-monitor

# 启动/停止/重启服务
sudo systemctl start video-monitor
sudo systemctl stop video-monitor
sudo systemctl restart video-monitor

# 查看服务日志
sudo journalctl -u video-monitor -f
```

## 核心架构

### 主要组件：VideoMonitor 类

`monitor.py` (约1900行) 是整个系统的核心，包含完整的监控逻辑和 WGMM 算法实现。

#### 关键方法分类

**初始化与配置**
- `__init__()`: 初始化监控系统，加载环境变量和配置
- `load_env_file()`: 加载 .env 文件中的环境变量
- `_load_wgmm_config()`: 加载 WGMM 算法配置（从 wgmm_config.json）
- `_save_wgmm_config()`: 保存 WGMM 算法配置

**WGMM 核心算法**
- `adjust_check_frequency()`: WGMM 算法主函数，根据历史数据计算下次检查间隔
  - 使用多维度时间特征编码（日、周、月周、年月）
  - 计算高斯核相似性和指数时间衰减权重
  - 自适应调整 lambda 参数（遗忘速度）
  - 动态学习维度权重
- `generate_mtime_file()`: 生成历史发布时间戳文件（首次运行时）
- `_calculate_adaptive_lambda()`: 自适应计算 lambda 参数
- `learn_dimension_weights()`: 学习各维度权重

**三层检测架构**
- `check_potential_new_parts()`: 第一层 - 分片预检查
- `quick_precheck()`: 第二层 - 快速ID检查
- `run_monitor()`: 第三层 - 完整深度检查（主监控循环）

**数据管理**
- `sync_urls_from_gist()`: 从 GitHub Gist 同步已备份的 URL 列表
- `load_known_urls()`: 加载本地已知 URL（local_known.txt）
- `save_known_urls()`: 保存本地已知 URL
- `get_video_upload_time()`: 获取视频上传时间戳

**日志与通知**
- `send_bark_push()`: 发送 Bark 推送通知
- `notify_new_videos()`: 通知发现新视频
- `notify_critical_error()`: 通知严重错误（会发送 Bark 通知）
- `log_message()`: 统一日志记录接口
- `log_critical_error()`: 记录严重错误到 critical_errors.log

**工具方法**
- `run_yt_dlp()`: 执行 yt-dlp 命令并处理输出
- `get_video_parts()`: 获取视频分片信息
- `get_all_videos_parallel()`: 并行获取视频信息
- `cleanup()`: 清理临时文件

### WGMM 算法核心概念

**时间特征编码**
- 日周期：使用 sin/cos 将小时数转换为周期性特征
- 周周期：处理星期几的模式
- 月周周期：每月中的第几个星期
- 年月周期：月份特征

**关键参数**
- `SIGMA` (0.8): 高斯核标准差，控制时间相似性容忍度
- `LAMBDA` (0.0001): 指数衰减率，控制历史记忆遗忘速度
- `DEFAULT_INTERVAL` (3600秒): 基础轮询间隔
- `MIN_INTERVAL` (300秒): 最小检查间隔，防止过度请求

**低活跃期调整**
- 根据小时和星期维度的活跃度线性调整检查频率
- 活跃度为0时检查间隔延长4倍
- 最大间隔可达30天（长期停更期）

## 文件结构

### 必需配置文件（手动创建）

- `.env`: 环境变量配置（GITHUB_TOKEN, BARK_DEVICE_KEY, GIST_ID, BILIBILI_UID）
- `cookies.txt`: B站登录凭证（从浏览器开发者工具导出）

### 自动生成的数据文件

- `local_known.txt`: 本地已知URL列表（双层URL管理的核心）
- `wgmm_config.json`: WGMM算法状态持久化
- `mtime.txt`: 历史发布时间戳（算法训练数据）
- `miss_history.txt`: 检测失败历史记录（负面事件数据）
- `urls.log`: 主运行日志（INFO/WARNING/ERROR级别）
- `critical_errors.log`: 严重错误专用日志（CRITICAL级别）

### 配置文件

- `requirements.txt`: Python依赖（requests, numpy）
- `pyproject.toml`: Ruff配置（line-length=92, 使用tab缩进）
- `video-monitor.service`: systemd服务配置文件

## 开发模式

使用 `--dev` 标志可以在沙盒环境中测试系统：

- 不修改配置文件（is_manual_run 保持为 True）
- 不写入 wgmm_config.json
- 使用内存中的 sandbox_* 变量
- 运行单次检查后立即退出
- 适合快速验证代码逻辑和算法计算

## 双层URL管理机制

系统维护两个URL集合：

1. **`memory_urls`**: 从 GitHub Gist 读取的已备份视频URL列表
2. **`known_urls`**: 包含所有已检测到的视频（memory_urls + 本地检测到但未同步的）

只有 `truly_new_urls`（不在 known_urls 中）才会触发通知。这种设计防止了 Gist 更新延迟导致的重复通知。

## Commit 规范

遵循 Conventional Commits 规范：

```
<type>: <description>
```

**常用类型：**
- `fix:` - Bug 修复
- `refactor:` - 代码重构（不改变功能）

**示例：**
- `fix: 修改环境变量缺失提示信息，简化错误输出`
- `refactor: 简化代码格式，合并多行表达式为单行`

## 重要注意事项

### 错误处理策略

- **普通错误**: 记录到日志，可选发送 Bark 通知
- **严重错误 (CRITICAL)**: 记录到 critical_errors.log，自动发送 Bark 通知
- **mtime.txt 生成失败**: 经过3次尝试仍失败时会触发严重错误通知

### 性能优化

- 使用三层检测架构避免不必要的完整扫描
- 并行处理视频信息获取（ThreadPoolExecutor）
- 日志文件自动大小限制（urls.log: 1000行，critical_errors.log: 500行）
- WGMM 算法计算复杂度 O(n)，典型内存占用 < 1MB

### 安全相关

- `.env` 和 `cookies.txt` 已被 `.gitignore` 排除
- 敏感文件不纳入版本控制
- systemd 服务配置使用安全沙盒设置（NoNewPrivileges, PrivateTmp, ProtectSystem）

## 调试技巧

### 查看日志

```bash
# 查看主日志
tail -f urls.log

# 查看严重错误日志
cat critical_errors.log

# 使用 systemd 查看服务日志
sudo journalctl -u video-monitor -n 100
```

### 检查算法状态

查看 `wgmm_config.json` 了解当前算法参数：
```bash
cat wgmm_config.json
```

### 测试环境

在开发模式下测试系统：
```bash
python3 monitor.py --dev
```

这将运行一次完整的检查流程，但不修改任何配置文件，适合反复测试。
