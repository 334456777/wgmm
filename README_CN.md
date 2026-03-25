# 🎯 WGMM 智能视频监控系统

基于**加权高斯混合模型(WGMM)**机器学习算法的B站视频智能监控系统,自适应调整监控频率,在保证及时性的同时节省 **60-80%** 的网络请求。

## ✨ 核心亮点

| 🏆 特性 | 📊 指标 | 🔍 技术实现 |
|-------|-------|-----------|
| **🧠 智能预测精度** | 时间命中率 >95% | WGMM机器学习算法,周期性模式识别 |
| **⚡ 资源效率提升** | 节省网络请求 60-80% | 三层检测架构,智能频率调整 |
| **🎯 响应及时性** | 新视频检测延迟 <30分钟 | 发布高峰期提供5分钟级密集监控 |
| **🔄 自适应能力** | 2-3次新模式即可学习 | 指数衰减权重,自动适应习惯变化 |
| **🛡️ 系统可靠性** | 7×24小时稳定运行 | 多重故障恢复,自动数据修复机制 |

## 🚀 快速开始

### 1️⃣ 准备配置文件(仅需2个文件)

```bash
# 复制环境变量模板
cp data/.env.example data/.env

# 编辑 .env 文件,填入你的配置
nano data/.env
```

**必需配置**:
```bash
GITHUB_TOKEN=your_github_token          # GitHub Token (需要 gist 权限)
BARK_DEVICE_KEY=your_bark_key          # Bark 推送设备密钥
GIST_ID=your_gist_id                   # GitHub Gist ID
BILIBILI_UID=your_bilibili_uid         # 要监控的UP主UID
```

**获取方法**:
- **GITHUB_TOKEN**: https://github.com/settings/tokens (勾选 `gist` 权限)
- **BARK_DEVICE_KEY**: iOS Bark App 中复制
- **GIST_ID**: 创建新 Gist 后从 URL 中获取
- **BILIBILI_UID**: UP主主页 URL 中获取 (如 `space.bilibili.com/123456789`)

### 2️⃣ 准备 cookies.txt

从浏览器导出 B站登录凭证:

1. 登录 B站后打开开发者工具 (F12)
2. 访问任意视频页面
3. Application → Cookies → 复制所有 cookies
4. 保存到项目目录的 `data/cookies.txt` 文件

**格式示例**:
```
# Netscape HTTP Cookie File
.bilibili.com	TRUE	/	FALSE	1234567890	cookie_name	cookie_value
```

### 3️⃣ 启动监控

```bash
# 激活虚拟环境(项目已包含 .venv)
source .venv/bin/activate

# 开发模式:运行单次检查后退出(不修改配置)
python monitor.py --dev

# 正常模式:持续监控
python monitor.py

# systemd 服务方式(推荐生产环境)
sudo systemctl start video-monitor
sudo systemctl enable video-monitor  # 开机自启
```

### 4️⃣ 查看状态

```bash
# systemd 服务状态
sudo systemctl status video-monitor

# 查看日志
tail -f urls.log                      # 主日志
cat critical_errors.log               # 严重错误日志

# systemd 服务日志
sudo journalctl -u video-monitor -f   # 实时查看服务日志
```

## 📁 文件结构

```
wgmm/
├── monitor.py                    # 主程序 (2296行,58个方法)
├── requirements.txt              # 依赖包清单
├── pyproject.toml                # Ruff 代码质量配置
├── video-monitor.service         # systemd 服务配置
│
├── data/                         # 数据目录 (自动创建)
│   ├── .env                      # 环境变量配置 ⚠️ 需手动创建
│   ├── .env.example              # 环境变量模板 (已纳入版本控制)
│   ├── cookies.txt               # B站登录凭证 ⚠️ 需手动创建
│   ├── local_known.txt           # 本地已知URL列表 (自动生成)
│   ├── wgmm_config.json          # WGMM算法状态 (自动生成)
│   ├── mtime.txt                 # 历史发布时间戳 (自动生成)
│   └── miss_history.txt          # 失败历史记录 (自动生成)
│
├── urls.log                      # 主运行日志 (自动生成)
└── critical_errors.log           # 严重错误日志 (自动生成)
```

**自动生成文件说明**:
- 程序首次运行时会自动创建所有数据文件
- 无需手动创建或维护
- 配置文件已加入 `.gitignore`,不会被提交

## 🧠 WGMM 算法简介

### 设计灵感

如果你看过《咒术回战》,可以把 WGMM 算法想象成**八握剑异戒神将·魔虚罗**——

魔虚罗的核心能力是**适应**:每次受到攻击后,法阵转动一格,逐渐适应对手的术式,最终完全免疫并反制。WGMM 的工作方式与此异曲同工:

| 魔虚罗 | WGMM 算法 |
|--------|-----------|
| 被攻击后法阵转动,逐步适应术式 | 每次检查后更新参数,逐步学习发布模式 |
| 适应速度与攻击强度有关 | 自适应 λ:模式变化越大,遗忘越快,适应越快 |
| 完全适应后对该术式免疫 | σ 收敛后精准匹配时间模式,几乎不做无效请求 |
| 面对新术式需要重新适应 | UP 主改变习惯时,算法自动重新学习 |

简单来说:WGMM 就是一个不断"挨打"(观测数据)、不断"适应"(更新参数)、最终精准预判 UP 主发布时间的算法。

### 核心原理

WGMM (Weighted Gaussian Mixture Model) 算法通过分析历史发布时间,预测未来发布概率:

1. **四维时间特征编码**
   - 日周期 (sin/cos)
   - 周周期 (sin/cos)
   - 月内周 (1-5)
   - 年内月 (1-12)

2. **高斯核相似度计算**
   ```
   相似度 = exp(-距离² / (2σ²))
   ```

3. **指数时间衰减权重**
   ```
   权重 = exp(-λ × 年龄小时数)
   ```

4. **自适应学习**
   - 动态调整维度权重
   - 自适应 lambda (遗忘速度)
   - 自适应 sigma (时间容忍度)

### 智能特性

- **周期性模式识别**: 自动识别"每周三下午"、"工作日晚上"等发布模式
- **记忆衰退模拟**: 近期事件权重更高,快速适应习惯变化
- **低活跃期优化**: 低峰期自动延长检查间隔至30天
- **峰值预测**: 提前15天扫描,在发布高峰期提供5分钟级密集监控

**详细算法原理**: 参见 [docs/wgmm-algorithm.md](docs/wgmm-algorithm.md)

## 🔧 管理命令

### systemd 服务管理

```bash
# 启动/停止/重启
sudo systemctl start video-monitor
sudo systemctl stop video-monitor
sudo systemctl restart video-monitor

# 开机自启
sudo systemctl enable video-monitor
sudo systemctl disable video-monitor

# 查看状态和日志
sudo systemctl status video-monitor
sudo journalctl -u video-monitor -f
```

### Python 命令

```bash
# 激活虚拟环境
source .venv/bin/activate

# 开发模式: 单次检查后退出
python monitor.py --dev

# 正常模式: 持续监控
python monitor.py
```

## ⚙️ 配置调优

### 查看算法状态

```bash
# 查看当前配置
cat data/wgmm_config.json

# 查看日志中的预测结果
grep "WGMM调频" urls.log | tail -20
```

### 参数调整位置

核心参数位于 `monitor.py` 第 466-478 行:

```python
SIGMA = 0.8              # 时间相似性容忍度 (0.5-1.5)
LAMBDA = 0.0001          # 记忆遗忘速度 (0.00005-0.0005)
DEFAULT_INTERVAL = 3600  # 默认基础间隔 (秒)
MIN_INTERVAL = 300       # 最小检查间隔 (5分钟)
MAX_INTERVAL = 2592000   # 最大检查间隔 (30天)
```

