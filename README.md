# 🎯 WGMM Intelligent Video Monitoring System

Bilibili video intelligent monitoring system based on **Weighted Gaussian Mixture Model (WGMM)** machine learning algorithm, adaptively adjusts monitoring frequency, ensuring timeliness while saving **60-80%** of network requests.

## ✨ Core Highlights

| 🏆 Feature | 📊 Metric | 🔍 Technical Implementation |
|-----------|-----------|---------------------------|
| **🧠 Intelligent Prediction Accuracy** | Time hit rate >95% | WGMM ML algorithm, periodic pattern recognition |
| **⚡ Resource Efficiency Improvement** | Save network requests 60-80% | Three-layer detection architecture, intelligent frequency adjustment |
| **🎯 Response Timeliness** | New video detection latency <30min | 5-minute intensive monitoring during peak release periods |
| **🔄 Adaptive Capability** | Learn new patterns in 2-3 instances | Exponential decay weights, automatically adapt to habit changes |
| **🛡️ System Reliability** | 7×24 hours stable operation | Multiple failure recovery, automatic data repair mechanism |

## 🚀 Quick Start

### 1️⃣ Prepare Configuration Files (only 2 files needed)

```bash
# Copy environment variable template
cp .env.example .env

# Edit .env file, fill in your configuration
nano .env
```

**Required Configuration**:
```bash
GITHUB_TOKEN=your_github_token          # GitHub Token (requires gist permission)
BARK_DEVICE_KEY=your_bark_key          # Bark push device key
GIST_ID=your_gist_id                   # GitHub Gist ID
BILIBILI_UID=your_bilibili_uid         # UP主 UID to monitor
```

**Acquisition Methods**:
- **GITHUB_TOKEN**: https://github.com/settings/tokens (check `gist` permission)
- **BARK_DEVICE_KEY**: Copy from iOS Bark App
- **GIST_ID**: Get from URL after creating new Gist
- **BILIBILI_UID**: Get from UP主 homepage URL (e.g. `space.bilibili.com/123456789`)

### 2️⃣ Prepare cookies.txt

Export Bilibili login credentials from browser:

1. Open developer tools (F12) after logging into Bilibili
2. Visit any video page
3. Application → Cookies → Copy all cookies
4. Save to `cookies.txt` file in project directory

**Format Example**:
```
# Netscape HTTP Cookie File
.bilibili.com	TRUE	/	FALSE	1234567890	cookie_name	cookie_value
```

### 3️⃣ Start Monitoring

```bash
# Activate virtual environment (project already includes .venv)
source .venv/bin/activate

# Development mode: run single check then exit (don't modify config)
python monitor.py --dev

# Normal mode: continuous monitoring
python monitor.py

# systemd service mode (recommended for production)
sudo systemctl start video-monitor
sudo systemctl enable video-monitor  # Auto-start on boot
```

### 4️⃣ Check Status

```bash
# systemd service status
sudo systemctl status video-monitor

# View logs
tail -f urls.log                      # Main log
cat critical_errors.log               # Critical error log

# systemd service logs
sudo journalctl -u video-monitor -f   # Real-time service log viewing
```

## 📁 File Structure

```
wgmm/
├── monitor.py                    # Main program (2296 lines, 58 methods)
├── requirements.txt              # Dependency list
├── pyproject.toml                # Ruff code quality configuration
├── video-monitor.service         # systemd service configuration
│
├── .env                          # Environment variables ⚠️ Manual creation required
├── cookies.txt                   # Bilibili login credentials ⚠️ Manual creation required
│
├── local_known.txt               # Local known URL list (auto-generated)
├── wgmm_config.json              # WGMM algorithm state (auto-generated)
├── mtime.txt                     # Historical release timestamps (auto-generated)
├── miss_history.txt              # Failure history records (auto-generated)
├── urls.log                      # Main runtime log (auto-generated)
└── critical_errors.log           # Critical error log (auto-generated)
```

**Auto-generated File Notes**:
- All data files are automatically created on first run
- No manual creation or maintenance required
- Configuration files added to `.gitignore`, won't be committed

## 🧠 WGMM Algorithm Introduction

### Design Inspiration

If you've watched "Jujutsu Kaisen", imagine the WGMM algorithm as **Eight-Handled Sword Divergent Sila Divine General Mahoraga**—

Mahoraga's core ability is **adaptation**: After each attack, the wheel turns one notch, gradually adapting to the opponent's technique, eventually becoming completely immune and countering. WGMM works similarly:

