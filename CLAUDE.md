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
- **ADR 001**: 保持 Python 实现，不迁移到 Go（见 `docs/adr/001-keep-python-implementation.md`）
- **ADR 002**: 不引入 X-Algorithm 推荐系统技术（见 `docs/adr/002-do-not-adopt-x-algorithm-techniques.md`）

在提出重大架构变更前，请务必阅读这些 ADR 文档和 `CONTRIBUTING.md`。

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

**代码风格规范（强制要求）：**
- 使用 **tab 缩进**（而非空格）
- 行长度限制：**92 字符**
- docstring 和注释使用英文标点符号（避免全角符号）
- 遵循 Google 风格的 docstring
- 所有函数必须包含 docstring 说明功能、参数和返回值

**配置管理：**
- ❌ **禁止修改** `pyproject.toml` 中的 ruff 配置
- ruff 配置（包括 ignore 规则、line-length、缩进风格等）是项目强制标准
- 如需调整代码风格，必须修改代码以符合现有配置，而非修改配置文件

**适用范围：**
- ruff 只检查和格式化 `.py` 文件（Python 代码）
- Markdown 文档（如 CLAUDE.md、README.md）不需要 ruff 检查

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

### WGMM 算法数学核心

理解这些数学原理对修改算法至关重要：

**1. 时间特征周期性编码** (monitor.py:1667-1727)
- **问题**：线性时间无法表示周期性（23:59 和 00:01 差距大）
- **解决**：使用 sin/cos 编码将时间映射到单位圆
  ```python
  day_sin = sin(2π × seconds_in_day / 86400)
  day_cos = cos(2π × seconds_in_day / 86400)
  ```
- **四个维度**：日周期（24小时）、周周期（7天）、月周（每月第几周）、年月（月份）

**2. 高斯核相似性** (monitor.py:1849-1864)
- **作用**：将时间距离转换为 0-1 的相似度得分
- **公式**：`similarity = exp(-dist² / (2σ²))`
- **参数**：σ 控制时间容忍度，越小越严格

**3. 指数时间衰减** (monitor.py:1838)
- **作用**：近期事件权重更大，远期事件逐渐"遗忘"
- **公式**：`weight = exp(-λ × age_hours)`
- **参数**：λ 控制遗忘速度，当前为 0.0001/小时

**4. 自适应学习机制**
- **动态维度权重** (monitor.py:1127-1193)：算法学习哪些时间维度重要
- **自适应 Lambda** (monitor.py:1053-1111)：根据发布方差调整遗忘速度
- **自适应 Sigma** (monitor.py:1195-1238)：根据数据离散度调整时间容忍度

### 常见代码修改场景

**场景 1：调整预测激进程度**
```python
# 更激进：更频繁检查（适合热点UP主）
mapping_curve = 2.0  # → 改为 3.0 或更高
peak_advance_minutes = 5  # → 改为 10（更早检查）

# 更保守：减少请求（适合冷门UP主）
mapping_curve = 2.0  # → 改为 1.5
```

**场景 2：修改时间容忍度**
```python
# 更严格：只匹配极相似时间
sigmas["day"] = 0.8  # → 改为 0.5

# 更宽松：容忍更大时间差异
sigmas["week"] = 1.0  # → 改为 1.5
```

**场景 3：调整记忆速度**
```python
# 快速适应：UP主经常改变习惯
lambda_base = 0.0001  # → 改为 0.0002

# 长期记忆：UP主习惯稳定
lambda_base = 0.0001  # → 改为 0.00005
```

### 性能优化要点

代码已经高度优化，修改时需注意：

**向量化计算** (monitor.py:1810-1894)
- 使用 NumPy 向量操作，避免 Python 循环
- `_batch_calculate_scores` 可一次计算数百个时间点
- 修改时保持向量化风格，避免引入显式循环

**批处理优化** (monitor.py:1896-1975)
- 峰值预测使用广播机制避免重复计算
- 所有历史事件一次性计算相似性
- 不要将批处理改为循环调用

**内存管理** (monitor.py:952-998)
- `prune_old_data` 自动删除权重过低的历史数据
- 保持 O(n) 时间复杂度，n 为历史事件数

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

### 系统架构关键流程

