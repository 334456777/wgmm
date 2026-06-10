# WGMM 建模改进研究（第二轮）：ADR 006 之后还剩什么结构空间

**研究对象**：仓库当前 WGMM 源码（已含 ADR 006 首峰解码，commit `992fb17` 之后）。
**实验样本**：`data/mtime.txt` 快照（408 行 → 去重 306 → 600s 链式聚合 223 个发布事件，2024-06-30 → 2026-06-02，跨度 702 天）+ `data/miss_history.txt`（54 条负向事件）。
**验证协议**：随机化 walk-forward 交叉验证，N=40 切分点 × expanding/sliding 双模式 × 3 个随机 seed（42/7/123），每口径 995 次预测，误差单位小时。
**一句话结论**：在首峰解码之后，**没有任何候选建模机制能再带来系统性的 MAE 下降**——当前 WGMM 的 L1 误差（67.8h）已贴住该序列"事后最优常数预测器"的无条件下界（67.35h，差 0.7%），信息论分析证明剩余可利用的条件信息（≲5% 边缘熵）不足以撼动由重尾间隔主导（91% 误差质量）的 L1 积分。**建议：一行代码都不改**；本报告的产出是判据与边界，而非补丁。

---

## 1. 建模改进增益表（核心结果）

口径：**expanding 模式，seed=42，N=40 切分点，995 次预测**。Δ 均为「该模型 − WGMM baseline」的逐切分点配对差，均值 ± 标准差（N=40 个切分点的 MAE 之差）；负值 = 比 baseline 好。win = 该模型在 40 个切分点中胜出的比例；p = 双侧符号检验。**判定增益的标准：均值下降且标准差不爆炸**。

| # | 建模改进（机制） | 对应假设缺口 | ΔMAE (h) 均值±标准差 | Δ% | ΔRMSE% | win | p | 结论 |
|---|---|---|---:|---:|---:|---:|---:|---|
| 1 | 纯更新过程（间隔对数 KDE + 中位数解码，完全不用日历） | A1 无等待时间结构 | **−0.05 ± 4.74** | −0.1% | −3.8% | 0.47 | 0.87 | 统计等价 → **放弃**（但它是关键诊断，见 §3.1） |
| 2 | 组合（联合核 × 条件 × 衰减更新密度） | A1+A2+A3+A6 | +0.53 ± 4.17 | +0.8% | −0.6% | 0.50 | 1.00 | 放弃（机制叠加无协同） |
| 3 | 非平稳：模型自身 λ 复用到更新密度 | A6 平稳假设 | +0.58 ± 5.54 | +0.9% | −3.1% | 0.30 | 0.017 | 放弃 |
| 4 | 核宽：留一似然全局带宽 | A4 启发式带宽 | +1.03 ± 3.06 | +1.5% | −2.4% | 0.42 | 0.43 | 放弃（复证 ADR 006-2d） |
| 5 | 核宽：Abramson 局部自适应带宽 | A4 全局单带宽 | +1.13 ± 3.13 | +1.7% | −2.4% | 0.40 | 0.27 | 放弃（复证 ADR 006-2d） |
| 6 | 非平稳：固定 90 天半衰期衰减 | A6 平稳假设 | +1.34 ± 3.86 | +2.0% | −1.9% | 0.30 | 0.017 | 放弃（复证 ADR 006-2b） |
| 7 | 概率化重构：周期得分 × 更新密度 + 中位数解码 | A1×A5 | +1.60 ± 2.73 | +2.3% | −1.8% | 0.25 | 0.0022 | 放弃（显著小幅更差） |
| 8 | 序列依赖：Markov-1 条件更新密度（NW 核加权） | A3 丢弃序列顺序 | +1.75 ± 2.87 | +2.6% | −1.9% | 0.28 | 0.0064 | 放弃（复证 ADR 006-2a，MI 佐证见 §5） |
| 9 | 概率化重构：泊松首达重释（生存函数中位数解码） | A5 得分非概率 | +2.06 ± 7.92 | +3.0% | **−8.1%** | 0.40 | 0.27 | MAE 判据下放弃；**唯一系统性形状改进**（尾部误差 −16%，6 个 run 全部一致，见 §3.2） |
| 10 | 多尺度联合：加权乘积（联合）周期核 | A2 维度可加 | +3.25 ± 2.23 | +4.8% | +0.6% | 0.07 | <10⁻⁴ | 放弃（显著更差，复证 ADR 006-2c） |
| 11 | 对比度归一化周期因子 max(s−s̄,0) × 更新密度 | A5 DC 偏置 | +3.89 ± 5.14 | +5.7% | +3.6% | 0.17 | <10⁻⁴ | 放弃 |
| 12 | 组合密度上的首峰解码 | 解码×密度交叉项 | +9.66 ± 9.86 | +14.2% | −0.7% | 0.28 | 0.0064 | 放弃 |
| 诊断 | 周期得分(15天)直接当密度取中位数 | A5 的反证 | +69.91 ± 29.75 | +102.9% | +28.6% | 0.00 | <10⁻⁵ | **诊断**：score 不是到达密度 |
| 诊断 | 周期得分(45天)直接当密度取中位数 | A5 的反证 | +399.01 ± 42.98 | +587.5% | +287.8% | 0.00 | <10⁻⁵ | 同上（视野越长崩得越狠） |
| 参照 | 无条件中位数预测器 t_last + median(Δt) | — | −0.03 ± 4.42 | −0.0% | −3.5% | 0.47 | 0.87 | **参照线**：baseline 与之统计打平 |

**Baseline（仓库源码原样，首峰解码）：MAE 67.92 ± 26.79 h，RMSE 122.62 ± 60.20 h，MedAE 22.71 h。**
**该测试集的无条件 L1 下界（事后最优常数 = 测试间隔中位数 30.5h）：MAE = 67.35 h。** Baseline 距下界 0.48h（0.7%）。

sliding 模式与另外两个 seed 的全部结果方向一致（§4.3、§4.4）；没有任何机制在任何口径下同时满足「均值下降且标准差不爆炸」。

---

## 2. WGMM baseline：源码读出的数学结构与隐含假设

### 2.1 数学结构（以 `wgmm_monitor/wgmm/` 源码为准）

设正向事件集 E = {tᵢ}（`mtime.txt` 经去重 + 600s 链式聚合为 UP 主行为粒度，`aggregate_publish_events`），负向事件集 M = {mⱼ}（`miss_history.txt` 经 3×IQR 间隔过滤，`filter_outliers`）。

**特征映射**（`features.py`）：每个时刻 t 映射到 4+K 个周期维度的单位圆嵌入 φ_d(t) = (sin, cos)：

- `day`：当日秒数 / 86400（本地时区，生产环境为 Asia/Shanghai）
- `week`：本周秒数 / 604800
- `month_week`：月内第几周 / 6
- `year_month`：月份 / 12
- `custom_k`：t mod P_k（P_k 为自相关周期发现的 ≤3 个非日历周期；注意此维用原始 UTC 时间戳）

**得分**（`scoring.py`）：目标时刻 t 对单一事件源的得分为指数遗忘加权的日历相似度平均：