| Mahoraga | WGMM Algorithm |
|----------|---------------|
| Wheel turns after attack, gradually adapting to technique | Update parameters after each check, gradually learning release patterns |
| Adaptation speed related to attack intensity | Adaptive λ: greater pattern change → faster forgetting → faster adaptation |
| Complete immunity after adaptation | σ converges to precisely match time patterns, almost no无效 requests |
| Need to readapt to new techniques | Algorithm automatically relearns when UP主 changes habits |

Simply put: WGMM is an algorithm that constantly "takes hits" (observes data), constantly "adapts" (updates parameters), and ultimately accurately predicts UP主 release times.

### Core Principles

WGMM (Weighted Gaussian Mixture Model) algorithm predicts future release probabilities by analyzing historical release times:

1. **Four-Dimensional Time Feature Encoding**
   - Daily cycle (sin/cos)
   - Weekly cycle (sin/cos)
   - Week of month (1-5)
   - Month of year (1-12)

2. **Gaussian Kernel Similarity Calculation**
   ```
   Similarity = exp(-distance² / (2σ²))
   ```

3. **Exponential Time Decay Weights**
   ```
   Weight = exp(-λ × age_hours)
   ```

4. **Adaptive Learning**
   - Dynamically adjust dimension weights
   - Adaptive lambda (forgetting speed)
   - Adaptive sigma (time tolerance)

### Intelligent Features

- **Periodic Pattern Recognition**: Automatically identify release patterns like "every Wednesday afternoon", "weekday evenings"
- **Memory Decay Simulation**: Higher weights for recent events, quickly adapt to habit changes
- **Low Activity Period Optimization**: Automatically extend check interval to 30 days during low-activity periods
- **Peak Prediction**: Scan 15 days ahead, provide 5-minute intensive monitoring during release peaks

**Detailed Algorithm Principles**: See [docs/wgmm-algorithm.md](docs/wgmm-algorithm.md)

## 🔧 Management Commands

### systemd Service Management

```bash
# Start/Stop/Restart
sudo systemctl start video-monitor
sudo systemctl stop video-monitor
sudo systemctl restart video-monitor

# Auto-start on boot
sudo systemctl enable video-monitor
sudo systemctl disable video-monitor

# View status and logs
sudo systemctl status video-monitor
sudo journalctl -u video-monitor -f
```

### Python Commands

```bash
# Activate virtual environment
source .venv/bin/activate

# Development mode: Single check then exit
python monitor.py --dev

# Normal mode: Continuous monitoring
python monitor.py
```

## ⚙️ Configuration Tuning

### View Algorithm Status

```bash
# View current configuration
cat wgmm_config.json

# View prediction results in logs
grep "WGMM调频" urls.log | tail -20
```

### Parameter Adjustment Location

Core parameters located at lines 466-478 in `monitor.py`:

```python
SIGMA = 0.8              # Time similarity tolerance (0.5-1.5)
LAMBDA = 0.0001          # Memory forgetting speed (0.00005-0.0005)
DEFAULT_INTERVAL = 3600  # Default base interval (seconds)
MIN_INTERVAL = 300       # Minimum check interval (5 minutes)
MAX_INTERVAL = 2592000   # Maximum check interval (30 days)
```

