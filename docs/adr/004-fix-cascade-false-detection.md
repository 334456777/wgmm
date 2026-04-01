# ADR 004: 修复级联误检测故障

## 状态
已采纳 (Accepted)

## 日期
2026-04-01

## 背景 (Context)

### 事件概述

2026年4月1日 18:49 至 19:53 期间，系统在检测到 1 个真正新视频后，级联触发了 18 次虚假"新视频"检测，导致：
- 连续发送多条误报通知
- `mtime.txt` 被 18 条虚假时间戳污染
- `local_known.txt` 被冗余基础 URL 污染
- `miss_history.txt` 记录了 7 条不合理的负事件
- 系统在约 1 小时内执行了 10+ 次全量扫描

### 事件时间线

| 时间 | 事件 | 影响 |
|------|------|------|
| 18:49 | 正常检测到 1 个新视频 | WGMM 进入峰值响应模式 (4m27s) |
| 18:55 - 19:23 | quick_precheck 反复返回 True | Gist 未更新，连续 4 次全量扫描 |
| 19:28 | 第 5 次全量扫描，B站限流 | `get_all_videos_parallel()` 全面失败 |
| 19:31 | 降级为基础 URL → 误判 18 个"新视频" | 虚假通知 + mtime.txt 污染 |
| 19:36 | 手动备份更新 Gist | quick_precheck 恢复正常 |
| 19:52 | 系统恢复正常 | 间隔回到 2天10小时 |

### 根因链条

三个 Bug 相互级联导致故障：

```
Bug 3: quick_precheck 只检查 Gist（不检查本地状态）
  → Gist 未自动更新（需手动备份），新视频已加入本地但 memory_urls 仍为旧数据，反复触发全量扫描
  → B站限流
  → Bug 1: 分片展开失败时降级为基础 URL
  → URL 格式不匹配（无 ?p= vs 有 ?p=）
  → 18 个多P视频基础 URL 被误判为"新视频"
  → Bug 2: 上传时间获取失败时使用当前时间
  → mtime.txt 写入 18 条相同的虚假时间戳
```

#### Bug 1: 分片展开失败时降级为基础 URL（Critical）

**位置**: `monitor.py` 第 2349-2351 行

当 `get_all_videos_parallel()` 返回空（限流导致所有 yt-dlp 调用失败），代码降级使用未展开的基础 URL：

```python
# 修复前
if not all_parts:
    self.log_info("处理分片时出错, 错误已处理")
    all_parts = video_urls  # ← 基础 URL，无 ?p= 展开信息
```

基础 URL（如 `BV1xxx`）与 Gist/known_urls 中存储的展开格式（如 `BV1xxx?p=1`）不匹配，导致集合差集产生大量误判。

#### Bug 2: 上传时间获取失败时使用当前时间（Important）

**位置**: `monitor.py` 第 553、557-562 行

```python
# 修复前
current_time = int(time.time())  # 获取当前时间

for url in new_urls:
    upload_time = self.get_video_upload_time(url)
    if upload_time:
        timestamps.append(upload_time)
    else:
        self.log_warning("降级使用当前时间")
        timestamps.append(current_time)  # ← 用"现在"冒充上传时间
```

在级联故障中，18 个 URL 的上传时间获取全部失败，mtime.txt 被写入 18 条完全相同的时间戳 `1775039489`。这些虚假数据会误导 WGMM 算法认为"周三 19:31 是高频发布时间"。

#### Bug 3: quick_precheck 仅检查 Gist 不检查本地状态（Medium）

**位置**: `monitor.py` 第 1741 行

```python
# 修复前
video_exists = any(latest_id in url for url in self.memory_urls)
```

`quick_precheck()` 只检查 `self.memory_urls`（来自 Gist 的云端数据），不检查 `self.known_urls`（包含本地已检测到的视频）。Gist 不会自动更新（需要手动备份），检测到新视频后约 40 分钟才手动更新 Gist，期间 `known_urls` 已包含新视频但 `memory_urls` 仍为旧数据，导致反复触发全量扫描。