```
s⁺(t) = [ Σᵢ 1{tᵢ≤t} · e^(−λ⁺·ageᵢ) · Σ_d ω_d · e^(−‖φ_d(t)−φ_d(tᵢ)‖² / 2σ_d²) ]
        / [ Σᵢ 1{tᵢ≤t} · e^(−λ⁺·ageᵢ) ] / Σ_d ω_d        ∈ [0,1]
s(t)  = clip( s⁺(t) − r·s⁻(t), 0, 1 ),   r = clip(0.7 + 0.2/(1+cv), 0.5, 0.95)
```

其中 ageᵢ = (t−tᵢ)/3600 小时，**维度组合是加性的**（Σ_d ω_d K_d，边缘核的凸组合），归一化分母 Σᵢ wᵢ 使 s 成为「相似度均值」而非密度。

**学习**（`learning.py`）：全部为启发式而非似然/预测目标驱动——λ 由间隔方差自适应（[0.3, 15]×λ₀，λ₀=10⁻⁴/h）；ω_d ∝ 该维离散直方图的 均值/标准差（集中度），归一化到和=2 后 EMA；σ_d = 3×归一化标准差，裁剪 [0.2,3] 后 EMA(0.7/0.3)；周期发现 = 小时分箱计数的 FFT 自相关峰（滞后 48h–90d，排除日/周/月/年 ±20% 及互谐波，取前 3）。

**预测/解码**（`scheduler.py`，ADR 006 后）：自 now 起 15 天网格扫描 s(t)，取**首个得分高于扫描均值的局部峰**作为"下一次发布时间"；当前得分相对 [min,max] 的位置经 γ=2 幂映射插值出检查间隔 ∈ [P20(间隔), 峰距]。

### 2.2 隐含建模假设（候选改进对应的结构缺口）

- **A1 纯日历条件强度**：s(t) 只依赖 t 的日历相位与事件年龄，不含 t − t_last 项——没有更新过程/等待时间结构（首峰解码隐式补了一部分：取"最近的模态"）。
- **A2 维度可加**：Σ_d ω_d K_d 是边缘核混合，表达不了维度合取（如"周五∧晚间"≠"周五"+"晚间"）。
- **A3 袋装事件（可交换性）**：事件作为加权袋处理，相邻间隔的序列相关性被丢弃。
- **A4 似然无关的启发式学习**：λ/ω/σ 由方差与集中度启发式确定，每维一个全局带宽。
- **A5 得分非概率**：s(t) 是 [0,1] 相似度，不归一化、不积分为 1，**不是下一次到达时间的密度**——因此只能取峰解码，无法给出 L1 最优点估计（条件中位数）或预测区间。
- **A6 平稳 + 全局指数遗忘**：非平稳性仅以单一 λ 的指数衰减表达。

### 2.3 数据格式探测（实验样本）

`mtime.txt`：408 行，全部为纯数字 Unix 秒时间戳（单列、无表头、文件内乱序）；102 个完全重复值（多 P 视频共享同一 ctime），去重后 306；按仓库自己的 600s 链式聚合折成 **223 个发布事件**。间隔分布重尾：中位 28.3h，均值 75.9h，P25=4.4h（爆发式连发），P90=192h，P99=590h，CV≈2.4；P(Δt>15天)=3.2%，P(Δt>45天)=0.45%。`miss_history.txt`：54 条 Unix 秒负向事件，仅覆盖 2026-01-14 之后（实验中按因果时点取子集，早期切分点负向集为空，与生产冷启动一致）。

---

## 3. 各项改进详述

### 3.1 概率化重构（A5 + A1）：score 不是到达密度，首峰解码 ≈ 隐式更新先验

**数学动机**。点过程预测的标准分解是 f(t | 历史) ∝ 周期调制 × 等待时间密度。WGMM 只有前者，且 s(t) 不是密度（A5）。若 s(t) 真是"下一次发布"的密度，那么对它取**中位数**（L1 最优点估计）应当不差于取峰。

**数值证据（诊断阶梯）**：

| 密度假设 | 解码 | MAE (h) | 相对 baseline |
|---|---|---:|---:|
| s(t) 当密度，15 天视野 | 中位数 | 137.8 | +102.9% |
| s(t) 当密度，45 天视野 | 中位数 | 466.9 | +587.5% |
| s(t) 重释为泊松强度（标定到平均间隔） | 生存中位数 | 70.0 | +3.0%（RMSE −8.1%） |
| s(t) × 间隔 KDE（更新调制） | 中位数 | 69.5 | +2.3% |
| 纯间隔 KDE（无日历） | 中位数 | 67.9 | −0.1% |
| **s(t) + 首峰解码（源码现状）** | 首峰 | **67.9** | 0 |

视野越长、中位数解码崩得越狠（s 是准平稳周期信号，其质量中位数落在视野中部）——**证明 s(t) 在结构上不是到达密度**。而把更新结构补进去后（s×g 或纯 g），中位数解码立即恢复到 baseline 水平。结论：**ADR 006 的首峰解码已经隐式补上了更新先验**——score 在 now 附近被"刚发生的事件自身的核"抬高（age≈0 时遗忘权重=1、自相似度=1），首峰因此天然落在近处，等效于一个爆发跟随机制。分层数据证实（§4.2）：短间隔段（<24h）baseline 10.9h vs 无条件中位数 18.6h（**−40%**），这正是日历+首峰结构的真实价值所在。

**为何可推广**：任何"日历相似度"型得分（不止 WGMM）都不能直接归一化当预测密度用——这是结构性质（周期平稳信号的质量中位数与首达时间无关），换任何数据都成立。同时"显式更新密度 × 周期得分"不优于"首峰解码"也有一般性原因：两者编码的是同一信息（最近模态 + 间隔尺度），显式乘积反而引入 KDE 的估计方差。**结论：放弃显式概率化（0 增益 + 新增方差），确认首峰解码为正确的轻量等价物。**

### 3.2 泊松首达重释：唯一的系统性"形状"改进（A5）

把 s(t) 重释为非齐次泊松强度 λ(t) = c·s(t)（c 标定为视野内期望事件数 = 视野/平均间隔），预测 = 生存函数 S(t)=exp(−∫λ) 的 0.5 分位点。**6 个 run（3 seed × 2 模式）全部一致**：ΔMAE +1.0~+3.3h（+1.5~+5%），ΔRMSE **−7.4~−8.7%**。分层归因：长间隔段（96–360h）误差 141.9h vs baseline 168.1h（−16%），代价是短间隔段 41.0h vs 10.9h（中位预测后移：MedAE 43.1h vs 22.7h）。

**为何可推广**：生存中位数 = ln2/平均强度 量级，天然比"首峰"更靠后，从而在重尾分布上以牺牲典型情形换取尾部平方误差——这是解码目标函数的一般性质，与具体数据无关。**结论：MAE 判据下放弃。但若未来调度损失更接近 RMSE（极端漏检代价高），这是现成的、一行式的 Pareto 选项。**

### 3.3 序列依赖（A3）：Markov-1 条件核——放弃，且给出可推广的预检判据

**动机**：相邻间隔若相关（人类活动的爆发性，Barabási 式机制），条件密度 g(Δ|Δ_prev) 应优于边缘 g(Δ)。实现为对历史间隔按 log Δ_prev 相似度做 Nadaraya-Watson 加权的 KDE。

