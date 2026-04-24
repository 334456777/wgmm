# ADR 001: 保持 Python 实现，不迁移到 Go

## 状态

已过时 (Superseded)

## 日期

2026-01-21

## 当前状态说明

本 ADR 是历史记录，已不再作为当前架构说明使用。

过时原因：

- 文中描述的是旧版单文件 `monitor.py` 的代码规模、方法数量和维护形态。
- 当前实现已经是小型模块化单体应用：`monitor.py` 仅作为入口壳，实际实现位于 `wgmm_monitor/`。
- 当前开发、测试和文档入口已经改为 `README.md`、`README_CN.md`、`docs/development-guide.md`、`docs/code_logic_flow.md` 和 `docs/code-reference.md`。

仍有参考价值的历史结论：

- 当时评估认为 Go 迁移无法显著改善 WGMM 的实际运行瓶颈。
- 当前实现仍然使用 Python + NumPy，但这个事实应以当前文档和代码为准，而不是以本 ADR 的旧数据为准。

## 历史背景 (Context)

当时项目评估过是否从 Python 迁移到 Go。评估重点是：

- WGMM 算法计算主要由 NumPy 向量化完成。
- 单次算法计算耗时远小于 `yt-dlp` 和网络 I/O。
- Go 重写需要重新实现数值计算、B站检测、Gist/Bark 集成和 systemd 运行链路。
- 迁移收益不足以覆盖重写、验证和长期维护成本。

## 历史决策 (Historical Decision)

当时决定不迁移到 Go，继续使用 Python + NumPy。

## 历史理由 (Rationale)

### 性能瓶颈不在语言运行时

WGMM 的调频计算是毫秒级工作，完整检查主要等待 `yt-dlp`、B站网络响应、Gist API 和睡眠调度。把 Python 改写为 Go 不会解决这些 I/O 等待。

### NumPy 已经适合当前算法

当前算法依赖批量时间特征、指数衰减和高斯核得分。NumPy 的向量化实现已经足够快，也比手写 Go 数值循环更容易保持正确性。

### 重写风险高于收益

Go 迁移会带来：

- 重新实现 WGMM 数学逻辑。
- 重写外部客户端和持久化逻辑。
- 重新验证历史数据兼容性。
- 重新处理 cookies、`yt-dlp`、systemd 和日志行为。

这些工作对监控效果没有明确收益。

## 当前替代依据

当前实现和开发流程以以下文档为准：

- [README.md](../../README.md)
- [README_CN.md](../../README_CN.md)
- [CONTRIBUTING.md](../../CONTRIBUTING.md)
- [开发指南](../development-guide.md)
- [代码逻辑流程](../code_logic_flow.md)
- [代码参考](../code-reference.md)
- [WGMM 算法说明](../wgmm-algorithm.md)

当前验证命令：

```bash
source .venv/bin/activate
ruff check monitor.py wgmm_monitor tests
ruff format --check monitor.py wgmm_monitor tests
python -m unittest discover -s tests
python monitor.py --wgmm-core-only
python monitor.py --dev
```

## 相关决策

- [ADR 002](002-do-not-adopt-x-algorithm-techniques.md): 不引入推荐系统技术
- [ADR 003](003-avoid-large-refactoring.md): 历史上的大型重构风险记录，已被当前模块化实现取代
- [ADR 004](004-fix-cascade-false-detection.md): 修复级联误检测故障