### 数据污染范围

| 文件 | 污染内容 | 影响 |
|------|----------|------|
| `mtime.txt` | 18 条虚假时间戳 `1775039489` | WGMM 学习到错误的发布模式 |
| `local_known.txt` | 23 个多P视频冗余基础 URL | 无害但冗余 |
| `miss_history.txt` | 7 条级联产生的负事件记录 | 轻微影响算法参数 |

## 决策 (Decision)

**修复三个 Bug 并清理被污染的数据文件。**

### Bug 1 修复: 跳过检测而非降级

```python
# 修复后
if not all_parts:
    self.log_warning("分片扩展失败(可能被限流), 跳过本次检测")
    self.adjust_check_frequency(found_new_content=False)
    self.cleanup()
    return
```

当分片扩展失败时，直接跳过本次检测周期。分片扩展失败是瞬时错误（限流），使用未展开的基础 URL 只会产生垃圾结果。

### Bug 2 修复: 跳过时间戳而非伪造

```python
# 修复后（删除 current_time 变量）
for url in new_urls:
    upload_time = self.get_video_upload_time(url)
    if upload_time:
        timestamps.append(upload_time)
    else:
        self.log_warning(f"跳过时间戳保存(获取失败): {url}")
```

获取失败时跳过该时间戳，不写入任何数据。缺失一个数据点远比写入一个错误数据点安全。

### Bug 3 修复: 同时检查 Gist 和本地状态

```python
# 修复后
all_known = set(self.memory_urls) | self.known_urls
video_exists = any(latest_id in url for url in all_known)
```

将 `memory_urls`（Gist）和 `known_urls`（本地）合并后再检查，容忍 Gist 手动更新间隔期间的数据不一致。

### 数据清理

1. **mtime.txt**: 删除 18 条 `1775039489` 时间戳
2. **miss_history.txt**: 删除 7 条级联产生的负事件记录
3. **local_known.txt**: 删除 23 个多P视频的冗余基础 URL
4. **wgmm_config.json**: 基于清理后的数据重新计算

## 理由 (Rationale)

### Bug 1: 为什么跳过而非 URL 规范化

| 方案 | 优点 | 缺点 |
|------|------|------|
| ✅ 跳过检测 | 简单可靠，不引入新逻辑 | 可能错过本次检测窗口 |
| ❌ URL 规范化 | 可以继续检测 | 增加脆弱逻辑，URL 格式变化时可能出问题 |

分片扩展失败是瞬时错误，等待下一个检测周期（通常几小时内）即可恢复。URL 规范化需要处理各种边缘情况（BV号提取、参数排序等），增加了复杂度和出错概率。

### Bug 2: 为什么跳过而非保守估计

| 方案 | 优点 | 缺点 |
|------|------|------|
| ✅ 跳过时间戳 | 数据零污染 | 缺失一个训练数据点 |
| ❌ 使用当前时间 | 不断点 | 污染 WGMM 训练数据 |
| ❌ 使用保守估计 | 比当前时间好 | 仍然是错误数据 |

WGMM 算法通过指数衰减加权和自适应 lambda 参数处理数据稀疏性，跳过一个数据点的影响可忽略不计。但写入错误的时间戳（尤其是大量相同的错误时间戳）会严重扭曲模型的学习结果。

### Bug 3: 为什么合并检查而非其他方案

| 方案 | 优点 | 缺点 |
|------|------|------|
| ✅ 合并 memory_urls + known_urls | 简单高效，容忍 Gist 手动更新间隔 | 无 |
| ❌ 重试 Gist 同步 | 确保 memory_urls 最新 | 增加延迟和 API 调用 |
| ❌ 添加去重逻辑 | 减少冗余检查 | 需要额外状态管理 |

