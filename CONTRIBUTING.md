# 贡献指南

感谢你对 WGMM 智能视频监控系统的关注！本文档将指导你如何为项目做出贡献。

## 📋 目录

- [项目理念](#项目理念)
- [开发环境设置](#开发环境设置)
- [代码质量标准](#代码质量标准)
- [提交规范](#提交规范)
- [架构决策原则](#架构决策原则)
- [测试要求](#测试要求)
- [文档要求](#文档要求)

## 🎯 项目理念

### 设计哲学

WGMM 项目遵循以下核心设计原则：

1. **Simple is Better（简单即美）**
   - 保持单体架构，避免过度模块化
   - 优先选择简洁的解决方案，而非复杂的架构
   - 代码应清晰易懂，而非过度抽象

2. **专注核心价值**
   - WGMM 是**监控工具**，而非预测系统
   - 核心价值：自适应检查、及时通知、稳定可靠
   - 预测准确性 95% 已足够，无需过度优化

3. **实用主义**
   - 解决实际问题，而非追逐技术热点
   - 优先选择成熟稳定的技术栈
   - 避免为了技术而技术的过度工程化

4. **稳定可靠**
   - 7×24 小时无人值守运行
   - 系统稳定性优于新功能
   - 向后兼容性优先

### 架构决策记录 (ADR)

项目的重要技术决策记录在 `docs/adr/` 目录中，贡献前请务必阅读：

- **ADR 001**: 保持 Python 实现，不迁移到 Go
- **ADR 002**: 不引入 X-Algorithm 推荐系统技术

这些决策代表了项目的长期方向，除非有充分的理由，否则不应违背。

## 🛠️ 开发环境设置

### 前置要求

- Python 3.14+
- Git
- 一个代码编辑器（推荐 VS Code 或 PyCharm）

### 环境配置

```bash
# 1. 克隆仓库
git clone https://github.com/yourusername/wgmm.git
cd wgmm

# 2. 激活虚拟环境（项目已包含 .venv）
source .venv/bin/activate

# 3. 验证依赖
pip list

# 4. 运行测试（开发模式）
python monitor.py --dev
```

### 推荐工具

- **代码格式化**: Ruff
- **类型检查**: Pyright（可选）
- **Git 客户端**: Git CLI 或 GitHub Desktop

## ✅ 代码质量标准

### 强制要求

**每次修改 Python 代码后，必须运行以下命令确保代码质量符合规范。**

```bash
# 激活虚拟环境
source .venv/bin/activate

# 1. 使用 ruff 检查 Python 代码质量
ruff check monitor.py

# 2. 使用 ruff 格式化 Python 代码
ruff format monitor.py

# 3. 如果 ruff check 发现问题，尝试自动修复
ruff check --fix monitor.py
```

### 代码质量标准

**必须通过的检查**:
- ✅ `ruff check` 必须通过（All checks passed!）
- ✅ `ruff format` 必须通过（already formatted 或格式化成功）

**代码风格规范**:
- 使用 **tab 缩进**（而非空格）
- 行长度限制：**92 字符**
- docstring 和注释使用英文标点符号（避免全角符号）
- 遵循 Google 风格的 docstring

### 配置管理

**重要**: 不可修改 `pyproject.toml` 中的 ruff 配置

- ❌ 禁止修改 ruff 配置（包括 ignore 规则、line-length、缩进风格等）
- ✅ 如需调整代码风格，必须修改代码以符合现有配置，而非修改配置文件

**适用范围**:
- ruff 只检查和格式化 `.py` 文件（Python 代码）
- Markdown 文档（如 CLAUDE.md、README.md）不需要 ruff 检查

## 📝 提交规范

### Commit 规范

**重要**: 本存储库强制遵循 Conventional Commits 规范。

### 基本格式

```
<type>: <description>
```

### 提交类型（Type）

**常用类型**:
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

**单行示例**:
- `fix: 修复环境变量缺失提示信息，简化错误输出`
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

### 创建提交的完整流程

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
```

## 🏗️ 架构决策原则

### 避免的改进方向

以下改进方向已被明确拒绝（参考 ADR 002）：

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

### 欢迎的改进方向

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

## 🧪 测试要求

### 当前测试状态

项目当前没有自动化测试套件，这是由于：

- 单体架构易于理解和调试
- 开发模式（`--dev`）可快速验证逻辑
- 系统稳定性已通过长期运行验证

### 测试原则

如果你添加新功能，请：

1. **手动测试**
   ```bash
   # 开发模式：运行单次检查后立即退出
   python monitor.py --dev
   ```

2. **长期运行测试**
   - 在实际环境中运行至少 7 天
   - 验证稳定性和资源占用
   - 检查日志是否有异常

3. **边缘情况测试**
   - 网络中断
   - B站 API 变化
   - 系统时间调整
   - 配置文件损坏

### 未来测试计划

如果项目复杂度增加，可以考虑：

- 单元测试（pytest）
- 集成测试
- 性能基准测试

## 📚 文档要求

### 代码注释

**所有函数必须包含**：

1. **Docstring**（Google 风格）
   ```python
   def adjust_check_frequency(self, found_new_content: bool = False) -> None:
       """WGMM 算法主函数，根据历史数据计算下次检查间隔。

       算法流程：
       1. 加载正向和负向历史事件
       2. 数据预处理（异常值过滤、剪枝）
       3. 自适应参数学习（lambda、sigma、权重）
       4. 计算当前时间发布概率
       5. 峰值预测扫描
       6. 映射概率到检查间隔

       Args:
           found_new_content: 是否检测到新内容，用于算法学习

       Returns:
           None（直接更新配置文件和日志）
       """
   ```

2. **关键逻辑的行内注释**
   ```python
   # 使用 IQR 方法过滤异常值
   q1 = np.percentile(intervals, 25)
   q3 = np.percentile(intervals, 75)
   iqr = q3 - q1
   ```

3. **数学公式说明**
   - 对于复杂的数学计算，添加公式说明
   - 参考现有代码的注释风格

### 文档更新

如果你修改了功能，请同步更新：

- **README.md**: 如果影响用户使用
- **CLAUDE.md**: 如果影响开发流程
- **DECISIONS.md 或 docs/adr/**: 如果是架构决策
- **本文档**: 如果影响贡献流程

## 🤝 贡献流程

### 1. 发现问题或提出建议

在提交 PR 之前，请先创建 Issue 讨论：

- Bug 报告：详细描述问题、复现步骤、预期行为
- 功能建议：说明使用场景、预期收益、替代方案
- 文档改进：指明不准确或缺失的部分

### 2. Fork 和分支

```bash
# 1. Fork 仓库到你的账号
# 2. Clone 你的 fork
git clone https://github.com/yourusername/wgmm.git
cd wgmm

# 3. 创建功能分支
git checkout -b feature/your-feature-name
```

### 3. 开发和测试

```bash
# 1. 激活虚拟环境
source .venv/bin/activate

# 2. 开发你的功能
# ...

# 3. 代码质量检查
ruff check monitor.py
ruff format monitor.py

# 4. 开发模式测试
python monitor.py --dev
```

### 4. 提交和推送

```bash
# 1. 提交代码
git add .
git commit -m "feat: 添加XXX功能"

# 2. 推送到你的 fork
git push origin feature/your-feature-name
```

### 5. 创建 Pull Request

在 GitHub 上创建 PR，确保：

- 标题遵循 Conventional Commits 规范
- 描述中关联相关 Issue
- 说明改动内容和测试情况
- 通过所有代码质量检查

## 📋 PR 审查标准

PR 将根据以下标准审查：

- ✅ 代码质量：`ruff check` 和 `ruff format` 必须通过
- ✅ 功能正确：通过开发模式测试和长期运行验证
- ✅ 文档完整：代码注释、相关文档已更新
- ✅ 符合理念：不违背项目设计哲学和 ADR 决策
- ✅ 向后兼容：不破坏现有功能和配置

## 🌟 贡献者行为准则

- **尊重他人**: 建设性讨论，避免人身攻击
- **接受反馈**: 乐于接受改进建议
- **协作优先**: 团队决策优于个人偏好
- **简单实用**: 优先选择简单实用的解决方案

## 📞 联系方式

- **Issues**: 项目 GitHub Issues 页面
- **Discussions**: 项目 GitHub Discussions 页面（如有）
- **Email**: 见仓库维护者信息

## 📄 许可证

通过贡献代码，你同意你的贡献将在项目的许可证下发布。

---

**再次感谢你的贡献！让我们一起保持 WGMM 项目的简洁、稳定和高效。** 🎉