**证据**：expanding +1.75±2.87h（win 28%，p=0.0064，显著更差）；sliding −0.25±3.75（噪声内）。信息论直接解释（§5）：六分位离散下 I(Δtₖ; Δtₖ₋₁)=0.054 bits，仅占边缘熵 2.585 bits 的 **2.1%**，循环移位代理检验 p=0.94——**该序列的相邻间隔在统计上不可区分于独立**。ADR 006 第一轮研究的独立估计（0.09–0.17 nats / 2.47 nats ≈ 3.5–6.9%）同方向。

**可推广判据（方法论产出）**：对任意新的发布序列，先做带代理检验的 MI 预检；MI 占比 <~15% 或 p>0.05 时，任何序列模型（Markov/核回归/注意力）的期望增益都低于估计方差，不值得上。**结论：放弃。**

### 3.4 非平稳性（A6）：两种衰减 + 窗口化全部中性——放弃

**动机**：若 UP 主行为漂移，近期间隔应比远期更有预测力。测试三种实现：① 把模型自身的自适应 λ（本数据 ≈8×10⁻⁴/h，半衰期≈36 天）复用到更新密度的样本权重（零新增超参）；② 固定 90 天半衰期；③ sliding 窗口（W=60 事件）整体对照。

**证据**：① +0.58±5.54h；② +1.34±3.86h；③ baseline 自身 expanding 67.9h vs sliding 69.2h——**截断历史使 baseline 变差**，三条证据互相印证：该序列没有可变现的漂移结构，WGMM 现有的 λ 指数遗忘已覆盖可用的非平稳性。复证 ADR 006-2b（EWMA 零影响）。

**为何可推广**：expanding vs sliding 的系统对比本身就是漂移检测器——若窗口化不能降误差，加权衰减也不会（窗口化是衰减的极限形式）。**结论：放弃。**

### 3.5 多尺度联合结构（A2）：联合核显著更差——复证 ADR 006-2c

**动机**：加性边缘混合表达不了"周五∧晚间"式合取；把组合方式换成加权乘积核 exp(−Σ_d ω_d·d²_d/2σ_d²)（等价于积空间上的 Mahalanobis 联合核），其余完全同源码。

**证据**：expanding +3.25±2.23h（win 7%，p<10⁻⁴），sliding +4.20±5.12（p=0.0007），三 seed 一致（+2.9~+4.2h）。ADR 006 第一轮用独立实现（hour×wday 2D 核）得到同向结论（+35%；本轮因保留了更新项，恶化幅度小得多但方向相同）。

**为何可推广**：n≈200 事件、4+K 维上，联合核的方差代价（每个核覆盖的有效样本数按维度指数缩减）大于合取偏置的收益；且周期分量在 L1 中本来就被等待时间项压制（§4.2：长尾贡献 91% 误差），在被压制的分量里精修交互结构是二阶修正。样本量判据：联合核需要每个"日历格"内有足够事件（此处 24×7 格 ≈ 1.3 事件/格——远不够）。**结论：放弃。**

### 3.6 核宽自适应（A4）：Silverman ≈ LOO ≈ Abramson——放弃

**证据**：留一似然全局带宽 +1.03±3.06h；Abramson 局部带宽 +1.13±3.13h；两者与 Silverman 规则（renew_x_per，+1.60）在彼此噪声内。复证 ADR 006-2d（kNN 局部 σ 零改善）。**为何可推广**：~200 样本的一维（对数间隔）KDE 处于带宽不敏感区；带宽优化只在样本量小一个数量级或维度更高时才可能成为约束。**结论：放弃。**

### 3.7 其余变体（附注）

- **对比度归一化** max(s−s̄,0)：+3.89h。去除 DC 后把质量过度集中到峰附近，放大了周期分量的估计噪声——「显著性判据适合选峰，不适合重整密度」。放弃。
- **组合密度上的首峰解码**：+9.66h。KDE 的平滑峰与 score 的相位峰相乘后峰位偏移，两种"峰语义"不可交换。放弃。
- **全机制组合**（联合核×条件×衰减）：+0.53h——各机制单独无增益，叠加也无协同。放弃。

---

## 4. 验证方法

### 4.1 协议

- **任务定义**：在第 i 个发布事件的链末时刻（该次发布行为的最后一个时间戳）作为锚点，预测下一个发布事件（链起点）的绝对时间；误差 = |预测 − 实际| 小时。
- **切分**：k 均匀随机采样于事件序列的 [30%, 95%]（即 k ∈ [67, 211]），N=40 个不重复切分点；train = 前 k 个事件，test = 其后事件，每切分最多走 25 步，共 995 次预测/口径。
- **expanding**：走步时历史持续增长；**sliding**：历史固定为最近 60 个事件。两种都跑（§4.3）。
- **因果性**：所有学习（λ、周期发现、ω、σ、KDE、带宽）只用锚点之前的数据；目标严格在锚点之后。**无 embargo**：下一事件预测的 train/test 边界就是锚点本身，特征不跨界，不存在标签重叠泄漏（embargo 针对固定视野回归的标签重叠场景，此处不适用）。
- **生产保真**：直接 `import wgmm_monitor.wgmm.*` 调用仓库源码；每个切分点先空跑 20 次学习流程，模拟生产环境每次检查都运行 `decide_next_frequency` 导致的 EMA 收敛（ω/σ/方差状态随走步演化）；时区设为 Asia/Shanghai（`day`/`week` 特征依赖本地时区）。
- **统计口径**：每切分点算 MAE/RMSE，报告 N=40 个切分点的均值±标准差；相对 baseline 的 Δ 为逐切分点配对差。**已知局限**：不同切分点的测试窗口重叠，40 个 MAE 并非独立样本（标准差略偏小），故同时报告 win rate、符号检验，并用 3 个 seed 复核。

### 4.2 误差分层归因（expanding，seed=42，995 次预测）

测试间隔分布：中位 30.5h，均值 77.1h，P(>360h)=1.7%。**长于中位数的间隔贡献了 91% 的 baseline 总误差质量**——L1 由重尾主导。

| 模型 | 短 <24h (n=430) | 中 24–96h (n=302) | 长 96–360h (n=246) | 极长 >360h (n=17) | MedAE | MAE |
|---|---:|---:|---:|---:|---:|---:|
| WGMM baseline | **10.9** | 33.6 | 168.1 | 665.4 | **22.7** | 67.8 |
| 无条件中位数 | 18.6 | **26.0** | 165.0 | 649.7 | 24.1 | 67.8 |
| 纯更新 KDE | 19.7 | 25.2 | 164.0 | 648.7 | 25.6 | 67.8 |
| 泊松首达 | 41.0 | 20.5 | **141.9** | **637.5** | 43.1 | 69.9 |
| s×g 概率化 | 17.4 | 29.8 | 168.5 | 656.9 | 24.8 | 69.5 |
| 联合乘积核×g | 13.4 | 36.8 | 172.7 | 668.7 | 23.7 | 71.1 |

解读：baseline 的日历结构在短间隔段真实有效（−40% vs 无条件中位数），但在中/长段反向损耗，总 MAE 与"瞎猜中位数"精确打平；各改进只是在分段之间搬运误差。**没有任何模型能同时拿下两端**——因为"下一个间隔属于哪个分段"恰恰是 MI≈0 所证明的不可知信息。

### 4.3 expanding vs sliding 对比（seed=42）