**Tuning Guide**: See [docs/wgmm-algorithm.md#参数调优](docs/wgmm-algorithm.md#参数调优)

## 📚 Documentation Navigation

### User Documentation
- **[This README](README.md)** - Quick start and basic usage
- **[FAQ](#常见问题)** - Frequently asked questions

### Development Documentation
- **[docs/development-guide.md](docs/development-guide.md)** - Complete development guide
  - Code quality checks (Ruff)
  - Debugging techniques
  - Troubleshooting
  - Performance monitoring

### Technical References
- **[docs/wgmm-algorithm.md](docs/wgmm-algorithm.md)** - WGMM algorithm detailed explanation
  - Mathematical principles
  - Parameter tuning
  - Code modification scenarios

- **[docs/code-logic-flow.md](docs/code-logic-flow.md)** - System architecture flow
  - Main monitoring loop
  - Three-layer detection architecture
  - Data flow

- **[docs/code-reference.md](docs/code-reference.md)** - Code reference
  - VideoMonitor class method categories
  - Performance optimization points

### Architecture Decision Records
- **[docs/adr/001-keep-python-implementation.md](docs/adr/001-keep-python-implementation.md)** - Decision to keep Python implementation
- **[docs/adr/002-do-not-adopt-x-algorithm-techniques.md](docs/adr/002-do-not-adopt-x-algorithm-techniques.md)** - Decision not to adopt recommendation system techniques
- **[docs/adr/003-avoid-large-refactoring.md](docs/adr/003-avoid-large-refactoring.md)** - Decision to adopt monolithic architecture

### Contributing Guide
- **[CONTRIBUTING.md](CONTRIBUTING.md)** - Contributing guide
  - Development environment setup
  - Code quality standards
  - Commit conventions

## ❓ FAQ

### Q1: Why does the algorithm form 3-day check intervals?

**A**: This is a natural result of WGMM algorithm's mathematical calculation, not hard-coded.

The algorithm naturally produces 3-day intervals through the following mechanisms:

1. **Week dimension has highest weight** (learned weight ≈ 0.67)
2. **sigma_week = 1.0** makes adjacent day similarity ≈ 0.606
3. **3-day interval** can cover both weekday and weekend extremes with high similarity

**Detailed Mathematical Explanation**: See [docs/wgmm-algorithm.md#3天间隔的数学原理](docs/wgmm-algorithm.md#3天间隔的数学原理)

### Q2: How much historical data does WGMM algorithm need to start effective prediction?

**A**:
- **Minimum 10 data points**: Can start basic prediction
- **50 data points**: Can identify basic periodic patterns
- **100+ data points**: Stable prediction, accurately identify complex patterns

### Q3: If UP主 changes release habits, how long can the algorithm adapt?

**A**: Due to exponential decay weight mechanism:
- **2-3 new pattern releases**: Start adjusting prediction
- **1-2 weeks**: Completely adapt to new release habits

### Q4: How to reset algorithm learning?

**A**: Delete `wgmm_config.json` and `mtime.txt`, restart program to relearn:

```bash
rm wgmm_config.json mtime.txt
sudo systemctl restart video-monitor
```

### Q5: What to do if prediction frequency is abnormal?

**A**:
1. Check logs to understand current heat score: `grep "热力" urls.log | tail -5`
2. Check if historical data is normal: `wc -l mtime.txt`
3. To relearn, reset algorithm as in Q4

### Q6: What to do if cookies.txt expires?

**A**:
1. Re-export cookies from browser
2. Replace `cookies.txt` file
3. Restart service: `sudo systemctl restart video-monitor`

## 🔍 Troubleshooting

### System Check

```bash
# Check service status
sudo systemctl status video-monitor

# View detailed logs
sudo journalctl -u video-monitor -n 100

# Check configuration files
cat .env
ls -l cookies.txt
```

### Common Issues

**Issue 1: Service cannot start**
- Check if `.env` file exists and is configured correctly
- Check if `cookies.txt` exists
- View detailed error logs: `sudo journalctl -u video-monitor -n 50`

**Issue 2: Cannot detect new videos**
- Verify if cookies.txt has expired
- Manually run `python monitor.py --dev` to test
- Check if BILIBILI_UID is correct

**Issue 3: Prediction frequency too long/short**
- Normal phenomenon, algorithm adaptively adjusts based on historical data
- Low activity periods may be up to 30 days, peak periods may be as short as 5 minutes
- Can reset algorithm to relearn (see Q4)

**Detailed Troubleshooting**: See [docs/development-guide.md#故障排查](docs/development-guide.md#故障排查)

## 📊 Performance Metrics

| Metric | Typical Value |
|--------|--------------|
| WGMM algorithm calculation | ~10ms |
| Three-layer detection time | ~2s (mainly in yt-dlp I/O) |
| Memory usage | <10MB |
| CPU usage | <1% (mostly sleeping) |
| Network request saving rate | 60-80% (compared to fixed 1-hour interval) |

## 🛡️ Security

- `.env` and `cookies.txt` excluded by `.gitignore`
- Sensitive files not under version control
- systemd service uses secure sandbox settings
- Recommend regularly changing GitHub Token

## 📝 Development Standards

### Code Quality Checks

**Must run after modifying code**:

```bash
source .venv/bin/activate
ruff check monitor.py        # Must pass
ruff format monitor.py       # Must pass
```

### Commit Convention

Follow Conventional Commits specification:

```bash
feat: Add new feature
fix: Fix bug
docs: Update documentation
refactor: Code refactoring
```

**Detailed Guide**: See [CONTRIBUTING.md](CONTRIBUTING.md)

## 🤝 Contributing

Contributions welcome! Please first read [CONTRIBUTING.md](CONTRIBUTING.md) to understand:
- Development environment setup
- Code quality standards
- Commit conventions
- Architecture decision principles

## 📄 License

MIT License

## 🙏 Acknowledgments

- **yt-dlp** - Powerful video metadata extraction tool
- **Bark** - Excellent iOS push service
- **NumPy** - Efficient numerical computation library

---

**Need help?**
- 📖 Check [Documentation](#📚-文档导航)
- 🐛 [Submit Issue](https://github.com/yourusername/wgmm/issues)
- 💬 [View FAQ](#常见问题)
