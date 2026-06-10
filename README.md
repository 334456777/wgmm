# WGMM Intelligent Video Monitoring System

WGMM is a Bilibili video monitor that adjusts its polling interval with a
Weighted Gaussian Mixture Model. It keeps the public entrypoint simple
(`python monitor.py`) while the implementation is split into a small modular
monolith under `wgmm_monitor/`.

The goal is practical monitoring: detect new uploads and new multi-part video
sections promptly while reducing unnecessary network requests.

## Quick Start

### Requirements

- Python 3.14+
- The project `.venv` virtual environment
- `yt-dlp` available on `PATH`
- Bilibili cookies exported to `data/cookies.txt`
- GitHub Gist and Bark credentials in `data/.env`

Check the external `yt-dlp` executable:

```bash
which yt-dlp
yt-dlp --version
```

### Configure

```bash
cp data/.env.example data/.env
nano data/.env
```

Required keys:

```bash
GITHUB_TOKEN=your_github_token
BARK_DEVICE_KEY=your_bark_key
GIST_ID=your_gist_id
BILIBILI_UID=your_bilibili_uid
BARK_APP_TITLE=your_app_title
```

Create `data/cookies.txt` in Netscape cookie format. The application validates
that this file exists and is not empty before starting.

### Run

```bash
source .venv/bin/activate

python monitor.py
python monitor.py --dev
python monitor.py --wgmm-core-only
```

Mode behavior:

- `python monitor.py`: production loop, waits until `next_check_time`, runs one
  monitor cycle, then repeats.
- `python monitor.py --dev`: runs the full detection chain once, does not write
  WGMM config, and does not send new-video notifications.
- `python monitor.py --wgmm-core-only`: runs one WGMM frequency decision and
  skips Bilibili video detection.

### systemd

```bash
sudo systemctl status video-monitor
sudo systemctl start video-monitor
sudo systemctl stop video-monitor
sudo systemctl restart video-monitor
sudo journalctl -u video-monitor -f
```

## Repository Layout

```text
wgmm/
├── monitor.py                    # Thin entrypoint: wgmm_monitor.cli.main()
├── wgmm_monitor/
│   ├── cli.py                    # Argument parsing and mode selection
│   ├── app.py                    # Runtime object assembly
│   ├── config.py                 # data/.env loading
│   ├── models.py                 # RuntimePaths, AppConfig, WgmmConfig, results
│   ├── runtime_logger.py         # Console, urls.log, critical_errors.log
│   ├── clients/
│   │   ├── bark.py               # Bark HTTP client
│   │   ├── gist.py               # GitHub Gist API client
│   │   ├── ytdlp.py              # yt-dlp subprocess wrapper
│   │   └── bilibili_api.py       # Bilibili view API client (real ctime)
│   ├── services/
│   │   ├── monitor.py            # Main three-layer monitoring flow
│   │   ├── bilibili.py           # Bilibili and yt-dlp operations
│   │   ├── frequency.py          # WGMM service orchestration
│   │   ├── history.py            # Upload timestamp generation/maintenance
│   │   └── notification.py       # Notification messages
│   ├── stores/
│   │   ├── config_store.py       # data/wgmm_config.json
│   │   ├── history_store.py      # data/mtime.txt and miss_history.txt
│   │   └── url_store.py          # data/local_known.txt
│   ├── wgmm/
│   │   ├── constants.py          # Algorithm defaults
│   │   ├── features.py           # Time feature extraction
│   │   ├── learning.py           # Lambda, weights, sigma, period discovery
│   │   ├── scheduler.py          # Next-frequency decision
│   │   └── scoring.py            # Point and batch score calculation
│   └── utils/
│       ├── files.py              # Line-limited file rewriting
│       └── time.py               # Timezone offset and interval formatting
├── tests/                        # unittest suite (96% coverage, no network/subprocess)
├── docs/
├── requirements.txt              # Runtime dependencies
├── requirements-dev.txt          # Dev tools: ruff + coverage
├── pyproject.toml
└── video-monitor.service
```

Runtime files:

```text
data/.env                  # Manual, ignored
data/cookies.txt           # Manual, ignored
data/local_known.txt       # Generated local URL state
data/wgmm_config.json      # Generated WGMM state
data/mtime.txt             # Generated positive upload history
data/miss_history.txt      # Generated negative check history
urls.log                   # Main runtime log
critical_errors.log        # Critical runtime log
```

## How Monitoring Works

The app uses two URL sets:

- `memory_urls`: URLs read from GitHub Gist `urls.txt`.
- `known_urls`: local complete known state, loaded from `data/local_known.txt`
  and merged with `memory_urls`.

Only URLs missing from both layers are treated as truly new content.