| 模型 | expanding MAE±std | expanding ΔMAE | sliding MAE±std | sliding ΔMAE |
|---|---:|---:|---:|---:|
| WGMM baseline | 67.92 ± 26.79 | 0 | 69.18 ± 26.56 | 0 |
| 无条件中位数 | 67.89 ± 24.06 | −0.03 ± 4.42 | 66.88 ± 24.03 | −2.30 ± 4.73 |
| 纯更新 KDE | 67.87 ± 23.93 | −0.05 ± 4.74 | 67.80 ± 24.39 | −1.38 ± 4.21 |
| 泊松首达 | 69.98 ± 21.38 | +2.06 ± 7.92 | 70.60 ± 22.07 | +1.42 ± 6.74 |
| s×g 概率化 | 69.52 ± 24.98 | +1.60 ± 2.73 | 70.44 ± 25.41 | +1.26 ± 3.53 |
| Markov-1 条件 | 69.68 ± 25.11 | +1.75 ± 2.87 | 68.93 ± 24.89 | −0.25 ± 3.75 |
| λ 复用衰减 | 68.51 ± 24.78 | +0.58 ± 5.54 | 69.93 ± 25.06 | +0.75 ± 3.96 |
| 联合乘积核 | 71.17 ± 26.03 | +3.25 ± 2.23 | 73.38 ± 27.09 | +4.20 ± 5.12 |

sliding 中无条件中位数名义上最优（−2.30h）但 p=0.15 不显著；expanding 下 baseline 不输任何模型。**baseline 自身 expanding 优于 sliding（−1.3h）**：截断历史有损，进一步否证漂移结构。

### 4.4 多 seed 稳健性（expanding，ΔMAE h）

| 模型 | seed 42 | seed 7 | seed 123 | ΔRMSE%（三 seed） |
|---|---:|---:|---:|---|
| 无条件中位数 | −0.03 | −0.27 | −0.11 | −3.4 ~ −3.5 |
| 纯更新 KDE | −0.05 | −0.20 | −0.07 | −3.6 ~ −3.8 |
| 泊松首达 | +2.06 | +2.89 | +3.28 | **−7.4 ~ −8.1** |
| s×g 概率化 | +1.60 | +0.67 | +1.35 | −1.8 ~ −2.3 |
| Markov-1 条件 | +1.75 | +0.89 | +1.86 | −1.9 ~ −2.6 |
| λ 复用衰减 | +0.58 | +0.60 | +0.55 | −2.7 ~ −3.1 |
| 联合乘积核 | +3.25 | +2.86 | +3.33 | +0.4 ~ +0.6 |
| 局部带宽 | +1.13 | +0.27 | +0.92 | −2.4 ~ −2.9 |

baseline MAE 三 seed：67.9 / 66.8 / 64.2h（seed 间波动 ±1.9h ≈ ±3%）。**所有机制的 |ΔMAE| 均不超过 seed 噪声带，方向跨 seed 一致。**

---

## 5. 信息论可预测性标尺（不确定性度量）

把 222 个对数间隔按六分位离散（等概率分箱，边缘熵恒为 log₂6 = 2.585 bits），互信息及循环移位代理检验（2000 次移位，保边缘破依赖）：

| 量 | 数值 | 解读 |
|---|---|---|
| H(Δt)（六分位） | 2.585 bits | 边缘不确定性（分箱构造下的满熵） |
| I(Δtₖ; Δtₖ₋₁) | 0.054 bits（**2.1%**） | 代理检验 p=0.94 → **与独立不可区分** |
| I(Δtₖ; Δtₖ₋₁)（octave 分箱稳健性） | 0.54 bits | p=0.28 → 同样不显著（14 个稀疏箱的插件估计偏置） |
| I(Δt; 锚点时段)（4h 分桶日历信息） | 0.083 bits（**3.2%**） | p=0.0485，边缘显著——日历对间隔确有微弱信息 |
| ADR 006 第一轮独立估计 | 0.09–0.17 nats / 2.47 nats（3.5–6.9%） | 两轮独立估计同量级 |

**增益预算论证**：序列 + 日历可利用的条件信息合计 ≲5% 边缘熵。即使全部完美变现，期望 MAE 改善也只有个位数百分比——恰好是观测到的 ±3% seed 噪声带量级。这解释了**全部**实验结果：不是实现不好，而是信息不存在。配合 §1 的下界对照（baseline 距事后最优常数仅 0.7%），结论是封闭的：

> **该序列在 UP 主行为粒度上近似"无记忆重尾更新过程 + 微弱日历调制"。WGMM（ADR 006 后）已把这两块都吃掉了：日历调制由首峰解码变现（短间隔段 −40%），重尾部分则无人能赢。**

**可推广的预检清单**（对任何新的发布时间序列，跑改进之前先算这四个数）：

1. 间隔 CV 与长尾误差占比（>0.5 即 L1 被尾部锁死，条件机制空间极小）；
2. 带代理检验的 I(Δtₖ; Δtₖ₋₁)（<15% 边缘熵或 p>0.05 → 不上序列模型）；
3. expanding vs sliding 的 baseline 对照（sliding 不优 → 不上非平稳机制）；
4. baseline MAE 与"事后最优常数"下界的距离（<5% → 只剩误差形状可调，考虑 §3.2 的生存中位数解码换 RMSE）。

---

## 6. 与 ADR 006 的关系

| 机制 | ADR 006 第一轮结论 | 本轮（独立实现）结论 | 一致性 |
|---|---|---|---|
| 首峰解码 | 并入（−57% MAE） | 作为 baseline，复证其 67.3h ≈ 本轮 67.9h | ✓ |
| 序列依赖 | 放弃（−2.9%，噪声内） | 放弃（+2.6%，MI p=0.94） | ✓ |
| 非平稳 | 放弃（EWMA 零影响） | 放弃（两种衰减+窗口化全中性） | ✓ |
| 多尺度联合 | 放弃（+35%） | 放弃（+4.8%，方向一致） | ✓ |
| 局部带宽 | 放弃（−0.1%） | 放弃（+1.7%；LOO 带宽亦中性） | ✓ |
| 概率化重构/泊松首达 | （未测） | 放弃（MAE）；记录为 RMSE−8% 的 Pareto 选项 | 新增 |
| 下界与信息论封闭论证 | 部分（MI nats） | 完整（L1 下界 + MI 代理检验 + 分层归因） | 新增 |

本轮全部结论支持维持现状；无需新 ADR（无代码变更），若未来需要 RMSE 取向的调度损失，可引用 §3.2。

---

## 7. 复现

环境：Python ≥3.10 + numpy（仓库 `requirements.txt` 已含）；在**仓库根目录**运行（脚本依赖 `import wgmm_monitor`）；数据放 `data/mtime.txt`、`data/miss_history.txt`。脚本不保留为仓库文件，全文嵌入如下；保存为任意路径后：

```bash
python3 wgmm_improvement_experiment.py --mtime data/mtime.txt --miss data/miss_history.txt \
    --splits 40 --max-preds 25 --seed 42 --out results.json
```

运行约 5 分钟（单核）；`--seed 7/123` 复现稳健性表；分层归因用第二个脚本读取 `results.json`。本报告全部数字由 numpy 2.4.6 / Python 3.11.15 产生。

### 7.1 主实验脚本（wgmm_improvement_experiment.py）

