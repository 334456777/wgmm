# ADR 004: 修复级联误检测故障

## 状态

已采纳 (Accepted)

## 日期

2026-04-01

## 当前实现说明

该故障修复已经体现在当前模块化实现中：

- 主流程：`wgmm_monitor/services/monitor.py`
- B站检测：`wgmm_monitor/services/bilibili.py`
- 上传时间保存：`wgmm_monitor/services/history.py`

本文保留事故背景和决策原因，路径已更新为当前模块位置。

## 背景 (Context)

2026-04-01 18:49 至 19:53，系统在检测到 1 个真实新视频后，级联触发多次虚假“新视频”检测，造成：

- 连续误报通知。
- `data/mtime.txt` 写入虚假时间戳。
- `data/local_known.txt` 写入冗余基础 URL。
- `data/miss_history.txt` 写入不合理负向事件。
- 短时间内多次全量扫描，进一步增加 B站限流风险。

根因链：

```text
quick_precheck 只检查 Gist 状态
    -> 本地已知但 Gist 未更新的视频反复触发完整扫描
    -> B站限流
    -> 分片展开失败
    -> 旧实现降级使用基础 URL
    -> 基础 URL 与 ?p= 展开 URL 格式不一致
    -> 多个旧视频被误判为新视频
    -> 上传时间获取失败时用当前时间兜底
    -> mtime.txt 被虚假时间戳污染
```

## 决策 (Decision)

修复三个会级联放大的缺陷，并清理被污染的数据文件。

### 1. 分片扩展失败时跳过本轮检测

当前位置：`wgmm_monitor/services/monitor.py`

```python
if not all_parts:
	self.logger.log_warning("分片扩展失败(可能被限流), 跳过本次检测")
	self.adjust_check_frequency(found_new_content=False)
	self.cleanup()
	return
```

分片展开失败通常表示限流或瞬时 I/O 异常。此时继续使用未展开的基础 URL 会产生格式不一致的集合差集，风险高于跳过本轮。

### 2. 上传时间获取失败时跳过时间戳

当前位置：`wgmm_monitor/services/history.py`

```python
upload_time = self.bilibili.get_video_upload_time(url)
if upload_time:
	timestamps.append(upload_time)
else:
	self.logger.log_warning(f"跳过时间戳保存(获取失败): {url}")
```

缺少一个正向样本可以接受，写入错误时间戳会污染 WGMM 模型。

### 3. quick_precheck 同时检查 Gist 与本地状态

当前位置：`wgmm_monitor/services/bilibili.py`

```python
all_known = set(memory_urls) | known_urls
video_exists = any(latest_id in url for url in all_known)
```

`memory_urls` 来自 Gist，`known_urls` 是本地完整已知状态。合并检查可容忍 Gist 延迟更新。

## 理由 (Rationale)

### 为什么跳过分片失败，而不是 URL 规范化

URL 规范化需要处理 BV 号、参数顺序、`?p=`、单 P 与多 P 等边界，容易引入新的脆弱逻辑。分片展开失败是瞬时错误，等待下一次检查更安全。

### 为什么跳过时间戳，而不是使用当前时间

WGMM 的训练数据是发布时间。当前检查时间不是发布时间，尤其在批量失败时会制造一组完全相同的虚假样本，严重误导 `day`、`week`、`custom_N` 等维度学习。

### 为什么合并 `memory_urls` 和 `known_urls`

本地状态已经记录刚发现但尚未同步到 Gist 的 URL。`quick_precheck()` 是完整检查的入口守门人，必须使用完整已知状态，而不是只用云端状态。

## 后果 (Consequences)

正面影响：

- 消除基础 URL 误判为新视频的路径。
- 不再向 `mtime.txt` 写入伪造上传时间。
- Gist 延迟更新不会反复触发全量扫描。
- 三个修复互相独立，任一层都能阻断部分级联。

负面影响：

- 分片扩展失败时可能延迟到下一轮才发现新内容。
- 上传时间获取失败时会少一个训练样本。

这些负面影响可接受，因为数据零污染优先于单轮检测完整性。

## 数据清理

事故后需要清理：

- `data/mtime.txt` 中的虚假时间戳。
- `data/miss_history.txt` 中由级联误检测产生的负向事件。
- `data/local_known.txt` 中冗余基础 URL。
- 必要时重新运行 WGMM 调频刷新 `data/wgmm_config.json`。

## 经验教训 (Lessons Learned)

### 状态源必须明确

`memory_urls` 是云端状态，不等于完整已知状态。入口预检查必须使用 `memory_urls | known_urls`。

### 降级路径不能制造错误数据

当外部系统失败时，可以跳过、重试或告警，但不能用看似可用的错误数据继续训练模型。

### 数据污染比漏一轮检查更严重

WGMM 可以处理稀疏样本，但错误样本会改变周期权重、sigma 和未来峰值判断。对训练数据写入要保守。

## 相关决策

- [ADR 002](002-do-not-adopt-x-algorithm-techniques.md): 不引入推荐系统技术
- [ADR 003](003-avoid-large-refactoring.md): 历史上的大型重构风险记录
