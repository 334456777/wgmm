# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

这是一个基于加权高斯混合模型（WGMM）的B站视频智能监控系统，使用机器学习算法自适应调整监控频率，在保证及时性的同时节省 60-80% 的网络请求。

## 开发命令

### 基本运行

**注意：** 项目文件夹内已包含 `.venv` 虚拟环境，所有依赖已安装，建议使用虚拟环境运行。

```bash
# 激活虚拟环境（首次运行前需要）
source .venv/bin/activate

# 虚拟环境中运行（推荐）
python monitor.py

# 开发模式：运行单次检查后立即退出，不修改配置文件
python monitor.py --dev
# 或
python monitor.py -d

# 不使用虚拟环境直接运行（需要系统已安装依赖）
python3 monitor.py
```

### 代码质量

**重要：每次修改 Python 代码后，必须运行以下命令确保代码质量符合规范。**

```bash
# 激活虚拟环境（如果未激活）
source .venv/bin/activate

# 1. 使用 ruff 检查 Python 代码质量
ruff check monitor.py

# 2. 使用 ruff 格式化 Python 代码
ruff format monitor.py

# 3. 如果 ruff check 发现问题，尝试自动修复
ruff check --fix monitor.py
```

**代码质量检查标准：**
- ✅ `ruff check` 必须通过（All checks passed!）
- ✅ `ruff format` 必须通过（already formatted 或格式化成功）
- ❌ 任何检查失败都不应该提交代码

**适用范围：**
- ruff 只检查和格式化 `.py` 文件（Python 代码）
- Markdown 文档（如 CLAUDE.md、README.md）不需要 ruff 检查

**配置管理：**
- ❌ **禁止修改** `pyproject.toml` 中的 ruff 配置
- ruff 配置（包括 ignore 规则、line-length、缩进风格等）是项目强制标准
- 如需调整代码风格，必须修改代码以符合现有配置，而非修改配置文件
- 项目使用 tab 缩进、line-length=92、遵循 Google 风格的 docstring

**常见问题：**
- 如果检查失败，查看错误信息并根据提示修复
- 项目使用 tab 缩进，line-length=92
- docstring 和注释使用英文标点符号（避免全角符号）
- 详见 `pyproject.toml` 配置文件

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

### 代码理解提示

**重要：** `monitor.py` 中的所有函数和类都包含详细的中文注释（docstring 和行内注释）。

当你需要理解某个函数或变量的用途时，可以：
1. **使用 Grep 工具搜索**函数名或关键词，快速定位相关代码
2. **阅读函数的 docstring**，其中包含算法原理、参数说明和返回值描述
3. **查看行内注释**，了解复杂逻辑的实现细节
4. **参考本文档的"关键方法分类"**，快速了解函数的整体功能

例如，搜索 `def adjust_check_frequency` 可以找到 WGMM 算法的主函数，其 docstring 详细说明了算法的 6 个步骤。

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

**重要：** 本存储库强制遵循 Conventional Commits 规范，所有提交都必须符合此格式。

查看提交历史可以验证规范执行情况：
```bash
git log --oneline -20
```

### 基本格式

```
<type>: <description>
```

### 提交类型（Type）

**常用类型：**
- `fix:` - Bug 修复
- `feat:` - 新功能
- `docs:` - 文档更新（注释、README、配置文件说明等）
- `refactor:` - 代码重构（不改变功能）
- `style:` - 代码风格调整（不影响代码运行的格式化）
- `test:` - 添加或修改测试
- `chore:` - 构建、工具、依赖更新等杂项

### 提交说明（Description）

- 使用中文书写
- 简洁描述做了什么
- 不超过 50 个字符
- 首字母不大写，结尾不加标点

**单行示例：**
- `fix: 修改环境变量缺失提示信息，简化错误输出`
- `docs: 添加WGMM算法FAQ到README，解释3天间隔的数学原理`
- `refactor: 简化代码格式，合并多行表达式为单行`

### 多行提交消息格式

对于复杂的提交，建议使用多行格式：

```bash
git commit -m "$(cat <<'EOF'
<type>: <简短描述（不超过50字）>

<详细说明（可选）>

- 要点1
- 要点2

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>
EOF
)"
```

**实际示例：**
```bash
git commit -m "$(cat <<'EOF'
docs: 为 monitor.py 添加完整的中文注释，优化代码可读性

- 为所有函数添加 docstring 和行内注释
- 详细说明 WGMM 算法的数学原理和实现细节
- 标注三层检测架构的工作流程
- 在 CLAUDE.md 中添加代码理解提示章节

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>
EOF
)"
```

### 创建提交的步骤

**强制要求：提交前必须通过代码质量检查！**

```bash
# 1. 代码质量检查（必须通过）
source .venv/bin/activate
ruff check monitor.py        # 必须显示 "All checks passed!"
ruff format monitor.py       # 必须显示 "already formatted" 或格式化成功

# 2. 查看修改
git status
git diff

# 3. 添加文件
git add <文件名>

# 4. 创建提交（单行）
git commit -m "fix: 修复XXX问题"

# 5. 创建提交（多行）
git commit -m "$(cat <<'EOF'
docs: 添加详细注释

- 为核心函数添加文档字符串
- 说明算法实现细节
EOF
)"

# 6. 推送到远程
git push
```

**完整的提交流程：**
```bash
# 一键检查并提交的完整示例
source .venv/bin/activate && \
ruff check monitor.py && \
ruff format monitor.py && \
git add monitor.py && \
git commit -m "fix: 修复XXX问题" && \
git push
```

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

## 算法原理文档

### WGMM 算法常见问题

README.md 的结尾包含详细的 FAQ 部分，解答了关于 WGMM 算法的常见问题：

- **Q1: 为什么算法会形成3天的检查间隔？是硬编码的吗？**
  - 详细解释了算法通过数学计算自然涌现出3天间隔的原理
  - 包含星期维度编码、高斯核相似性计算、数学验证
  - 说明这是从数据中学习模式，而非预设规则

- **Q2: WGMM算法的核心参数有哪些？如何调优？**
  - 列出所有核心参数配置
  - 针对不同UP主类型的优化策略（高频/中频/低频）

- **Q3: 如何查看算法当前的学习状态？**
- **Q4: 算法需要多少历史数据才能开始有效预测？**
- **Q5: 如果UP主改变发布习惯，算法多久能适应？**

当用户询问算法原理、参数调优或为什么系统会以特定频率检查时，可以引导他们查看 README.md 的 FAQ 部分。