```python
#!/usr/bin/env python3
"""WGMM 建模改进验证实验 — 随机化 walk-forward 交叉验证.

在仓库根目录运行:
    python3 wgmm_improvement_experiment.py --mtime data/mtime.txt --miss data/miss_history.txt

对每个随机切分点 k: train = 前 k 个发布事件, test = 其后事件(走步预测, 上限 --max-preds).
expanding = 训练集随走步增长; sliding = 固定最近 WINDOW_EVENTS 个事件.
所有模型在同一锚点/同一历史上预测"下一次发布事件的绝对时间", 误差单位小时.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time

os.environ["TZ"] = "Asia/Shanghai"  # 生产环境为中国时区; day/week 特征依赖本地时区
time.tzset()
sys.path.insert(0, os.getcwd())

import numpy as np

from wgmm_monitor.models import WgmmConfig
from wgmm_monitor.wgmm import learning as wl
from wgmm_monitor.wgmm import scheduler as wsch
from wgmm_monitor.wgmm import scoring as ws
from wgmm_monitor.wgmm.constants import LAMBDA_BASE, LOOKAHEAD_DAYS, SECONDS_IN_DAY
from wgmm_monitor.wgmm.features import vectorized_time_features_numpy

GRID_STEP = 600.0        # 改进模型密度网格步长(秒)
HORIZON_DAYS = 45        # 改进模型预测视野(天), 覆盖 99.5% 的历史间隔
WINDOW_EVENTS = 60       # sliding 模式训练窗口(事件数)
WARMUP_FITS = 20         # 每个切分点先空跑 N 次学习, 模拟生产环境 EMA 收敛
MIN_POS = 10             # 与 MIN_HISTORY_COUNT 一致


# ---------------- 数据加载(镜像 HistoryStore.load_history_file) ----------------
def load_unique_ts(path: str) -> list[int]:
	seen: set[int] = set()
	out: list[int] = []
	for line in open(path, encoding="utf-8").read().splitlines():
		s = line.strip()
		if s.isdigit():
			v = int(s)
			if v > 0 and v not in seen:
				out.append(v)
				seen.add(v)
	return out


def chains_with_ends(sorted_ts: list[int], gap: int = 600) -> tuple[list[int], list[int]]:
	"""600s 链式聚合(同 aggregate_publish_events), 同时返回每条链的末尾时间戳."""
	starts = [sorted_ts[0]]
	ends = [sorted_ts[0]]
	prev = sorted_ts[0]
	for t in sorted_ts[1:]:
		if t - prev > gap:
			starts.append(t)
			ends.append(t)
		else:
			ends[-1] = t
		prev = t
	return starts, ends


# ---------------- 忠实复刻仓库 fit 流程(decide_next_frequency 学习段) ----------------
def wgmm_fit(pos_raw: list[int], neg_raw: list[int], now: int, cfg: WgmmConfig) -> dict:
	pos = wl.aggregate_publish_events(pos_raw, now)
	neg = wl.filter_outliers(neg_raw, now)
	lr = max(0.02, min(0.2, 0.3 - len(pos) * 0.001))
	pos_l, pos_v = wl.calculate_adaptive_lambda(pos, cfg.last_pos_variance, LAMBDA_BASE)
	neg_l, neg_v = wl.calculate_adaptive_lambda(neg, cfg.last_neg_variance, LAMBDA_BASE)
	cfg.discovered_periods = wl.sync_discovered_periods(
		cfg.discovered_periods, wl.discover_periods(pos)
	)
	extra = list(cfg.discovered_periods)
	w0, s0 = wl.initialize_wgmm_dimensions(cfg)
	weights = wl.learn_dimension_weights(pos, w0, lr, extra)
	sigmas = {k: float(v) for k, v in wl.learn_adaptive_sigmas(pos, s0, extra).items()}
	iv = np.diff(np.array(sorted(pos), dtype=np.float64))
	cv = float(np.std(iv) / np.mean(iv)) if len(iv) > 0 and np.mean(iv) > 0 else 1.0
	res = float(np.clip(0.7 + 0.2 / (1.0 + cv), 0.5, 0.95))
	cfg.dimension_weights = weights
	cfg.sigmas = sigmas
	cfg.last_lambda = pos_l
	cfg.last_pos_variance = pos_v
	cfg.last_neg_variance = neg_v
	cfg.last_update = now
	return {
		"pos": pos, "neg": neg, "w": weights, "sg": sigmas,
		"pos_l": pos_l, "neg_l": neg_l, "res": res, "extra": extra,
		"iv_h": iv / 3600.0,
	}


# ---------------- M0: 源码原样的 WGMM 预测(首个显著峰, ADR 006) ----------------
def predict_baseline(fit: dict, now: int) -> float:
	cs = ws.calculate_point_score(
		now, fit["pos"], fit["neg"], fit["w"], fit["pos_l"], fit["neg_l"],
		fit["sg"], fit["res"], fit["extra"],
	)
	gw = fit["sg"]["day"] * SECONDS_IN_DAY / 24.0 * 2.0
	peak_t, _peak_s, _stats = wsch.scan_future_peak(
		current_timestamp=now, lookahead_days=LOOKAHEAD_DAYS, gaussian_width=gw,
		current_score=cs, positive_events=fit["pos"], negative_events=fit["neg"],
		dimension_weights=fit["w"], pos_lambda=fit["pos_l"], neg_lambda=fit["neg_l"],
		sigmas=fit["sg"], resistance_coefficient=fit["res"], extra_periods=fit["extra"],
	)
	return float(peak_t)


# ---------------- 密度构件 ----------------
def score_grid(fit: dict, now: int, horizon_s: float) -> tuple[np.ndarray, np.ndarray]:
	"""仓库原版加性(边缘和)周期得分, 在网格上批量计算."""
	ts = np.arange(now + GRID_STEP, now + horizon_s + GRID_STEP, GRID_STEP)
	sc = ws.batch_calculate_scores(
		ts, fit["pos"], fit["neg"], fit["w"], fit["pos_l"], fit["neg_l"],
		fit["sg"], fit["res"], fit["extra"],
	)
	return ts, np.maximum(sc, 0.0)


def product_score_grid(fit: dict, ts: np.ndarray) -> np.ndarray:
	"""联合(加权乘积)周期核: C_i = exp(-Σ_d ω_d·d²_d/(2σ_d²)). 其余与源码一致."""

	def source_scores(events: list[int], lam: float) -> np.ndarray:
		if not events:
			return np.zeros(len(ts), dtype=np.float64)
		ev = np.array(events, dtype=np.float64)
		ev_feat = vectorized_time_features_numpy(ev, fit["extra"])
		tg_feat = vectorized_time_features_numpy(ts, fit["extra"])
		ages = (ts[:, None] - ev[None, :]) / 3600.0
		valid = ages >= 0
		wts = np.zeros_like(ages)
		wts[valid] = np.exp(-lam * ages[valid])
		log_kernel = np.zeros((len(ts), len(ev)), dtype=np.float64)
		for dim, weight in fit["w"].items():
			d_sq = (
				tg_feat[f"{dim}_sin"][:, None] - ev_feat[f"{dim}_sin"][None, :]
			) ** 2 + (tg_feat[f"{dim}_cos"][:, None] - ev_feat[f"{dim}_cos"][None, :]) ** 2
			log_kernel += -weight * d_sq / (2.0 * fit["sg"].get(dim, 1.0) ** 2)
		raw = wts * np.exp(log_kernel) * valid
		wsum = np.sum(wts * valid, axis=1)
		with np.errstate(divide="ignore", invalid="ignore"):
			mean = np.where(wsum > 1e-12, np.sum(raw, axis=1) / wsum, 0.0)
		return np.clip(mean, 0.0, 1.0)

	pos_s = source_scores(fit["pos"], fit["pos_l"])
	neg_s = source_scores(fit["neg"], fit["neg_l"])
	return np.maximum(pos_s - fit["res"] * neg_s, 0.0)


def silverman_bw(x: np.ndarray) -> float:
	n = len(x)
	sd = float(np.std(x))
	iqr = float(np.percentile(x, 75) - np.percentile(x, 25))
	sigma = min(sd, iqr / 1.34) if iqr > 0 else sd
	return max(0.9 * sigma * n ** (-0.2), 0.05)


def interval_kde_grid(
	iv_h: np.ndarray,
	delta_h: np.ndarray,
	weights: np.ndarray | None = None,
	adaptive: bool = False,
	fixed_h: float | None = None,
) -> np.ndarray:
	"""对数空间高斯 KDE 的更新(renewal)密度 g(Δ), 含 1/Δ Jacobian."""
	x = np.log(iv_h)
	h0 = fixed_h if fixed_h is not None else silverman_bw(x)
	if adaptive:
		pilot = np.exp(-((x[:, None] - x[None, :]) ** 2) / (2 * h0**2)).sum(axis=1)
		geo = float(np.exp(np.mean(np.log(pilot))))
		lam = np.clip(np.sqrt(geo / pilot), 0.3, 3.0)
		h = h0 * lam
	else:
		h = np.full(len(x), h0)
	w = np.ones(len(x)) if weights is None else np.asarray(weights, dtype=np.float64)
	if w.sum() < 1e-12:
		w = np.ones(len(x))
	lg = np.log(np.maximum(delta_h, 1e-6))
	dens = (w[None, :] / h[None, :] * np.exp(
		-((lg[:, None] - x[None, :]) ** 2) / (2 * h[None, :] ** 2)
	)).sum(axis=1)
	return dens / np.maximum(delta_h, 1e-6)


def loo_bandwidth(x: np.ndarray) -> float:
	"""留一对数似然在 Silverman 邻域内选全局带宽."""
	h0 = silverman_bw(x)
	d2 = (x[:, None] - x[None, :]) ** 2
	np.fill_diagonal(d2, np.inf)
	best_h, best_ll = h0, -np.inf
	for f in np.geomspace(0.25, 3.0, 12):
		h = h0 * f
		dens = np.exp(-d2 / (2 * h * h)).sum(axis=1) / ((len(x) - 1) * h)
		ll = float(np.log(np.maximum(dens, 1e-300)).sum())
		if ll > best_ll:
			best_ll, best_h = ll, h
	return best_h


def peak_decode(ts: np.ndarray, dens: np.ndarray) -> float | None:
	"""镜像 ADR 006 的解码: 首个高于均值的局部峰, 无则取最高峰."""
	if dens.sum() <= 1e-300:
		return None
	g = np.diff(dens)
	pk = np.where((g[:-1] > 0) & (g[1:] < 0))[0] + 1
	if len(pk) == 0:
		return float(ts[int(np.argmax(dens))])
	sig = dens[pk] > dens.mean()
	idx = int(pk[sig][0]) if sig.any() else int(pk[np.argmax(dens[pk])])
	return float(ts[idx])


def median_decode(ts: np.ndarray, dens: np.ndarray) -> float | None:
	"""MAE 最优点预测 = 预测密度的中位数(网格内线性插值)."""
	c = np.cumsum(dens)
	if c[-1] <= 1e-300:
		return None
	half = c[-1] / 2.0
	idx = int(np.searchsorted(c, half))
	if idx == 0:
		return float(ts[0])
	frac = (half - c[idx - 1]) / max(c[idx] - c[idx - 1], 1e-300)
	return float(ts[idx - 1] + frac * (ts[idx] - ts[idx - 1]))


def hazard_decode(ts: np.ndarray, score: np.ndarray, mean_iv_h: float) -> float | None:
	"""把 WGMM 得分重释为非齐次泊松强度的首达时间中位数.

	标定: 视野内期望事件数 = 视野/平均间隔; 中位数即生存函数 0.5 处.
	"""
	dt_h = GRID_STEP / 3600.0
	total = float(score.sum() * dt_h)
	if total <= 1e-12 or mean_iv_h <= 0:
		return None
	c_scale = (len(ts) * dt_h / mean_iv_h) / total
	cum = np.cumsum(score) * dt_h
	target = math.log(2.0) / c_scale
	idx = int(np.searchsorted(cum, target))
	if idx >= len(ts):
		return float(ts[-1])
	if idx == 0:
		return float(ts[0])
	frac = (target - cum[idx - 1]) / max(cum[idx] - cum[idx - 1], 1e-300)
	return float(ts[idx - 1] + frac * (ts[idx] - ts[idx - 1]))


# ---------------- 各模型在单一锚点上的预测 ----------------
def predict_all(fit: dict, now: int, naive_fallback: float) -> dict[str, float]:
	preds: dict[str, float] = {}
	pos = fit["pos"]
	iv_h = fit["iv_h"]
	iv_h = iv_h[iv_h > 0]
	med_iv = float(np.median(iv_h)) if len(iv_h) else 1.0
	mean_iv = float(np.mean(iv_h)) if len(iv_h) else 1.0

	preds["wgmm_base"] = predict_baseline(fit, now)
	preds["naive_med"] = max(pos[-1] + med_iv * 3600.0, now + 1.0)

	horizon_s = HORIZON_DAYS * 86400.0
	ts, s45 = score_grid(fit, now, horizon_s)
	n15 = int(LOOKAHEAD_DAYS * 86400.0 / GRID_STEP)
	delta_h = (ts - pos[-1]) / 3600.0  # 距上一发布事件(链起点)的间隔

	def dec(name: str, dens: np.ndarray, grid: np.ndarray = ts) -> None:
		p = median_decode(grid, dens)
		preds[name] = p if p is not None else naive_fallback

	dec("median15", s45[:n15], ts[:n15])
	dec("median45", s45)
	p = hazard_decode(ts, s45, mean_iv)
	preds["pp_hazard"] = p if p is not None else naive_fallback

	if len(iv_h) >= 3:
		g_base = interval_kde_grid(iv_h, delta_h)
		dec("renewal", g_base)
		dec("renew_x_per", s45 * g_base)
		pk = peak_decode(ts, s45 * g_base)
		preds["renew_x_per_peak"] = pk if pk is not None else naive_fallback
		# 对比度归一化周期因子(镜像 ADR006 的"显著=高于均值"判据, 去除 DC 偏置)
		dec("renew_x_ctr", np.maximum(s45 - s45.mean(), 0.0) * g_base)
		# 核宽: 留一似然全局带宽
		g_loo = interval_kde_grid(iv_h, delta_h, fixed_h=loo_bandwidth(np.log(iv_h)))
		dec("renew_loobw", s45 * g_loo)
		# 序列依赖: 用上一间隔做 Nadaraya-Watson 条件加权
		if len(iv_h) >= 25:
			ctx = np.log(iv_h[:-1])
			tgt_w_ctx = np.log(iv_h[-1])
			h_ctx = silverman_bw(ctx)
			w_cond = np.exp(-((ctx - tgt_w_ctx) ** 2) / (2 * h_ctx**2))
			g_cond = interval_kde_grid(iv_h[1:], delta_h, weights=w_cond)
		else:
			g_cond = g_base
		dec("renew_cond", s45 * g_cond)
		# 非平稳: 把模型自己的自适应遗忘 λ 也作用到更新密度上
		ends_h = (now - np.array(sorted(pos), dtype=np.float64)[1:]) / 3600.0
		k = min(len(ends_h), len(iv_h))
		w_decay = np.exp(-fit["pos_l"] * ends_h[-k:])
		g_decay = interval_kde_grid(iv_h[-k:], delta_h, weights=w_decay)
		dec("renew_decay", s45 * g_decay)
		# 非平稳(较温和): 固定 90 天半衰期
		w_decay90 = np.exp(-(math.log(2.0) / 2160.0) * ends_h[-k:])
		g_decay90 = interval_kde_grid(iv_h[-k:], delta_h, weights=w_decay90)
		dec("renew_decay90", s45 * g_decay90)
		# 联合(乘积)周期核
		p45 = product_score_grid(fit, ts)
		dec("renew_x_prod", p45 * g_base)
		# 局部自适应带宽 (Abramson)
		g_abw = interval_kde_grid(iv_h, delta_h, adaptive=True)
		dec("renew_abw", s45 * g_abw)
		# 组合: 乘积周期核 × (条件 × 衰减) 更新密度
		if len(iv_h) >= 25:
			k2 = min(len(ends_h), len(iv_h) - 1)
			w_combo = w_cond[-k2:] * np.exp(-fit["pos_l"] * ends_h[-k2:])
			g_combo = interval_kde_grid(iv_h[1:][-k2:], delta_h, weights=w_combo)
		else:
			g_combo = g_decay
		dec("combo", p45 * g_combo)
	else:
		for name in (
			"renewal", "renew_x_per", "renew_x_per_peak", "renew_x_ctr", "renew_loobw",
			"renew_cond", "renew_decay", "renew_decay90", "renew_x_prod", "renew_abw",
			"combo",
		):
			preds[name] = naive_fallback
	return preds


MODELS = [
	"wgmm_base", "median15", "median45", "pp_hazard", "renewal", "renew_x_per",
	"renew_x_per_peak", "renew_x_ctr", "renew_loobw", "renew_cond", "renew_decay",
	"renew_decay90", "renew_x_prod", "renew_abw", "combo", "naive_med",
]


# ---------------- walk-forward 主循环 ----------------
def run_split(
	k: int,
	mode: str,
	pos_raw: list[int],
	neg_raw: list[int],
	starts: list[int],
	ends: list[int],
	max_preds: int,
) -> tuple[dict[str, list[float]], list[dict]]:
	n = len(starts)
	errors: dict[str, list[float]] = {m: [] for m in MODELS}
	records: list[dict] = []
	cfg = WgmmConfig()

	def history(now: int, last_idx: int) -> tuple[list[int], list[int]]:
		if mode == "sliding":
			cut = starts[max(0, last_idx - WINDOW_EVENTS + 1)]
		else:
			cut = 0
		p = [t for t in pos_raw if cut <= t <= now]
		g = [t for t in neg_raw if cut <= t <= now]
		return p, g

	now0 = ends[k - 1]
	p0, g0 = history(now0, k - 1)
	for _ in range(WARMUP_FITS):
		wgmm_fit(p0, g0, now0, cfg)

	for i in range(k, min(k + max_preds, n)):
		now = ends[i - 1]
		target = float(starts[i])
		p_raw, g_raw = history(now, i - 1)
		fit = wgmm_fit(p_raw, g_raw, now, cfg)
		if len(fit["pos"]) < MIN_POS or len(fit["iv_h"]) < 2:
			continue
		med_iv = float(np.median(fit["iv_h"][fit["iv_h"] > 0]))
		naive_fb = max(fit["pos"][-1] + med_iv * 3600.0, now + 1.0)
		preds = predict_all(fit, now, naive_fb)
		rec = {"k": k, "i": i, "gap_h": round((target - now) / 3600.0, 3)}
		for m in MODELS:
			e = abs(preds[m] - target) / 3600.0
			errors[m].append(e)
			rec[m] = round(e, 3)
		records.append(rec)
	return errors, records


# ---------------- 信息熵分析 ----------------
def entropy_bits(counts: np.ndarray) -> float:
	p = counts[counts > 0].astype(np.float64)
	p = p / p.sum()
	return float(-(p * np.log2(p)).sum())


def mi_with_surrogate(
	x: np.ndarray, y: np.ndarray, n_sur: int = 2000, seed: int = 7
) -> tuple[float, float]:
	"""离散 MI(x;y) 及循环移位代理检验 p 值(保边缘分布、破依赖)."""

	def mi(a: np.ndarray, b: np.ndarray) -> float:
		ja = a * (b.max() + 1) + b
		h_a = entropy_bits(np.bincount(a))
		h_b = entropy_bits(np.bincount(b))
		h_ab = entropy_bits(np.bincount(ja))
		return h_a + h_b - h_ab

	obs = mi(x, y)
	rng = np.random.default_rng(seed)
	null = np.array(
		[mi(np.roll(x, int(s)), y) for s in rng.integers(1, len(x) - 1, size=n_sur)]
	)
	return obs, float(np.mean(null >= obs))


def entropy_analysis(starts: list[int]) -> dict:
	iv_h = np.diff(np.array(starts, dtype=np.float64)) / 3600.0
	iv_h = iv_h[iv_h > 0]
	logiv = np.log2(iv_h)
	qs = np.quantile(logiv, np.linspace(0, 1, 7)[1:-1])
	bins6 = np.digitize(logiv, qs)
	octave = np.clip(np.floor(logiv).astype(int) - int(np.floor(logiv.min())), 0, None)

	out: dict = {}
	for name, b in (("quantile6", bins6), ("octave", octave)):
		h_m = entropy_bits(np.bincount(b))
		mi_markov, p_markov = mi_with_surrogate(b[:-1], b[1:])
		out[name] = {
			"H_marginal_bits": round(h_m, 3),
			"H_cond_prev_bits": round(h_m - mi_markov, 3),
			"MI_prev_bits": round(mi_markov, 3),
			"p_surrogate": round(p_markov, 4),
		}
	# 间隔与日历(起点小时段)的互信息: 周期结构与更新结构的耦合
	hours = np.array(
		[time.localtime(t).tm_hour // 4 for t in starts[:-1]], dtype=int
	)[: len(bins6)]
	mi_cal, p_cal = mi_with_surrogate(hours, bins6)
	out["MI_interval_vs_hourbucket"] = {"MI_bits": round(mi_cal, 3), "p": round(p_cal, 4)}
	out["n_intervals"] = int(len(iv_h))
	return out


# ---------------- 汇总 ----------------
def summarize(per_split: dict[str, dict[str, list[float]]], records: list[dict]) -> dict:
	models = {m: {"mae": [], "rmse": []} for m in MODELS}
	for _k, errs in per_split.items():
		for m in MODELS:
			e = np.array(errs[m])
			if len(e) == 0:
				continue
			models[m]["mae"].append(float(e.mean()))
			models[m]["rmse"].append(float(np.sqrt((e**2).mean())))
	pooled = {m: np.array([r[m] for r in records]) for m in MODELS}
	out = {}
	base_mae = np.array(models["wgmm_base"]["mae"])
	base_rmse = np.array(models["wgmm_base"]["rmse"])
	for m in MODELS:
		mae = np.array(models[m]["mae"])
		rmse = np.array(models[m]["rmse"])
		d = mae - base_mae
		dr = rmse - base_rmse
		wins = int((d < 0).sum())
		n = len(d)
		p_sign = min(
			1.0,
			2.0
			* sum(math.comb(n, i) for i in range(0, min(wins, n - wins) + 1))
			* 0.5**n,
		)
		out[m] = {
			"mae_mean": round(float(mae.mean()), 2),
			"mae_std": round(float(mae.std(ddof=1)), 2),
			"rmse_mean": round(float(rmse.mean()), 2),
			"rmse_std": round(float(rmse.std(ddof=1)), 2),
			"dmae_mean": round(float(d.mean()), 2),
			"dmae_std": round(float(d.std(ddof=1)), 2),
			"dmae_pct": round(float(d.mean() / base_mae.mean() * 100.0), 1),
			"drmse_mean": round(float(dr.mean()), 2),
			"drmse_std": round(float(dr.std(ddof=1)), 2),
			"win_rate": round(wins / n, 3),
			"p_sign": round(p_sign, 5),
			"n_splits": n,
			"medae_pooled": round(float(np.median(pooled[m])), 2),
			"mae_pooled": round(float(pooled[m].mean()), 2),
			"n_preds": int(len(pooled[m])),
		}
	return out


def main() -> None:
	ap = argparse.ArgumentParser()
	ap.add_argument("--mtime", default="data/mtime.txt")
	ap.add_argument("--miss", default="data/miss_history.txt")
	ap.add_argument("--splits", type=int, default=40)
	ap.add_argument("--max-preds", type=int, default=25)
	ap.add_argument("--seed", type=int, default=42)
	ap.add_argument("--out", default="/tmp/wgmm_exp/results.json")
	args = ap.parse_args()

	pos_raw = load_unique_ts(args.mtime)
	neg_raw = load_unique_ts(args.miss)
	starts, ends = chains_with_ends(sorted(pos_raw))
	n = len(starts)
	k_lo, k_hi = int(math.ceil(n * 0.30)), int(math.floor(n * 0.95))
	rng = np.random.default_rng(args.seed)
	ks = sorted(rng.choice(np.arange(k_lo, k_hi + 1), size=args.splits, replace=False))
	print(f"events={n} span_days={(starts[-1]-starts[0])/86400:.0f} "
		f"k_range=[{k_lo},{k_hi}] N={len(ks)}", flush=True)

	results = {"meta": {
		"n_events": n, "ks": [int(k) for k in ks], "seed": args.seed,
		"max_preds": args.max_preds, "grid_step_s": GRID_STEP,
		"horizon_days": HORIZON_DAYS, "window_events": WINDOW_EVENTS,
		"warmup_fits": WARMUP_FITS, "tz": os.environ["TZ"],
		"numpy": np.__version__, "python": sys.version.split()[0],
	}}
	t0 = time.time()
	for mode in ("expanding", "sliding"):
		per_split: dict[str, dict[str, list[float]]] = {}
		mode_records: list[dict] = []
		for j, k in enumerate(ks):
			per_split[str(k)], recs = run_split(
				int(k), mode, pos_raw, neg_raw, starts, ends, args.max_preds
			)
			mode_records.extend(recs)
			print(f"[{mode}] split {j+1}/{len(ks)} k={k} "
				f"({time.time()-t0:.0f}s)", flush=True)
		results[mode] = {
			"summary": summarize(per_split, mode_records),
			"per_split_mae": {
				k: {m: round(float(np.mean(v[m])), 2) for m in MODELS if len(v[m])}
				for k, v in per_split.items()
			},
			"records": mode_records,
		}
	results["entropy"] = entropy_analysis(starts)

	os.makedirs(os.path.dirname(args.out), exist_ok=True)
	json.dump(results, open(args.out, "w"), ensure_ascii=False, indent=1)
	for mode in ("expanding", "sliding"):
		print(f"\n===== {mode} =====")
		s = results[mode]["summary"]
		order = sorted(MODELS, key=lambda m: s[m]["mae_mean"])
		for m in order:
			r = s[m]
			print(f"{m:16s} MAE {r['mae_mean']:7.2f}±{r['mae_std']:6.2f}h "
				f"RMSE {r['rmse_mean']:7.2f}±{r['rmse_std']:6.2f}h "
				f"MedAE {r['medae_pooled']:6.2f}h "
				f"ΔMAE {r['dmae_mean']:+7.2f}±{r['dmae_std']:5.2f} "
				f"({r['dmae_pct']:+5.1f}%) win {r['win_rate']:.2f} p {r['p_sign']:.4f}")
	print("\nentropy:", json.dumps(results["entropy"], ensure_ascii=False))
	print(f"\ntotal {time.time()-t0:.0f}s -> {args.out}")


if __name__ == "__main__":
	main()
```