**主监控循环** (monitor.py:500-700)
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

**WGMM 预测流程** (monitor.py:786-1400)
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

**数据流向**
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

### 核心文件

- `monitor.py`: 主程序（约2200行，54个方法），包含完整的监控逻辑和 WGMM 算法实现
- `requirements.txt`: Python 依赖包清单（requests, numpy）
- `pyproject.toml`: Ruff 代码质量检查配置（line-length=92, tab缩进）
- `video-monitor.service`: systemd 系统服务配置文件
- `README.md`: 用户文档，包含算法原理、FAQ、使用指南
- `CONTRIBUTING.md`: 贡献指南，包含开发流程、代码质量标准、架构决策原则
- `CLAUDE.md`: 本文件，面向 AI 助手的开发指南

### 文档目录

- `docs/adr/`: 架构决策记录（Architecture Decision Records）
  - `001-keep-python-implementation.md`: 保持 Python 实现的决策
  - `002-do-not-adopt-x-algorithm-techniques.md`: 不引入推荐系统技术的决策

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

### Claude 辅助文件

为了帮助未来的 Claude 实例更快理解项目并提高工作效率，建议在需要时创建以下辅助文件：

- `.claude/`: Claude 专用配置目录（如果使用 Claude Code）
- 项目特定的速查文件（按需创建）

**文件组织原则**：
- 📋 **快速查找**: 将最常用的信息集中在 CLAUDE.md 顶层
- 🎯 **任务导向**: 按开发任务组织内容
- 💡 **示例驱动**: 提供丰富的代码示例和使用场景
- 🔄 **保持同步**: 代码修改时同步更新 CLAUDE.md

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

**文档更新要求**：
- 🔴 **强制**：`feat:`、`refactor:` 类型提交必须更新相关文档
- 🟡 **推荐**：`fix:` 类型提交建议更新相关说明
- 📝 **docs:** 类型提交专门用于文档更新，应与代码修改分开提交

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

# 3. 检查是否需要更新文档（重大修改必须更新）
# - 新功能？→ 更新 README.md
# - 架构变更？→ 更新 CLAUDE.md
# - 贡献流程变更？→ 更新 CONTRIBUTING.md
# - 新的架构决策？→ 创建新的 ADR 文件

# 4. 添加文件（包括文档）
git add <文件名>
git add README.md CLAUDE.md CONTRIBUTING.md  # 如果更新了文档

# 5. 创建提交（单行）
git commit -m "fix: 修复XXX问题"

# 6. 创建提交（多行）
git commit -m "$(cat <<'EOF'
docs: 添加详细注释

- 为核心函数添加文档字符串
- 说明算法实现细节
EOF
)"

# 7. 推送到远程
git push
```

**完整的提交流程：**
```bash
# 一键检查并提交的完整示例（包含文档检查）
source .venv/bin/activate && \
ruff check monitor.py && \
ruff format monitor.py && \
git add monitor.py README.md CLAUDE.md CONTRIBUTING.md && \
git commit -m "feat: 添加XXX功能

