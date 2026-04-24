# ADR 005: 采用模块化单体结构（反转 ADR 003 的禁止规则）

## 状态
已采纳 (Accepted)

## 日期
2026-04-24

## 背景 (Context)

### 起点

ADR 003（2026-01-24）在一次失败的重构尝试之后，明文禁止"拆分单体文件为多个模块"等一系列大规模重构动作，目的是保护用户对 `monitor.py` 的直接掌控、控制 AI 协作的 Token 消耗。

三个月后，`monitor.py` 随着功能迭代仍然停留在 2500+ 行量级，包含 54 个方法，混合了 CLI 参数解析、日志、HTTP 客户端、B 站检测、WGMM 算法、持久化与主循环等职责。这带来了以下新的实际问题：

1. **测试困难**：`VideoMonitor` 将所有依赖（网络、文件、算法、日志）绑在同一个类实例中，无法在不 mock 全局副作用的情况下测试任一业务分支。
2. **局部改动需要读整个文件**：修改 WGMM 得分曲线时，必须绕过 URL 管理、通知、cookies 验证等无关代码；Ruff 和人工 review 的注意力分散。
3. **ADR 003 的前提已经变化**：当时对"AI 大重构不可控"的判断是基于 Claude Sonnet 4.5 的 Token 成本与上下文能力。在 Claude Opus 4.6/4.7 的条件下，一次性抽取的成本与风险都明显下降。

### 2026-04-24 的重构

重构在 commit `2d4f72d` 中完成：

- `monitor.py` 降级为 6 行的 CLI 入口壳，调用 `wgmm_monitor.cli.main`
- 业务分层进入 `wgmm_monitor/` 包：
  - `clients/`：Bark、Gist、yt-dlp 外部依赖
  - `services/`：bilibili、frequency、history、monitor、notification 五项业务
  - `stores/`：config、history、url 三种持久化
  - `wgmm/`：constants、features、learning、scheduler、scoring 五个算法模块
  - `utils/`、`models.py`、`config.py`、`runtime_logger.py`、`app.py`
- 新增 `tests/`：6 个文件、24 个单元测试
- Ruff check / Ruff format / `python -m unittest` 全部通过

## 决策 (Decision)

**采用模块化单体（modular monolith）作为本项目的目标结构，反转 ADR 003 "禁止拆分单体文件"的具体规则。**

注意：这**不是**拥抱 Pipeline / 微服务 / 插件系统。ADR 002（拒绝 X-Algorithm 风格推荐系统）与 ADR 003 中关于"简单即美""不要引入跨进程边界"的**精神**继续适用。

### 具体原则

1. **保留的 ADR 003 精神**：
   - ✅ 拒绝多进程 / 分布式 / 插件化架构
   - ✅ 拒绝预测系统、特征工程平台等过度工程
   - ✅ 单次代码修改仍应尽量控制在可一次 review 的规模
   - ✅ 每次修改必须通过 Ruff + unittest

2. **新采纳的规则**：
   - ✅ 业务逻辑按"外部依赖 / 领域服务 / 持久化 / 纯算法"分层
   - ✅ `monitor.py` 仅作为入口，不再承载实现
   - ✅ 新增依赖时，优先考虑能否通过构造函数注入，使其可被 Fake 替换
   - ✅ 每个服务对外暴露的公开方法必须有至少一个单元测试覆盖

3. **依旧禁止**（ADR 002/003 共同约束）：
   - ❌ 引入消息队列、分布式调度、微服务
   - ❌ 把 WGMM 拆到独立的预测服务
   - ❌ 新增 ORM、DI 框架、插件系统等"企业级"基础设施
   - ❌ 将 `wgmm_monitor/` 继续拆分为多个顶层 Python 包

## 理由 (Rationale)

### 1. 测试可行性的质变

重构前，`adjust_check_frequency` 只能通过运行完整主循环来间接验证。重构后，`decide_next_frequency`、`FrequencyService`、`MonitorService.run_monitor` 各自有独立的单元测试（24 个，全部绿，耗时 0.02s）。这直接满足了 ADR 003 自身列出的"小步快进：修改后立即验证"原则——当时无法做到，现在可以。

### 2. 分层边界仍然轻量

新结构共 25 个文件、2791 行，与重构前 2529 行的 `monitor.py` 相比只多 262 行。没有引入任何新运行期依赖：仍然只有 `numpy` 和 `requests`。没有引入框架（无 FastAPI、无 Celery、无 Pydantic validator）。每个子模块平均 100 行量级，符合 ADR 003 "可一次理解完一个单元"的目标。

### 3. ADR 002 的独立约束并未动摇

