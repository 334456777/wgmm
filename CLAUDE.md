# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

这是一个基于加权高斯混合模型（WGMM）的B站视频智能监控系统，使用机器学习算法自适应调整监控频率，在保证及时性的同时节省 60-80% 的网络请求。

**核心设计哲学**:
- **Simple is Better（简单即美）**: 保持单体架构，避免过度模块化
- **专注核心价值**: WGMM 是监控工具，而非预测系统
- **实用主义**: 解决实际问题，而非追逐技术热点
- **稳定可靠**: 7×24 小时无人值守运行

**重要架构决策**:
- **ADR 001**: 保持 Python 实现，不迁移到 Go
- **ADR 002**: 不引入 X-Algorithm 推荐系统技术
- **ADR 003**: 采用单体架构，拒绝 Pipeline 模块化重构

> 在提出重大架构变更前，请务必阅读 `docs/adr/` 目录中的架构决策记录。

## 快速开始

### 基本运行

**注意：** 项目文件夹内已包含 `.venv` 虚拟环境，所有依赖已安装。

```bash
# 激活虚拟环境
source .venv/bin/activate

# 正常运行
python monitor.py

# 开发模式：运行单次检查后立即退出，不修改配置文件
python monitor.py --dev
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

## 文件结构

### 核心文件

- **`monitor.py`**: 主程序（约2200行），包含完整的监控逻辑和 WGMM 算法实现
- **`requirements.txt`**: Python 依赖包清单
- **`pyproject.toml`**: Ruff 代码质量检查配置
- **`video-monitor.service`**: systemd 系统服务配置
- **`README.md`**: 用户文档，包含算法原理、FAQ、使用指南
- **`CONTRIBUTING.md`**: 贡献指南

### 必需配置文件（手动创建）

- **`data/.env`**: 环境变量配置（GITHUB_TOKEN, BARK_DEVICE_KEY, GIST_ID, BILIBILI_UID）
- **`data/cookies.txt`**: B站登录凭证

### 自动生成的数据文件

- **`data/local_known.txt`**: 本地已知URL列表
- **`data/wgmm_config.json`**: WGMM算法状态持久化
- **`data/mtime.txt`**: 历史发布时间戳（算法训练数据）
- **`data/miss_history.txt`**: 检测失败历史记录
- **`urls.log`**: 主运行日志
- **`critical_errors.log`**: 严重错误专用日志

## 文档导航

> 详细的技术文档、算法原理、代码参考等已移至 `docs/` 目录。本文件仅保留最核心的快速参考。

### 用户文档

- **`README.md`**: 用户使用指南、算法原理、FAQ

### 开发文档（docs/ 目录）

#### 核心开发指南
- **`docs/development-guide.md`**: 完整开发指南
  - 代码质量检查
  - 调试技巧
  - 维护建议
  - 故障排查
  - 性能监控

#### 技术参考
- **`docs/wgmm-algorithm.md`**: WGMM 算法详解
  - 数学原理
  - 参数调优
  - 代码修改场景

- **`docs/wgmm-config-params.md`**: wgmm_config.json 参数说明
  - 各参数含义与默认值
  - 自适应学习逻辑
  - 参数关系总览

- **`docs/wgmm-universality-analysis.md`**: WGMM 算法普适性研究
  - 八种 UP 主发布模式分析
  - 算法适用边界与固有局限
  - 普适性结论

- **`docs/code-logic-flow.md`**: 系统架构流程
  - 主监控循环
  - 三层检测架构
  - 数据流向

- **`docs/code-reference.md`**: 代码参考
  - VideoMonitor 类方法分类
  - 性能优化要点
  - 代码理解提示

#### 架构决策记录（ADR）
- **`docs/adr/001-keep-python-implementation.md`**: 保持 Python 实现的决策
- **`docs/adr/002-do-not-adopt-x-algorithm-techniques.md`**: 不引入推荐系统技术的决策
- **`docs/adr/003-avoid-large-refactoring.md`**: 采用单体架构的决策

### 文档使用建议

**快速上手**:
1. 先阅读 `README.md` 了解项目背景和用户视角
2. 阅读 `docs/development-guide.md` 了解开发流程

**深入理解**:
3. 阅读 `docs/wgmm-algorithm.md` 理解算法原理
4. 阅读 `docs/code-logic-flow.md` 理解系统架构
5. 参考 `docs/code-reference.md` 查阅具体代码

**架构变更**:
6. 在提出重大变更前，必须先阅读 `docs/adr/` 中的所有文档
7. 参考现有 ADR 格式，创建新的架构决策记录

## 开发模式

使用 `--dev` 标志可以在沙盒环境中测试系统：

- 不修改配置文件（is_manual_run 保持为 True）
- 不写入 wgmm_config.json
- 使用内存中的 sandbox_* 变量
- 运行单次检查后立即退出
- 适合快速验证代码逻辑和算法计算

**示例**:
```bash
# 运行单次检查，不修改配置
python monitor.py --dev