- 更新了 README.md 功能说明
- 更新了 CLAUDE.md 架构说明
- 更新了 CONTRIBUTING.md 贡献流程" && \
git push
```

**文档更新检查清单**：
在提交重大修改前，确认以下文档是否需要更新：

- [ ] `README.md`
  - [ ] 新功能的使用说明
  - [ ] 配置参数的变化
  - [ ] API 接口的变化
  - [ ] FAQ 部分的更新

- [ ] `CLAUDE.md`
  - [ ] 架构图和流程图
  - [ ] 核心组件说明
  - [ ] 开发命令的变化
  - [ ] 调试技巧的补充

- [ ] `CONTRIBUTING.md`
  - [ ] 新的开发流程
  - [ ] 代码质量标准的变化
  - [ ] 测试要求的变化
  - [ ] 架构决策的更新

- [ ] `docs/adr/`
  - [ ] 是否需要新的 ADR 文件
  - [ ] 现有 ADR 是否需要更新

## 架构决策原则

### 明确拒绝的改进方向

根据 ADR 002，以下改进方向已被明确拒绝：

- ❌ **Pipeline 模块化重构**
  - 理由：破坏简洁性，维护成本暴增
  - 当前单体架构对本项目复杂度是合适的

- ❌ **两阶段预测架构**
  - 理由：数据量太小（n<1000），无性能瓶颈
  - 当前 WGMM 算法性能已经足够（~10ms）

- ❌ **Transformer 时间序列编码**
  - 理由：过度工程化，周期性模式不需要深度学习
  - 当前 sin/cos 编码已完美解决问题

- ❌ **多目标预测系统**
  - 理由：不适用视频发布场景
  - 当前单一目标（是否有新视频）已足够

- ❌ **分布式预测集群**
  - 理由：无需横向扩展
  - 当前单机架构已满足需求

- ❌ **复杂特征工程**
  - 理由：当前四维时间特征已足够
  - 过多特征会增加复杂度而收益有限

### 欢迎的改进方向（低优先级）

以下改进方向是合理的，但优先级较低：

- ✅ **预测准确度度量体系**
  - 添加准确率、召回率、F1 分数追踪
  - **用于监控性能退化，而非驱动架构变更**
  - 实施成本：3-4天

- ✅ **配置外部化**
  - 将硬编码参数移到配置文件（YAML）
  - 支持热加载，便于调参
  - 实施成本：3-5天

- ✅ **监控和告警**
  - 添加 Prometheus metrics
  - 检测异常情况（如连续多次漏检）
  - 实施成本：1周

### 提出重大变更的流程

如果你认为需要违背现有 ADR 的决策，请按以下流程：

1. **在 Issue 中讨论**
   - 详细说明理由和数据
   - 提供 ROI 分析
   - 展示替代方案对比

2. **获得共识**
   - 等待维护者和其他贡献者的反馈
   - 准备好回应质疑

3. **创建新的 ADR**
   - 如果决定采纳，创建新的 ADR 文件
   - 记录决策理由和预期后果
   - 更新相关文档

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

## 项目维护建议

### 常规维护任务

**每日检查**（可选）:
```bash
# 查看系统状态
./monitor.sh status

# 查看最近的日志
./monitor.sh logs 50
```

**每周维护**（推荐）:
```bash
# 检查是否有严重错误
cat critical_errors.log

# 查看算法学习状态
cat wgmm_config.json

# 检查磁盘空间
df -h
```

**每月维护**（可选）:
```bash
# 更新 yt-dlp
source .venv/bin/activate
pip install -U yt-dlp

# 检查 cookies.txt 是否过期
# （如果检测失败，重新从浏览器导出）
```

### 故障排查清单

当系统出现问题时，按以下顺序排查：

1. **检查服务状态**
   ```bash
   ./monitor.sh status
   sudo systemctl status video-monitor  # 如果使用 systemd
   ```

2. **查看日志**
   ```bash
   # 主日志
   ./monitor.sh logs 100

   # 严重错误日志
   cat critical_errors.log

   # systemd 日志
   sudo journalctl -u video-monitor -n 100
   ```

3. **验证配置**
   ```bash
   # 检查必需文件
   ./monitor.sh test

   # 验证环境变量
   cat .env

   # 验证 cookies
   # （手动检查 cookies.txt 格式和内容）
   ```

4. **测试网络连接**
   ```bash
   # 测试 B站连接
   curl -I https://www.bilibili.com

   # 测试 GitHub API
   curl -I https://api.github.com
   ```

5. **重启服务**
   ```bash
   ./monitor.sh restart
   # 或
   sudo systemctl restart video-monitor
   ```

### 性能监控

系统已高度优化，典型性能指标：

| 指标 | 典型值 | 说明 |
|------|--------|------|
| WGMM 算法计算 | ~10ms | NumPy 向量化计算 |
| 三层检测 | ~2s | 主要耗时在 yt-dlp I/O |
| 内存占用 | <10MB | 非常高效 |
| CPU 使用率 | <1% | 大部分时间在睡眠等待 |
| 网络请求节省率 | 60-80% | 相比固定1小时间隔 |

如果发现性能明显下降，按以下步骤排查：

1. 检查历史数据量（mtime.txt 行数）
2. 检查网络延迟和带宽
3. 检查磁盘 I/O 性能
4. 检查系统资源（CPU、内存）

### 数据备份建议

虽然系统使用 GitHub Gist 作为云端备份，但仍建议定期备份本地数据：

```bash
# 创建备份目录
mkdir -p backups/$(date +%Y%m%d)