ADR 002 拒绝的是 X-Algorithm 风格的推荐系统技术（Transformer 时序编码、两阶段预测、特征工程平台等），以及把 WGMM 打造成通用预测产品的动机。这与"模块化 vs 单体"是两个正交维度。本 ADR 只撤销 ADR 003 中"禁止拆文件"这一条，ADR 002 的所有条款继续完整生效。

### 4. AI 协作成本曲线变化

ADR 003 提出时的关键约束是 Claude Sonnet 4.5 下做 2700 行重构需要 200K+ token 对话。在更强的模型和更成熟的工作流下，一次性抽取加测试的 Token 与时间成本均已降至可接受区间。ADR 是可以被反转的——前提是反转的理由被显式记录，而不是悄悄改写旧文档。这也是本 ADR 存在的意义。

## 后果 (Consequences)

### 正面影响

1. **单元测试第一次可写**：`FrequencyService` 和 `MonitorService` 可以用 Fake 依赖独立验证。
2. **算法层纯函数化**：`wgmm/scheduler.decide_next_frequency` 等函数不再持有副作用，更容易 review 与推理。
3. **修改面更小**：调整算法不需要读完 URL 管理代码；调整 B 站检测不需要读完 WGMM。
4. **CLAUDE.md 与实际代码能对齐**：过去 "grep `def adjust_check_frequency` monitor.py" 的引导不再有效，新的入口文档可以直接指向具体模块路径。

### 负面影响

1. **跨文件跳转**：追一条完整执行链需要在 3-5 个文件之间跳转，不如 2500 行单文件直接 `PageDown` 流畅。
2. **重复导入**：小工具函数（时间格式化、文件截断）必须通过 import 使用，比以前直接调用方法多一层寻址。
3. **文档维护成本**：ADR 003 的"禁止拆分"结论曾被多处文档引用，本次反转需要同步更新所有文档入口（CLAUDE.md、README、docs/）。
4. **API 签名分化**：重构前 `FrequencyDecision` 不存在；外部脚本如果依赖 `VideoMonitor.wgmm_config` 这类字段，会直接失败。本项目当前不对外暴露 API，这一点影响为零。

### 权衡结论

测试可行性的质变是关键收益，在没有引入框架 / 不增加运行期复杂度的前提下拿到。负面主要是"追链路多跳几次文件"这种一次性学习成本。收益远大于成本，因此决策成立。

## 与既有 ADR 的关系

| ADR | 关系 |
| --- | --- |
| ADR 001（保持 Python 实现） | 未受影响。继续有效。ADR 005 不涉及语言选型。 |
| ADR 002（拒绝 X-Algorithm 推荐系统技术） | 未受影响。继续有效。禁止推荐系统技术的所有具体条款在 ADR 005 下依然适用。 |
| ADR 003（不进行大型代码重构） | **被本 ADR 取代**。ADR 003 中"禁止拆分单体文件""禁止多阶段重构""单次修改不超过100行"三条具体规则失效；其风险控制精神（小步验证、Token 预算、回滚策略）继续作为经验保留。 |
| ADR 004（修复级联误检测） | 未受影响。级联修复在本重构中移至 `wgmm_monitor/services/monitor.py` 对应位置，逻辑一致。 |

## 依然适用的 ADR 003 精神

下列原则在 ADR 005 下继续作为纪律：

- **小步快进**：新增模块时，保持单次 commit 可一次性 review。
- **测试伴随**：抽取新函数必须伴随至少一个单元测试。
- **可回滚**：每个功能 commit 保持可独立 revert，不允许"前 3 个 commit 破坏 + 第 4 个 commit 修复"的打包方式。
- **Ruff 作为刚性门槛**：不允许为追求模块化绕过代码风格规则。

## 变更流程追认

ADR 003 与 CLAUDE.md 均要求"提出重大变更前，先在 Issue 中讨论并提供 ROI 分析"。本次重构实际上是在未经 Issue 讨论的前提下先完成代码抽取（commit `2d4f72d`），再补写 ADR。这一次序不符合流程要求，应视为本项目的流程失误，ADR 005 以追认形式存在。今后涉及对 ADR 的反转，应先发起讨论、再动代码。

## 参考资料

- Commit `2d4f72d`：实际重构（monitor.py → wgmm_monitor/）
- Commit `7fda60f`：新增 24 个单元测试
- [ADR 003: 不进行大型代码重构](./003-avoid-large-refactoring.md) - 本 ADR 取代对象
- [ADR 002: 不引入 X-Algorithm 推荐系统技术](./002-do-not-adopt-x-algorithm-techniques.md) - 保留生效