# 查看算法当前参数
cat data/wgmm_config.json | python -m json.tool
```

## 双层 URL 管理机制

系统维护两个URL集合：

1. **`memory_urls`**: 从 GitHub Gist 读取的已备份视频URL列表
2. **`known_urls`**: 包含所有已检测到的视频（memory_urls + 本地检测到但未同步的）

只有 `truly_new_urls`（不在 known_urls 中）才会触发通知。这种设计防止了 Gist 更新延迟导致的重复通知。

**数据流向**:
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

## Commit 规范

**重要：** 本存储库强制遵循 Conventional Commits 规范，所有提交都必须符合此格式。

### 基本格式

```
<type>: <description>
```

### 提交类型（Type）

**常用类型：**
- `fix:` - Bug 修复
- `feat:` - 新功能
- `docs:` - 文档更新
- `refactor:` - 代码重构
- `style:` - 代码风格调整
- `test:` - 添加或修改测试
- `chore:` - 构建、工具、依赖更新等杂项

### 提交说明（Description）

- **使用英文书写**
- 简洁描述做了什么
- 不超过 50 个字符
- 首字母不大写，结尾不加标点

**单行示例：**
- `fix: simplify missing env var error message`
- `docs: add WGMM algorithm FAQ explaining 3-day interval math`
- `refactor: merge multi-line expressions into single lines`

### 多行提交消息格式

```bash
git commit -m "$(cat <<'EOF'
<type>: <short description (under 50 chars)>

<详细说明（可选）>

- 要点1
- 要点2

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>
EOF
)"
```

### 提交前检查清单

```bash
# 1. 代码质量检查（必须通过）
source .venv/bin/activate
ruff check monitor.py        # 必须显示 "All checks passed!"
ruff format monitor.py       # 必须显示 "already formatted" 或格式化成功

# 2. 查看修改
git status
git diff

# 3. 检查是否需要更新文档
# - 新功能？→ 更新 README.md
# - 架构变更？→ 更新相关文档
# - 新的架构决策？→ 创建新的 ADR 文件

# 4. 添加文件（包括文档）
git add <文件名>

# 5. 创建提交
git commit -m "feat: 添加XXX功能"