# 备份关键文件
cp local_known.txt backups/$(date +%Y%m%d)/
cp wgmm_config.json backups/$(date +%Y%m%d)/
cp mtime.txt backups/$(date +%Y%m%d)/
cp miss_history.txt backups/$(date +%Y%m%d)/

# 压缩备份
cd backups
tar czf wgmm_backup_$(date +%Y%m%d).tar.gz $(date +%Y%m%d)/
```

## 开发最佳实践

### 高效工作流程

**推荐的 Claude 辅助工作流程**：

1. **快速理解项目**（首次接触）
   ```bash
   # 1. 阅读快速参考
   cat QUICKREF.md

   # 2. 查看项目概述
   head -100 CLAUDE.md

   # 3. 理解核心架构
   grep "class VideoMonitor" monitor.py
   grep "def adjust_check_frequency" monitor.py
   ```

2. **处理开发任务**（日常开发）
   ```bash
   # 1. 查找任务指南
   grep "任务关键词" TASKS.md

   # 2. 查看相关代码
   # 使用 Grep 工具搜索函数名或关键词

   # 3. 参考类似修改
   git log --oneline -20
   ```

3. **快速定位问题**（调试时）
   ```bash
   # 1. 查看错误日志
   tail -100 critical_errors.log

   # 2. 搜索相关代码
   grep "错误关键词" monitor.py

   # 3. 查看相关函数的 docstring
   # (使用 Grep 搜索函数定义)
   ```

### 代码审查清单

在提交代码前，确认以下项目：

- [ ] `ruff check monitor.py` 通过
- [ ] `ruff format monitor.py` 通过
- [ ] 所有新增函数都有 Google 风格的 docstring
- [ ] 复杂逻辑有行内注释说明
- [ ] 数学公式有注释说明
- [ ] 开发模式测试通过：`python monitor.py --dev`
- [ ] 长期运行测试通过（至少7天）
- [ ] **重大修改后已更新相关文档**（README.md、CLAUDE.md、CONTRIBUTING.md）
- [ ] Commit 消息遵循 Conventional Commits 规范
- [ ] 不违背任何现有 ADR 决策

**文档更新要求**：
- 🔴 **强制**：重大修改（新功能、架构变更、参数调整）必须更新相关文档
- 🟡 **推荐**：小修改（Bug修复、代码优化）建议更新相关说明
- 📋 **需更新的文档**：
  - `README.md`：如果影响用户使用或功能说明
  - `CLAUDE.md`：如果影响开发流程或架构说明
  - `CONTRIBUTING.md`：如果影响贡献流程或代码质量标准
  - `docs/adr/`：如果是新的架构决策，需创建新的 ADR 文件

### 调试技巧

**使用开发模式快速测试**:
```bash
# 运行单次检查，不修改配置
python monitor.py --dev

# 查看详细的计算过程
# （在代码中添加 print 或使用 logging.debug）
```

**查看算法学习状态**:
```bash
# 查看当前参数
cat wgmm_config.json | python -m json.tool

# 查看历史数据分布
awk '{print strftime("%Y-%m-%d %H:%M:%S", $1)}' mtime.txt | \
    awk '{print $2}' | cut -d: -f1 | sort | uniq -c
```

**临时修改参数测试**:
```bash
# 备份配置
cp wgmm_config.json wgmm_config.json.bak

# 修改参数（使用 jq 或手动编辑）
# ...

# 测试
python monitor.py --dev

# 恢复配置
cp wgmm_config.json.bak wgmm_config.json
```

## 获取帮助

如果遇到问题：

1. **查看文档**
   - README.md: 用户文档和 FAQ
   - CONTRIBUTING.md: 贡献指南
   - CLAUDE.md: 本文件
   - docs/adr/: 架构决策记录

2. **查看日志**
   - urls.log: 主运行日志
   - critical_errors.log: 严重错误日志

3. **运行诊断**
   ```bash
   ./monitor.sh test
   ```

4. **提交 Issue**
   - 详细描述问题
   - 提供复现步骤
   - 附上相关日志
   - 说明系统和环境信息