### 7.2 分层归因脚本（analyze.py）

```python
#!/usr/bin/env python3
"""逐预测记录的分层归因分析."""
import json
import sys

import numpy as np

R = json.load(open(sys.argv[1] if len(sys.argv) > 1 else "/tmp/wgmm_exp/results_final.json"))
KEY = [
	"wgmm_base", "naive_med", "renewal", "pp_hazard", "renew_x_per",
	"renew_cond", "renew_decay", "renew_x_prod", "renew_abw", "combo",
]
for mode in ("expanding", "sliding"):
	recs = R[mode]["records"]
	gaps = np.array([r["gap_h"] for r in recs])
	print(f"\n===== {mode}: n_preds={len(recs)} =====")
	print(f"test gap dist: median={np.median(gaps):.1f}h mean={gaps.mean():.1f}h "
		f"p90={np.percentile(gaps,90):.1f}h P(>360h)={np.mean(gaps>360)*100:.1f}%")
	med = np.median(gaps)
	print(f"无条件 L1 下界(事后最优常数=测试中位数 {med:.1f}h): "
		f"MAE={np.abs(gaps-med).mean():.2f}h")
	buckets = [(0, 24, "短(<24h)"), (24, 96, "中(24-96h)"), (96, 360, "长(96-360h)"),
		(360, 1e9, "极长(>360h)")]
	hdr = "model".ljust(16) + "".join(
		f"{lbl}(n={int(((gaps>=a)&(gaps<b)).sum())})".rjust(18) for a, b, lbl in buckets
	) + "   MedAE  MAE"
	print(hdr)
	for m in KEY:
		errs = np.array([r[m] for r in recs])
		cells = []
		for a, b, _l in buckets:
			msk = (gaps >= a) & (gaps < b)
			cells.append(f"{errs[msk].mean():9.1f}h".rjust(18))
		print(m.ljust(16) + "".join(cells)
			+ f" {np.median(errs):7.2f}h {errs.mean():7.2f}h")
	# baseline 预测偏差方向: 用 wgmm_base 误差与 gap 的关系判断系统性早预测
	base = np.array([r["wgmm_base"] for r in recs])
	short = gaps < med
	print(f"baseline: MAE|短gap={base[short].mean():.1f}h MAE|长gap={base[~short].mean():.1f}h "
		f"(长尾主导度: 长gap侧占总误差 {base[~short].sum()/base.sum()*100:.0f}%)")
```