# 6. 推送到远程
git push
```

> 详细的提交流程和文档更新要求请参考 `docs/development-guide.md`。

## 架构决策原则

### 明确拒绝的改进方向

根据 ADR 002，以下改进方向已被明确拒绝：

- ❌ **Pipeline 模块化重构**: 破坏简洁性，维护成本暴增
- ❌ **两阶段预测架构**: 数据量太小，无性能瓶颈
- ❌ **Transformer 时间序列编码**: 过度工程化，周期性模式不需要深度学习
- ❌ **多目标预测系统**: 不适用视频发布场景
- ❌ **分布式预测集群**: 无需横向扩展
- ❌ **复杂特征工程**: 当前四维时间特征已足够

### 欢迎的改进方向（低优先级）

- ✅ **预测准确度度量体系**: 添加准确率、召回率、F1 分数追踪
- ✅ **配置外部化**: 将硬编码参数移到配置文件
- ✅ **监控和告警**: 添加 Prometheus metrics

### 提出重大变更的流程

1. **在 Issue 中讨论** - 详细说明理由和数据，提供 ROI 分析
2. **获得共识** - 等待维护者和其他贡献者的反馈
3. **创建新的 ADR** - 记录决策理由和预期后果

> 详细的架构决策请阅读 `docs/adr/` 目录中的文档。

## 重要注意事项

### 代码质量检查

**强制要求：每次修改 Python 代码后必须运行 ruff 检查**

```bash
source .venv/bin/activate
ruff check monitor.py        # 必须通过
ruff format monitor.py       # 必须通过
```

**代码风格规范**:
- 使用 **tab 缩进**（而非空格）
- 行长度限制：**92 字符**
- 遵循 Google 风格的 docstring
- 所有函数必须包含 docstring

### 错误处理策略

- **普通错误**: 记录到日志，可选发送 Bark 通知
- **严重错误 (CRITICAL)**: 记录到 critical_errors.log，自动发送 Bark 通知

### 性能指标

系统已高度优化，典型性能指标：

| 指标 | 典型值 | 说明 |
|------|--------|------|
| WGMM 算法计算 | ~10ms | NumPy 向量化计算 |
| 三层检测 | ~2s | 主要耗时在 yt-dlp I/O |
| 内存占用 | <10MB | 非常高效 |
| CPU 使用率 | <1% | 大部分时间在睡眠等待 |
| 网络请求节省率 | 60-80% | 相比固定1小时间隔 |

### 安全相关

- `.env` 和 `cookies.txt` 已被 `.gitignore` 排除
- 敏感文件不纳入版本控制
- systemd 服务配置使用安全沙盒设置

## 代码理解提示

**重要：** `monitor.py` 中的所有函数和类都包含详细的中文注释（docstring 和行内注释）。

当你需要理解某个函数或变量的用途时，可以：
1. **使用 Grep 工具搜索**函数名或关键词，快速定位相关代码
2. **阅读函数的 docstring**，其中包含算法原理、参数说明和返回值描述
3. **查看行内注释**，了解复杂逻辑的实现细节

例如：
- 搜索 `def adjust_check_frequency` 可以找到 WGMM 算法的主函数
- 搜索 `def check_potential_new_parts` 可以找到分片预检查逻辑
- 搜索 `def quick_precheck` 可以找到快速ID检查逻辑

## 核心架构速览

### VideoMonitor 类关键方法

`monitor.py` 是整个系统的核心，包含完整监控逻辑和 WGMM 算法实现。

**初始化与配置**
- `__init__()`, `load_env_file()`, `_load_wgmm_config()`, `_save_wgmm_config()`

**WGMM 核心算法**
- `adjust_check_frequency()`: WGMM 算法主函数
- `generate_mtime_file()`: 生成历史发布时间戳文件
- `_calculate_adaptive_lambda()`: 自适应计算 lambda 参数
- `learn_dimension_weights()`: 学习各维度权重

**三层检测架构**
- `check_potential_new_parts()`: 第一层 - 分片预检查
- `quick_precheck()`: 第二层 - 快速ID检查
- `run_monitor()`: 第三层 - 完整深度检查（主监控循环）

**数据管理**
- `sync_urls_from_gist()`: 从 GitHub Gist 同步已备份的 URL 列表
- `load_known_urls()`: 加载本地已知 URL
- `save_known_urls()`: 保存本地已知 URL

**日志与通知**
- `send_bark_push()`: 发送 Bark 推送通知
- `notify_new_videos()`: 通知发现新视频
- `notify_critical_error()`: 通知严重错误

### 主监控循环

```
run_monitor() 主循环
├── sync_urls_from_gist()       # 从 GitHub Gist 同步已知 URL
├── check_potential_new_parts() # 第一层：分片预检查
├── quick_precheck()            # 第二层：快速 ID 检查
│   └── 如果有变化 → 触发完整检查
├── get_all_videos_parallel()   # 第三层：完整深度检查
├── notify_new_videos()         # 发送通知
└── adjust_check_frequency()    # WGMM 计算下次检查时间
```

### WGMM 算法流程

```
adjust_check_frequency()
├── 加载正向事件(mtime.txt)和负向事件(miss_history.txt)
├── filter_outliers()           # 过滤异常值
├── prune_old_data()            # 剪枝低权重历史数据
├── _calculate_adaptive_lambda() # 自适应计算遗忘速度
├── learn_dimension_weights()   # 学习各维度重要性
├── learn_adaptive_sigmas()      # 学习时间容忍度
├── _calculate_point_score()    # 计算当前时间发布概率
├── _batch_calculate_scores()   # 扫描未来15天找峰值
└── 映射得分 → 检查间隔
```

## 快速参考

### 常见代码修改场景

**调整预测激进程度**:
```python
# 更激进：更频繁检查
mapping_curve = 2.0  # → 改为 3.0
peak_advance_minutes = 5  # → 改为 10

# 更保守：减少请求
mapping_curve = 2.0  # → 改为 1.5
```

**修改时间容忍度**:
```python
# 更严格
sigmas["day"] = 0.8  # → 改为 0.5

# 更宽松
sigmas["week"] = 1.0  # → 改为 1.5
```

**调整记忆速度**:
```python
# 快速适应
lambda_base = 0.0001  # → 改为 0.0002

# 长期记忆
lambda_base = 0.0001  # → 改为 0.00005
```

### 查看日志

```bash
# 查看主日志
tail -f urls.log

# 查看严重错误日志
cat critical_errors.log

# 使用 systemd 查看服务日志
sudo journalctl -u video-monitor -n 100
```

### 故障排查

当系统出现问题时，按以下顺序排查：

1. **检查服务状态**: `sudo systemctl status video-monitor`
2. **查看日志**: `tail -100 urls.log` 或 `cat critical_errors.log`
3. **验证配置**: 检查 `.env` 和 `cookies.txt`
4. **测试网络连接**: `curl -I https://www.bilibili.com`
5. **重启服务**: `sudo systemctl restart video-monitor`

> 详细的故障排查指南请参考 `docs/development-guide.md`。

## 获取帮助

如果遇到问题：

1. **查看文档**
   - README.md: 用户文档和 FAQ
   - docs/development-guide.md: 开发指南
   - docs/wgmm-algorithm.md: 算法详解
   - docs/adr/: 架构决策记录

2. **查看日志**
   - urls.log: 主运行日志
   - critical_errors.log: 严重错误日志

3. **查看代码注释**
   - 所有函数都有详细的中文 docstring
   - 复杂逻辑有行内注释说明

4. **提交 Issue**
   - 详细描述问题
   - 提供复现步骤
   - 附上相关日志
