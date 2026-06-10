# 贡献指南

本文档说明当前模块化实现下的开发、测试和提交流程。项目仍然是一个小型单体应用：`monitor.py` 只保留命令行入口，实际实现按职责分布在 `wgmm_monitor/` 中。

## 项目原则

WGMM 的核心价值是监控效率，而不是构建通用预测平台。

- 保持实现简单，避免引入大型框架或复杂流水线。
- 代码可以模块化，但模块边界必须服务于可读性和测试性。
- `clients` 只封装外部系统，`stores` 只做本地持久化，`services` 编排业务流程，`wgmm` 保持纯算法层。
- 算法修改应优先证明对监控及时性、稳定性或请求节省率有实际收益。

历史 ADR 中可能包含旧的单文件决策。当前代码以 `wgmm_monitor/` 的小型模块化单体实现为准。

## 开发环境

```bash
source .venv/bin/activate
pip install -r requirements-dev.txt  # 开发工具: ruff + coverage
pip list
which yt-dlp
yt-dlp --version
```

手动运行需要：

- `data/.env`
- `data/cookies.txt`
- `yt-dlp` 在 `PATH` 中

测试不应依赖真实 Gist、Bark 或 B站请求；需要外部系统时使用 fake 或 mock。

## 代码质量

修改 Python 代码后必须运行：

```bash
source .venv/bin/activate
ruff check monitor.py wgmm_monitor tests
ruff format monitor.py wgmm_monitor tests
python -m unittest discover -s tests
```

提交前推荐使用 `ruff format --check` 做只读检查：

```bash
ruff format --check monitor.py wgmm_monitor tests
```

项目代码风格：

- tab 缩进
- 行长度 92
- Google 风格 docstring
- 新增公共函数和复杂私有函数都应有 docstring
- 不修改 `pyproject.toml` 中的 Ruff 规则来绕过问题

## 测试要求

当前测试套件位于 `tests/`，使用标准库 `unittest`：

```bash
python -m unittest discover -s tests
```

根据改动范围补充测试：

- WGMM 纯算法：优先测试 `wgmm_monitor/wgmm/learning.py`、`scheduler.py`、`scoring.py`。
- 本地持久化：测试 `wgmm_monitor/stores/`（含 OSError 容错路径）。
- 主监控流程：用 fake client/service 测试 `wgmm_monitor/services/monitor.py` 分支。
- 外部客户端：mock `requests`/`subprocess` 测试 Bark/Gist/yt-dlp 的参数组装与异常路径。
- CLI 或装配逻辑：尽量保持薄层，测试参数分发与启动校验。

覆盖率基线整体 ≥ 90%，新增代码应附带测试：

```bash
python -m coverage run -m unittest discover -s tests
python -m coverage report --show-missing
```

冒烟测试顺序：

```bash
python monitor.py --wgmm-core-only
python monitor.py --dev
python -m unittest discover -s tests
```

`--wgmm-core-only` 用于隔离 WGMM 调频；`--dev` 跑完整检测链，但不会写 WGMM 配置，也不会发送新视频通知。

## 提交规范

本仓库使用 Conventional Commits：

```text
<type>: <description>
```

常用类型：

- `fix:` 修复缺陷
- `feat:` 新功能
- `docs:` 文档
- `refactor:` 不改变行为的重构
- `style:` 格式或风格调整
- `test:` 测试
- `chore:` 工具、依赖、杂项

Description 使用英文，简洁描述做了什么，不大写开头，不加句号。

示例：

```bash
git commit -m "fix: skip scan when part expansion fails"
git commit -m "docs: sync architecture docs with modules"
git commit -m "test: cover scheduler custom periods"
```

复杂提交可使用多行消息：

```bash
git commit -m "$(cat <<'EOF'
docs: sync monitor architecture docs

- update module references after the split
- document unittest and smoke-test commands
- mark historical ADR notes explicitly
EOF
)"
```

## 提交前清单

```bash
source .venv/bin/activate
ruff check monitor.py wgmm_monitor tests
ruff format --check monitor.py wgmm_monitor tests
python -m unittest discover -s tests
python -m coverage run -m unittest discover -s tests && python -m coverage report
git status
git diff
```

如果改动会触达真实运行链路，再按需要运行：

```bash
python monitor.py --wgmm-core-only
python monitor.py --dev
sudo systemctl status video-monitor
```

## 文档更新

下列变更需要同步文档：

- 用户运行方式、配置项、日志或故障排查变化：更新 `README.md` 和 `README_CN.md`。
- 模块边界、调用流程、数据流变化：更新 `docs/code_logic_flow.md` 和 `docs/code-reference.md`。
- WGMM 状态字段或算法流程变化：更新 `docs/wgmm-algorithm.md` 和 `docs/wgmm-config-params.md`。
- 贡献、测试或提交流程变化：更新本文档和 `docs/development-guide.md`。
- 新的长期架构决策：新增 ADR，而不是重写历史事实。

## PR 审查重点

- 行为是否符合当前监控目标。
- 模块边界是否清晰，没有把业务编排塞进 `clients` 或 `stores`。
- 外部失败是否有合理降级，不污染 `mtime.txt`、`miss_history.txt`、`local_known.txt`。
- Ruff、格式检查和 unittest 是否通过。
- 文档是否同步。

## 获取帮助

排查顺序：

1. 看 `urls.log` 和 `critical_errors.log`。
2. 运行 `python monitor.py --wgmm-core-only` 隔离 WGMM。
3. 运行 `python monitor.py --dev` 验证检测链。
4. 检查 `which yt-dlp`、`yt-dlp --version`、`data/.env`、`data/cookies.txt`。
5. 在 Issue 中提供复现步骤、相关日志和运行模式。