`known_urls` 已经是一个 Python set，合并操作成本极低。这个修改在不增加任何复杂度的前提下消除了 Gist 手动更新间隔期间数据不一致导致的级联触发。

## 后果 (Consequences)

### 正面影响

1. ✅ **消除级联故障路径**: 三个 Bug 中的任何一个被修复都能独立阻止本次故障
2. ✅ **数据完整性**: 不再向 mtime.txt 写入虚假时间戳
3. ✅ **Gist 更新间隔容忍**: 即使 Gist 尚未手动更新，也不会触发重复全量扫描
4. ✅ **代码更简洁**: Bug 1 修复后减少了 fallback 逻辑的复杂度

### 负面影响

1. ⚠️ **检测窗口可能错过**: 分片扩展失败时会跳过整个检测周期，如果恰好在视频发布时被限流，可能延迟数小时才能检测到
2. ⚠️ **时间戳可能不完整**: 上传时间获取失败时不保存，可能导致 WGMM 训练数据少于实际发布数量

### 中性影响

1. 📝 **quick_precheck 行为变化**: 现在检查 Gist + 本地状态，之前仅检查 Gist。在正常情况下行为一致，仅在 Gist 尚未手动更新时有差异
2. 📝 **分片扩展失败时不再降级**: 之前的降级行为虽然有问题，但在非限流场景下可以正常工作

### 权衡结论

⚠️ 两个负面影响都是可接受的：
- 限流是瞬时错误，下一个检查周期通常在几小时内，延迟可接受
- WGMM 算法设计上就能处理稀疏数据，少量缺失不影响准确性

✅ 三个修复提供了多层防御：
- 即使 Bug 3 未修复（Gist 仍未手动更新），Bug 1 会阻止误检测
- 即使 Bug 1 未修复（限流仍然发生），Bug 2 会阻止数据污染
- 即使 Bug 2 未修复（时间戳仍然伪造），Bug 3 会减少触发频率

## 相关决策

- **ADR 001**: 保持 Python 实现（✅ 继续有效）
- **ADR 002**: 不引入推荐系统技术（✅ 继续有效）
- **ADR 003**: 采用单体架构（✅ 继续有效，本次修复仅改动 ~15 行代码）

## 经验教训 (Lessons Learned)

### Bug 3 为什么难以察觉

这是很常见的认知盲区，几个原因：

**1. "两层防御"之间的隐含假设**

设计了双层 URL 管理（`memory_urls` + `known_urls`），但 `quick_precheck()` 只用了其中一层。在代码审查时，大脑会自动假设"既然已有 `known_urls` 的完整检查（第 2359-2360 行），`quick_precheck` 用哪层都行"——但实际上 `quick_precheck` 是入口守门人，它决定了是否进入后面的完整检查。

**2. 正常情况下行为一致**

`quick_precheck` 用 `memory_urls` 还是 `memory_urls | known_urls`，在 Gist 已更新时结果完全相同。这个 bug 只在检测到新视频后、手动更新 Gist 前的窗口期内才暴露（本次约 40 分钟），本地测试几乎不可能复现。

**3. 关注点在别处**

`quick_precheck` 的注释和意图是"快速 ID 检查"，审查时注意力集中在 yt-dlp 调用和 ID 提取的正确性上，而不是数据源选择。数据源用的是 `self.memory_urls` 这个名字，语义上看起来就是"已知的"，容易产生"够用了"的错觉。

**4. 单个 bug 无害，级联才致命**

即使 Bug 3 触发了重复全量扫描，正常情况下也不会出问题——是 B站限流 + Bug 1 降级 + Bug 2 伪造时间戳三者叠加才导致故障。这种多条件组合的故障路径靠人工审查极难预见。

**简单说**：不是疏忽了，是这类"只在特定时序窗口才显现"的逻辑缺陷，几乎不可能通过代码审查发现，只有跑在生产环境遇到真实事件才会暴露。