**调优指南**: 参见 [docs/wgmm-algorithm.md#参数调优](docs/wgmm-algorithm.md#参数调优)

## 📚 文档导航

### 用户文档
- **[本 README](README.md)** - 快速开始和基本使用
- **[FAQ](#常见问题)** - 常见问题解答

### 开发文档
- **[docs/development-guide.md](docs/development-guide.md)** - 完整开发指南
  - 代码质量检查 (Ruff)
  - 调试技巧
  - 故障排查
  - 性能监控

### 技术参考
- **[docs/wgmm-algorithm.md](docs/wgmm-algorithm.md)** - WGMM 算法详解
  - 数学原理
  - 参数调优
  - 代码修改场景

- **[docs/code-logic-flow.md](docs/code-logic-flow.md)** - 系统架构流程
  - 主监控循环
  - 三层检测架构
  - 数据流向

- **[docs/code-reference.md](docs/code-reference.md)** - 代码参考
  - VideoMonitor 类方法分类
  - 性能优化要点

### 架构决策记录
- **[docs/adr/001-keep-python-implementation.md](docs/adr/001-keep-python-implementation.md)** - 保持 Python 实现的决策
- **[docs/adr/002-do-not-adopt-x-algorithm-techniques.md](docs/adr/002-do-not-adopt-x-algorithm-techniques.md)** - 不引入推荐系统技术的决策
- **[docs/adr/003-avoid-large-refactoring.md](docs/adr/003-avoid-large-refactoring.md)** - 采用单体架构的决策

### 贡献指南
- **[CONTRIBUTING.md](CONTRIBUTING.md)** - 贡献指南
  - 开发环境设置
  - 代码质量标准
  - 提交规范

## ❓ 常见问题

### Q1: 为什么算法会形成3天的检查间隔?

**A**: 这是 WGMM 算法通过数学计算自然涌现的结果,而非硬编码。

算法通过以下机制自然产生3天间隔:

1. **星期维度权重最高** (learned weight ≈ 0.67)
2. **sigma_week = 1.0** 使得相邻天相似度 ≈ 0.606
3. **3天间隔**能以较高相似度覆盖工作日和周末两个极端

**详细数学解释**: 参见 [docs/wgmm-algorithm.md#3天间隔的数学原理](docs/wgmm-algorithm.md#3天间隔的数学原理)

### Q2: WGMM 算法需要多少历史数据才能开始有效预测?

**A**:
- **最小10条数据**: 可以开始基础预测
- **50条数据**: 能够识别基本的周期性模式
- **100+条数据**: 稳定预测,准确识别复杂模式

### Q3: 如果UP主改变发布习惯,算法多久能适应?

**A**: 由于指数衰减权重机制:
- **2-3次新模式发布**: 开始调整预测
- **1-2周**: 完全适应新的发布习惯

### Q4: 如何重置算法学习?

**A**: 删除 `data/wgmm_config.json` 和 `data/mtime.txt`,重启程序即可重新学习:

```bash
rm data/wgmm_config.json data/mtime.txt
sudo systemctl restart video-monitor
```

### Q5: 预测频率异常怎么办?

**A**:
1. 查看日志了解当前热力得分: `grep "热力" urls.log | tail -5`
2. 检查历史数据是否正常: `wc -l data/mtime.txt`
3. 如需重新学习,参考 Q4 重置算法

### Q6: cookies.txt 过期怎么办?

**A**:
1. 重新从浏览器导出 cookies
2. 替换 `data/cookies.txt` 文件
3. 重启服务: `sudo systemctl restart video-monitor`

## 🔍 故障排查

### 系统检查

```bash
# 检查服务状态
sudo systemctl status video-monitor

# 查看详细日志
sudo journalctl -u video-monitor -n 100

# 检查配置文件
cat data/.env
ls -l data/cookies.txt
```

### 常见问题

**问题1: 服务无法启动**
- 检查 `data/.env` 文件是否存在且配置正确
- 检查 `data/cookies.txt` 是否存在
- 查看详细错误日志: `sudo journalctl -u video-monitor -n 50`

**问题2: 检测不到新视频**
- 验证 data/cookies.txt 是否过期
- 手动运行 `python monitor.py --dev` 测试
- 检查 BILIBILI_UID 是否正确

**问题3: 预测频率过长/过短**
- 正常现象,算法会根据历史数据自适应调整
- 低活跃期可能长达30天,高峰期可能短至5分钟
- 可通过重置算法重新学习 (见 Q4)

**详细故障排查**: 参见 [docs/development-guide.md#故障排查](docs/development-guide.md#故障排查)

## 📊 性能指标

| 指标 | 典型值 |
|------|--------|
| WGMM 算法计算 | ~10ms |
| 三层检测耗时 | ~2s (主要在 yt-dlp I/O) |
| 内存占用 | <10MB |
| CPU 使用率 | <1% (大部分时间在睡眠) |
| 网络请求节省率 | 60-80% (相比固定1小时间隔) |

## 🛡️ 安全性

- `data/.env` 和 `data/cookies.txt` 已被 `.gitignore` 排除
- 敏感文件不纳入版本控制
- systemd 服务使用安全沙盒设置
- 建议定期更换 GitHub Token

## 📝 开发规范

### 代码质量检查

**修改代码后必须运行**:

```bash
source .venv/bin/activate
ruff check monitor.py        # 必须通过
ruff format monitor.py       # 必须通过
```

### 提交规范

遵循 Conventional Commits 规范:

```bash
feat: 添加新功能
fix: 修复Bug
docs: 更新文档
refactor: 代码重构
```

**详细指南**: 参见 [CONTRIBUTING.md](CONTRIBUTING.md)

## 🤝 贡献

欢迎贡献! 请先阅读 [CONTRIBUTING.md](CONTRIBUTING.md) 了解:
- 开发环境设置
- 代码质量标准
- 提交规范
- 架构决策原则

## 📄 许可证

MIT License

## 🙏 致谢

- **yt-dlp** - 强大的视频元信息获取工具
- **Bark** - 优秀的 iOS 推送服务
- **NumPy** - 高效的数值计算库

---

**需要帮助?**
- 📖 查看 [文档](#📚-文档导航)
- 🐛 [提交 Issue](https://github.com/yourusername/wgmm/issues)
- 💬 [查看 FAQ](#常见问题)
