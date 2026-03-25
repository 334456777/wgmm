# 开发指南

本文档为 WGMM B站视频监控系统的开发者提供详细的开发流程、代码质量标准和维护指南。

## 目录

- [开发命令](#开发命令)
  - [基本运行](#基本运行)
  - [开发模式](#开发模式)
  - [systemd 服务管理](#systemd-服务管理)
- [代码质量标准](#代码质量标准)
  - [Ruff 代码检查](#ruff-代码检查)
  - [代码风格规范](#代码风格规范)
  - [配置管理](#配置管理)
- [Git 工作流程](#git-工作流程)
  - [Commit 规范](#commit-规范)
  - [提交前检查清单](#提交前检查清单)
  - [文档更新要求](#文档更新要求)
- [调试技巧](#调试技巧)
  - [查看日志](#查看日志)
  - [检查算法状态](#检查算法状态)
  - [开发模式测试](#开发模式测试)
  - [临时修改参数测试](#临时修改参数测试)
- [常规维护任务](#常规维护任务)
  - [每日检查](#每日检查)
  - [每周维护](#每周维护)
  - [每月维护](#每月维护)
  - [故障排查清单](#故障排查清单)

## 开发命令

### 基本运行

**注意：** 项目文件夹内已包含 `.venv` 虚拟环境，所有依赖已安装，建议使用虚拟环境运行。

```bash
# 激活虚拟环境（首次运行前需要）
source .venv/bin/activate

# 虚拟环境中运行（推荐）
python monitor.py

# 不使用虚拟环境直接运行（需要系统已安装依赖）
python3 monitor.py
```

### 开发模式

使用 `--dev` 或 `-d` 标志可以在沙盒环境中测试系统：

```bash
# 开发模式：运行单次检查后立即退出，不修改配置文件
python monitor.py --dev
# 或
python monitor.py -d
```

**开发模式特点：**
- 不修改配置文件（`is_manual_run` 保持为 `True`）
- 不写入 `wgmm_config.json`
- 使用内存中的 `sandbox_*` 变量
- 运行单次检查后立即退出
- 适合快速验证代码逻辑和算法计算

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

## 代码质量标准

### Ruff 代码检查

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

### 代码风格规范

**强制要求：**
- 使用 **tab 缩进**（而非空格）
- 行长度限制：**92 字符**
- docstring 和注释使用英文标点符号（避免全角符号）
- 遵循 Google 风格的 docstring
- 所有函数必须包含 docstring 说明功能、参数和返回值

### 配置管理

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

## Git 工作流程

### Commit 规范

**重要：** 本存储库强制遵循 Conventional Commits 规范，所有提交都必须符合此格式。

查看提交历史可以验证规范执行情况：
```bash
git log --oneline -20
```

#### 基本格式

```
<type>: <description>
```

#### 提交类型（Type）

**常用类型：**
- `fix:` - Bug 修复
- `feat:` - 新功能
- `docs:` - 文档更新（注释、README、配置文件说明等）
- `refactor:` - 代码重构（不改变功能）
- `style:` - 代码风格调整（不影响代码运行的格式化）
- `test:` - 添加或修改测试
- `chore:` - 构建、工具、依赖更新等杂项

#### 提交说明（Description）

- 使用中文书写
- 简洁描述做了什么
- 不超过 50 个字符
- 首字母不大写，结尾不加标点

**单行示例：**
- `fix: 修改环境变量缺失提示信息，简化错误输出`
- `docs: 添加WGMM算法FAQ到README，解释3天间隔的数学原理`
- `refactor: 简化代码格式，合并多行表达式为单行`

#### 多行提交消息格式

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

### 提交前检查清单

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

### 文档更新要求

**文档更新强制级别：**
- 🔴 **强制**：`feat:`、`refactor:` 类型提交必须更新相关文档
- 🟡 **推荐**：`fix:` 类型提交建议更新相关说明
- 📝 `docs:` 类型提交专门用于文档更新，应与代码修改分开提交

**文档更新检查清单：**
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

查看 `data/wgmm_config.json` 了解当前算法参数：
```bash
# 查看原始 JSON
cat data/wgmm_config.json

# 格式化输出
cat data/wgmm_config.json | python -m json.tool

# 查看历史数据分布（按小时统计）
awk '{print strftime("%Y-%m-%d %H:%M:%S", $1)}' data/mtime.txt | \
    awk '{print $2}' | cut -d: -f1 | sort | uniq -c
```

### 开发模式测试

在开发模式下测试系统：
```bash
# 运行单次检查，不修改配置
python monitor.py --dev

# 查看详细的计算过程
# （在代码中添加 print 或使用 logging.debug）
```

### 临时修改参数测试

```bash
# 备份配置
cp data/wgmm_config.json data/wgmm_config.json.bak

# 修改参数（使用 jq 或手动编辑）
# ...

# 测试
python monitor.py --dev

# 恢复配置
cp data/wgmm_config.json.bak data/wgmm_config.json
```

## 常规维护任务

### 每日检查

（可选）定期检查系统运行状态：

```bash
# 查看系统状态
sudo systemctl status video-monitor

# 查看最近的日志
tail -f urls.log

# 使用 systemd 查看服务日志
sudo journalctl -u video-monitor -n 50 -f
```

### 每周维护

（推荐）每周进行一次全面检查：

```bash
# 检查是否有严重错误
cat critical_errors.log

# 查看算法学习状态
cat data/wgmm_config.json | python -m json.tool

# 检查磁盘空间
df -h

# 检查日志文件大小
ls -lh urls.log critical_errors.log
```

### 每月维护

（可选）每月进行一次依赖更新：

```bash
# 更新 yt-dlp
source .venv/bin/activate
pip install -U yt-dlp

# 检查 cookies.txt 是否过期
# （如果检测失败，重新从浏览器导出）

# 更新系统依赖（如果需要）
pip install -U -r requirements.txt
```

### 故障排查清单

当系统出现问题时，按以下顺序排查：

#### 1. 检查服务状态

```bash
# 使用 systemctl 检查
sudo systemctl status video-monitor

# 查看服务是否在运行
sudo systemctl is-active video-monitor
```

#### 2. 查看日志

```bash
# 主日志（最近100行）
tail -100 urls.log

# 严重错误日志
cat critical_errors.log

# systemd 日志（最近100行）
sudo journalctl -u video-monitor -n 100

# 实时跟踪 systemd 日志
sudo journalctl -u video-monitor -f
```

#### 3. 验证配置

```bash
# 检查必需文件是否存在
ls -la data/.env data/cookies.txt data/local_known.txt data/wgmm_config.json

# 验证环境变量
cat data/.env

# 验证 cookies.txt 格式（应该是 Netscape 格式）
head -5 data/cookies.txt

# 测试环境变量加载
source .venv/bin/activate
python -c "import os; print(os.getenv('BILIBILI_UID'))"
```

#### 4. 测试网络连接

```bash
# 测试 B站连接
curl -I https://www.bilibili.com

# 测试 GitHub API
curl -I https://api.github.com

# 测试网络延迟
ping -c 3 www.bilibili.com
```

#### 5. 手动运行测试

```bash
# 激活虚拟环境
source .venv/bin/activate

# 开发模式运行单次检查
python monitor.py --dev

# 查看详细输出
python monitor.py --dev 2>&1 | tee test_run.log
```

#### 6. 重启服务

```bash
# 重启 systemd 服务
sudo systemctl restart video-monitor

# 检查重启后的状态
sudo systemctl status video-monitor
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

**性能问题排查：**

如果发现性能明显下降，按以下步骤排查：

1. **检查历史数据量**
   ```bash
   # 查看 mtime.txt 行数
   wc -l data/mtime.txt

   # 如果超过 1000 行，可能需要考虑数据剪枝
   ```

2. **检查网络延迟和带宽**
   ```bash
   # 测试到 B站的速度
   curl -o /dev/null -s -w "Time: %{time_total}s\n" https://www.bilibili.com
   ```

3. **检查磁盘 I/O 性能**
   ```bash
   # 查看磁盘使用率
   df -h

   # 查看磁盘 I/O（需要 iostat 工具）
   iostat -x 1 5
   ```

4. **检查系统资源**
   ```bash
   # 查看 CPU 和内存使用
   top -p $(pgrep -f "python.*monitor.py")

   # 查看进程详细信息
   ps aux | grep monitor.py
   ```

### 数据备份建议

虽然系统使用 GitHub Gist 作为云端备份，但仍建议定期备份本地数据：

```bash
# 创建备份目录
mkdir -p backups/$(date +%Y%m%d)

# 备份关键文件
cp data/local_known.txt backups/$(date +%Y%m%d)/
cp data/wgmm_config.json backups/$(date +%Y%m%d)/
cp data/mtime.txt backups/$(date +%Y%m%d)/
cp data/miss_history.txt backups/$(date +%Y%m%d)/
cp data/.env backups/$(date +%Y%m%d)/  # 注意：敏感文件，妥善保管

# 压缩备份
cd backups
tar czf wgmm_backup_$(date +%Y%m%d).tar.gz $(date +%Y%m%d)/
rm -rf $(date +%Y%m%d)/

# 列出备份文件
ls -lh wgmm_backup_*.tar.gz
```

**自动化备份脚本示例：**

创建 `backup.sh` 文件：

```bash
#!/bin/bash
# 自动备份脚本

BACKUP_DIR="backups/$(date +%Y%m%d)"
mkdir -p "$BACKUP_DIR"

# 备份关键文件
cp data/local_known.txt data/wgmm_config.json data/mtime.txt data/miss_history.txt "$BACKUP_DIR/"

# 压缩备份
tar czf "backups/wgmm_backup_$(date +%Y%m%d).tar.gz" "$BACKUP_DIR/"
rm -rf "$BACKUP_DIR"

# 只保留最近30天的备份
find backups/ -name "wgmm_backup_*.tar.gz" -mtime +30 -delete

echo "备份完成: backups/wgmm_backup_$(date +%Y%m%d).tar.gz"
```

添加到 crontab 定期执行：

```bash
# 编辑 crontab
crontab -e

# 添加每周日凌晨2点执行备份
0 2 * * 0 cd /path/to/wgmm && bash backup.sh
```

## 开发最佳实践

### 高效工作流程

**推荐的开发工作流程：**

1. **快速理解项目**（首次接触）
   ```bash
   # 1. 阅读本开发指南
   cat docs/development-guide.md

   # 2. 查看项目概述
   head -100 CLAUDE.md

   # 3. 理解核心架构
   grep "class VideoMonitor" monitor.py
   grep "def adjust_check_frequency" monitor.py
   ```

2. **处理开发任务**（日常开发）
   ```bash
   # 1. 激活虚拟环境
   source .venv/bin/activate

   # 2. 查看相关代码
   # 使用 Grep 工具搜索函数名或关键词

   # 3. 参考类似修改
   git log --oneline -20

   # 4. 开发模式测试
   python monitor.py --dev
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

**代码质量：**
- [ ] `ruff check monitor.py` 通过
- [ ] `ruff format monitor.py` 通过
- [ ] 所有新增函数都有 Google 风格的 docstring
- [ ] 复杂逻辑有行内注释说明
- [ ] 数学公式有注释说明

**功能测试：**
- [ ] 开发模式测试通过：`python monitor.py --dev`
- [ ] 长期运行测试通过（至少7天）
- [ ] 所有已知用例都能正常工作

**文档更新：**
- [ ] 重大修改后已更新相关文档（README.md、CLAUDE.md、CONTRIBUTING.md）
- [ ] Commit 消息遵循 Conventional Commits 规范

**架构合规：**
- [ ] 不违背任何现有 ADR 决策
- [ ] 如有重大架构变更，已创建新的 ADR 文件

### 常见代码修改场景

#### 场景 1：调整预测激进程度

```python
# 更激进：更频繁检查（适合热点UP主）
mapping_curve = 2.0  # → 改为 3.0 或更高
peak_advance_minutes = 5  # → 改为 10（更早检查）

# 更保守：减少请求（适合冷门UP主）
mapping_curve = 2.0  # → 改为 1.5
```

#### 场景 2：修改时间容忍度

```python
# 更严格：只匹配极相似时间
sigmas["day"] = 0.8  # → 改为 0.5

# 更宽松：容忍更大时间差异
sigmas["week"] = 1.0  # → 改为 1.5
```

#### 场景 3：调整记忆速度

```python
# 快速适应：UP主经常改变习惯
lambda_base = 0.0001  # → 改为 0.0002

# 长期记忆：UP主习惯稳定
lambda_base = 0.0001  # → 改为 0.00005
```

## 相关文档

- **CLAUDE.md**: 面向 AI 助手的完整开发指南（包含架构细节）
- **CONTRIBUTING.md**: 贡献指南（包含代码质量标准、架构决策原则）
- **README.md**: 用户文档和算法 FAQ
- **docs/adr/**: 架构决策记录（ADR 001-003）

## 获取帮助

如果遇到问题：

1. **查看文档**
   - README.md: 用户文档和 FAQ
   - CONTRIBUTING.md: 贡献指南
   - CLAUDE.md: 完整开发指南
   - docs/adr/: 架构决策记录

2. **查看日志**
   - urls.log: 主运行日志
   - critical_errors.log: 严重错误日志

3. **搜索相关代码**
   - 使用 Grep 工具搜索关键词
   - 阅读函数的 docstring 和注释

4. **提交 Issue**
   - 详细描述问题
   - 提供复现步骤
   - 附上相关日志
   - 说明系统和环境信息