```text
GitHub Gist urls.txt
    -> memory_urls
        + data/local_known.txt
    -> known_urls
    -> compare against current Bilibili scan
    -> truly new URLs
    -> Bark notification + Gist new.txt update
```

The monitor flow is implemented in `wgmm_monitor/services/monitor.py`:

1. Sync known URLs from Gist.
2. Run multi-part precheck.
3. Run latest-video ID precheck.
4. If either precheck finds a change, fetch and expand the full video list.
5. Save real upload timestamps for new URLs (via the Bilibili view API `ctime`, not the UP-spoofable `pubdate`).
6. Notify through Bark and write `new.txt` to Gist.
7. Ask WGMM for the next check time.

## WGMM Summary

The pure algorithm layer is under `wgmm_monitor/wgmm/`.

- `features.py` encodes day, week, month-week, year-month, and optional
  `custom_N` periods with sin/cos features.
- `learning.py` filters outliers, learns adaptive lambda/sigma/weights, and
  discovers non-calendar periods with autocorrelation when enough data exists.
- `scoring.py` computes positive and negative weighted Gaussian scores.
- `scheduler.py` scans the next 15 days, picks the first significant peak as
  the next-publish estimate (ADR 006), maps relative score to an interval,
  applies peak advance based on observed `yt-dlp` duration, and updates
  `WgmmConfig`.

See [docs/wgmm-algorithm.md](docs/wgmm-algorithm.md) and
[docs/wgmm-config-params.md](docs/wgmm-config-params.md).

## Development

```bash
source .venv/bin/activate
pip install -r requirements-dev.txt  # dev tools: ruff + coverage

ruff check monitor.py wgmm_monitor tests
ruff format monitor.py wgmm_monitor tests
python -m unittest discover -s tests
python -m coverage run -m unittest discover -s tests && python -m coverage report
python monitor.py --wgmm-core-only
python monitor.py --dev
```

For code changes, run Ruff and the full unittest suite. Use
`--wgmm-core-only` to isolate the scheduler from Bilibili/Gist/Bark calls, and
use `--dev` to exercise the full detection chain without writing WGMM config or
sending new-video notifications.

## Troubleshooting

Useful checks:

```bash
source .venv/bin/activate
which yt-dlp
yt-dlp --version
ls -l data/cookies.txt
tail -100 urls.log
cat critical_errors.log
sudo journalctl -u video-monitor -n 100
```

Common cases:

- Missing environment variables: startup prints `缺少必要的环境变量` and exits.
- Missing or empty cookies: startup logs a critical error and exits.
- `yt-dlp` missing from `PATH`: `YtDlpClient` logs an error and returns a failed
  result; check `which yt-dlp`.
- Gist fetch failure: the cycle logs a critical error. If there is no baseline
  URL data, the cycle is skipped.
- Bilibili rate limiting or split expansion failure: the cycle logs a warning,
  skips detection for that run, and records a non-new-content WGMM decision.
- Notification failure: the monitor logs the failure; URL state and frequency
  decisions still proceed.

## Documentation

- [README_CN.md](README_CN.md): Chinese user guide
- [CONTRIBUTING.md](CONTRIBUTING.md): contribution workflow
- [docs/development-guide.md](docs/development-guide.md): development and
  troubleshooting guide
- [docs/code_logic_flow.md](docs/code_logic_flow.md): current architecture flow
- [docs/code-reference.md](docs/code-reference.md): module reference
- [docs/wgmm-algorithm.md](docs/wgmm-algorithm.md): algorithm details
- [docs/wgmm-config-params.md](docs/wgmm-config-params.md): config fields
- [docs/wgmm-universality-analysis.md](docs/wgmm-universality-analysis.md):
  algorithm applicability analysis
- [docs/adr/001-keep-python-implementation.md](docs/adr/001-keep-python-implementation.md)
- [docs/adr/002-do-not-adopt-x-algorithm-techniques.md](docs/adr/002-do-not-adopt-x-algorithm-techniques.md)
- [docs/adr/003-avoid-large-refactoring.md](docs/adr/003-avoid-large-refactoring.md)
- [docs/adr/004-fix-cascade-false-detection.md](docs/adr/004-fix-cascade-false-detection.md)
- [docs/adr/005-adopt-modular-monolith.md](docs/adr/005-adopt-modular-monolith.md)
- [docs/adr/006-wgmm-first-peak-decode.md](docs/adr/006-wgmm-first-peak-decode.md)
- [docs/adr/007-keep-wgmm-structure-unchanged.md](docs/adr/007-keep-wgmm-structure-unchanged.md)

## Security

- `data/.env` and `data/cookies.txt` are ignored by Git.
- Do not commit Gist tokens, Bark keys, cookies, or logs with sensitive content.
- The systemd unit should run with the provided project paths and sandbox
  settings.

## License

MIT License
