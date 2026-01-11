#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bilibili视频监控系统

核心功能: 
- 基于加权高斯混合模型的智能频率预测
- 三层检测策略: 分片预检查 + 快速检查 + 完整检查
- 双波源对抗机制: 正向得分 - 阻力系数 × 负向得分
- 分级通知系统: Bark推送集成

数据文件: 
- mtime.txt: 正向事件 (视频发布时间戳)
- miss_history.txt: 负向事件 (检测失败时间戳)
- wgmm_config.json: 算法状态持久化
- local_known.txt: 本地已知URL记录

依赖: yt-dlp, requests
"""

import os
import sys
import subprocess
import time
import shutil
import requests
import logging
import json
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed, Future
import signal
from typing import TYPE_CHECKING, Any
from types import FrameType

# ==================== 环境配置 ====================
def load_env_file(env_path: str = '.env') -> None:
    """从.env文件加载环境变量

    Args:
        env_path: .env文件路径, 默认为当前目录
    """
    if not os.path.exists(env_path):
        return
    
    try:
        with open(env_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if '=' in line:
                    key, value = line.split('=', 1)
                    key = key.strip()
                    value = value.strip()
                    if key and not os.getenv(key):
                        os.environ[key] = value
    except Exception as e:
        print(f"Warning: Failed to load .env file: {e}", file=sys.stderr)

# 在导入后加载 .env
load_env_file()

class VideoMonitor:
    """Bilibili视频监控系统主类

    核心机制: 
    1. 多层级检测策略: 分片预检查 → 快速检查 → 完整检查
    2. WGMM智能频率: 基于历史模式的自适应调整
    3. 分级通知: Bark推送 (critical/timeSensitive/active/passive)

    属性说明: 
    - memory_urls: Gist同步的已备份URL (内存化替代文件读写)
    - known_urls: 本地已知URL集合 (双层管理机制)
    - ytdlp耗时监控: 用于网络阻抗阻尼计算

    运行要求: 
    - yt-dlp可用 + cookies.txt有效 + GitHub Token具备Gist权限
    """
    
    # 类常量定义
    DEFAULT_CHECK_INTERVAL: int = 24000  # 默认检查间隔 (秒)= 400分钟
    FALLBACK_INTERVAL: int = 7200  # 降级检查间隔 (秒)= 2小时
    MAX_RETRY_ATTEMPTS: int = 3  # 最大重试次数

    def __init__(self) -> None:
        """初始化监控系统

        配置GitHub Gist、Bark通知、日志系统和信号处理器
        """
        # ==================== GitHub Gist 配置 ====================
        self.GIST_ID: str = os.getenv("GIST_ID", "")
        self.GITHUB_TOKEN: str = os.getenv("GITHUB_TOKEN", "")
        self.GIST_BASE_URL: str = "https://api.github.com/gists"
        self.BILIBILI_UID: str = os.getenv("BILIBILI_UID", "")

        # 验证必要配置
        if not all([self.GIST_ID, self.GITHUB_TOKEN, self.BILIBILI_UID, self.bark_device_key]):
            print("Error: Missing required environment variables in .env", file=sys.stderr)
            sys.exit(1)

        # ==================== 核心数据结构 ====================
        self.memory_urls: list[str] = []  # Gist同步的已备份URL
        self.known_urls: set[str] = set()  # 本地已知URL (防止重复通知)

        # ==================== 文件路径配置 ====================
        self.log_file: str = "urls.log"  # 主日志文件
        self.critical_log_file: str = "critical_errors.log"  # 重大错误专用日志
        self.wgmm_config_file: str = "wgmm_config.json"  # WGMM 算法配置文件
        self.local_known_file: str = "local_known.txt"  # 本地已知 URL 持久化文件
        self.mtime_file: str = "mtime.txt"  # 视频发布时间戳历史
        self.miss_history_file: str = "miss_history.txt"  # 失败历史记录文件
        self.cookies_file: str = "cookies.txt"  # Bilibili 登录凭证
        self.tmp_outputs_dir: str = "tmp_outputs"  # 临时输出目录
        
        # ==================== Bark 推送通知配置 ====================
        self.bark_device_key: str = os.getenv("BARK_DEVICE_KEY", "")
        self.bark_base_url: str = "https://api.day.app"
        self.bark_app_title: str = "菠萝视频备份"
        
        # ==================== 网络阻抗监控 ====================
        self.last_ytdlp_duration: float = 0.0  # yt-dlp耗时 (秒)
        self.normal_ytdlp_duration: float = 60.0  # 正常耗时基准 (移动平均)

        # ==================== 初始化子系统 ====================
        self.setup_logging()
        self.load_known_urls()

        # ==================== 信号处理器 ====================
        signal.signal(signal.SIGTERM, self.signal_handler)
        signal.signal(signal.SIGINT, self.signal_handler)

    def setup_logging(self) -> None:
        """配置日志系统

        初始化Python logging模块, 统一日志格式和级别
        """
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        self.logger: logging.Logger = logging.getLogger(__name__)

    def load_known_urls(self) -> None:
        """从本地文件加载已知URL集合"""
        try:
            if os.path.exists(self.local_known_file):
                with open(self.local_known_file, 'r', encoding='utf-8') as f:
                    self.known_urls = set(line.strip() for line in f if line.strip())
            else:
                self.known_urls = set()
                self.save_known_urls()
        except Exception as e:
            self.log_warning(f"加载本地已知 URL 失败: {e}, 将使用空集合")
            self.known_urls = set()

    def save_known_urls(self) -> None:
        """保存已知URL集合到本地文件"""
        try:
            with open(self.local_known_file, 'w', encoding='utf-8') as f:
                f.write('\n'.join(sorted(self.known_urls)))
        except Exception as e:
            self.log_critical_error(f"保存本地已知 URL 失败: {e}", "save_known_urls", send_notification=False)

    def signal_handler(self, signum: int, frame: FrameType | None) -> None:
        """系统信号处理器

        处理SIGTERM和SIGINT信号, 确保程序优雅退出

        Args:
            signum: 信号编号 (SIGTERM=15, SIGINT=2)
            frame: 栈帧对象 (调试用)
        """
        self.log_message(f"收到信号 {signum}, 正在清理并退出...")
        try:
            self.save_known_urls()
        except Exception as e:
            self.log_message(f"保存 URL 状态失败: {e}")
        self.cleanup()
        sys.exit(0)

    def log_message(self, message: str, level: str = 'INFO') -> None:
        """记录日志消息到文件和控制台

        Args:
            message: 日志消息内容
            level: 日志级别 (INFO/WARNING/ERROR/CRITICAL)
        """
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        log_entry = f"{timestamp} - {level} - {message}\n"
        
        with open(self.log_file, 'a', encoding='utf-8') as f:
            f.write(log_entry)
            
        self.limit_file_lines(self.log_file, 100000)
        print(f"{timestamp} - {level} - {message}")

    def log_info(self, message: str) -> None:
        """记录信息级别日志"""
        self.log_message(message, 'INFO')

    def log_warning(self, message: str) -> None:
        """记录警告级别日志"""
        self.log_message(message, 'WARNING')

    def log_error(self, message: str, send_bark_notification: bool = True) -> None:
        """记录错误日志并可选发送通知

        Args:
            message: 错误消息
            send_bark_notification: 是否发送Bark通知
        """
        self.log_message(message, 'ERROR')

        if send_bark_notification:
            if self.notify_error(message):
                timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                print(f"{timestamp} - INFO - 错误通知已发送")
            else:
                timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                print(f"{timestamp} - WARNING - 错误通知发送失败")

    def log_critical_error(
        self,
        message: str,
        context: str = "",
        send_notification: bool = True
    ) -> None:
        """记录严重错误并发送通知

        Args:
            message: 错误消息
            context: 错误上下文 (方法名、阶段等)
            send_notification: 是否发送critical级别通知
        """
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        full_message = f"{message}"
        if context:
            full_message += f" [上下文: {context}]"

        try:
            critical_log_entry = f"{timestamp} - CRITICAL - {full_message}\n"
            with open(self.critical_log_file, 'a', encoding='utf-8') as f:
                f.write(critical_log_entry)
            self._limit_critical_log_lines()
        except Exception as e:
            print(f"{timestamp} - CRITICAL - 无法写入重大错误日志: {e}")
            print(f"{timestamp} - CRITICAL - 原始错误: {full_message}")

        try:
            self.log_error(full_message, send_bark_notification=False)
        except Exception:
            print(f"{timestamp} - ERROR - {full_message}")

        if send_notification:
            if self.notify_critical_error(message, context):
                print(f"{timestamp} - INFO - 重大错误通知已发送")
            else:
                print(f"{timestamp} - WARNING - 重大错误通知发送失败")

    def _limit_critical_log_lines(self, max_lines: int = 20000) -> None:
        """限制重大错误日志文件行数 (内部方法)

        Args:
            max_lines: 最大保留行数
        """
        try:
            self.limit_file_lines(self.critical_log_file, max_lines)
        except Exception:
            # 静默忽略, 避免无限递归
            pass

    def limit_file_lines(self, filepath: str, max_lines: int) -> None:
        """限制指定文件的行数

        Args:
            filepath: 文件路径
            max_lines: 最大保留行数
        """
        try:
            if os.path.exists(filepath):
                with open(filepath, 'r', encoding='utf-8') as f:
                    lines = f.readlines()

                if len(lines) > max_lines:
                    if filepath == self.log_file:
                        keep_lines = lines[:2] + lines[-(max_lines-2):]
                    elif filepath == self.critical_log_file:
                        keep_lines = lines[:1] + lines[-(max_lines-1):]
                    else:
                        keep_lines = lines[-max_lines:]

                    with open(filepath, 'w', encoding='utf-8') as f:
                        f.writelines(keep_lines)
        except Exception as e:
            self.log_critical_error(f"限制文件行数时出错: {e}", f"文件: {filepath}", send_notification=False)

    def send_bark_push(
        self,
        title: str,
        body: str,
        level: str = "active",
        sound: str | None = None,
        group: str | None = None,
        icon: str | None = None,
        url: str | None = None,
        is_archive: bool = True,
        call: bool = False,
        volume: int | None = None
    ) -> bool:
        """发送Bark推送通知 (统一接口)

        所有通知方法的底层实现, 基于Bark API v2.0规范

        Args:
            title: 通知标题
            body: 通知正文
            level: 通知优先级 (active/timeSensitive/passive/critical)
            sound: 铃声名称
            group: 通知分组
            url: 点击跳转链接
            call: 是否持续响铃 (30秒)

        Returns:
            是否发送成功
        """
        import urllib.parse
        
        try:
            encoded_title = urllib.parse.quote(title)
            encoded_body = urllib.parse.quote(body)
            base_url = f"{self.bark_base_url}/{self.bark_device_key}/{encoded_title}/{encoded_body}"

            params = []
            if level and level != "active":
                params.append(f"level={level}")
            if sound:
                params.append(f"sound={urllib.parse.quote(sound)}")
            if call:
                params.append("call=1")
            if volume is not None and level == "critical":
                params.append(f"volume={volume}")
            if group:
                params.append(f"group={urllib.parse.quote(group)}")
            if icon:
                params.append(f"icon={urllib.parse.quote(icon)}")
            if url:
                params.append(f"url={urllib.parse.quote(url)}")
            if is_archive:
                params.append("isArchive=1")

            full_url = f"{base_url}?{'&'.join(params)}" if params else base_url
            response = requests.get(full_url, timeout=30)
            return response.status_code == 200

        except Exception as e:
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            print(f"{timestamp} - WARNING - Bark推送失败: {e}")
            return False

    def notify_new_videos(self, count: int, has_new_parts: bool = False) -> bool:
        """发送新视频发现通知

        检测到新视频时发送推送, timeSensitive级别可突破专注模式。
        """
        body = f"发现 {count} 个新视频{'(含新分片)' if has_new_parts else ''}等待备份"

        return self.send_bark_push(
            title=self.bark_app_title,
            body=body,
            level="timeSensitive",
            sound="minuet",
            group="新视频"
        )

    def notify_error(self, message: str) -> bool:
        """发送普通错误通知, active级别"""
        return self.send_bark_push(
            title=f"{self.bark_app_title} - 错误",
            body=message,
            level="active",
            group="错误"
        )

    def notify_critical_error(self, message: str, context: str = "") -> bool:
        """发送严重错误通知, critical级别, 忽略静音和持续响铃"""
        body = message + (f" ({context})" if context else "")

        return self.send_bark_push(
            title=f"⚠️ {self.bark_app_title} - 严重错误",
            body=body,
            level="critical",
            sound="alarm",
            volume=8,
            call=True,
            group="严重错误"
        )

    def notify_service_issue(self, message: str) -> bool:
        """发送服务异常通知, timeSensitive级别"""
        return self.send_bark_push(
            title=f"{self.bark_app_title} - 服务异常",
            body=message,
            level="timeSensitive",
            group="服务异常"
        )

    def get_next_check_time(self) -> int:
        """从 WGMM 配置文件读取下次检查时间戳"""
        try:
            if os.path.exists(self.wgmm_config_file):
                with open(self.wgmm_config_file, 'r', encoding='utf-8') as f:
                    config: dict[str, Any] = json.load(f)
                return config.get('next_check_time', 0)
            return 0
        except Exception as e:
            self.log_warning(f"读取next_check_time失败: {e}")
            return 0

    def save_next_check_time(self, next_check_timestamp: int) -> None:
        """保存下次检查时间到配置文件"""
        try:
            # 读取现有配置, 保留其他字段
            config: dict[str, Any] = {}
            if os.path.exists(self.wgmm_config_file):
                with open(self.wgmm_config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)

            # 更新并写回
            config['next_check_time'] = next_check_timestamp
            with open(self.wgmm_config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            self.log_critical_error(f"保存next_check_time失败: {e}", "save_next_check_time 方法", send_notification=False)

    def sync_urls_from_gist(self) -> bool:
        """从 GitHub Gist 同步 URL 列表到内存和已知列表"""
        if not self.GIST_ID:
            self.log_critical_error("GIST_ID 未配置", "Gist 同步", send_notification=True)
            return False

        if not self.GITHUB_TOKEN:
            self.log_critical_error("GITHUB_TOKEN 未配置", "Gist 同步", send_notification=True)
            return False

        headers = {"Authorization": f"Bearer {self.GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
        url = f"{self.GIST_BASE_URL}/{self.GIST_ID}"

        try:
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            data = response.json()
            files = data.get("files", {})

            if len(files) != 1:
                self.log_critical_error(f"Gist 文件数量错误: 期望 1 个, 实际 {len(files)} 个", "Gist 同步验证", send_notification=True)
                return False

            content = next(iter(files.values())).get("content", "")
            self.memory_urls = [line.strip() for line in content.splitlines() if line.strip()]
            self.known_urls.update(self.memory_urls)
            self.save_known_urls()
            return True

        except requests.exceptions.HTTPError as e:
            self.log_critical_error(f"Gist API 请求失败: HTTP {e.response.status_code}", "Gist 同步", send_notification=True)
            return False
        except Exception as e:
            self.log_critical_error(f"从 Gist 获取数据失败: {str(e)}", "Gist 同步", send_notification=True)
            return False

    def get_video_upload_time(self, video_url: str) -> int | None:
        """获取视频的真实上传时间戳"""
        try:
            success, stdout, stderr = self.run_yt_dlp([
                '--cookies', self.cookies_file,
                '--print', '%(timestamp)s|%(upload_date)s',
                '--no-download',
                video_url
            ], timeout=60)

            if not success or not stdout:
                self.log_warning(f"获取视频上传时间失败: {video_url[:50]}...")
                return None

            parts = stdout.strip().split('|')

            # 优先使用 timestamp
            if len(parts) >= 1 and parts[0] and parts[0] != 'NA':
                try:
                    return int(parts[0])
                except ValueError:
                    pass

            # 其次使用 upload_date
            if len(parts) >= 2 and parts[1] and parts[1] != 'NA':
                try:
                    dt = datetime.strptime(parts[1], '%Y%m%d')
                    return int(dt.timestamp())
                except ValueError:
                    pass

            self.log_warning(f"无法解析视频上传时间: {stdout[:50]}")
            return None

        except Exception as e:
            self.log_warning(f"获取视频上传时间异常: {e}")
            return None

    def save_real_upload_timestamps(self, new_urls: set[str]) -> None:
        """保存新视频的真实上传时间戳"""
        if not new_urls:
            return

        # 确保 mtime.txt 存在
        if not os.path.exists(self.mtime_file):
            if not self.generate_mtime_file("save_real_upload_timestamps"):
                self.log_warning("无法创建 mtime.txt, 仍然保存时间戳")

        timestamps = []
        current_time = int(time.time())

        for url in new_urls:
            upload_time = self.get_video_upload_time(url)
            if upload_time:
                timestamps.append(upload_time)
            else:
                self.log_warning(f"降级使用当前时间: {url[:50]}...")
                timestamps.append(current_time)

        if timestamps:
            sorted_timestamps = sorted(timestamps)
            with open(self.mtime_file, 'a') as f:
                for ts in sorted_timestamps:
                    f.write(f"{ts}\n")
            self.limit_file_lines(self.mtime_file, 100000)

    def create_mtime_from_info_json(self) -> bool:
        """使用 yt-dlp 获取视频元信息创建 mtime.txt"""
        temp_info_dir = "temp_info_json"
        os.makedirs(temp_info_dir, exist_ok=True)

        try:
            success, stdout, stderr = self.run_yt_dlp([
                '--cookies', self.cookies_file,
                '--write-info-json',
                '--skip-download',
                '--restrict-filenames',
                '--output', f'{temp_info_dir}/%(id)s.%(ext)s',
                f'https://space.bilibili.com/{self.BILIBILI_UID}/video'
            ], timeout=600)

            if not success:
                self.log_warning(f"获取元信息失败: {stderr[:100]}")
                return False

            timestamps = []
            info_files = []

            for root, dirs, files in os.walk(temp_info_dir):
                for file in files:
                    if file.endswith('.info.json'):
                        info_files.append(os.path.join(root, file))

            for info_file in info_files:
                try:
                    with open(info_file, 'r', encoding='utf-8') as f:
                        info_data = json.load(f)

                    upload_timestamp = None

                    if 'timestamp' in info_data and info_data['timestamp']:
                        upload_timestamp = int(info_data['timestamp'])
                    elif 'upload_date' in info_data and info_data['upload_date']:
                        try:
                            dt = datetime.strptime(info_data['upload_date'], '%Y%m%d')
                            upload_timestamp = int(dt.timestamp())
                        except ValueError:
                            pass

                    if upload_timestamp and upload_timestamp > 0:
                        timestamps.append(upload_timestamp)

                except Exception as e:
                    self.log_warning(f"解析 info.json 文件失败: {info_file} - {e}")
                    continue

            try:
                shutil.rmtree(temp_info_dir)
            except Exception as e:
                self.log_warning(f"清理临时目录失败: {e}")

            if not timestamps:
                self.log_warning("未能从任何 info.json 文件中提取到有效时间戳")
                return False

            sorted_timestamps = sorted(timestamps)
            with open(self.mtime_file, 'w') as f:
                for timestamp in sorted_timestamps:
                    f.write(f"{timestamp}\n")

            self.log_info(f"成功创建 mtime.txt, 包含 {len(sorted_timestamps)} 个时间戳")
            return True

        except Exception as e:
            self.log_warning(f"创建 mtime.txt 时出错: {e}")
            try:
                shutil.rmtree(temp_info_dir)
            except:
                pass
            return False

    def generate_mtime_file(self, context: str = "") -> bool:
        """生成 mtime.txt 文件的通用函数, 支持多次重试"""
        max_attempts = 3
        attempt = 0

        while attempt < max_attempts:
            if os.path.exists(self.mtime_file) and os.path.getsize(self.mtime_file) > 0:
                return True

            attempt += 1
            if attempt == 1:
                self.log_info(f"mtime.txt 不可用, 第 {attempt} 次尝试生成 [{context}]")
            else:
                self.log_warning(f"mtime.txt 仍不可用, 第 {attempt} 次尝试生成 [{context}]")

            if self.create_mtime_from_info_json():
                if os.path.exists(self.mtime_file) and os.path.getsize(self.mtime_file) > 0:
                    self.log_info(f"mtime.txt 第 {attempt} 次生成成功 [{context}]")
                    return True
                else:
                    self.log_warning(f"mtime.txt 第 {attempt} 次生成后仍不可用 [{context}]")
            else:
                self.log_warning(f"mtime.txt 第 {attempt} 次生成失败 [{context}]")

        error_msg = f"经过 {max_attempts} 次尝试仍无法生成可用的 mtime.txt"
        if context:
            error_msg += f" [上下文: {context}]"
        self.log_critical_error(error_msg, "generate_mtime_file 方法", send_notification=True)
        return False

    def adjust_check_frequency(self, found_new_content: bool = False) -> None:
        """WGMM 2.0: 基于双波源对抗的智能频率预测

        算法核心: 正向得分 - 阻力系数 × 负向得分
        未来展望: 15天窗口搜索峰值, 智能提前唤醒

        Args:
            found_new_content: 是否发现新内容, 影响历史记录写入
        """
        import math
        import calendar
        import json
        from collections import defaultdict

        # ==================== 模型超参数配置 ====================
        # 高斯核标准差
        SIGMA_DAY = 0.8
        SIGMA_WEEK = 1.0
        SIGMA_MONTH_WEEK = 1.5
        SIGMA_YEAR_MONTH = 2.0

        # 维度权重
        WEIGHT_DAY = 0.5
        WEIGHT_WEEK = 1.0
        WEIGHT_MONTH_WEEK = 0.3
        WEIGHT_YEAR_MONTH = 0.2

        # 时间衰减
        LAMBDA_MIN = 0.00005
        LAMBDA_BASE = 0.0001
        LAMBDA_MAX = 0.0005

        # 轮询间隔
        DEFAULT_INTERVAL = 3600
        MAX_INTERVAL = 300

        # 映射参数
        MAPPING_CURVE = 2.0
        LEARNING_RATE = 0.1
        MIN_HISTORY_COUNT = 10

        # 双波源对抗
        RESISTANCE_COEFFICIENT = 0.8
        WEIGHT_THRESHOLD = 0.001
        LOOKAHEAD_DAYS = 15
        PEAK_ADVANCE_MINUTES = 5

        # 时间常量
        SECONDS_IN_DAY = 86400
        SECONDS_IN_WEEK = 604800

        # 配置文件管理
        config_file = os.path.join(os.path.dirname(self.mtime_file), 'wgmm_config.json')

        def load_config():
            default_config = {
                'dimension_weights': {'day': WEIGHT_DAY, 'week': WEIGHT_WEEK, 'month_week': WEIGHT_MONTH_WEEK, 'year_month': WEIGHT_YEAR_MONTH},
                'last_lambda': LAMBDA_BASE,
                'last_pos_variance': 0.0,
                'last_neg_variance': 0.0,
                'last_update': 0,
                'next_check_time': 0,
                'is_manual_run': True,
            }
            try:
                if os.path.exists(config_file):
                    with open(config_file, 'r', encoding='utf-8') as f:
                        config = json.load(f)
                    for key, value in default_config.items():
                        if key not in config:
                            config[key] = value
                        elif isinstance(value, dict):
                            for sub_key, sub_value in value.items():
                                if sub_key not in config[key]:
                                    config[key][sub_key] = sub_value
                    return config
                else:
                    with open(config_file, 'w', encoding='utf-8') as f:
                        json.dump(default_config, f, indent=2, ensure_ascii=False)
                    self.log_info(f"已创建WGMM配置文件: {config_file}")
                    return default_config
            except Exception as e:
                self.log_warning(f"加载WGMM配置文件失败, 使用默认配置: {e}")
                return default_config

        def save_config(config_data):
            try:
                with open(config_file, 'w', encoding='utf-8') as f:
                    json.dump(config_data, f, indent=2, ensure_ascii=False)
            except Exception as e:
                self.log_critical_error(f"保存WGMM配置文件失败: {e}", "save_config 方法", send_notification=False)

        config = load_config()
        dimension_weights_from_config = config['dimension_weights']
        is_manual_run = config.get('is_manual_run', True)

        if is_manual_run:
            config['is_manual_run'] = False

        current_timestamp = int(time.time())
        current_dt = datetime.fromtimestamp(current_timestamp)

        def load_miss_history():
            if not os.path.exists(self.miss_history_file):
                return []
            try:
                with open(self.miss_history_file, 'r') as f:
                    return [int(line.strip()) for line in f if line.strip().isdigit()]
            except Exception as e:
                self.log_warning(f"读取失败历史记录失败: {e}")
                return []

        def save_to_miss_history(timestamp):
            if is_manual_run:
                return
            try:
                with open(self.miss_history_file, 'a') as f:
                    f.write(f"{timestamp}\n")
                self.limit_file_lines(self.miss_history_file, 100000)
            except Exception as e:
                self.log_warning(f"写入失败历史记录失败: {e}")

        if not os.path.exists(self.mtime_file):
            if not self.generate_mtime_file("adjust_check_frequency"):
                self.save_next_check_time(int(time.time()) + 7200)
                return

        def load_history_file(filepath):
            try:
                with open(filepath, 'r') as f:
                    raw_data = [line.strip() for line in f if line.strip().isdigit()]
                seen_timestamps = set()
                filtered = []
                for timestamp_str in raw_data:
                    timestamp = int(timestamp_str)
                    if timestamp > 0 and timestamp not in seen_timestamps:
                        filtered.append(timestamp)
                        seen_timestamps.add(timestamp)
                return filtered
            except Exception as e:
                self.log_warning(f"读取历史文件失败 {filepath}: {e}")
                return []

        positive_events = load_history_file(self.mtime_file)
        negative_events = load_miss_history()

        def filter_outliers(timestamps, current_time):
            if len(timestamps) < 3:
                return [ts for ts in timestamps if ts <= current_time]
            sorted_ts = sorted(timestamps)
            intervals = [sorted_ts[i+1] - sorted_ts[i] for i in range(len(sorted_ts)-1)]
            if not intervals:
                return sorted_ts
            intervals_sorted = sorted(intervals)
            q1 = intervals_sorted[len(intervals_sorted) // 4]
            q3 = intervals_sorted[(3 * len(intervals_sorted)) // 4]
            iqr = q3 - q1
            lower_bound = q1 - 3 * iqr
            upper_bound = q3 + 3 * iqr
            filtered = [sorted_ts[0]]
            for i in range(len(intervals)):
                if lower_bound <= intervals[i] <= upper_bound:
                    filtered.append(sorted_ts[i+1])
            return [ts for ts in filtered if ts <= current_time]

        positive_events = filter_outliers(positive_events, current_timestamp)
        negative_events = filter_outliers(negative_events, current_timestamp)

        def prune_old_data(events, last_lambda, threshold):
            if not events or not os.path.exists(self.mtime_file if events is positive_events else self.miss_history_file):
                return events
            pruned = []
            removed_count = 0
            for timestamp in events:
                age_hours = (current_timestamp - timestamp) / 3600.0
                if age_hours < 0:
                    continue
                weight = math.exp(-last_lambda * age_hours)
                if weight >= threshold:
                    pruned.append(timestamp)
                else:
                    removed_count += 1
            if removed_count > 0:
                filepath = self.mtime_file if events is positive_events else self.miss_history_file
                try:
                    with open(filepath, 'w') as f:
                        for ts in pruned:
                            f.write(f"{ts}\n")
                except Exception as e:
                    self.log_warning(f"数据剪枝失败: {e}")
                    return events
            return pruned

        last_lambda = config.get('last_lambda', LAMBDA_BASE)
        positive_events = prune_old_data(positive_events, last_lambda, WEIGHT_THRESHOLD)
        negative_events = prune_old_data(negative_events, last_lambda, WEIGHT_THRESHOLD)

        def check_history_sufficient(events, name):
            if not events:
                return False
            if len(events) < MIN_HISTORY_COUNT:
                self.log_info(f"{name}正向数据不足({len(events)}条)")
                return False
            return True

        pos_sufficient = check_history_sufficient(positive_events, "正向")
        neg_sufficient = check_history_sufficient(negative_events, "负向")

        if not pos_sufficient:
            self.log_info("正向数据不足, 进入学习期模式")
            if not os.path.exists(self.mtime_file):
                self.generate_mtime_file("学习期数据不足")
            self.save_next_check_time(int(time.time()) + 3600)
            if is_manual_run:
                config['is_manual_run'] = False
                save_config(config)
            return

        def calculate_interval_stats(timestamps):
            sorted_ts = sorted(timestamps)
            if len(sorted_ts) < 2:
                return DEFAULT_INTERVAL, 0
            intervals = [sorted_ts[i+1] - sorted_ts[i] for i in range(len(sorted_ts)-1)]
            mean_interval = sum(intervals) / len(intervals)
            variance = sum((x - mean_interval) ** 2 for x in intervals) / len(intervals)
            return int(mean_interval), variance

        BASE_INTERVAL, pos_interval_variance = calculate_interval_stats(positive_events)
        neg_interval_variance = calculate_interval_stats(negative_events)[1] if neg_sufficient else 0.0

        def _calculate_adaptive_lambda(timestamps, last_variance) -> tuple[float, float]:
            if len(timestamps) < 2:
                return LAMBDA_BASE, 0.0
            sorted_ts = sorted(timestamps)
            intervals = [sorted_ts[i+1] - sorted_ts[i] for i in range(len(sorted_ts)-1)]
            current_variance = sum((x - sum(intervals)/len(intervals)) ** 2 for x in intervals) / len(intervals)
            variance_trend_normalized = (current_variance - last_variance) / last_variance if last_variance > 0 else 0.0
            normalized_variance = current_variance / (86400 ** 2)
            lambda_factor = math.log(1 + normalized_variance * 10) / math.log(11) if normalized_variance > 0 else 0
            base_adaptive_lambda = LAMBDA_MIN + (LAMBDA_MAX - LAMBDA_MIN) * lambda_factor
            trend_correction = variance_trend_normalized * 0.3 * base_adaptive_lambda
            adaptive_lambda = base_adaptive_lambda + trend_correction
            return max(LAMBDA_MIN, min(LAMBDA_MAX, adaptive_lambda)), current_variance

        last_pos_variance = config.get('last_pos_variance', 0.0)
        pos_lambda, pos_current_variance = _calculate_adaptive_lambda(positive_events, last_pos_variance)
        last_neg_variance = config.get('last_neg_variance', 0.0)
        neg_lambda, neg_current_variance = _calculate_adaptive_lambda(negative_events, last_neg_variance) if neg_sufficient else (pos_lambda, 0.0)

        def get_week_of_month(dt):
            month_calendar = calendar.monthcalendar(dt.year, dt.month)
            for week_num, week in enumerate(month_calendar, 1):
                if dt.day in week:
                    return week_num
            return 1

        def calculate_dimension_strength(timestamps, dimension):
            counts = defaultdict(int)
            for ts in timestamps:
                dt = datetime.fromtimestamp(ts)
                if dimension == 'day':
                    key = dt.hour
                elif dimension == 'week':
                    key = dt.weekday()
                elif dimension == 'month_week':
                    key = get_week_of_month(dt)
                elif dimension == 'year_month':
                    key = dt.month
                else:
                    continue
                counts[key] += 1
            if not counts:
                return 0.0
            values = list(counts.values())
            mean_val = sum(values) / len(values)
            if mean_val == 0:
                return 0.0
            variance = sum((x - mean_val) ** 2 for x in values) / len(values)
            std_dev = math.sqrt(variance)
            return mean_val / std_dev if std_dev > 0 else mean_val

        def learn_dimension_weights(timestamps, old_weights):
            if len(timestamps) < 20:
                return old_weights
            dimension_scores = {
                'day': calculate_dimension_strength(timestamps, 'day'),
                'week': calculate_dimension_strength(timestamps, 'week'),
                'month_week': calculate_dimension_strength(timestamps, 'month_week'),
                'year_month': calculate_dimension_strength(timestamps, 'year_month')
            }
            total_score = sum(dimension_scores.values())
            if total_score > 0:
                new_weights = {k: v / total_score * 2.0 for k, v in dimension_scores.items()}
            else:
                new_weights = old_weights
            smoothed_weights = {}
            for key in new_weights:
                smoothed_weights[key] = old_weights[key] * (1 - LEARNING_RATE) + new_weights[key] * LEARNING_RATE
            return smoothed_weights

        dimension_weights = learn_dimension_weights(positive_events, dimension_weights_from_config)

        # 纯计算方法: 单点得分计算
        def _calculate_point_score(target_timestamp, pos_events, neg_events, dimension_weights, pos_lambda, neg_lambda) -> float:
            # 步骤1: 时间特征向量化
            target_dt = datetime.fromtimestamp(target_timestamp)
            current_second_of_day = target_dt.hour * 3600 + target_dt.minute * 60 + target_dt.second
            current_second_of_week = (target_dt.weekday() * SECONDS_IN_DAY) + current_second_of_day
            current_week_of_month = get_week_of_month(target_dt)
            current_month_of_year = target_dt.month

            # 步骤2: 三角函数特征变换
            current_day_sin = math.sin(2 * math.pi * current_second_of_day / SECONDS_IN_DAY)
            current_day_cos = math.cos(2 * math.pi * current_second_of_day / SECONDS_IN_DAY)
            current_week_sin = math.sin(2 * math.pi * current_second_of_week / SECONDS_IN_WEEK)
            current_week_cos = math.cos(2 * math.pi * current_second_of_week / SECONDS_IN_WEEK)
            current_month_week_sin = math.sin(2 * math.pi * current_week_of_month / 6)
            current_month_week_cos = math.cos(2 * math.pi * current_week_of_month / 6)
            current_year_month_sin = math.sin(2 * math.pi * current_month_of_year / 12)
            current_year_month_cos = math.cos(2 * math.pi * current_month_of_year / 12)

            def calculate_source_score(events, lambda_decay):
                # 步骤3: 双波源计算 (正向/负向)
                if not events:
                    return 0.0
                total_score = 0.0
                valid_events = 0
                scores = []
                for event_timestamp in events:
                    try:
                        age_hours = (target_timestamp - event_timestamp) / 3600.0
                        if age_hours < 0:
                            continue
                        weight = math.exp(-lambda_decay * age_hours)
                        event_dt = datetime.fromtimestamp(event_timestamp)
                        event_second_of_day = event_dt.hour * 3600 + event_dt.minute * 60 + event_dt.second
                        event_second_of_week = (event_dt.weekday() * SECONDS_IN_DAY) + event_second_of_day
                        event_week_of_month = get_week_of_month(event_dt)
                        event_month_of_year = event_dt.month

                        event_day_sin = math.sin(2 * math.pi * event_second_of_day / SECONDS_IN_DAY)
                        event_day_cos = math.cos(2 * math.pi * event_second_of_day / SECONDS_IN_DAY)
                        event_week_sin = math.sin(2 * math.pi * event_second_of_week / SECONDS_IN_WEEK)
                        event_week_cos = math.cos(2 * math.pi * event_second_of_week / SECONDS_IN_WEEK)
                        event_month_week_sin = math.sin(2 * math.pi * event_week_of_month / 6)
                        event_month_week_cos = math.cos(2 * math.pi * event_week_of_month / 6)
                        event_year_month_sin = math.sin(2 * math.pi * event_month_of_year / 12)
                        event_year_month_cos = math.cos(2 * math.pi * event_month_of_year / 12)

                        day_dist_sq = ((current_day_sin - event_day_sin) ** 2 + (current_day_cos - event_day_cos) ** 2)
                        day_gaussian = math.exp(-day_dist_sq / (2 * SIGMA_DAY ** 2))
                        week_dist_sq = ((current_week_sin - event_week_sin) ** 2 + (current_week_cos - event_week_cos) ** 2)
                        week_gaussian = math.exp(-week_dist_sq / (2 * SIGMA_WEEK ** 2))
                        month_week_dist_sq = ((current_month_week_sin - event_month_week_sin) ** 2 + (current_month_week_cos - event_month_week_cos) ** 2)
                        month_week_gaussian = math.exp(-month_week_dist_sq / (2 * SIGMA_MONTH_WEEK ** 2))
                        year_month_dist_sq = ((current_year_month_sin - event_year_month_sin) ** 2 + (current_year_month_cos - event_year_month_cos) ** 2)
                        year_month_gaussian = math.exp(-year_month_dist_sq / (2 * SIGMA_YEAR_MONTH ** 2))

                        # 步骤4: 加权高斯混合合成
                        combined_gaussian = (dimension_weights['day'] * day_gaussian +
                                           dimension_weights['week'] * week_gaussian +
                                           dimension_weights['month_week'] * month_week_gaussian +
                                           dimension_weights['year_month'] * year_month_gaussian)
                        score = weight * combined_gaussian
                        total_score += score
                        scores.append(score)
                        valid_events += 1
                    except (ValueError, OSError):
                        continue
                if valid_events == 0:
                    return 0.0
                if len(scores) > 0:
                    min_score = min(scores)
                    max_score = max(scores)
                    if max_score > min_score:
                        normalized_score = (total_score / valid_events - min_score) / (max_score - min_score)
                    else:
                        normalized_score = 0.5
                else:
                    normalized_score = 0.5
                return max(0.0, min(1.0, normalized_score))

            # 步骤5: 对抗机制合成
            pos_score = calculate_source_score(pos_events, pos_lambda)
            neg_score = calculate_source_score(neg_events, neg_lambda) if neg_events else 0.0
            final_score = pos_score - RESISTANCE_COEFFICIENT * neg_score
            return max(0.0, min(1.0, final_score))

        # 步骤6: 当前得分计算
        BASE_INTERVAL, _ = calculate_interval_stats(positive_events)
        current_score = _calculate_point_score(current_timestamp, positive_events, negative_events, dimension_weights, pos_lambda, neg_lambda)

        # 步骤7: 非线性映射
        exponential_score = current_score ** MAPPING_CURVE
        base_interval_sec = BASE_INTERVAL - (BASE_INTERVAL - MAX_INTERVAL) * exponential_score
        base_frequency_sec = int(max(MAX_INTERVAL, min(BASE_INTERVAL * 2, base_interval_sec)))

        # 步骤8: 未来展望与峰值预测
        lookahead_seconds = LOOKAHEAD_DAYS * SECONDS_IN_DAY
        lookahead_start = current_timestamp + base_frequency_sec
        lookahead_end = current_timestamp + lookahead_seconds
        gaussian_width = (SIGMA_DAY * SECONDS_IN_DAY / 24) * 2
        min_step = gaussian_width * 0.5
        max_step = gaussian_width * 4
        scan_start = max(lookahead_start, current_timestamp + 600)

        best_peak_time = None
        best_peak_score = 0.0
        scan_time = scan_start
        last_score = current_score

        while scan_time <= lookahead_end:
            scan_score = _calculate_point_score(scan_time, positive_events, negative_events, dimension_weights, pos_lambda, neg_lambda)
            gradient = scan_score - last_score
            is_peak = False
            if scan_time > scan_start:
                if scan_score > last_score:
                    next_scan = scan_time + min_step
                    if next_scan <= lookahead_end:
                        next_score = _calculate_point_score(next_scan, positive_events, negative_events, dimension_weights, pos_lambda, neg_lambda)
                        if scan_score > next_score:
                            is_peak = True
            if is_peak and scan_score > best_peak_score:
                best_peak_score = scan_score
                best_peak_time = scan_time
            if abs(gradient) < 0.01:
                step = min(max_step, min_step * 3)
            else:
                step = min_step
            if is_peak or (scan_score > 0.7 and abs(gradient) < 0.05):
                step = min_step * 0.5
            last_score = scan_score
            scan_time += step

        # 步骤9: 唤醒决策
        final_frequency_sec = base_frequency_sec
        if best_peak_time and best_peak_score > 0.6:
            peak_interval = best_peak_time - current_timestamp
            if peak_interval < base_frequency_sec * 1.2:
                advanced_time = best_peak_time - (PEAK_ADVANCE_MINUTES * 60)
                advanced_interval = advanced_time - current_timestamp
                if advanced_interval > 300:
                    final_frequency_sec = int(advanced_interval)

        # 步骤10: 网络阻抗阻尼
        impedance_factor = 1.0
        if self.last_ytdlp_duration > self.normal_ytdlp_duration * 2:
            impedance_ratio = self.last_ytdlp_duration / max(self.normal_ytdlp_duration, 1.0)
            impedance_factor = 1.0 + min(0.5, (impedance_ratio - 2.0) * 0.1)
        final_frequency_sec = int(final_frequency_sec * impedance_factor)

        # 步骤11: 写入失败历史记录
        if not found_new_content and not is_manual_run:
            save_to_miss_history(current_timestamp)

        # 步骤12: 保存配置
        next_check_timestamp = int(time.time()) + final_frequency_sec
        self.save_next_check_time(next_check_timestamp)
        config['dimension_weights'] = dimension_weights
        config['last_lambda'] = pos_lambda
        config['last_pos_variance'] = pos_current_variance
        config['last_neg_variance'] = neg_current_variance
        config['last_update'] = current_timestamp
        config['next_check_time'] = next_check_timestamp
        save_config(config)

        # 格式化日志
        polling_days = final_frequency_sec // 86400
        polling_hours = (final_frequency_sec % 86400) // 3600
        polling_minutes = (final_frequency_sec % 3600) // 60
        polling_seconds = final_frequency_sec % 60
        polling_interval_parts = []
        if polling_days > 0:
            polling_interval_parts.append(f"{polling_days} 天")
        if polling_hours > 0:
            polling_interval_parts.append(f"{polling_hours} 小时")
        if polling_minutes > 0:
            polling_interval_parts.append(f"{polling_minutes} 分钟")
        if polling_seconds > 0 or not polling_interval_parts:
            polling_interval_parts.append(f"{polling_seconds} 秒")
        polling_interval_str = " ".join(polling_interval_parts)
        self.log_info(f"WGMM调频 - 轮询间隔: {polling_interval_str}")

    def run_yt_dlp(self, command_args: list[str], timeout: int = 300) -> tuple[bool, str, str]:
        """执行 yt-dlp 命令, 捕获耗时用于网络阻尼计算"""
        start_time = time.time()
        try:
            result = subprocess.run(
                ['yt-dlp'] + command_args,
                capture_output=True,
                text=True,
                timeout=timeout,
                encoding='utf-8'
            )
            elapsed = time.time() - start_time
            self.last_ytdlp_duration = elapsed

            # 更新正常耗时基准 (移动平均, 仅在成功时更新)
            if result.returncode == 0:
                self.normal_ytdlp_duration = 0.9 * self.normal_ytdlp_duration + 0.1 * elapsed

            return result.returncode == 0, result.stdout.strip(), result.stderr.strip()
        except subprocess.TimeoutExpired:
            elapsed = time.time() - start_time
            self.last_ytdlp_duration = elapsed
            self.log_warning(f"yt-dlp 命令超时: {' '.join(command_args[:3])}...")
            return False, "", "命令超时"
        except Exception as e:
            elapsed = time.time() - start_time
            self.last_ytdlp_duration = elapsed
            self.log_error(f"执行 yt-dlp 命令失败: {e}", send_bark_notification=False)
            return False, "", str(e)

    def quick_precheck(self) -> bool:
        """快速预检查: 通过最新视频ID判断是否需要完整检查"""
        if not self.memory_urls:
            self.log_info("memory_urls 为空, 触发完整检查")
            return True

        success, stdout, stderr = self.run_yt_dlp([
            '--cookies', self.cookies_file,
            '--flat-playlist',
            '--print', '%(id)s',
            '--playlist-end', '1',
            f'https://space.bilibili.com/{self.BILIBILI_UID}/video'
        ])

        if not success or not stdout:
            self.log_info("快速检查失败, 触发完整检查")
            return True

        latest_id = stdout.strip()
        video_exists = any(latest_id in url for url in self.memory_urls)

        return not video_exists

    def check_potential_new_parts(self) -> bool:
        """检查现有多分片视频是否有新分片

        分析已有的多分片视频, 检查是否有新的分片发布。
        这是一个高效的预检查方法, 避免完整扫描。
        """
        if not self.memory_urls:
            self.log_info("内存数据为空, 跳过分片预检查")
            return False

        has_new_parts = False

        try:
            # 提取分片视频的基础 URL 和最高分片号
            base_urls = {}
            for url in self.memory_urls:
                if '?p=' in url:
                    base_url = url.split('?p=')[0]
                    part_str = url.split('?p=')[1]
                    try:
                        part_num = int(part_str)
                        if base_url not in base_urls or part_num > base_urls[base_url]:
                            base_urls[base_url] = part_num
                    except ValueError:
                        continue

            # 检查是否有新分片
            for base_url, max_part in base_urls.items():
                if max_part > 1:  # 只检查多分片视频
                    next_part = max_part + 1
                    next_url = f"{base_url}?p={next_part}"

                    success, _, _ = self.run_yt_dlp([
                        '--cookies', self.cookies_file,
                        '--simulate',
                        next_url
                    ])

                    if success:
                        has_new_parts = True

                        # 继续检查更多分片 (最多 5 个)
                        check_part = next_part + 1
                        while check_part <= next_part + 5:
                            check_url = f"{base_url}?p={check_part}"
                            success, _, _ = self.run_yt_dlp([
                                '--cookies', self.cookies_file,
                                '--simulate',
                                check_url
                            ])
                            if success:
                                check_part += 1
                            else:
                                break

        except Exception as e:
            self.log_warning(f"预测检查出错: {e}")
            return False

        return has_new_parts

    def get_video_parts(self, video_url: str) -> list[str]:
        """获取单个视频的所有分片链接"""
        success, stdout, stderr = self.run_yt_dlp([
            '--cookies', self.cookies_file,
            '--flat-playlist',
            '--print', '%(webpage_url)s',
            video_url
        ])

        if success and stdout:
            return [line.strip() for line in stdout.split('\n') if line.strip()]
        else:
            self.log_warning(f"获取分片失败: {stderr[:50]}...")
            return []

    def get_all_videos_parallel(self, video_urls: list[str]) -> list[str]:
        """并行获取所有视频的分片信息, 使用5线程提高效率"""
        all_parts = []
        os.makedirs(self.tmp_outputs_dir, exist_ok=True)

        try:
            with ThreadPoolExecutor(max_workers=5) as executor:
                future_to_url = {
                    executor.submit(self.get_video_parts, url): url
                    for url in video_urls
                }

                for future in as_completed(future_to_url):
                    url = future_to_url[future]
                    try:
                        parts = future.result()
                        all_parts.extend(parts)
                    except Exception as e:
                        self.log_warning(f"处理分片出错: {str(url)[:50]}... {e}")

        except Exception as e:
            self.log_critical_error(f"并行处理时出错: {e}", "get_all_videos_parallel 方法", send_notification=True)

        return all_parts

    def cleanup(self) -> None:
        """清理临时文件和资源"""
        try:
            if os.path.exists(self.tmp_outputs_dir):
                shutil.rmtree(self.tmp_outputs_dir)
        except Exception as e:
            self.log_critical_error(f"清理临时文件失败: {e}", "cleanup 方法", send_notification=False)

    def cleanup_and_wait(self) -> None:
        """清理资源并等待下次检查"""
        self.cleanup()

        try:
            next_check_timestamp = self.get_next_check_time()

            if next_check_timestamp > 0:
                current_timestamp = int(time.time())
                wait_seconds = next_check_timestamp - current_timestamp

                if wait_seconds <= 0:
                    frequency_sec = 24000  # 400 分钟 = 24000 秒
                    next_check_timestamp = current_timestamp + frequency_sec
                    wait_seconds = frequency_sec
                    self.log_info("等待时间出现负数, 使用默认 400 分钟间隔")
                    self.save_next_check_time(next_check_timestamp)

                next_dt = datetime.fromtimestamp(next_check_timestamp)
                weekday_name = ['周一', '周二', '周三', '周四', '周五', '周六', '周日'][next_dt.weekday()]
                next_check_time = f"{next_dt.strftime('%Y年%m月%d日')} {weekday_name} {next_dt.strftime('%H:%M:%S')}"
                self.log_info(f"下次检查: {next_check_time}")
                time.sleep(wait_seconds)
            else:
                frequency_sec = 24000  # 400 分钟 = 24000 秒
                next_check_timestamp = int(time.time()) + frequency_sec
                next_dt = datetime.fromtimestamp(next_check_timestamp)
                weekday_name = ['周一', '周二', '周三', '周四', '周五', '周六', '周日'][next_dt.weekday()]
                next_check_time = f"{next_dt.strftime('%Y年%m月%d日')} {weekday_name} {next_dt.strftime('%H:%M:%S')}"
                self.save_next_check_time(next_check_timestamp)
                self.log_info(f"下次检查: {next_check_time}")
                time.sleep(frequency_sec)

        except (FileNotFoundError, ValueError) as e:
            # 默认 400 分钟 (24000 秒) 后检查
            frequency_sec = 24000  # 400 分钟 = 24000 秒
            next_check_timestamp = int(time.time()) + frequency_sec
            next_dt = datetime.fromtimestamp(next_check_timestamp)
            weekday_name = ['周一', '周二', '周三', '周四', '周五', '周六', '周日'][next_dt.weekday()]
            next_check_time = f"{next_dt.strftime('%Y年%m月%d日')} {weekday_name} {next_dt.strftime('%H:%M:%S')}"
            self.save_next_check_time(next_check_timestamp)
            self.log_info(f"下次检查: {next_check_time}")
            time.sleep(frequency_sec)

    def run_monitor(self) -> None:
        """主监控流程

        执行三层检测策略: 
        1. 分片预检查: 检测多分片视频的新分片
        2. 快速检查: 通过最新视频ID快速判断更新
        3. 完整检查: 获取所有视频链接并对比

        核心流程: 
        - GitHub Gist数据同步 → 预检查 → 完整检查 → 新视频发现 → 频率调整
        """
        try:
            self.log_message("检查开始                  <--")
            # 步骤1: Gist数据同步
            sync_success = self.sync_urls_from_gist()

            if not sync_success and not self.memory_urls:
                self.log_warning("无法获取基准数据 (Gist 失败且内存 urls 为空), 跳过本次检查")
                self.cleanup_and_wait()
                return

            # 步骤2: 两层预检查
            found_new_parts = self.check_potential_new_parts()
            found_new_videos = self.quick_precheck()

            self.log_info(f"预检查完成 - 预测检查: {'发现新内容' if found_new_parts else '无新内容'} "
                          f"快速检查: {'发现新内容' if found_new_videos else '无新内容'}")

            # 步骤3: 条件性完整检查
            if not (found_new_parts or found_new_videos):
                self.adjust_check_frequency(found_new_content=False)
                self.cleanup_and_wait()
                return

            # 步骤4: 完整检查
            success, stdout, stderr = self.run_yt_dlp([
                '--cookies', self.cookies_file,
                '--flat-playlist',
                '--print', '%(webpage_url)s',
                f'https://space.bilibili.com/{self.BILIBILI_UID}/video'
            ])

            if not success or not stdout:
                self.log_critical_error("无法获取视频列表", "完整检查阶段", send_notification=True)
                self.adjust_check_frequency(found_new_content=False)
                self.cleanup_and_wait()
                return

            video_urls = [line.strip() for line in stdout.split('\n') if line.strip()]

            if not video_urls:
                self.log_critical_error("未获取到任何内容", "完整检查阶段", send_notification=True)
                self.adjust_check_frequency(found_new_content=False)
                self.cleanup_and_wait()
                return

            # 步骤5: 并行获取分片
            all_parts = self.get_all_videos_parallel(video_urls)

            if not all_parts:
                self.log_info("处理分片时出错, 错误已处理")
                all_parts = video_urls

            # 步骤6: URL比对
            existing_urls_set = set(self.memory_urls)
            current_urls_set = set(all_parts)

            # 两层URL集合管理
            gist_missing_urls = current_urls_set - existing_urls_set  # Gist未同步
            truly_new_urls = gist_missing_urls - self.known_urls  # 真正的新视频

            if gist_missing_urls:
                # 步骤7: 三层显示逻辑
                old_count = len(gist_missing_urls) - len(truly_new_urls)
                new_count = len(truly_new_urls)

                display = f"{'*' * old_count}{' ' if old_count > 0 and new_count > 0 else ''}{'*' * new_count}"
                self.log_info(display)

                # 步骤8: 时间戳保存与通知
                if truly_new_urls:
                    self.save_real_upload_timestamps(truly_new_urls)

                self.known_urls.update(gist_missing_urls)
                self.save_known_urls()

                if not self.notify_new_videos(len(gist_missing_urls), has_new_parts=found_new_parts):
                    self.log_critical_error("通知发送失败 - 无法向用户推送新视频通知", "notify_new_videos", send_notification=False)
                
                # 步骤9: 频率调整
                if truly_new_urls:
                    self.adjust_check_frequency(found_new_content=True)
                else:
                    self.adjust_check_frequency(found_new_content=False)
            else:
                if found_new_parts:
                    self.log_info("完整检查未发现新视频 - 但发现新分片, 已处理")
                    self.adjust_check_frequency(found_new_content=True)
                else:
                    self.log_info("完整检查未发现新内容 - 快速检查结果已确认, 无更新")
                    self.adjust_check_frequency(found_new_content=False)

            # 步骤10: 清理并等待
            self.cleanup_and_wait()

        except KeyboardInterrupt:
            self.log_info("收到中断信号, 正在退出...")
            self.cleanup()
            sys.exit(0)
        except Exception as e:
            self.log_critical_error(f"监控脚本运行时出现意外错误: {e}", "run_monitor", send_notification=True)
            self.cleanup_and_wait()

def main() -> None:
    """程序入口点

    创建监控实例并启动主循环
    """
    monitor = VideoMonitor()

    # 标记为手动运行 (避免首次运行惩罚)
    try:
        if os.path.exists(monitor.wgmm_config_file):
            with open(monitor.wgmm_config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
            config['is_manual_run'] = True
            with open(monitor.wgmm_config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
    except Exception as e:
        monitor.log_warning(f"设置手动运行标志失败: {e}")

    try:
        while True:
            monitor.run_monitor()
    except KeyboardInterrupt:
        monitor.log_info("程序被用户中断")
        monitor.cleanup()
        sys.exit(0)
    except Exception as e:
        monitor.log_critical_error(f"主循环出现严重错误: {e}", "main", send_notification=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
