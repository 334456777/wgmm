#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bilibili 视频监控系统
======================

基于智能频率调整的视频更新检测系统, 支持分片预检查、快速检查和完整检查的多层级检测策略。

主要功能:
    - 监控指定 Bilibili 用户空间的视频更新
    - 使用 WGMM (加权高斯混合模型) 算法智能调整检查频率
    - 通过 Bark 推送通知新视频发现和系统异常
    - 支持多分片视频的智能检测

依赖:
    - yt-dlp: 用于获取视频信息
    - requests: 用于 API 调用
    
作者: VideoMonitor Team
版本: 2.0.0
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

# ==================== 加载环境变量 ====================
def load_env_file(env_path: str = '.env') -> None:
    """加载 .env 文件中的环境变量
    
    Args:
        env_path: .env 文件路径，默认为当前目录的 .env
    """
    if not os.path.exists(env_path):
        return
    
    try:
        with open(env_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                # 跳过空行和注释
                if not line or line.startswith('#'):
                    continue
                # 解析 KEY=VALUE
                if '=' in line:
                    key, value = line.split('=', 1)
                    key = key.strip()
                    value = value.strip()
                    # 只在环境变量不存在时设置
                    if key and not os.getenv(key):
                        os.environ[key] = value
    except Exception as e:
        print(f"Warning: Failed to load .env file: {e}", file=sys.stderr)

# 在导入后立即加载 .env
load_env_file()

class VideoMonitor:
    """Bilibili 视频监控系统主类
    
    该类实现了一个完整的视频更新监控系统, 包含以下核心功能：
    
    1. **多层级检测策略**:
       - 分片预检查：检测已有多分片视频的新分片
       - 快速检查：通过最新视频 ID 快速判断是否有更新
       - 完整检查：获取所有视频链接并进行比对
    
    2. **智能频率调整 (WGMM)**:
       使用加权高斯混合模型算法, 根据历史发布时间模式
       动态调整检查频率, 在活跃时段增加检查频率。
    
    3. **分级通知系统**:
       通过 Bark API 发送推送通知, 支持不同优先级：
       - critical: 严重错误, 强制响铃
       - timeSensitive: 时效性通知, 可突破专注模式
       - active: 普通通知
       - passive: 静默通知
    
    Attributes:
        GIST_ID: GitHub Gist ID, 用于存储已备份的视频 URL 列表
        GITHUB_TOKEN: GitHub API 访问令牌
        memory_urls: 内存中缓存的已备份视频 URL 列表
        known_urls: 本地已知的所有视频 URL 集合（包括已备份和待备份）
        bark_device_key: Bark 推送服务的设备密钥
        
    Example:
        >>> monitor = VideoMonitor()
        >>> monitor.run_monitor()  # 执行一次检查
        
    Note:
        运行前需要确保:
        - yt-dlp 已安装并可用
        - cookies.txt 文件包含有效的 Bilibili 登录凭证
        - GitHub Token 具有 Gist 读取权限
    """
    
    # 类常量定义
    DEFAULT_CHECK_INTERVAL: int = 24000  # 默认检查间隔 (秒)= 400分钟
    FALLBACK_INTERVAL: int = 7200  # 降级检查间隔 (秒)= 2小时
    MAX_RETRY_ATTEMPTS: int = 3  # 最大重试次数

    def __init__(self) -> None:
        """初始化视频监控系统实例
        
        执行以下初始化操作：
        1. 配置 GitHub Gist API 访问参数
        2. 初始化内存数据结构
        3. 设置文件路径常量
        4. 配置 Bark 推送通知参数
        5. 初始化日志系统
        6. 注册系统信号处理器
        
        Raises:
            无直接异常, 但信号注册失败会导致程序无法优雅退出
        """
        # ==================== GitHub Gist 配置 ====================
        # 用于存储和同步已备份视频的 URL 列表
        self.GIST_ID: str = os.getenv("GIST_ID", "")
        self.GITHUB_TOKEN: str = os.getenv("GITHUB_TOKEN", "")
        self.GIST_BASE_URL: str = "https://api.github.com/gists"
        self.BILIBILI_UID: str = os.getenv("BILIBILI_UID", "")
        
        # 验证必要的环境变量
        if not self.GIST_ID or not self.GITHUB_TOKEN:
            print("Error: Missing required environment variables. Please check your .env file.", file=sys.stderr)
            print("Required: GIST_ID, GITHUB_TOKEN, BILIBILI_UID", file=sys.stderr)
            sys.exit(1)
        
        if not self.BILIBILI_UID:
            print("Error: Missing BILIBILI_UID in .env file.", file=sys.stderr)
            sys.exit(1)

        # ==================== 核心数据结构 ====================
        # 内存化的 URL 列表, 替代文件读写提高性能
        self.memory_urls: list[str] = []  # 从 Gist 同步的 URL 列表（代表已备份的视频）
        self.known_urls: set[str] = set()  # 本地已知的所有 URL（包括 Gist 未同步的）

        # ==================== 文件路径配置 ====================
        self.log_file: str = "urls.log"  # 主日志文件
        self.critical_log_file: str = "critical_errors.log"  # 重大错误专用日志
        self.wgmm_config_file: str = "wgmm_config.json"  # WGMM 算法配置文件
        self.local_known_file: str = "local_known.txt"  # 本地已知 URL 持久化文件
        self.mtime_file: str = "mtime.txt"  # 视频发布时间戳历史
        self.cookies_file: str = "cookies.txt"  # Bilibili 登录凭证
        self.tmp_outputs_dir: str = "tmp_outputs"  # 临时输出目录
        
        # ==================== Bark 推送通知配置 ====================
        self.bark_device_key: str = os.getenv("BARK_DEVICE_KEY", "")
        self.bark_base_url: str = "https://api.day.app"
        self.bark_app_title: str = "菠萝视频备份"
        
        # 验证 Bark 配置
        if not self.bark_device_key:
            print("Error: Missing BARK_DEVICE_KEY in .env file.", file=sys.stderr)
            sys.exit(1)
        
        # ==================== 控制论优化：运行时性能监控 ====================
        # 捕获 yt-dlp 实际运行耗时,作为网络环境健康度指标
        # 用于实现循环阻尼(Loop Damping),防止在网络拥堵时过度请求
        self.last_ytdlp_duration: float = 0.0  # 最后一次 yt-dlp 耗时 (秒)
        self.normal_ytdlp_duration: float = 30.0  # 正常耗时基准 (秒,通过移动平均自适应)
        
        # ==================== 初始化子系统 ====================
        self.setup_logging()
        self.load_known_urls()  # 加载本地已知 URL
        
        # ==================== 注册信号处理器 ====================
        # 确保程序能够优雅地响应终止信号
        signal.signal(signal.SIGTERM, self.signal_handler)
        signal.signal(signal.SIGINT, self.signal_handler)

    def setup_logging(self) -> None:
        """配置日志系统
        
        初始化 Python 标准 logging 模块, 设置统一的日志格式和级别。
        日志同时输出到控制台和文件。
        
        日志格式: ``YYYY-MM-DD HH:MM:SS - 消息内容``
        
        Note:
            此方法仅初始化 logging 模块, 实际的日志写入
            由 :meth:`log_message` 方法处理。
        """
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        self.logger: logging.Logger = logging.getLogger(__name__)

    def load_known_urls(self) -> None:
        """从本地文件加载已知 URL 集合
        
        读取 local_known.txt 文件，恢复程序上次运行时的已知 URL 状态。
        如果文件不存在，将自动创建空文件。
        """
        try:
            if os.path.exists(self.local_known_file):
                with open(self.local_known_file, 'r', encoding='utf-8') as f:
                    # 纯文本格式：每行一个 URL
                    self.known_urls = set(line.strip() for line in f if line.strip())
            else:
                # 文件不存在，创建初始空文件
                self.known_urls = set()
                self.save_known_urls()
        except Exception as e:
            self.log_warning(f"加载本地已知 URL 失败: {e}，将使用空集合")
            self.known_urls = set()

    def save_known_urls(self) -> None:
        """保存已知 URL 集合到本地文件
        
        将当前的 known_urls 集合持久化到 local_known.txt 文件，
        以便程序重启后能够恢复状态。使用纯文本格式，每行一个 URL。
        """
        try:
            with open(self.local_known_file, 'w', encoding='utf-8') as f:
                # 保存为纯文本格式，每行一个 URL（按字典序排序便于查看和对比）
                f.write('\n'.join(sorted(self.known_urls)))
        except Exception as e:
            self.log_warning(f"保存本地已知 URL 失败: {e}")

    def signal_handler(self, signum: int, frame: FrameType | None) -> None:
        """系统信号处理器
        
        处理 SIGTERM 和 SIGINT 信号, 确保程序能够优雅地退出。
        在退出前会清理临时文件和资源。
        
        Args:
            signum: 接收到的信号编号
                   - SIGTERM (15): 终止信号
                   - SIGINT (2): 键盘中断 (Ctrl+C)
            frame: 当前的栈帧对象, 用于调试 (通常不使用)
            
        Note:
            此方法被注册为信号处理器, 由操作系统在接收到信号时调用。
            调用 :meth:`cleanup` 清理资源后, 程序以状态码 0 退出。
        """
        self.log_message(f"收到信号 {signum}, 正在清理并退出...")
        self.cleanup()
        sys.exit(0)

    def log_message(self, message: str, level: str = 'INFO') -> None:
        """记录日志消息到文件和控制台
        
        这是日志系统的核心方法, 所有日志记录最终都通过此方法执行。
        日志会同时写入文件和输出到控制台, 并自动管理日志文件大小。
        
        Args:
            message: 日志消息内容
            level: 日志级别, 可选值:
                   - 'INFO': 信息 (默认)
                   - 'WARNING': 警告
                   - 'ERROR': 错误
                   - 'CRITICAL': 严重错误
                   
        日志格式::
        
            YYYY-MM-DD HH:MM:SS - LEVEL - 消息内容
            
        Note:
            日志文件会自动限制在 100,000 行以内, 超出时保留最新的日志。
        """
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        log_entry = f"{timestamp} - {level} - {message}\n"
        
        with open(self.log_file, 'a', encoding='utf-8') as f:
            f.write(log_entry)
            
        self.limit_file_lines(self.log_file, 100000)
        print(f"{timestamp} - {level} - {message}")

    def log_info(self, message: str) -> None:
        """记录信息级别的日志
        
        用于记录正常运行状态和关键事件。
        
        Args:
            message: 信息消息内容
            
        Example:
            >>> self.log_info("检查开始")
            >>> self.log_info(f"发现 {count} 个新视频")
        """
        self.log_message(message, 'INFO')

    def log_warning(self, message: str) -> None:
        """记录警告级别的日志
        
        警告表示预期内的异常情况, 程序可以自动降级处理。
        不会触发 Bark 通知。
        
        Args:
            message: 警告消息内容
            
        Example:
            >>> self.log_warning("缓存文件不存在, 使用默认值")
        """
        self.log_message(message, 'WARNING')

    def log_error(self, message: str, send_bark_notification: bool = True) -> None:
        """记录错误日志并可选发送 Bark 推送通知
        
        记录 ERROR 级别的日志, 并根据参数决定是否发送 Bark 通知。
        用于记录功能性错误, 这些错误通常不会导致程序崩溃。
        
        Args:
            message: 错误消息内容
            send_bark_notification: 是否发送 Bark 通知
                                   - True: 发送通知 (默认)
                                   - False: 仅记录日志
                                   
        Example:
            >>> # 发送通知的错误
            >>> self.log_error("API 请求失败")
            >>> # 不发送通知的错误 (避免通知轰炸)
            >>> self.log_error("缓存读取失败", send_bark_notification=False)
        """
        self.log_message(message, 'ERROR')
        
        # 发送 Bark 通知
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
        """记录严重错误并发送 Bark 通知
        
        这是最高级别的错误处理方法。除了记录到日志文件外, 
        还会发送 ``critical`` 级别的 Bark 通知。
        
        Args:
            message: 错误消息内容
            context: 错误发生的上下文 (如方法名、阶段等)
            send_notification: 是否发送 Bark 通知
                              - True: 发送通知 (默认)
                              - False: 仅记录日志
                              
        Note:
            - 错误会同时记录到 ``urls.log`` 和 ``critical_errors.log``
            - 使用 ``critical`` 级别通知, 会忽略设备静音设置
            message: 错误消息
            context: 错误上下文信息
            send_notification: 是否发送 Bark 通知
        """
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        full_message = f"{message}"
        if context:
            full_message += f" [上下文: {context}]"
            
        # 记录到重大错误专用日志文件 (直接写入, 避免调用可能有问题的方法)
        try:
            critical_log_entry = f"{timestamp} - CRITICAL - {full_message}\n"
            with open(self.critical_log_file, 'a', encoding='utf-8') as f:
                f.write(critical_log_entry)
            
            # 限制日志文件大小
            self._limit_critical_log_lines()
        except Exception as e:
            # 日志写入失败时, 至少输出到控制台
            print(f"{timestamp} - CRITICAL - 无法写入重大错误日志: {e}")
            print(f"{timestamp} - CRITICAL - 原始错误: {full_message}")
            
        # 同时记录到常规日志
        try:
            self.log_error(full_message, send_bark_notification=False)  # 避免重复通知
        except Exception:
            print(f"{timestamp} - ERROR - {full_message}")
            
        # 发送 Bark 通知 (使用 critical 级别)
        if send_notification:
            if self.notify_critical_error(message, context):
                print(f"{timestamp} - INFO - 重大错误通知已发送")
            else:
                print(f"{timestamp} - WARNING - 重大错误通知发送失败")

    def _limit_critical_log_lines(self, max_lines: int = 20000) -> None:
        """限制重大错误日志文件的行数 (内部方法)
        
        保持重大错误日志文件在合理大小范围内, 避免占用过多磁盘空间。
        
        Args:
            max_lines: 最大保留行数, 默认 20,000 行
            
        Note:
            此方法静默忽略所有错误, 避免在错误处理流程中产生无限递归。
        """
        try:
            self.limit_file_lines(self.critical_log_file, max_lines)
        except Exception:
            # 静默忽略, 避免无限递归
            pass

    def limit_file_lines(self, filepath: str, max_lines: int) -> None:
        """限制指定文件的行数
        
        根据不同文件类型采用不同的日志轮转策略：
        
        - ``urls.log``: 保留前 2 行 (标题), 删除中间的旧日志
        - ``critical_errors.log``: 保留第 1 行 (标题), 删除中间的旧日志  
        - 其他文件: 保留最新的指定行数
        
        Args:
            filepath: 要限制的文件路径
            max_lines: 最大保留行数
            
        Raises:
            此方法内部捕获所有异常并记录到重大错误日志。
        """
        try:
            if os.path.exists(filepath):
                with open(filepath, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                
                if len(lines) > max_lines:
                    # 根据文件类型确定保留策略
                    if filepath == self.log_file:  # urls.log
                        # 保留前2行 (注释和标题), 然后保留最新的 max_lines-2 行
                        keep_lines = lines[:2] + lines[-(max_lines-2):]
                    elif filepath == self.critical_log_file:  # critical_errors.log
                        # 保留第1行 (注释), 然后保留最新的 max_lines-1 行
                        keep_lines = lines[:1] + lines[-(max_lines-1):]
                    else:
                        # 其他文件保留最新的指定行数
                        keep_lines = lines[-max_lines:]
                    
                    with open(filepath, 'w', encoding='utf-8') as f:
                        f.writelines(keep_lines)
        except Exception as e:
            # 记录到重大错误日志, 避免无限递归
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
        """发送 Bark 推送通知 (统一接口)
        
        根据 Bark API v2.0 规范发送推送通知。这是所有通知方法的底层实现, 
        支持完整的 Bark API 参数。
        
        Args:
            title: 通知标题, 在通知中以粗体显示
            body: 通知正文内容
            level: 通知优先级, 控制通知的展示行为
                   
                   - ``"active"``: 默认级别, 立即亮屏显示
                   - ``"timeSensitive"``: 时效性通知, 可突破专注模式
                   - ``"passive"``: 被动通知, 仅添加到通知列表, 不亮屏
                   - ``"critical"``: 严重警告, 忽略静音和勿扰模式
                   
            sound: 通知铃声名称 (如 ``"minuet"``, ``"alarm"``, ``"bell"``)
            group: 通知分组名称, 相同分组的通知会聚合显示
            icon: 自定义图标的 URL (需要 iOS 15+)
            url: 点击通知后跳转的 URL, 支持 http/https 和自定义 scheme
            is_archive: 是否将通知保存到 Bark 历史记录
            call: 是否启用持续响铃模式 (响铃 30 秒, 适合重要提醒)
            volume: 通知音量 (0-10), 仅在 ``level="critical"`` 时生效
            
        Returns:
            发送是否成功。``True`` 表示服务器返回 200 状态码。
            
        Example:
            >>> # 发送普通通知
            >>> self.send_bark_push("标题", "内容")
            True
            
            >>> # 发送紧急通知 (忽略勿扰模式)
            >>> self.send_bark_push(
            ...     title="紧急警告",
            ...     body="服务器宕机",
            ...     level="critical",
            ...     sound="alarm",
            ...     volume=10,
            ...     call=True
            ... )
        """
        import urllib.parse
        
        try:
            # 构建基础URL: /device_key/title/body
            encoded_title = urllib.parse.quote(title)
            encoded_body = urllib.parse.quote(body)
            base_url = f"{self.bark_base_url}/{self.bark_device_key}/{encoded_title}/{encoded_body}"
            
            # 构建查询参数列表
            params = []
            
            # 通知级别 (active 是默认值, 不需要显式传递)
            if level and level != "active":
                params.append(f"level={level}")
            
            # 声音相关参数
            if sound:
                params.append(f"sound={urllib.parse.quote(sound)}")
            if call:
                params.append("call=1")
            if volume is not None and level == "critical":
                params.append(f"volume={volume}")
            
            # 通知分组
            if group:
                params.append(f"group={urllib.parse.quote(group)}")
            
            # 自定义图标
            if icon:
                params.append(f"icon={urllib.parse.quote(icon)}")
            
            # 点击跳转 URL
            if url:
                params.append(f"url={urllib.parse.quote(url)}")
            
            # 保存到历史记录
            if is_archive:
                params.append("isArchive=1")
            
            # 组装完整 URL
            full_url = f"{base_url}?{'&'.join(params)}" if params else base_url
            
            response = requests.get(full_url, timeout=30)
            return response.status_code == 200
            
        except Exception as e:
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            print(f"{timestamp} - WARNING - Bark推送失败: {e}")
            return False

    def notify_new_videos(self, count: int, has_new_parts: bool = False) -> bool:
        """发送新视频发现通知
        
        当检测到新视频时调用此方法发送推送通知。
        使用 ``timeSensitive`` 级别, 可以突破 iOS 专注模式。
        
        Args:
            count: 发现的新视频数量
            has_new_parts: 是否包含多分片视频的新分片
            
        Returns:
            通知是否发送成功
            
        Returns:
            bool: 发送是否成功
        """
        if has_new_parts:
            body = f"发现 {count} 个新视频(含新分片)等待备份"
        else:
            body = f"发现 {count} 个新视频等待备份"
        
        return self.send_bark_push(
            title=self.bark_app_title,
            body=body,
            level="timeSensitive",  # 时效性通知, 可突破专注模式
            sound="minuet",
            group="新视频"
        )

    def notify_error(self, message: str) -> bool:
        """发送普通错误通知
        
        用于通知一般性错误, 使用 ``active`` 级别 (默认)。
        这类错误通常不会导致程序崩溃, 但需要用户注意。
        
        Args:
            message: 错误消息内容
            
        Returns:
            通知是否发送成功
        """
        return self.send_bark_push(
            title=f"{self.bark_app_title} - 错误",
            body=message,
            level="active",
            group="错误"
        )

    def notify_critical_error(self, message: str, context: str = "") -> bool:
        """发送严重错误通知
        
        用于通知系统级的严重错误, 使用 ``critical`` 级别。
        此级别会忽略设备的静音和勿扰模式, 强制播放警报声。
        
        Args:
            message: 错误消息内容
            context: 错误发生的上下文信息 (可选)
            
        Returns:
            通知是否发送成功
            
        Note:
            此方法会启用持续响铃模式 (30秒), 确保用户注意到通知。
        """
        body = message
        if context:
            body += f" ({context})"
        
        return self.send_bark_push(
            title=f"⚠️ {self.bark_app_title} - 严重错误",
            body=body,
            level="critical",  # 忽略静音和勿扰模式
            sound="alarm",
            volume=8,
            call=True,  # 持续响铃 30 秒
            group="严重错误"
        )

    def notify_service_issue(self, message: str) -> bool:
        """发送服务异常通知
        
        用于通知外部服务问题 (如 Gist 同步失败、API 超时等)。
        使用 ``timeSensitive`` 级别, 可以突破专注模式但不会强制响铃。
        
        Args:
            message: 问题描述
            
        Returns:
            通知是否发送成功
        """
        return self.send_bark_push(
            title=f"{self.bark_app_title} - 服务异常",
            body=message,
            level="timeSensitive",
            group="服务异常"
        )

    def get_next_check_time(self) -> int:
        """从 WGMM 配置文件读取下次检查时间戳
        
        从 ``wgmm_config.json`` 文件中读取预计算的下次检查时间。
        该时间由 WGMM 算法根据历史数据模式计算得出。
        
        Returns:
            下次检查的 Unix 时间戳 (秒)。
            如果文件不存在或读取失败, 返回 0。
            
        Example:
            >>> monitor = VideoMonitor()
            >>> next_time = monitor.get_next_check_time()
            >>> if next_time > 0:
            ...     print(f"下次检查: {datetime.fromtimestamp(next_time)}")
        """
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
        """保存下次检查时间到配置文件
        
        将计算得出的下次检查时间戳持久化到 ``wgmm_config.json``, 
        以便程序重启后能够恢复检查计划。
        
        Args:
            next_check_timestamp: 下次检查的 Unix 时间戳 (秒)
            
        Note:
            此方法会保留配置文件中的其他字段 (如维度权重等)。
        """
        try:
            # 读取现有配置, 保留其他字段
            config: dict[str, Any] = {}
            if os.path.exists(self.wgmm_config_file):
                with open(self.wgmm_config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
            
            # 更新 next_check_time 字段
            config['next_check_time'] = next_check_timestamp
            
            # 写回文件
            with open(self.wgmm_config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            self.log_warning(f"保存next_check_time失败: {e}")

    def sync_urls_from_gist(self) -> bool:
        """从 GitHub Gist 下载内容并更新内存中的 URL 列表
        
        使用 GitHub API 获取 Gist 内容, 并将其解析为 URL 列表
        存储在 ``self.memory_urls`` 中。
        
        Returns:
            是否成功同步 URL 列表
            
        Note:
            - 验证 GIST_ID 和 GITHUB_TOKEN 必须存在
            - 验证 Gist 必须只包含一个文件
            - 失败时会发送 CRITICAL 级别错误通知
            - 超时时间为 30 秒
        """
        # 验证必需的配置
        if not self.GIST_ID:
            self.log_critical_error("GIST_ID 未配置", "Gist 同步", send_notification=True)
            return False
            
        if not self.GITHUB_TOKEN:
            self.log_critical_error("GITHUB_TOKEN 未配置", "Gist 同步", send_notification=True)
            return False
        
        headers = {
            "Authorization": f"Bearer {self.GITHUB_TOKEN}",
            "Accept": "application/vnd.github.v3+json",
        }
        url = f"{self.GIST_BASE_URL}/{self.GIST_ID}"
        
        try:
            response: requests.Response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            data: dict[str, Any] = response.json()
            
            files: dict[str, Any] = data.get("files", {})
            
            # 验证 Gist 必须只包含一个文件
            file_count = len(files)
            if file_count != 1:
                self.log_critical_error(
                    f"Gist 文件数量错误: 期望 1 个，实际 {file_count} 个",
                    "Gist 同步验证",
                    send_notification=True
                )
                return False
            
            # 获取唯一的文件（不再验证文件名）
            file_data: dict[str, Any] = next(iter(files.values()))
            content: str = file_data.get("content", "")
            
            # 直接在内存中处理字符串, 分割成列表
            self.memory_urls = [line.strip() for line in content.splitlines() if line.strip()]
            
            # 将 Gist 中的 URL 也加入 known_urls（这些是已备份的视频，应该标记为已知）
            self.known_urls.update(self.memory_urls)
            self.save_known_urls()  # 立即保存
            
            return True
            
        except requests.exceptions.HTTPError as e:
            self.log_critical_error(
                f"Gist API 请求失败: HTTP {e.response.status_code}",
                "Gist 同步",
                send_notification=True
            )
            return False
        except Exception as e:
            self.log_critical_error(
                f"从 Gist 获取数据失败: {str(e)}",
                "Gist 同步",
                send_notification=True
            )
            return False

    def get_video_upload_time(self, video_url: str) -> int | None:
        """获取视频的真实上传时间戳
        
        通过 yt-dlp 获取视频的元信息, 提取真实的上传时间戳。
        
        Args:
            video_url: 视频的 URL 地址
            
        Returns:
            视频的上传时间戳 (Unix timestamp), 获取失败时返回 None
            
        Note:
            - 优先使用 timestamp 字段
            - 其次使用 upload_date 字段 (格式 YYYYMMDD)
            - 如果都无法获取, 返回 None
        """
        try:
            # 使用 --print 获取时间戳和上传日期
            success, stdout, stderr = self.run_yt_dlp([
                '--cookies', self.cookies_file,
                '--print', '%(timestamp)s|%(upload_date)s',
                '--no-download',
                video_url
            ], timeout=60)
            
            if not success or not stdout:
                self.log_warning(f"获取视频上传时间失败: {video_url[:50]}...")
                return None
            
            # 解析输出：timestamp|upload_date
            parts = stdout.strip().split('|')
            
            # 优先使用 timestamp
            if len(parts) >= 1 and parts[0] and parts[0] != 'NA':
                try:
                    return int(parts[0])
                except ValueError:
                    pass
            
            # 其次使用 upload_date (格式: YYYYMMDD)
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
        """保存新视频的真实上传时间戳
        
        为每个新发现的视频获取其真实上传时间, 并追加到 mtime.txt。
        这确保了 WGMM 算法使用的是视频实际发布时间, 而非检查发现时间。
        
        Args:
            new_urls: 新发现的视频 URL 集合
            
        Note:
            - 如果无法获取某个视频的上传时间, 会使用当前时间作为降级方案
            - 如果 mtime.txt 不存在, 会尝试自动创建
            - 获取到的时间戳会按升序排序后追加
            
        See Also:
            - ``get_video_upload_time()``: 获取单个视频的上传时间
            - ``save_discovery_timestamp()``: 旧方法 (使用当前时间)
        """
        if not new_urls:
            return
            
        # 确保 mtime.txt 存在
        if not os.path.exists(self.mtime_file):
            if not self.generate_mtime_file("save_real_upload_timestamps"):
                self.log_warning("无法创建 mtime.txt, 仍然保存时间戳")
        
        timestamps = []
        current_time = int(time.time())
        
        self.log_info(f"正在获取 {len(new_urls)} 个新视频的真实上传时间...")
        
        for url in new_urls:
            upload_time = self.get_video_upload_time(url)
            
            if upload_time:
                timestamps.append(upload_time)
            else:
                # 降级：无法获取真实时间时使用当前时间
                self.log_warning(f"降级使用当前时间: {url[:50]}...")
                timestamps.append(current_time)
        
        if timestamps:
            # 按时间排序后追加
            sorted_timestamps = sorted(timestamps)
            
            with open(self.mtime_file, 'a') as f:
                for ts in sorted_timestamps:
                    f.write(f"{ts}\n")
            
            self.limit_file_lines(self.mtime_file, 100000)
            self.log_info(f"成功保存 {len(timestamps)} 个真实上传时间戳")

    def create_mtime_from_info_json(self) -> bool:
        """使用 yt-dlp 获取视频元信息创建 mtime.txt
        
        当 ``mtime.txt`` 不存在时, 通过 yt-dlp 的 ``--write-info-json`` 功能
        获取所有视频的发布时间, 并将这些时间戳写入 ``mtime.txt`` 文件。
        
        Returns:
            是否成功创建 ``mtime.txt`` 文件
            
        Note:
            - 此操作可能需要较长时间 (最多 10 分钟超时)
            - 临时文件存储在 ``temp_info_json`` 目录
            - 操作完成后会自动清理临时目录
            
        See Also:
            ``generate_mtime_file()``: 包装此方法的主入口
        """
        # 创建临时目录用于存储 info json 文件
        temp_info_dir = "temp_info_json"
        os.makedirs(temp_info_dir, exist_ok=True)
        
        try:
            # 使用 yt-dlp 获取所有视频的元信息
            success, stdout, stderr = self.run_yt_dlp([
                '--cookies', self.cookies_file,
                '--write-info-json',
                '--skip-download',
                '--restrict-filenames',
                '--output', f'{temp_info_dir}/%(id)s.%(ext)s',
                f'https://space.bilibili.com/{self.BILIBILI_UID}/video'
            ], timeout=600)  # 增加超时时间到 10 分钟
            
            if not success:
                self.log_warning(f"获取元信息失败: {stderr[:100]}")  # 降级为 WARNING, 会在 generate_mtime_file 中重试
                return False
                
            # 收集所有 .info.json 文件中的上传时间戳
            timestamps = []
            info_files = []
            
            # 查找所有 .info.json 文件
            for root, dirs, files in os.walk(temp_info_dir):
                for file in files:
                    if file.endswith('.info.json'):
                        info_files.append(os.path.join(root, file))
                        
            self.log_info(f"找到 {len(info_files)} 个 info.json 文件")
            
            # 解析每个 info.json 文件获取时间戳
            for info_file in info_files:
                try:
                    with open(info_file, 'r', encoding='utf-8') as f:
                        info_data = json.load(f)
                        
                    # 尝试获取上传时间戳
                    upload_timestamp = None
                    
                    # 优先使用 timestamp 字段
                    if 'timestamp' in info_data and info_data['timestamp']:
                        upload_timestamp = int(info_data['timestamp'])
                    # 其次使用 upload_date 字段
                    elif 'upload_date' in info_data and info_data['upload_date']:
                        upload_date = info_data['upload_date']
                        try:
                            # upload_date 格式通常是 YYYYMMDD
                            dt = datetime.strptime(upload_date, '%Y%m%d')
                            upload_timestamp = int(dt.timestamp())
                        except ValueError:
                            pass
                        
                    if upload_timestamp and upload_timestamp > 0:
                        timestamps.append(upload_timestamp)
                        
                except Exception as e:
                    self.log_warning(f"解析 info.json 文件失败: {info_file} - {e}")
                    continue
                    
            # 清理临时目录
            try:
                shutil.rmtree(temp_info_dir)
            except Exception as e:
                self.log_warning(f"清理临时目录失败: {e}")
                
            if not timestamps:
                self.log_warning("未能从任何 info.json 文件中提取到有效时间戳")
                return False
                
            # 排序时间戳 (保留重复的时间戳)
            sorted_timestamps = sorted(timestamps)
            
            # 写入 mtime.txt
            with open(self.mtime_file, 'w') as f:
                for timestamp in sorted_timestamps:
                    f.write(f"{timestamp}\n")
                    
            self.log_info(f"成功创建 mtime.txt, 包含 {len(sorted_timestamps)} 个时间戳")
            return True
            
        except Exception as e:
            self.log_warning(f"创建 mtime.txt 时出错: {e}")
            # 清理临时目录
            try:
                shutil.rmtree(temp_info_dir)
            except:
                pass
            return False

    def generate_mtime_file(self, context: str = "") -> bool:
        """生成 mtime.txt 文件的通用函数
        
        当 ``mtime.txt`` 不存在时, 尝试通过 yt-dlp 获取所有视频的发布时间
        并将这些时间戳写入 ``mtime.txt`` 文件。如果失败会进行多次重试。
        
        Args:
            context: 调用上下文信息, 用于日志记录和问题诊断
            
        Returns:
            是否成功生成 ``mtime.txt`` 文件
            
        Note:
            - 最多尝试 3 次
            - 所有尝试失败后会触发 CRITICAL 级别错误通知
            
        See Also:
            ``create_mtime_from_info_json()``: 实际执行文件创建的方法
        """
        max_attempts = 3
        attempt = 0
        
        while attempt < max_attempts:
            # 检查文件是否存在且不为空
            if os.path.exists(self.mtime_file) and os.path.getsize(self.mtime_file) > 0:
                return True
                
            attempt += 1
            if attempt == 1:
                self.log_info(f"mtime.txt 不可用, 第 {attempt} 次尝试生成 [{context}]")
            else:
                self.log_warning(f"mtime.txt 仍不可用, 第 {attempt} 次尝试生成 [{context}]")
                
            # 尝试生成 mtime.txt
            if self.create_mtime_from_info_json():
                # 生成成功后再次检查
                if os.path.exists(self.mtime_file) and os.path.getsize(self.mtime_file) > 0:
                    self.log_info(f"mtime.txt 第 {attempt} 次生成成功 [{context}]")
                    return True
                else:
                    self.log_warning(f"mtime.txt 第 {attempt} 次生成后仍不可用 [{context}]")
            else:
                self.log_warning(f"mtime.txt 第 {attempt} 次生成失败 [{context}]")
                
        # 所有尝试都失败了
        error_msg = f"经过 {max_attempts} 次尝试仍无法生成可用的 mtime.txt"
        if context:
            error_msg += f" [上下文: {context}]"
        self.log_critical_error(error_msg, "generate_mtime_file 方法", send_notification=True)
        return False

    def adjust_check_frequency(self, found_new_content: bool = False) -> None:
        """WGMM (加权高斯混合模型)自适应智能频率预测算法
        
        基于历史事件的时间周期性模式, 使用高斯核函数和指数衰减权重
        来预测当前时间点发生新事件的概率, 并动态调整检查频率。
        
        **控制论优化**: 实现完整的 PID 控制 + 反馈抑制 + 安全阻尼
        
        核心算法：
        1. 将历史时间戳转换为多维周期性特征 (sin/cos编码)
        2. 自动学习各维度的最优权重并保存到配置文件
        3. 使用高斯核函数和时间衰减权重计算热力得分
        4. 通过非线性映射将得分转换为检查间隔
        5. 根据历史数据自适应调整参数并持久化
        6. **PID-D 项**: 融入方差变化趋势,预判规律演变方向
        7. **反馈抑制**: 追踪预测失败,对连续未命中时段施加惩罚
        8. **时间遗忘**: 自动衰减历史失败记录,避免长期偏见
        9. **安全阻尼**: 根据网络耗时动态调整请求频率
        
        Args:
            found_new_content: 本次检查是否发现新内容
                             - True: 发现新内容 (预测成功,强化该时段模式)
                             - False: 未发现新内容 (可能是预测失败,触发抑制机制)
        
        周期性维度：
        - 日内周期：一天内的时刻 (0-86400秒)
        - 周内周期：一周内的时刻 (0-604800秒)
        - 月内周期：一月内第几周 (ISO标准)
        - 年内周期：一年内第几月 (1-12月)
        
        配置文件：wgmm_config.json (自动创建和更新)
        - 存储学习到的维度权重
        - 存储最后使用的衰减率
        - 存储最后更新时间戳
        """
        import math
        import calendar
        import json
        from collections import defaultdict
        
        # ==================== 模型超参数配置 ====================
        # 各维度的高斯核标准差 (控制时间模式匹配的严格程度)
        SIGMA_DAY = 0.8           # 日内周期标准差
        SIGMA_WEEK = 1.0          # 周内周期标准差
        SIGMA_MONTH_WEEK = 1.5    # 月内周数标准差
        SIGMA_YEAR_MONTH = 2.0    # 年内月份标准差
        
        # 初始维度权重 (算法会自动学习调整)
        WEIGHT_DAY = 0.5          # 日内周期初始权重
        WEIGHT_WEEK = 1.0         # 周内周期初始权重
        WEIGHT_MONTH_WEEK = 0.3   # 月内周数初始权重
        WEIGHT_YEAR_MONTH = 0.2   # 年内月份初始权重
        
        # 时间衰减参数
        LAMBDA_MIN = 0.00005      # 最小衰减率 (规律发布时)
        LAMBDA_BASE = 0.0001      # 基础衰减率
        LAMBDA_MAX = 0.0005       # 最大衰减率 (不规律发布时)
        
        # 轮询间隔参数
        DEFAULT_INTERVAL = 3600   # 默认基础轮询间隔 (秒)
        MAX_INTERVAL = 300        # 最高频轮询间隔 (秒)
        
        # 非线性映射参数
        MAPPING_CURVE = 2.0       # 指数映射曲线陡峭度 (值越大, 高得分时越敏感)
        
        # 学习参数
        LEARNING_RATE = 0.1       # 权重平滑学习率 (避免剧烈变化)
        MIN_HISTORY_COUNT = 10    # 最小历史数据量要求
        
        # 时间常量
        SECONDS_IN_DAY = 86400
        SECONDS_IN_WEEK = 604800
        
        # ==================== 配置文件管理 ====================
        # 配置文件路径 (与mtime.txt同目录)
        config_file = os.path.join(os.path.dirname(self.mtime_file), 'wgmm_config.json')
        
        # 加载或初始化配置
        def load_config():
            """加载配置文件, 如果不存在则创建"""
            default_config = {
                'dimension_weights': {
                    'day': WEIGHT_DAY,
                    'week': WEIGHT_WEEK,
                    'month_week': WEIGHT_MONTH_WEEK,
                    'year_month': WEIGHT_YEAR_MONTH
                },
                'last_lambda': LAMBDA_BASE,
                'last_update': 0,
                'next_check_time': 0,
                # ==================== 运行模式标识 ====================
                'is_manual_run': True,  # 手动运行标识 (True=手动运行不惩罚, False=自动运行会惩罚)
                # ==================== 控制论优化：反馈抑制追踪 ====================
                'false_positive_count': 0,  # 连续"未命中"次数 (预测高分但无新内容)
                # ==================== 控制论优化：方差趋势追踪 (PID-D 项) ====================
                'last_variance': 0.0,  # 上次计算的方差值
                'variance_trend': 0.0  # 方差变化趋势 (正=不规律加剧, 负=规律形成)
            }
            
            try:
                if os.path.exists(config_file):
                    with open(config_file, 'r', encoding='utf-8') as f:
                        config = json.load(f)
                    # 合并默认配置 (处理新增字段)
                    for key, value in default_config.items():
                        if key not in config:
                            config[key] = value
                        elif isinstance(value, dict):
                            for sub_key, sub_value in value.items():
                                if sub_key not in config[key]:
                                    config[key][sub_key] = sub_value
                    return config
                else:
                    # 文件不存在, 创建新配置
                    with open(config_file, 'w', encoding='utf-8') as f:
                        json.dump(default_config, f, indent=2, ensure_ascii=False)
                    self.log_info(f"已创建WGMM配置文件: {config_file}")
                    return default_config
            except Exception as e:
                self.log_warning(f"加载WGMM配置文件失败, 使用默认配置: {e}")
                return default_config
        
        def save_config(config_data):
            """保存配置到文件"""
            try:
                with open(config_file, 'w', encoding='utf-8') as f:
                    json.dump(config_data, f, indent=2, ensure_ascii=False)
            except Exception as e:
                self.log_warning(f"保存WGMM配置文件失败: {e}")
        
        # 加载配置
        config = load_config()
        dimension_weights_from_config = config['dimension_weights']
        
        # ==================== 控制论优化 1: 反馈抑制机制 + 时间遗忘 ====================
        # 目标：从"预测失败"中学习，避免在低价值时段过度检查
        # 原理：追踪连续未命中次数，施加递增惩罚；同时引入时间衰减，避免长期偏见
        
        false_positive_count = config.get('false_positive_count', 0)
        last_update_time = config.get('last_update', 0)
        is_manual_run = config.get('is_manual_run', True)  # 默认为手动运行
        
        # ==================== 时间遗忘机制：基于历史发布间隔的智能衰减 ====================
        # 目标：避免"带着昨天的偏见处理今天的任务"
        # 策略：基于历史平均发布间隔，动态计算遗忘周期
        # 读取历史数据计算平均发布间隔
        avg_publish_interval_hours = 4.0  # 默认4小时（向后兼容）
        
        if os.path.exists(self.mtime_file):
            try:
                with open(self.mtime_file, 'r') as f:
                    timestamps = [int(line.strip()) for line in f if line.strip().isdigit()]
                
                if len(timestamps) >= 2:
                    # 计算相邻视频的平均发布间隔
                    sorted_ts = sorted(timestamps)
                    intervals = [sorted_ts[i+1] - sorted_ts[i] for i in range(len(sorted_ts)-1)]
                    avg_interval_seconds = sum(intervals) / len(intervals)
                    avg_publish_interval_hours = avg_interval_seconds / 3600.0
                    
                    # 遗忘周期 = 平均发布间隔 * 0.5（保守策略）
                    # 理由：如果平均2天发一个视频，那么1天后应该开始遗忘之前的惩罚
                    avg_publish_interval_hours = max(1.0, avg_publish_interval_hours * 0.5)
            except Exception as e:
                self.log_warning(f"计算平均发布间隔失败: {e}, 使用默认值4小时")
        
        # 应用时间遗忘：每经过一个遗忘周期，原谅1次失败
        if last_update_time > 0:
            elapsed_hours = (int(time.time()) - last_update_time) / 3600.0
            
            if elapsed_hours > avg_publish_interval_hours:
                decay_amount = int(elapsed_hours / avg_publish_interval_hours)
                if decay_amount > 0:
                    false_positive_count = max(0, false_positive_count - decay_amount)
                    self.log_info(f"时间遗忘: 距上次检查 {elapsed_hours:.1f}小时，遗忘周期 {avg_publish_interval_hours:.1f}小时，减少惩罚 {decay_amount} 次")
        
        # 更新失败计数器 (仅在自动运行时计数)
        if is_manual_run:
            # 手动运行：不更新计数器，避免误触发惩罚
            # 但需要将标志设为 False，以便下次自动运行时正常工作
            config['is_manual_run'] = False
        else:
            # 自动运行：正常更新失败计数器
            if found_new_content:
                # 预测成功：重置失败计数，强化当前时段模式
                false_positive_count = 0
            else:
                # 预测失败：累积失败计数，准备施加抑制
                false_positive_count += 1
        
        config['false_positive_count'] = false_positive_count
        
        # 计算抑制惩罚强度
        # 阈值：连续失败 ≥3 次时触发
        # 强度：每多失败 1 次，增加 15% 惩罚 (上限 60%)
        inhibition_penalty = 0.0
        if false_positive_count >= 3:
            inhibition_penalty = min(0.6, (false_positive_count - 2) * 0.15)
        
        # ==================== 获取当前时间 ====================
        current_timestamp = int(time.time())
        current_dt = datetime.fromtimestamp(current_timestamp)
        
        # ==================== 检查和生成历史数据文件 ====================
        if not os.path.exists(self.mtime_file):
            if not self.generate_mtime_file("adjust_check_frequency"):
                frequency_sec = 7200  # 120分钟
                next_check_timestamp = int(time.time()) + frequency_sec
                next_check_time = datetime.fromtimestamp(next_check_timestamp).strftime('%Y年%m月%d日 %H:%M:%S')
                self.log_info(f"WGMM调频 - mtime.txt无法生成, 使用默认频率: 2小时 下次检查: {next_check_time}")  # 改为INFO, 降级处理
                self.save_next_check_time(next_check_timestamp)
                return
        
        # ==================== 加载历史时间戳数据 ====================
        historical_events = []
        try:
            with open(self.mtime_file, 'r') as f:
                raw_data = [line.strip() for line in f if line.strip().isdigit()]
                # 去重并保持时间顺序
                seen_timestamps = set()
                for timestamp_str in raw_data:
                    timestamp = int(timestamp_str)
                    if timestamp > 0 and timestamp not in seen_timestamps:
                        historical_events.append(timestamp)
                        seen_timestamps.add(timestamp)
        except Exception as e:
            self.log_warning(f"读取mtime.txt失败: {e}, 尝试重新生成")  # 降级为WARNING, 可自动恢复
            if self.generate_mtime_file("读取失败后重新生成"):
                # 重新尝试读取
                try:
                    with open(self.mtime_file, 'r') as f:
                        raw_data = [line.strip() for line in f if line.strip().isdigit()]
                        seen_timestamps = set()
                        for timestamp_str in raw_data:
                            timestamp = int(timestamp_str)
                            if timestamp > 0 and timestamp not in seen_timestamps:
                                historical_events.append(timestamp)
                                seen_timestamps.add(timestamp)
                    self.log_info("重新生成mtime.txt后读取成功")
                except Exception as e2:
                    self.log_warning(f"重新生成mtime.txt后仍无法读取: {e2}, 使用默认频率")  # 降级为WARNING
                    frequency_sec = 7200
                    next_check_timestamp = int(time.time()) + frequency_sec
                    next_check_time = datetime.fromtimestamp(next_check_timestamp).strftime('%Y年%m月%d日 %H:%M:%S')
                    self.log_info(f"WGMM调频 - 使用默认频率: 2小时 下次检查: {next_check_time}")  # 改为INFO
                    self.save_next_check_time(next_check_timestamp)
                    return
        
        # ==================== 数据质量检查：过滤离群点 ====================
        def filter_outliers(timestamps, current_time):
            """使用IQR方法过滤异常时间戳"""
            if len(timestamps) < 3:
                return [ts for ts in timestamps if ts <= current_time]
            
            sorted_ts = sorted(timestamps)
            intervals = [sorted_ts[i+1] - sorted_ts[i] for i in range(len(sorted_ts)-1)]
            
            if not intervals:
                return sorted_ts
            
            # 计算四分位数和IQR
            intervals_sorted = sorted(intervals)
            q1_idx = len(intervals_sorted) // 4
            q3_idx = (3 * len(intervals_sorted)) // 4
            q1 = intervals_sorted[q1_idx]
            q3 = intervals_sorted[q3_idx]
            iqr = q3 - q1
            
            # 定义离群值边界 (使用3倍IQR, 比较宽松)
            lower_bound = q1 - 3 * iqr
            upper_bound = q3 + 3 * iqr
            
            # 过滤掉间隔异常的时间戳
            filtered = [sorted_ts[0]]
            for i in range(len(intervals)):
                if lower_bound <= intervals[i] <= upper_bound:
                    filtered.append(sorted_ts[i+1])
            
            # 移除未来时间戳
            return [ts for ts in filtered if ts <= current_time]
        
        historical_events = filter_outliers(historical_events, current_timestamp)
        
        # ==================== 检查是否有足够的历史数据 ====================
        if not historical_events:
            self.log_warning("无有效历史数据, 尝试重新生成")
            if self.generate_mtime_file("无有效数据重新生成"):
                try:
                    with open(self.mtime_file, 'r') as f:
                        raw_data = [line.strip() for line in f if line.strip().isdigit()]
                        seen_timestamps = set()
                        for timestamp_str in raw_data:
                            timestamp = int(timestamp_str)
                            if timestamp > 0 and timestamp not in seen_timestamps:
                                historical_events.append(timestamp)
                                seen_timestamps.add(timestamp)
                    historical_events = filter_outliers(historical_events, current_timestamp)
                except Exception:
                    pass
                    
            if not historical_events:
                frequency_sec = 7200
                next_check_timestamp = int(time.time()) + frequency_sec
                next_check_time = datetime.fromtimestamp(next_check_timestamp).strftime('%Y年%m月%d日 %H:%M:%S')
                self.log_info(f"WGMM调频 - 仍无有效历史数据, 使用默认频率: 2小时 下次检查: {next_check_time}")  # 改为INFO
                self.save_next_check_time(next_check_timestamp)
                return
        
        # 最小数据量检查：数据不足进入学习期
        if len(historical_events) < MIN_HISTORY_COUNT:
            self.log_info(f"历史数据不足({len(historical_events)}条), 进入学习期模式")  # 改为INFO, 正常学习阶段
            frequency_sec = 3600  # 学习期使用1小时间隔
            next_check_timestamp = int(time.time()) + frequency_sec
            next_check_time = datetime.fromtimestamp(next_check_timestamp).strftime('%Y年%m月%d日 %H:%M:%S')
            self.log_info(f"WGMM调频 - 学习期模式: 1小时 下次检查: {next_check_time}")
            self.save_next_check_time(next_check_timestamp)
            return
        
        # ==================== 计算历史统计信息 ====================
        def calculate_interval_stats(timestamps):
            """计算历史间隔的均值和方差"""
            sorted_ts = sorted(timestamps)
            if len(sorted_ts) < 2:
                return DEFAULT_INTERVAL, 0
            
            intervals = [sorted_ts[i+1] - sorted_ts[i] for i in range(len(sorted_ts)-1)]
            mean_interval = sum(intervals) / len(intervals)
            variance = sum((x - mean_interval) ** 2 for x in intervals) / len(intervals)
            
            return int(mean_interval), variance
        
        BASE_INTERVAL, interval_variance = calculate_interval_stats(historical_events)
        
        # ==================== 控制论优化 2: 方差变化趋势分析 (PID-D 项)====================
        # 目标：不仅看"当前方差大小"，更要看"方差变化方向"
        # 原理：实现 PID 控制的微分项(D)，预判规律演变趋势
        
        last_variance = config.get('last_variance', 0.0)
        if last_variance > 0:
            # 计算方差变化率 (标准化，以上次方差为基准)
            variance_trend = interval_variance - last_variance
            variance_trend_normalized = variance_trend / last_variance
        else:
            variance_trend = 0.0
            variance_trend_normalized = 0.0
        
        # 持久化当前方差，供下次使用
        config['last_variance'] = interval_variance
        config['variance_trend'] = variance_trend
        
        # ==================== 自适应调整衰减率 (融入方差趋势信号)====================
        def calculate_adaptive_lambda(variance, variance_trend_norm):
            """根据方差和方差趋势自适应调整时间衰减率
            
            **控制论优化**: 融入 PID 控制的微分项 (D-term)
            
            传统方法 (仅 P 项)：
                仅看当前方差 → 方差大 = 不规律 → 高衰减率
            
            优化方法 (P + D 项)：
                情况 A: 方差减小 (负趋势)→ 规律正在形成 → 降低衰减率 (信任模型)
                情况 B: 方差增大 (正趋势)→ 规律正在崩塌 → 提高衰减率 (怀疑模型)
            
            Args:
                variance: 当前方差值 (绝对值)
                variance_trend_norm: 标准化的方差变化率 (相对值，-1 到 1)
            
            Returns:
                自适应时间衰减率 λ ∈ [LAMBDA_MIN, LAMBDA_MAX]
            """
            # 基于当前方差的基础衰减率 (P 项)
            normalized_variance = variance / (86400 ** 2)
            
            if normalized_variance > 0:
                lambda_factor = math.log(1 + normalized_variance * 10) / math.log(11)
            else:
                lambda_factor = 0
            
            base_adaptive_lambda = LAMBDA_MIN + (LAMBDA_MAX - LAMBDA_MIN) * lambda_factor
            
            # 基于方差趋势的修正量 (D 项)
            # 修正幅度：基础衰减率的 ±30%
            trend_correction = variance_trend_norm * 0.3 * base_adaptive_lambda
            
            # 合成最终衰减率并限制在合理范围
            adaptive_lambda = base_adaptive_lambda + trend_correction
            adaptive_lambda = max(LAMBDA_MIN, min(LAMBDA_MAX, adaptive_lambda))
            
            return adaptive_lambda
        
        LAMBDA = calculate_adaptive_lambda(interval_variance, variance_trend_normalized)
        
        # ==================== ISO标准月内周数计算 ====================
        def get_week_of_month(dt):
            """使用ISO标准计算月内第几周 (1-6)"""
            month_calendar = calendar.monthcalendar(dt.year, dt.month)
            
            # 找到当前日期在第几周
            for week_num, week in enumerate(month_calendar, 1):
                if dt.day in week:
                    return week_num
            
            return 1  # 默认返回第1周
        
        # ==================== 自动学习维度权重 ====================
        def calculate_dimension_strength(timestamps, dimension):
            """计算单个维度的周期性强度
            
            通过分析历史数据在该维度上的分布集中度来评估周期性
            集中度越高, 说明该维度的周期性越强
            """
            counts = defaultdict(int)
            
            for ts in timestamps:
                dt = datetime.fromtimestamp(ts)
                
                match dimension:
                    case 'day':
                        key = dt.hour  # 按小时分组
                    case 'week':
                        key = dt.weekday()  # 按星期几分组
                    case 'month_week':
                        key = get_week_of_month(dt)  # 按月内第几周分组
                    case 'year_month':
                        key = dt.month  # 按月份分组
                    case _:
                        continue
                
                counts[key] += 1
            
            if not counts:
                return 0.0
            
            # 计算分布的集中度 (使用变异系数的倒数)
            values = list(counts.values())
            mean_val = sum(values) / len(values)
            
            if mean_val == 0:
                return 0.0
            
            variance = sum((x - mean_val) ** 2 for x in values) / len(values)
            std_dev = math.sqrt(variance)
            
            # 标准差越小, 周期性越强
            # 使用 mean/std 作为强度指标
            if std_dev > 0:
                strength = mean_val / std_dev
            else:
                strength = mean_val
            
            return strength
        
        def learn_dimension_weights(timestamps, old_weights):
            """根据历史数据自动学习各维度的最优权重"""
            if len(timestamps) < 20:
                # 数据不足, 使用当前权重
                return old_weights
            
            # 计算各维度的周期性强度
            dimension_scores = {
                'day': calculate_dimension_strength(timestamps, 'day'),
                'week': calculate_dimension_strength(timestamps, 'week'),
                'month_week': calculate_dimension_strength(timestamps, 'month_week'),
                'year_month': calculate_dimension_strength(timestamps, 'year_month')
            }
            
            # 标准化为权重 (总和约为2.0)
            total_score = sum(dimension_scores.values())
            if total_score > 0:
                new_weights = {k: v / total_score * 2.0 for k, v in dimension_scores.items()}
            else:
                new_weights = old_weights
            
            # 与历史权重平滑融合 (避免剧烈变化)
            smoothed_weights = {}
            for key in new_weights:
                smoothed_weights[key] = old_weights[key] * (1 - LEARNING_RATE) + new_weights[key] * LEARNING_RATE
            
            return smoothed_weights
        
        # 学习并更新维度权重
        dimension_weights = learn_dimension_weights(historical_events, dimension_weights_from_config)
        
        # ==================== 计算当前时间的周期性特征 ====================
        # 基础时间信息
        current_second_of_day = current_dt.hour * 3600 + current_dt.minute * 60 + current_dt.second
        current_second_of_week = (current_dt.weekday() * SECONDS_IN_DAY) + current_second_of_day
        current_week_of_month = get_week_of_month(current_dt)
        current_month_of_year = current_dt.month
        
        # 日内周期特征 (24小时循环)
        current_day_sin = math.sin(2 * math.pi * current_second_of_day / SECONDS_IN_DAY)
        current_day_cos = math.cos(2 * math.pi * current_second_of_day / SECONDS_IN_DAY)
        
        # 周内周期特征 (7天循环)
        current_week_sin = math.sin(2 * math.pi * current_second_of_week / SECONDS_IN_WEEK)
        current_week_cos = math.cos(2 * math.pi * current_second_of_week / SECONDS_IN_WEEK)
        
        # 月内周数特征 (最多6周循环)
        current_month_week_sin = math.sin(2 * math.pi * current_week_of_month / 6)
        current_month_week_cos = math.cos(2 * math.pi * current_week_of_month / 6)
        
        # 年内月份特征 (12个月循环)
        current_year_month_sin = math.sin(2 * math.pi * current_month_of_year / 12)
        current_year_month_cos = math.cos(2 * math.pi * current_month_of_year / 12)
        
        # ==================== 计算WGMM热力得分 ====================
        total_score = 0.0
        valid_events = 0
        scores = []  # 记录所有单个得分用于后续标准化
        
        for event_timestamp in historical_events:
            try:
                # 计算事件年龄 (小时)
                age_hours = (current_timestamp - event_timestamp) / 3600.0
                if age_hours < 0:  # 跳过未来时间戳 (理论上已被过滤)
                    continue
                
                # 计算时间衰减权重 (越久远权重越低)
                weight = math.exp(-LAMBDA * age_hours)
                
                # ==================== 计算历史事件的周期性特征 ====================
                event_dt = datetime.fromtimestamp(event_timestamp)
                event_second_of_day = event_dt.hour * 3600 + event_dt.minute * 60 + event_dt.second
                event_second_of_week = (event_dt.weekday() * SECONDS_IN_DAY) + event_second_of_day
                event_week_of_month = get_week_of_month(event_dt)
                event_month_of_year = event_dt.month
                
                # 日内周期特征
                event_day_sin = math.sin(2 * math.pi * event_second_of_day / SECONDS_IN_DAY)
                event_day_cos = math.cos(2 * math.pi * event_second_of_day / SECONDS_IN_DAY)
                
                # 周内周期特征
                event_week_sin = math.sin(2 * math.pi * event_second_of_week / SECONDS_IN_WEEK)
                event_week_cos = math.cos(2 * math.pi * event_second_of_week / SECONDS_IN_WEEK)
                
                # 月内周数特征
                event_month_week_sin = math.sin(2 * math.pi * event_week_of_month / 6)
                event_month_week_cos = math.cos(2 * math.pi * event_week_of_month / 6)
                
                # 年内月份特征
                event_year_month_sin = math.sin(2 * math.pi * event_month_of_year / 12)
                event_year_month_cos = math.cos(2 * math.pi * event_month_of_year / 12)
                
                # ==================== 计算各维度的高斯相似度 ====================
                # 日内周期距离和高斯值
                day_dist_sq = ((current_day_sin - event_day_sin) ** 2 + 
                              (current_day_cos - event_day_cos) ** 2)
                day_gaussian = math.exp(-day_dist_sq / (2 * SIGMA_DAY ** 2))
                
                # 周内周期距离和高斯值
                week_dist_sq = ((current_week_sin - event_week_sin) ** 2 + 
                               (current_week_cos - event_week_cos) ** 2)
                week_gaussian = math.exp(-week_dist_sq / (2 * SIGMA_WEEK ** 2))
                
                # 月内周数距离和高斯值
                month_week_dist_sq = ((current_month_week_sin - event_month_week_sin) ** 2 + 
                                     (current_month_week_cos - event_month_week_cos) ** 2)
                month_week_gaussian = math.exp(-month_week_dist_sq / (2 * SIGMA_MONTH_WEEK ** 2))
                
                # 年内月份距离和高斯值
                year_month_dist_sq = ((current_year_month_sin - event_year_month_sin) ** 2 + 
                                     (current_year_month_cos - event_year_month_cos) ** 2)
                year_month_gaussian = math.exp(-year_month_dist_sq / (2 * SIGMA_YEAR_MONTH ** 2))
                
                # ==================== 使用学习到的权重组合各维度 ====================
                combined_gaussian = (dimension_weights['day'] * day_gaussian + 
                                    dimension_weights['week'] * week_gaussian + 
                                    dimension_weights['month_week'] * month_week_gaussian + 
                                    dimension_weights['year_month'] * year_month_gaussian)
                
                # 计算最终得分：时间衰减权重 × 周期性相似度
                score = weight * combined_gaussian
                total_score += score
                scores.append(score)
                valid_events += 1
                
            except (ValueError, OSError) as e:
                # 跳过异常数据点
                continue
        
        # ==================== 处理无有效事件的情况 ====================
        if valid_events == 0:
            frequency_sec = 7200
            next_check_timestamp = int(time.time()) + frequency_sec
            next_check_time = datetime.fromtimestamp(next_check_timestamp).strftime('%Y年%m月%d日 %H:%M:%S')
            self.log_info(f"WGMM调频 - 无有效历史事件, 使用默认频率: 2小时 下次检查: {next_check_time}")  # 改为INFO
            self.save_next_check_time(next_check_timestamp)
            return
        
        # ==================== 使用Min-Max方法标准化得分 ====================
        if len(scores) > 0:
            min_score = min(scores)
            max_score = max(scores)
            
            # 如果所有得分相同, 使用中间值
            if max_score > min_score:
                normalized_score = (total_score / valid_events - min_score) / (max_score - min_score)
            else:
                normalized_score = 0.5
        else:
            normalized_score = 0.5
        
        # 限制得分范围在[0, 1]之间
        normalized_score = max(0.0, min(1.0, normalized_score))
        
        # ==================== 控制论优化 1: 应用反馈抑制惩罚 ====================
        # 根据连续失败次数，强制降低热力得分
        # 效果：在连续"预测失败"的时段，系统会自动降低检查频率
        if inhibition_penalty > 0:
            normalized_score = normalized_score * (1.0 - inhibition_penalty)
        
        # ==================== 非线性映射：得分转换为轮询间隔 ====================
        # 使用指数曲线使高得分时更敏感
        exponential_score = normalized_score ** MAPPING_CURVE
        
        # 线性插值：score=0时用BASE_INTERVAL, score=1时用MAX_INTERVAL
        polling_interval_sec = BASE_INTERVAL - (BASE_INTERVAL - MAX_INTERVAL) * exponential_score
        
        # 应用边界限制：不能低于MAX_INTERVAL, 不能高于BASE_INTERVAL的2倍
        base_frequency_sec = int(max(MAX_INTERVAL, min(BASE_INTERVAL * 2, polling_interval_sec)))
        
        # ==================== 控制论优化 3: 网络阻抗自适应阻尼 ====================
        # 目标：检测网络拥堵或风控，自动降低请求频率，避免被封禁
        # 原理：监控 yt-dlp 实际耗时，耗时异常时施加"冷却惩罚"
        
        impedance_factor = 1.0
        if self.last_ytdlp_duration > self.normal_ytdlp_duration * 2:
            # 计算阻抗比率：实际耗时 / 正常耗时
            impedance_ratio = self.last_ytdlp_duration / max(self.normal_ytdlp_duration, 1.0)
            # 阻尼系数：耗时越长，冷却越强 (上限 1.5 倍)
            impedance_factor = 1.0 + min(0.5, (impedance_ratio - 2.0) * 0.1)
        
        # 应用阻抗阻尼到最终检查频率
        final_frequency_sec = int(base_frequency_sec * impedance_factor)
        
        # ==================== 保存下次检查时间 ====================
        next_check_timestamp = int(time.time()) + final_frequency_sec
        next_check_time = datetime.fromtimestamp(next_check_timestamp).strftime('%Y年%m月%d日 %H:%M:%S')
        
        self.save_next_check_time(next_check_timestamp)
        
        # 保存更新后的配置
        config['dimension_weights'] = dimension_weights
        config['last_lambda'] = LAMBDA
        config['last_update'] = current_timestamp
        config['next_check_time'] = next_check_timestamp
        save_config(config)
        
        # ==================== 格式化并记录日志 ====================
        # 将轮询间隔转换为天时分秒格式
        polling_days = final_frequency_sec // 86400
        polling_hours = (final_frequency_sec % 86400) // 3600
        polling_minutes = (final_frequency_sec % 3600) // 60
        polling_seconds = final_frequency_sec % 60
        
        # 构建轮询间隔时间格式字符串 (只显示非零的部分)
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

        # 记录WGMM计算结果
        self.log_info(f"WGMM调频 - 轮询间隔: {polling_interval_str}")

    def run_yt_dlp(self, command_args: list[str], timeout: int = 300) -> tuple[bool, str, str]:
        """执行 yt-dlp 命令
        
        安全地执行 yt-dlp 命令, 包含超时控制和错误处理。
        
        **控制论优化**: 捕获实际运行耗时，作为网络环境健康度指标
        
        耗时数据用途：
        - 更新 `last_ytdlp_duration` (最近一次耗时)
        - 更新 `normal_ytdlp_duration` (移动平均基准)
        - 触发网络阻抗阻尼机制 (耗时异常时降低请求频率)
        
        Args:
            command_args: yt-dlp 命令参数列表 (不包含 ``yt-dlp`` 本身)
            timeout: 命令超时时间 (秒), 默认 300 秒
            
        Returns:
            三元组 ``(success, stdout, stderr)``：
            - ``success``: 命令是否执行成功 (返回码为 0)
            - ``stdout``: 标准输出内容
            - ``stderr``: 标准错误内容或错误消息
            
        Example:
            >>> success, stdout, stderr = self.run_yt_dlp([
            ...     '--cookies', 'cookies.txt',
            ...     '--flat-playlist',
            ...     '--print', '%(id)s',
            ...     'https://space.bilibili.com/xxx/video'
            ... ])
            >>> if success:
            ...     video_ids = stdout.split('\\n')
        """
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
            
            # 更新正常耗时基准 (移动平均，仅在成功时更新)
            # 权重：90% 历史 + 10% 当前，平滑波动
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
        """快速预检查功能
        
        获取最新视频的 ID, 检查是否已存在于 Gist 同步的 memory_urls 中。
        这样可以确保每次都以 Gist 数据为基准, 不会因本地缓存问题漏检。
        
        Returns:
            是否发现新内容 (需要进行完整检查)
            
        Note:
            - 如果预检查失败, 返回 ``True`` 触发完整检查以确保不漏检
            - 使用视频 ID 对比 (纯字母数字, 避免文件名特殊字符问题)
            - 直接与 memory_urls 对比, 不依赖本地缓存文件
            
        See Also:
            ``run_monitor()``: 调用此方法进行快速预检
        """
        # 确保 memory_urls 有数据
        if not self.memory_urls:
            self.log_warning("memory_urls 为空, 触发完整检查")
            return True
            
        success, stdout, stderr = self.run_yt_dlp([
            '--cookies', self.cookies_file,
            '--flat-playlist',
            '--print', '%(id)s',
            '--playlist-end', '1',
            f'https://space.bilibili.com/{self.BILIBILI_UID}/video'
        ])
        
        if not success or not stdout:
            self.log_warning("快速检查失败, 触发完整检查")
            return True  # 失败时触发完整检查, 确保不漏检
            
        latest_id = stdout.strip()
        
        # 检查 memory_urls 中是否包含此视频 ID
        # URL 格式如: https://www.bilibili.com/video/BVxxxxxx 或 https://www.bilibili.com/video/BVxxxxxx?p=2
        video_exists = any(latest_id in url for url in self.memory_urls)
        
        if video_exists:
            return False  # 视频已存在, 无需完整检查
        else:
            return True  # 发现新视频, 触发完整检查

    def check_potential_new_parts(self) -> bool:
        """检查现有多分片视频是否有新分片
        
        分析已有的多分片视频, 检查是否有新的分片发布。
        这是一个高效的预检查方法, 避免完整扫描。
        
        Returns:
            是否发现新分片
            
        Note:
            - 只检查多分片视频 (分片数 > 1)
            - 最多向前检查 5 个新分片
            - 失败时返回 ``False``, 依赖后续完整检查
        """
        if not self.memory_urls:
            self.log_info("内存数据为空, 跳过分片预检查")
            return False
            
        has_new_parts = False
        
        try:
            urls = self.memory_urls
                
            # 提取分片视频的基础 URL 和最高分片号
            base_urls = {}
            for url in urls:
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
        """获取单个视频的所有分片链接
        
        使用 yt-dlp 获取指定视频的所有分片 (如果是多分片视频)。
        
        Args:
            video_url: 视频 URL
            
        Returns:
            包含所有分片 URL 的列表。如果获取失败返回空列表。
            
        Example:
            >>> parts = self.get_video_parts('https://www.bilibili.com/video/BV1xxx')
            >>> for part_url in parts:
            ...     print(part_url)
        """
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
        """并行获取所有视频的分片信息
        
        使用线程池并行处理多个视频, 提高获取分片信息的效率。
        
        Args:
            video_urls: 视频 URL 列表
            
        Returns:
            包含所有视频分片 URL 的列表
            
        Note:
            - 使用 5 个工作线程并行处理
            - 单个视频失败不影响其他视频的处理
            - 严重错误会触发 CRITICAL 级别通知
        """
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
        """清理临时文件和资源
        
        删除临时目录和文件, 释放系统资源。
        
        Note:
            清理失败不发送通知, 避免在程序退出时产生不必要的告警。
        """
        try:
            if os.path.exists(self.tmp_outputs_dir):
                shutil.rmtree(self.tmp_outputs_dir)
        except Exception as e:
            self.log_critical_error(f"清理临时文件失败: {e}", "cleanup 方法", send_notification=False)

    def cleanup_and_wait(self) -> None:
        """清理资源并等待下次检查
        
        执行以下操作：
        
        1. 清理临时文件
        2. 读取下次检查时间配置
        3. 计算等待时间
        4. 进入休眠状态直到下次检查
        
        Note:
            - 如果等待时间为负数或无效, 使用默认 400 分钟间隔
            - 休眠期间可被信号中断
        """
        self.cleanup()
        
        try:
            next_check_timestamp = self.get_next_check_time()
            
            if next_check_timestamp > 0:
                current_timestamp = int(time.time())
                wait_seconds = next_check_timestamp - current_timestamp
                
                # 如果计算出的等待时间为负数或过小, 使用默认间隔
                if wait_seconds <= 0:
                    frequency_sec = 24000  # 400 分钟 = 24000 秒
                    next_check_timestamp = current_timestamp + frequency_sec
                    wait_seconds = frequency_sec
                    self.log_warning("等待时间出现负数, 使用默认 400 分钟间隔")

                    # 更新 next_check_time
                    self.save_next_check_time(next_check_timestamp)
                
                next_dt = datetime.fromtimestamp(next_check_timestamp)
                weekday_name = ['周一', '周二', '周三', '周四', '周五', '周六', '周日'][next_dt.weekday()]
                next_check_time = f"{next_dt.strftime('%Y年%m月%d日')} {weekday_name} {next_dt.strftime('%H:%M:%S')}"
                self.log_info(f"下次检查: {next_check_time}")
                time.sleep(wait_seconds)
            else:
                # 配置文件不存在或读取失败
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
        
        执行三层检测策略：
        
        1. **分片预检查**: 检查现有多分片视频的新分片
        2. **快速检查**: 检查最新视频 ID 变化
        3. **完整检查**: 获取所有视频链接并对比
        
        这种分层策略可以显著提高检查效率, 减少不必要的网络请求。
        
        Flow:
            1. 从 GitHub Gist 同步 URL 数据到内存
            2. 执行分片预检查和快速预检查
            3. 如果发现可能的新内容, 执行完整检查
            4. 对比新旧 URL 列表, 发现新视频时发送通知
            5. 调整检查频率并等待下次检查
            
        Note:
            - 捕获所有异常, 确保程序持续运行
            - 严重错误会触发 CRITICAL 级别通知
        """
        try:
            self.log_message("检查开始                  <--")
            # 1. 每次醒来, 先从 GitHub 同步数据到内存
            # sync_urls_from_gist() 会自动将 Gist 中的 URL 加入 known_urls
            sync_success = self.sync_urls_from_gist()

            # 如果获取失败且内存是空的, 无法进行比对, 直接等待下次
            if not sync_success and not self.memory_urls:
                self.log_warning("无法获取基准数据 (Gist 失败且内存 urls 为空), 跳过本次检查")
                self.cleanup_and_wait()
                return

            # 第一层：分片预检查
            found_new_parts = self.check_potential_new_parts()
            # 第二层：快速预检查
            found_new_videos = self.quick_precheck()

            # 压缩日志：一行显示两层检查结果
            self.log_info(f"预检查完成 - 预测检查: {'发现新内容' if found_new_parts else '无新内容'} "
                          f"快速检查: {'发现新内容' if found_new_videos else '无新内容'}")

            # 如果两层检查都没发现新内容, 跳过完整检查
            if not (found_new_parts or found_new_videos):
                # 未发现新内容, 传递 False 给频率调整
                self.adjust_check_frequency(found_new_content=False)
                self.cleanup_and_wait()
                return

            # 第三层：完整检查 - 获取所有视频链接
            success, stdout, stderr = self.run_yt_dlp([
                '--cookies', self.cookies_file,
                '--flat-playlist',
                '--print', '%(webpage_url)s',
                f'https://space.bilibili.com/{self.BILIBILI_UID}/video'
            ])

            if not success or not stdout:
                self.log_critical_error("无法获取视频列表", "完整检查阶段", send_notification=True)
                # 完整检查失败, 不算作"未发现新内容", 因为我们不确定
                self.adjust_check_frequency(found_new_content=False)
                self.cleanup_and_wait()
                return

            video_urls = [line.strip() for line in stdout.split('\n') if line.strip()]

            if not video_urls:
                self.log_critical_error("未获取到任何内容", "完整检查阶段", send_notification=True)
                self.adjust_check_frequency(found_new_content=False)
                self.cleanup_and_wait()
                return

            # 并行获取所有分片链接
            all_parts = self.get_all_videos_parallel(video_urls)

            if not all_parts:
                self.log_warning("处理分片时出错, 错误已处理")
                all_parts = video_urls  # 使用原始视频 URLs 作为后备

            # 4. 内存比对 - 使用两层检测逻辑
            existing_urls_set = set(self.memory_urls)  # Gist 中的 URL（已备份）
            current_urls_set = set(all_parts)  # 当前 B站上的所有视频
            
            # ==================== 两层 URL 集合管理 ====================
            # gist_missing_urls: Gist 中没有的视频（需要每次通知）
            # truly_new_urls: 本地也不知道的视频（真正的新视频，影响惩罚机制）
            
            gist_missing_urls = current_urls_set - existing_urls_set  # Gist 未同步的
            truly_new_urls = gist_missing_urls - self.known_urls  # 真正的新视频

            if gist_missing_urls:
                # 使用星号表示视频数量：*** ** 表示 Gist 未备份3个，新视频2个
                gist_stars = '*' * len(gist_missing_urls)
                new_stars = '*' * len(truly_new_urls)
                self.log_info(f"{gist_stars} {new_stars}")
                
                # 发送通知 - 通知所有 Gist 中没有的视频
                link_count = len(gist_missing_urls)
                
                # 只为真正的新视频保存时间戳（避免重复保存）
                if truly_new_urls:
                    self.save_real_upload_timestamps(truly_new_urls)
                
                # 更新本地已知 URL 集合
                self.known_urls.update(gist_missing_urls)

                if self.notify_new_videos(link_count, has_new_parts=found_new_parts):
                    # 不记录成功通知日志, 避免日志过多
                    pass
                else:
                    self.log_warning("通知发送失败")
                
                # 只有真正的新视频才算"发现新内容"，影响惩罚机制
                if truly_new_urls:
                    self.adjust_check_frequency(found_new_content=True)
                else:
                    # Gist 缺失但本地已知，说明是重复检查，不算新内容
                    self.adjust_check_frequency(found_new_content=False)
            else:
                self.log_info("完整检查未发现新内容")
                if found_new_parts:
                    # 分片检查发现了新内容
                    self.adjust_check_frequency(found_new_content=True)
                    self.log_info("检查完成 - 仅发现新分片")
                else:
                    # 快速检查误报, 完整检查未确认
                    self.adjust_check_frequency(found_new_content=False)
                    self.log_info("检查完成 - 快速检查发现新内容但完整检查未确认")

            # 不写日志 - 视频检查完成
            self.cleanup_and_wait()

        except KeyboardInterrupt:
            self.log_info("收到中断信号, 正在退出...")
            self.cleanup()
            sys.exit(0)
        except Exception as e:
            self.log_critical_error(f"监控脚本运行时出现意外错误: {e}", "run_monitor 方法", send_notification=True)
            self.cleanup_and_wait()

def main() -> None:
    """程序入口点
    
    创建 VideoMonitor 实例并启动主监控循环。
    
    程序会持续运行直到被用户中断 (Ctrl+C) 或发生致命错误。
    
    Exit Codes:
        0: 正常退出 (用户中断)
        1: 异常退出 (致命错误)
    """
    monitor = VideoMonitor()
    
    # ==================== 标记为手动运行 ====================
    # 程序启动时设置 is_manual_run = True
    # 这样首次运行不会因为没有发现新内容而触发惩罚
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
        monitor.log_critical_error(f"主循环出现严重错误: {e}", "main 函数", send_notification=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
