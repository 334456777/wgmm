#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import subprocess
import time
import shutil
import requests
import logging
import json
import argparse
import urllib.parse
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import signal
from typing import Any
from types import FrameType

import numpy as np


def parse_arguments():
    parser = argparse.ArgumentParser(description='Bilibili视频监控器')
    parser.add_argument('-d', '--dev', action='store_true',
                       help='开发模式：运行检查后立即退出，不等待下次检查时间')
    return parser.parse_args()


def load_env_file(env_path: str = '.env') -> None:
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
        print(f"无法加载 .env 文件: {e}", file=sys.stderr)


class VideoMonitor:

    DEFAULT_CHECK_INTERVAL: int = 24000
    FALLBACK_INTERVAL: int = 7200
    MAX_RETRY_ATTEMPTS: int = 3

    def __init__(self, dev_mode: bool = False) -> None:
        """初始化监控系统

        Args:
            dev_mode: 是否为开发模式（沙盒运行）
        """
        
        self.dev_mode: bool = dev_mode

        
        self.GIST_ID: str = os.getenv("GIST_ID", "")
        self.GITHUB_TOKEN: str = os.getenv("GITHUB_TOKEN", "")
        self.GIST_BASE_URL: str = "https://api.github.com/gists"
        self.BILIBILI_UID: str = os.getenv("BILIBILI_UID", "")

        
        self.bark_device_key: str = os.getenv("BARK_DEVICE_KEY", "")
        self.bark_base_url: str = "https://api.day.app"
        self.bark_app_title: str = "菠萝视频备份"

        
        if not all([self.GIST_ID, self.GITHUB_TOKEN, self.BILIBILI_UID, self.bark_device_key]):
            print("缺少必要的环境变量1", file=sys.stderr)
            sys.exit(1)

        
        self.memory_urls: list[str] = []  
        self.known_urls: set[str] = set()  

        
        if self.dev_mode:
            self.sandbox_config: dict = {}
            self.sandbox_known_urls: set[str] = set()
            self.sandbox_miss_history: list[int] = []
            self.sandbox_next_check_time: int = 0
            self.dev_new_videos: int = 0

        
        self.log_file: str = "urls.log"  
        self.critical_log_file: str = "critical_errors.log"  
        self.wgmm_config_file: str = "wgmm_config.json"  
        self.local_known_file: str = "local_known.txt"  
        self.mtime_file: str = "mtime.txt"  
        self.miss_history_file: str = "miss_history.txt"  
        self.cookies_file: str = "cookies.txt"  
        self.tmp_outputs_dir: str = "tmp_outputs"  

        self._validate_cookies_file()
        
        self.last_ytdlp_duration: float = 0.0  
        self.normal_ytdlp_duration: float = 60.0  

        
        self.wgmm_config: dict = self._load_wgmm_config()

        
        self.setup_logging()
        self.load_known_urls()

        
        signal.signal(signal.SIGTERM, self.signal_handler)
        signal.signal(signal.SIGINT, self.signal_handler)

    def setup_logging(self) -> None:
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        self.logger: logging.Logger = logging.getLogger(__name__)

    def load_known_urls(self) -> None:
        
        try:
            if os.path.exists(self.local_known_file):
                with open(self.local_known_file, 'r', encoding='utf-8') as f:
                    self.known_urls = set(line.strip() for line in f if line.strip())
            else:
                self.known_urls = set()
                if not self.dev_mode:
                    self.save_known_urls()
        except Exception as e:
            self.log_warning(f"加载本地已知 URL 失败: {e}, 将使用空集合")
            self.known_urls = set()

    def save_known_urls(self) -> None:
        
        if self.dev_mode:
            self.sandbox_known_urls = self.known_urls.copy()
            return

        try:
            with open(self.local_known_file, 'w', encoding='utf-8') as f:
                f.write('\n'.join(sorted(self.known_urls)))
        except Exception as e:
            self.log_critical_error(f"保存本地已知 URL 失败: {e}", "save_known_urls", send_notification=False)

    def _validate_cookies_file(self) -> None:
        cookies_path = self.cookies_file

        
        if not os.path.exists(cookies_path):
            error_msg = f"cookies文件不存在: {cookies_path}"
            self.log_critical_error(error_msg, "cookies_validation", send_notification=True)
            sys.exit(1)

        
        try:
            with open(cookies_path, 'r', encoding='utf-8') as f:
                content = f.read().strip()

            if not content:
                error_msg = f"cookies文件内容为空: {cookies_path}"
                self.log_critical_error(error_msg, "cookies_validation", send_notification=True)
                sys.exit(1)

        except Exception as e:
            error_msg = f"无法读取cookies文件 {cookies_path}: {e}"
            self.log_critical_error(error_msg, "cookies_validation", send_notification=True)
            sys.exit(1)

    def _load_wgmm_config(self) -> dict:
        
        default_config = {
            'dimension_weights': {'day': 0.3, 'week': 0.25, 'month_week': 0.25, 'year_month': 0.2},
            'last_lambda': 0.0001,
            'last_pos_variance': 0.0,
            'last_neg_variance': 0.0,
            'last_update': 0,
            'next_check_time': 0,
            'is_manual_run': True,
        }
        try:
            if os.path.exists(self.wgmm_config_file):
                with open(self.wgmm_config_file, 'r', encoding='utf-8') as f:
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
                with open(self.wgmm_config_file, 'w', encoding='utf-8') as f:
                    json.dump(default_config, f, indent=2, ensure_ascii=False)
                return default_config
        except Exception as e:
            self.log_warning(f"加载WGMM配置文件失败, 使用默认配置: {e}")
            return default_config

    def _save_wgmm_config(self) -> None:
        
        try:
            if self.dev_mode:
                return
            with open(self.wgmm_config_file, 'w', encoding='utf-8') as f:
                json.dump(self.wgmm_config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            self.log_warning(f"保存WGMM配置失败: {e}")

    def signal_handler(self, signum: int, frame: FrameType | None) -> None:
        self.log_message(f"收到信号 {signum}, 正在清理并退出...")
        try:
            self.save_known_urls()
        except Exception as e:
            self.log_message(f"保存 URL 状态失败: {e}")
        self.cleanup()
        sys.exit(0)

    def log_message(self, message: str, level: str = 'INFO') -> None:
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        log_entry = f"{timestamp} - {level} - {message}\n"

        
        if self.dev_mode:
            pass  
        else:
            with open(self.log_file, 'a', encoding='utf-8') as f:
                f.write(log_entry)
            self.limit_file_lines(self.log_file, 100000)

        
        print(f"{timestamp} - {level} - {message}")

    def log_info(self, message: str) -> None:
        
        self.log_message(message, 'INFO')

    def log_warning(self, message: str) -> None:
        
        self.log_message(message, 'WARNING')

    def log_error(self, message: str, send_bark_notification: bool = True) -> None:
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
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        full_message = f"{message}"
        if context:
            full_message += f" [上下文: {context}]"

        
        if not self.dev_mode:
            try:
                critical_log_entry = f"{timestamp} - CRITICAL - {full_message}\n"
                with open(self.critical_log_file, 'a', encoding='utf-8') as f:
                    f.write(critical_log_entry)
                self._limit_critical_log_lines()
            except Exception as e:
                print(f"{timestamp} - CRITICAL - 无法写入重大错误日志: {e}")
                print(f"{timestamp} - CRITICAL - 原始错误: {full_message}")

        
        print(f"{timestamp} - CRITICAL - {full_message}")

        
        if send_notification and not self.dev_mode:
            if self.notify_critical_error(message, context):
                print(f"{timestamp} - INFO - 重大错误通知已发送")
            else:
                print(f"{timestamp} - WARNING - 重大错误通知发送失败")

    def _limit_critical_log_lines(self, max_lines: int = 20000) -> None:
        try:
            self.limit_file_lines(self.critical_log_file, max_lines)
        except Exception:
            
            pass

    def limit_file_lines(self, filepath: str, max_lines: int) -> None:
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
        body = f"发现 {count} 个新视频{'(含新分片)' if has_new_parts else ''}等待备份"

        return self.send_bark_push(
            title=self.bark_app_title,
            body=body,
            level="timeSensitive",
            sound="minuet",
            group="新视频"
        )

    def notify_error(self, message: str) -> bool:
        
        return self.send_bark_push(
            title=f"{self.bark_app_title} - 错误",
            body=message,
            level="active",
            group="错误"
        )

    def notify_critical_error(self, message: str, context: str = "") -> bool:
        
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
        
        return self.send_bark_push(
            title=f"{self.bark_app_title} - 服务异常",
            body=message,
            level="timeSensitive",
            group="服务异常"
        )

    def get_next_check_time(self) -> int:
        
        if self.dev_mode:
            return self.sandbox_next_check_time

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
        
        if self.dev_mode:
            self.sandbox_next_check_time = next_check_timestamp
            return

        try:
            
            config: dict[str, Any] = {}
            if os.path.exists(self.wgmm_config_file):
                with open(self.wgmm_config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)

            
            config['next_check_time'] = next_check_timestamp
            with open(self.wgmm_config_file, 'w', encoding='utf-8') as f:
                    json.dump(config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            self.log_critical_error(f"保存next_check_time失败: {e}", "save_next_check_time 方法", send_notification=False)

    def sync_urls_from_gist(self) -> bool:
        
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

            if not self.dev_mode:
                self.save_known_urls()
            return True

        except requests.exceptions.HTTPError as e:
            self.log_critical_error(f"Gist API 请求失败: HTTP {e.response.status_code}", "Gist 同步", send_notification=True)
            return False
        except Exception as e:
            self.log_critical_error(f"从 Gist 获取数据失败: {str(e)}", "Gist 同步", send_notification=True)
            return False

    def get_video_upload_time(self, video_url: str) -> int | None:
        
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

            
            if len(parts) >= 1 and parts[0] and parts[0] != 'NA':
                try:
                    return int(parts[0])
                except ValueError:
                    pass

            
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
        
        if not new_urls:
            return

        if self.dev_mode:
            timestamps = []
            current_time = int(time.time())

            for url in new_urls:
                upload_time = self.get_video_upload_time(url)
                if upload_time:
                    timestamps.append(upload_time)
                else:
                    timestamps.append(current_time)

            if timestamps:
                self.dev_new_videos += len(new_urls)

            return

        
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
        
        if self.dev_mode and not (os.path.exists(self.mtime_file) and os.path.getsize(self.mtime_file) > 0):
            return True

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
        
        SIGMA_DAY = 0.8
        SIGMA_WEEK = 1.0
        SIGMA_MONTH_WEEK = 1.5
        SIGMA_YEAR_MONTH = 2.0

        
        WEIGHT_DAY = 0.5
        WEIGHT_WEEK = 1.0
        WEIGHT_MONTH_WEEK = 0.3
        WEIGHT_YEAR_MONTH = 0.2

        
        LAMBDA_MIN = 0.00005
        LAMBDA_BASE = 0.0001
        LAMBDA_MAX = 0.0005

        
        DEFAULT_INTERVAL = 3600
        MAX_INTERVAL = 300

        
        MAPPING_CURVE = 2.0
        LEARNING_RATE = 0.1
        MIN_HISTORY_COUNT = 10

        
        RESISTANCE_COEFFICIENT = 0.8
        WEIGHT_THRESHOLD = 0.001
        LOOKAHEAD_DAYS = 15
        PEAK_ADVANCE_MINUTES = 5

        
        SECONDS_IN_DAY = 86400
        SECONDS_IN_WEEK = 604800

        def get_local_timezone_offset():
            
            if time.localtime().tm_isdst and time.daylight:
                return -time.altzone
            else:
                return -time.timezone

        
        
        config = self.wgmm_config
        
        if 'dimension_weights' not in config:
            config['dimension_weights'] = {'day': WEIGHT_DAY, 'week': WEIGHT_WEEK, 'month_week': WEIGHT_MONTH_WEEK, 'year_month': WEIGHT_YEAR_MONTH}

        dimension_weights_from_config = config['dimension_weights']

        if self.dev_mode:
            is_manual_run = True
        else:
            is_manual_run = self.wgmm_config.get('is_manual_run', True)
            if is_manual_run:
                self.wgmm_config['is_manual_run'] = False

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
            if self.dev_mode:
                self.sandbox_miss_history.append(timestamp)
                return
            try:
                with open(self.miss_history_file, 'a') as f:
                    f.write(f"{timestamp}\n")
                self.limit_file_lines(self.miss_history_file, 100000)
            except Exception as e:
                self.log_warning(f"写入失败历史记录失败: {e}")

        if not os.path.exists(self.mtime_file):
            if not self.generate_mtime_file("adjust_check_frequency"):
                if not self.dev_mode:
                    self.save_next_check_time(int(time.time()) + 7200)
                else:
                    pass
                return

        def load_history_file(filepath):
            if self.dev_mode and filepath == self.mtime_file and not os.path.exists(filepath):
                return []

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

            sorted_ts = np.array(sorted(timestamps), dtype=np.float64)
            if len(sorted_ts) < 2:
                return timestamps

            intervals = np.diff(sorted_ts)
            if len(intervals) == 0:
                return timestamps

            q1 = np.percentile(intervals, 25)
            q3 = np.percentile(intervals, 75)

            iqr = q3 - q1
            lower_bound = q1 - 3.0 * iqr
            upper_bound = q3 + 3.0 * iqr

            mask = (intervals >= lower_bound) & (intervals <= upper_bound)

            filtered_indices = np.concatenate(([0], np.where(mask)[0] + 1))
            filtered_ts = sorted_ts[filtered_indices]

            current_mask = filtered_ts <= current_time
            final_ts = filtered_ts[current_mask]

            return final_ts.tolist()

        positive_events = filter_outliers(positive_events, current_timestamp)
        negative_events = filter_outliers(negative_events, current_timestamp)

        def prune_old_data(events, last_lambda, threshold):
            if not events or not os.path.exists(self.mtime_file if events is positive_events else self.miss_history_file):
                return events

            
            events_arr = np.array(events, dtype=np.float64)
            current_ts = float(current_timestamp)

            
            ages_hours = (current_ts - events_arr) / 3600.0
            weights = np.exp(-last_lambda * ages_hours)

            
            mask = (ages_hours >= 0) & (weights >= threshold)

            pruned_arr = events_arr[mask]

            
            if len(pruned_arr) < len(events_arr):
                filepath = self.mtime_file if events is positive_events else self.miss_history_file
                try:
                    
                    pruned_list = pruned_arr.astype(int).tolist()
                    with open(filepath, 'w') as f:
                        for ts in pruned_list:
                            f.write(f"{ts}\n")
                except Exception as e:
                    self.log_warning(f"数据剪枝失败: {e}")
                    return events
                return pruned_list

            return events

        last_lambda = config.get('last_lambda', LAMBDA_BASE)
        positive_events = prune_old_data(positive_events, last_lambda, WEIGHT_THRESHOLD)
        negative_events = prune_old_data(negative_events, last_lambda, WEIGHT_THRESHOLD)

        
        def check_positive_sufficient(events):
            return len(events) >= MIN_HISTORY_COUNT

        pos_sufficient = check_positive_sufficient(positive_events)

        if not pos_sufficient:
            self.log_info(f"正向数据不足({len(positive_events)}条), 进入学习期模式")
            if not os.path.exists(self.mtime_file):
                self.generate_mtime_file("学习期数据不足")
            if not self.dev_mode:
                self.save_next_check_time(int(time.time()) + 3600)
            if is_manual_run:
                self.wgmm_config['is_manual_run'] = False
                self._save_wgmm_config()
            return

        def calculate_interval_stats(timestamps):
            if len(timestamps) < 2:
                return float(DEFAULT_INTERVAL), 0.0

            timestamps_arr = np.array(sorted(timestamps), dtype=np.float64)
            intervals = np.diff(timestamps_arr)
            mean_interval = np.mean(intervals, dtype=np.float64)
            variance = np.var(intervals, dtype=np.float64)

            return float(mean_interval), float(variance)

        BASE_INTERVAL, pos_interval_variance = calculate_interval_stats(positive_events)
        neg_interval_variance = calculate_interval_stats(negative_events)[1]

        def _calculate_adaptive_lambda(timestamps, last_variance) -> tuple[float, float]:
            if len(timestamps) < 2:
                return float(LAMBDA_BASE), 0.0

            timestamps_arr = np.array(sorted(timestamps), dtype=np.float64)
            intervals = np.diff(timestamps_arr)
            current_variance = np.var(intervals, dtype=np.float64)

            if last_variance > 0:
                variance_trend_normalized = (current_variance - last_variance) / last_variance
            else:
                variance_trend_normalized = 0.0

            seconds_in_day_sq = 86400 ** 2
            normalized_variance = current_variance / seconds_in_day_sq

            if normalized_variance > 0:
                lambda_factor = np.log(1 + normalized_variance * 10) / np.log(11)
            else:
                lambda_factor = 0

            base_adaptive_lambda = LAMBDA_MIN + (LAMBDA_MAX - LAMBDA_MIN) * lambda_factor
            trend_correction = variance_trend_normalized * 0.3 * base_adaptive_lambda
            adaptive_lambda = base_adaptive_lambda + trend_correction

            final_lambda = np.clip(adaptive_lambda, LAMBDA_MIN, LAMBDA_MAX)

            return float(final_lambda), float(current_variance)

        last_pos_variance = config.get('last_pos_variance', 0.0)
        pos_lambda, pos_current_variance = _calculate_adaptive_lambda(positive_events, last_pos_variance)
        last_neg_variance = config.get('last_neg_variance', 0.0)
        
        neg_lambda, neg_current_variance = _calculate_adaptive_lambda(negative_events, last_neg_variance)

        def learn_dimension_weights(timestamps, old_weights):
            if len(timestamps) < 20:
                return old_weights

            
            raw_components = self._get_raw_time_components(np.array(timestamps, dtype=np.float64))

            dimension_scores = {}
            for dim in ['day', 'week', 'month_week', 'year_month']:
                keys = raw_components.get(dim, np.array([], dtype=np.int64))
                if len(keys) == 0:
                    dimension_scores[dim] = 0.0
                    continue

                unique_keys, counts = np.unique(keys, return_counts=True)
                counts_arr = counts.astype(np.float64)
                mean_val = np.mean(counts_arr)

                if mean_val == 0:
                    dimension_scores[dim] = 0.0
                else:
                    std_dev = np.std(counts_arr)
                    if std_dev > 0:
                        dimension_scores[dim] = float(mean_val / std_dev)
                    else:
                        dimension_scores[dim] = float(mean_val)

            scores_array = np.array(list(dimension_scores.values()), dtype=np.float64)
            total_score = np.sum(scores_array, dtype=np.float64)

            if total_score > 0:
                normalized_scores = scores_array / total_score * 2.0
                new_weights = dict(zip(dimension_scores.keys(), normalized_scores))
            else:
                new_weights = old_weights

            smoothed_weights = {}
            for key in dimension_scores.keys():
                old_weight = old_weights[key]
                new_weight = new_weights[key]
                smoothed = old_weight * (1 - LEARNING_RATE) + new_weight * LEARNING_RATE
                smoothed_weights[key] = float(smoothed)

            return smoothed_weights

        dimension_weights = learn_dimension_weights(positive_events, dimension_weights_from_config)

        
        sigmas = {
            'day': float(SIGMA_DAY),
            'week': float(SIGMA_WEEK),
            'month_week': float(SIGMA_MONTH_WEEK),
            'year_month': float(SIGMA_YEAR_MONTH)
        }

        BASE_INTERVAL, _ = calculate_interval_stats(positive_events)
        current_score = self._calculate_point_score(current_timestamp, positive_events, negative_events, dimension_weights, pos_lambda, neg_lambda, sigmas, RESISTANCE_COEFFICIENT)

        exponential_score = current_score ** MAPPING_CURVE
        base_interval_sec = BASE_INTERVAL - (BASE_INTERVAL - MAX_INTERVAL) * exponential_score

        base_frequency_sec = np.clip(base_interval_sec, MAX_INTERVAL, BASE_INTERVAL * 2)

        lookahead_seconds = LOOKAHEAD_DAYS * SECONDS_IN_DAY
        lookahead_start = current_timestamp + base_frequency_sec
        lookahead_end = current_timestamp + lookahead_seconds

        gaussian_width = (SIGMA_DAY * SECONDS_IN_DAY / 24.0) * 2.0
        min_step = float(gaussian_width * 0.25)
        max_step = float(gaussian_width * 4.0)

        scan_start = float(np.maximum(lookahead_start, current_timestamp + 600.0))

        best_peak_time = None
        best_peak_score = 0.0

        if lookahead_end > scan_start:
            if current_score > 0.5:
                scan_step = min_step
            else:
                scan_step = min_step * 2

            scan_times = np.arange(scan_start, lookahead_end + scan_step, scan_step, dtype=np.float64)

            
            scan_scores = self._batch_calculate_scores(scan_times, positive_events, negative_events, dimension_weights, pos_lambda, neg_lambda, sigmas, RESISTANCE_COEFFICIENT)

            if len(scan_scores) > 1:
                gradients = np.diff(scan_scores)
                peaks_mask = (gradients[:-1] > 0) & (gradients[1:] < 0)

                for i in range(len(peaks_mask)):
                    if peaks_mask[i]:
                        scan_idx = i + 1
                        if scan_scores[scan_idx] > 0.7 and abs(gradients[i]) < 0.05:
                            peaks_mask[i] = True

                peak_indices = np.where(peaks_mask)[0]

                if len(peak_indices) > 0:
                    peak_scores = scan_scores[peak_indices]
                    best_idx_in_peaks = np.argmax(peak_scores)
                    best_peak_idx = peak_indices[best_idx_in_peaks]

                    if peak_scores[best_idx_in_peaks] > best_peak_score:
                        best_peak_score = float(peak_scores[best_idx_in_peaks])
                        best_peak_time = float(scan_times[best_peak_idx])

        final_frequency_sec = base_frequency_sec
        if best_peak_time and best_peak_score > 0.6:
            peak_interval = best_peak_time - current_timestamp
            if peak_interval < base_frequency_sec * 1.2:
                advanced_time = best_peak_time - (PEAK_ADVANCE_MINUTES * 60.0)
                advanced_interval = advanced_time - current_timestamp
                if advanced_interval > 300:
                    final_frequency_sec = float(advanced_interval)

        impedance_factor = 1.0
        last_duration = self.last_ytdlp_duration
        normal_duration = self.normal_ytdlp_duration

        if last_duration > normal_duration * 2.0:
            impedance_ratio = last_duration / max(normal_duration, 1.0)
            impedance_factor = 1.0 + min(0.5, (impedance_ratio - 2.0) * 0.1)

        final_frequency_sec = float(final_frequency_sec * impedance_factor)
        if not found_new_content and not is_manual_run:
            save_to_miss_history(current_timestamp)

        next_check_timestamp = int(time.time()) + int(final_frequency_sec)
        self.save_next_check_time(next_check_timestamp)

        
        self.wgmm_config['last_update'] = current_timestamp
        self.wgmm_config['next_check_time'] = next_check_timestamp
        self.wgmm_config['dimension_weights'] = dimension_weights
        self.wgmm_config['last_lambda'] = pos_lambda
        self.wgmm_config['last_pos_variance'] = pos_current_variance
        self.wgmm_config['last_neg_variance'] = neg_current_variance

        if not self.dev_mode:
            self._save_wgmm_config()

        total_seconds = float(final_frequency_sec)
        polling_days_float = total_seconds / 86400.0
        polling_hours_float = (total_seconds % 86400.0) / 3600.0
        polling_minutes_float = (total_seconds % 3600.0) / 60.0
        polling_seconds_float = total_seconds % 60.0

        polling_days = int(polling_days_float)
        polling_hours = int(polling_hours_float)
        polling_minutes = int(polling_minutes_float)
        polling_seconds = int(polling_seconds_float)

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
        if not self.memory_urls:
            self.log_info("内存数据为空, 跳过分片预检查")
            return False

        has_new_parts = False

        try:
            
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

            
            for base_url, max_part in base_urls.items():
                if max_part > 1:  
                    next_part = max_part + 1
                    next_url = f"{base_url}?p={next_part}"

                    success, _, _ = self.run_yt_dlp([
                        '--cookies', self.cookies_file,
                        '--simulate',
                        next_url
                    ])

                    if success:
                        has_new_parts = True

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
        
        try:
            if os.path.exists(self.tmp_outputs_dir):
                shutil.rmtree(self.tmp_outputs_dir)
        except Exception as e:
            self.log_critical_error(f"清理临时文件失败: {e}", "cleanup 方法", send_notification=False)

        if self.dev_mode:
            try:
                temp_dirs = ["temp_info_json"]
                for temp_dir in temp_dirs:
                    if os.path.exists(temp_dir):
                        shutil.rmtree(temp_dir)
            except Exception as e:
                pass

    def wait_for_next_check(self) -> None:
        
        try:
            next_check_timestamp = self.get_next_check_time()

            if next_check_timestamp > 0:
                current_timestamp = int(time.time())
                wait_seconds = next_check_timestamp - current_timestamp

                next_dt = datetime.fromtimestamp(next_check_timestamp)
                weekday_name = ['周一', '周二', '周三', '周四', '周五', '周六', '周日'][next_dt.weekday()]
                next_check_time = f"{next_dt.strftime('%Y年%m月%d日')} {weekday_name} {next_dt.strftime('%H:%M:%S')}"

                if wait_seconds <= 0:
                    self.log_info(f"距离上次检查时间已过 {abs(wait_seconds)} 秒，立即开始检查")
                    return

                if self.dev_mode:
                    self.log_info(f"下次检查: {next_check_time}")
                    return

                self.log_info(f"下次检查: {next_check_time}")
                time.sleep(wait_seconds)
            else:
                self.log_info("未找到保存的检查时间，立即开始首次检查")
                return

        except (FileNotFoundError, ValueError) as e:
            self.log_info(f"配置文件异常 ({e})，立即开始检查")
            return
        except Exception as e:
            self.log_warning(f"等待逻辑异常: {e}，使用默认等待")
            if not self.dev_mode:
                frequency_sec = 24000
                time.sleep(frequency_sec)
            else:
                self.log_info("Dev模式下跳过异常等待")

    def _get_local_timezone_offset(self) -> float:
        
        if time.localtime().tm_isdst and time.daylight:
            return -time.altzone
        else:
            return -time.timezone

    def _vectorized_time_features_numpy(self, timestamps_array: np.ndarray) -> dict:
        if len(timestamps_array) == 0:
            return {
                'day_sin': np.array([], dtype=np.float64),
                'day_cos': np.array([], dtype=np.float64),
                'week_sin': np.array([], dtype=np.float64),
                'week_cos': np.array([], dtype=np.float64),
                'month_week_sin': np.array([], dtype=np.float64),
                'month_week_cos': np.array([], dtype=np.float64),
                'year_month_sin': np.array([], dtype=np.float64),
                'year_month_cos': np.array([], dtype=np.float64)
            }

        
        ts_arr = np.array(timestamps_array, dtype=np.float64)
        offset = self._get_local_timezone_offset()
        dt64_local = (ts_arr + offset).astype('datetime64[s]')

        
        seconds_in_day = (dt64_local.astype('int64') % 86400).astype(np.float64)
        days_since_epoch = dt64_local.astype('datetime64[D]').astype('int64')
        weekday = (days_since_epoch + 3) % 7
        dates_M = dt64_local.astype('datetime64[M]')
        months = (dates_M - dates_M.astype('datetime64[Y]')).astype(int) + 1

        
        day_of_month = (dt64_local.astype('datetime64[D]') - dates_M.astype('datetime64[D]')).astype(int) + 1
        first_day_epoch = dates_M.astype('datetime64[D]').astype('int64')
        first_weekday = (first_day_epoch + 3) % 7
        current_week_of_month = (day_of_month - 1 + first_weekday) // 7 + 1

        
        current_second_of_week = weekday * 86400.0 + seconds_in_day

        features = {}
        const_2pi = 2 * np.pi

        features['day_sin'] = np.sin(const_2pi * seconds_in_day / 86400.0)
        features['day_cos'] = np.cos(const_2pi * seconds_in_day / 86400.0)
        features['week_sin'] = np.sin(const_2pi * current_second_of_week / 604800.0)
        features['week_cos'] = np.cos(const_2pi * current_second_of_week / 604800.0)
        features['month_week_sin'] = np.sin(const_2pi * current_week_of_month / 6.0)
        features['month_week_cos'] = np.cos(const_2pi * current_week_of_month / 6.0)
        features['year_month_sin'] = np.sin(const_2pi * months / 12.0)
        features['year_month_cos'] = np.cos(const_2pi * months / 12.0)

        return features

    def _get_raw_time_components(self, timestamps_array: np.ndarray) -> dict:
        
        if len(timestamps_array) == 0:
            return {
                'day': np.array([], dtype=np.int64),
                'week': np.array([], dtype=np.int64),
                'month_week': np.array([], dtype=np.int64),
                'year_month': np.array([], dtype=np.int64)
            }

        ts_arr = np.array(timestamps_array, dtype=np.float64)
        offset = self._get_local_timezone_offset()
        dt64_local = (ts_arr + offset).astype('datetime64[s]')

        
        seconds_in_day = (dt64_local.astype('int64') % 86400)
        days_since_epoch = dt64_local.astype('datetime64[D]').astype('int64')
        dates_M = dt64_local.astype('datetime64[M]')

        hours = (seconds_in_day // 3600).astype(np.int64)
        weekday = (days_since_epoch + 3) % 7
        months = (dates_M - dates_M.astype('datetime64[Y]')).astype(int) + 1

        day_of_month = (dt64_local.astype('datetime64[D]') - dates_M.astype('datetime64[D]')).astype(int) + 1
        first_day_epoch = dates_M.astype('datetime64[D]').astype('int64')
        first_weekday = (first_day_epoch + 3) % 7
        month_week = (day_of_month - 1 + first_weekday) // 7 + 1

        return {
            'day': hours,
            'week': weekday,
            'month_week': month_week,
            'year_month': months
        }

    def _calculate_point_score(self, target_timestamp: float, pos_events: list, neg_events: list,
                             dimension_weights: dict, pos_lambda: float, neg_lambda: float,
                             sigmas: dict, resistance_coefficient: float) -> float:
        """
        单点得分计算 - 使用 NumPy 向量化
        """
        
        target_feat = self._vectorized_time_features_numpy(np.array([target_timestamp]))
        current_features = {k: v[0] for k, v in target_feat.items()}

        def calculate_source_score_vectorized(events_array, lambda_decay):
            if not events_array:
                return 0.0

            events_arr = np.array(events_array, dtype=np.float64)
            events_feat = self._vectorized_time_features_numpy(events_arr)

            ages_hours = (target_timestamp - events_arr) / 3600.0
            valid_mask = ages_hours >= 0
            if not np.any(valid_mask):
                return 0.0

            
            valid_ages = ages_hours[valid_mask]
            weights = np.exp(-lambda_decay * valid_ages, dtype=np.float64)

            
            def dist_sq(key):
                return ((current_features[f'{key}_sin'] - events_feat[f'{key}_sin'][valid_mask]) ** 2 +
                        (current_features[f'{key}_cos'] - events_feat[f'{key}_cos'][valid_mask]) ** 2)

            combined = (
                dimension_weights['day'] * np.exp(-dist_sq('day') / (2 * sigmas['day'] ** 2), dtype=np.float64) +
                dimension_weights['week'] * np.exp(-dist_sq('week') / (2 * sigmas['week'] ** 2), dtype=np.float64) +
                dimension_weights['month_week'] * np.exp(-dist_sq('month_week') / (2 * sigmas['month_week'] ** 2), dtype=np.float64) +
                dimension_weights['year_month'] * np.exp(-dist_sq('year_month') / (2 * sigmas['year_month'] ** 2), dtype=np.float64)
            )

            scores = weights * combined
            if len(scores) == 0:
                return 0.0

            total = np.sum(scores, dtype=np.float64)
            count = len(scores)

            
            if count == 1:
                return float(np.clip(scores[0], 0.0, 1.0))

            min_val, max_val = np.min(scores), np.max(scores)
            if max_val > min_val:
                return float(np.clip((total / count - min_val) / (max_val - min_val), 0.0, 1.0))
            else:
                return 0.5

        pos_score = calculate_source_score_vectorized(pos_events, pos_lambda)
        neg_score = calculate_source_score_vectorized(neg_events, neg_lambda) if neg_events else 0.0

        return float(np.clip(pos_score - (resistance_coefficient * neg_score), 0.0, 1.0))

    def _batch_calculate_scores(self, scan_times: np.ndarray, pos_events: list, neg_events: list,
                               dimension_weights: dict, pos_lambda: float, neg_lambda: float,
                               sigmas: dict, resistance_coefficient: float) -> np.ndarray:
        """
        向量化批量计算所有扫描点的得分
        """
        if len(scan_times) == 0:
            return np.array([], dtype=np.float64)

        
        targets_feat = self._vectorized_time_features_numpy(scan_times)

        def get_source_scores_vectorized(events, lambda_decay):
            
            if not events:
                return np.zeros(len(scan_times), dtype=np.float64)

            events_arr = np.array(events, dtype=np.float64)
            events_feat = self._vectorized_time_features_numpy(events_arr)

            
            ages = (scan_times[:, np.newaxis] - events_arr[np.newaxis, :]) / 3600.0
            valid_mask = ages >= 0
            weights = np.zeros_like(ages, dtype=np.float64)
            weights[valid_mask] = np.exp(-lambda_decay * ages[valid_mask])

            
            day_dist_sq = ((targets_feat['day_sin'][:, np.newaxis] - events_feat['day_sin'][np.newaxis, :]) ** 2 +
                           (targets_feat['day_cos'][:, np.newaxis] - events_feat['day_cos'][np.newaxis, :]) ** 2)
            week_dist_sq = ((targets_feat['week_sin'][:, np.newaxis] - events_feat['week_sin'][np.newaxis, :]) ** 2 +
                            (targets_feat['week_cos'][:, np.newaxis] - events_feat['week_cos'][np.newaxis, :]) ** 2)
            month_week_dist_sq = ((targets_feat['month_week_sin'][:, np.newaxis] - events_feat['month_week_sin'][np.newaxis, :]) ** 2 +
                                 (targets_feat['month_week_cos'][:, np.newaxis] - events_feat['month_week_cos'][np.newaxis, :]) ** 2)
            year_month_dist_sq = ((targets_feat['year_month_sin'][:, np.newaxis] - events_feat['year_month_sin'][np.newaxis, :]) ** 2 +
                                 (targets_feat['year_month_cos'][:, np.newaxis] - events_feat['year_month_cos'][np.newaxis, :]) ** 2)

            
            
            combined_gaussian = np.zeros_like(day_dist_sq, dtype=np.float64)

            
            dist_sq_dict = {
                'day': day_dist_sq,
                'week': week_dist_sq,
                'month_week': month_week_dist_sq,
                'year_month': year_month_dist_sq
            }

            
            for dim, dist_sq in dist_sq_dict.items():
                
                weight = dimension_weights[dim]
                sigma = sigmas[dim]

                
                coeff = -0.5 / (sigma ** 2)

                
                combined_gaussian += weight * np.exp(dist_sq * coeff, dtype=np.float64)

            
            raw_scores = weights * combined_gaussian * valid_mask

            
            total_scores = np.sum(raw_scores, axis=1, dtype=np.float64)
            valid_counts = np.sum(valid_mask, axis=1)

            with np.errstate(divide='ignore', invalid='ignore'):
                row_mins = np.min(np.where(valid_mask, raw_scores, np.inf), axis=1)
                row_maxs = np.max(np.where(valid_mask, raw_scores, -np.inf), axis=1)
                normalized_scores = (total_scores / np.maximum(valid_counts, 1.0) - row_mins) / (row_maxs - row_mins + 1e-9)
                result = np.where(valid_counts > 0, normalized_scores, 0.0)

            return np.clip(result, 0.0, 1.0)

        
        pos_scores = get_source_scores_vectorized(pos_events, pos_lambda)
        neg_scores = get_source_scores_vectorized(neg_events, neg_lambda)
        return np.clip(pos_scores - (resistance_coefficient * neg_scores), 0.0, 1.0)

    def run_monitor(self) -> None:
        try:
            self.log_message("检查开始                  <--")
            
            sync_success = self.sync_urls_from_gist()

            if not sync_success and not self.memory_urls:
                self.log_warning("无法获取基准数据 (Gist 失败且内存 urls 为空), 跳过本次检查")
                self.cleanup()
                return

            
            found_new_parts = self.check_potential_new_parts()
            found_new_videos = self.quick_precheck()

            self.log_info(f"预检查完成 - 预测检查: {'发现新内容' if found_new_parts else '无新内容'} "
                          f"快速检查: {'发现新内容' if found_new_videos else '无新内容'}")

            
            if not (found_new_parts or found_new_videos):
                self.adjust_check_frequency(found_new_content=False)
                self.cleanup()
                return

            
            success, stdout, stderr = self.run_yt_dlp([
                '--cookies', self.cookies_file,
                '--flat-playlist',
                '--print', '%(webpage_url)s',
                f'https://space.bilibili.com/{self.BILIBILI_UID}/video'
            ])

            if not success or not stdout:
                self.log_critical_error("无法获取视频列表", "完整检查阶段", send_notification=True)
                self.adjust_check_frequency(found_new_content=False)
                self.cleanup()
                return

            video_urls = [line.strip() for line in stdout.split('\n') if line.strip()]

            if not video_urls:
                self.log_critical_error("未获取到任何内容", "完整检查阶段", send_notification=True)
                self.adjust_check_frequency(found_new_content=False)
                self.cleanup()
                return

            
            all_parts = self.get_all_videos_parallel(video_urls)

            if not all_parts:
                self.log_info("处理分片时出错, 错误已处理")
                all_parts = video_urls

            
            existing_urls_set = set(self.memory_urls)
            current_urls_set = set(all_parts)

            
            gist_missing_urls = current_urls_set - existing_urls_set  
            truly_new_urls = gist_missing_urls - self.known_urls  

            if gist_missing_urls:
                
                old_count = len(gist_missing_urls) - len(truly_new_urls)
                new_count = len(truly_new_urls)

                display = f"{'*' * old_count}{' ' if old_count > 0 and new_count > 0 else ''}{'*' * new_count}"
                self.log_info(display)

                
                if truly_new_urls:
                    self.save_real_upload_timestamps(truly_new_urls)

                self.known_urls.update(gist_missing_urls)
                self.save_known_urls()

                if self.dev_mode:
                    self.dev_new_videos += len(gist_missing_urls)
                else:
                    if not self.notify_new_videos(len(gist_missing_urls), has_new_parts=found_new_parts):
                        self.log_critical_error("通知发送失败 - 无法向用户推送新视频通知", "notify_new_videos", send_notification=False)
                
                
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

            
            self.cleanup()

        except KeyboardInterrupt:
            self.log_info("收到中断信号, 正在退出...")
            self.cleanup()
            sys.exit(0)
        except Exception as e:
            self.log_critical_error(f"监控脚本运行时出现意外错误: {e}", "run_monitor", send_notification=True)
            self.cleanup()

def main() -> None:
    load_env_file()
    args = parse_arguments()  
    monitor = VideoMonitor(dev_mode=args.dev)

    if args.dev:
        try:
            monitor.run_monitor()
            monitor.wait_for_next_check()
            sys.exit(0)
        except KeyboardInterrupt:
            monitor.log_info("程序被用户中断")
            monitor.cleanup()
            sys.exit(0)
        except Exception as e:
            monitor.log_critical_error(f"运行出错: {e}", "main(dev)", send_notification=False)
            sys.exit(1)

    else:
        try:
            if os.path.exists(monitor.wgmm_config_file):
                try:
                    with open(monitor.wgmm_config_file, 'r', encoding='utf-8') as f:
                        config = json.load(f)
                    if 'is_manual_run' not in config:
                        config['is_manual_run'] = True
                        with open(monitor.wgmm_config_file, 'w', encoding='utf-8') as f:
                            json.dump(config, f, indent=2, ensure_ascii=False)
                        monitor.log_info("首次运行，已设置 is_manual_run = True")
                except Exception as e:
                    monitor.log_warning(f"初始化运行标志失败: {e}")
            else:
                
                monitor.log_info("首次运行，将自动初始化配置")
        except Exception as e:
            monitor.log_warning(f"初始化检查失败: {e}")

        try:
            while True:
                
                monitor.wait_for_next_check()
                
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
