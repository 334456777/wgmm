#!/bin/bash

# 视频监控启动脚本

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MONITOR_SCRIPT="$SCRIPT_DIR/monitor.py"
PID_FILE="$SCRIPT_DIR/monitor.pid"

# 自动检测Python解释器路径
PYTHON_CMD="python3"

# 静默检测和设置虚拟环境
init_python_cmd() {
    # 1. 优先检查项目本地的虚拟环境
    if [ -f "$SCRIPT_DIR/.venv/bin/python" ]; then
        PYTHON_CMD="$SCRIPT_DIR/.venv/bin/python"
    # 2. 其次检查是否通过 pyenv 激活了某个环境
    elif command -v pyenv &> /dev/null; then
        # 获取 pyenv 当前指定的 Python 路径
        PYTHON_CMD=$(pyenv which python 2>/dev/null || echo "python3")
    else
        # 3. 最后回退到系统默认的 python3
        PYTHON_CMD="python3"
    fi
}
# 检查Python脚本是否存在
if [ ! -f "$MONITOR_SCRIPT" ]; then
    echo "错误: 找不到 $MONITOR_SCRIPT"
    exit 1
fi

# 检查和设置虚拟环境
check_and_setup_venv() {
    local VENV_PATH="$SCRIPT_DIR/.venv"
    
    # 如果虚拟环境已经存在，更新PYTHON_CMD
    if [ -f "$VENV_PATH/bin/python" ]; then
        PYTHON_CMD="$VENV_PATH/bin/python"
        echo "使用虚拟环境: $PYTHON_CMD"
        return 0
    elif [ -f "$VENV_PATH/bin/python3" ]; then
        PYTHON_CMD="$VENV_PATH/bin/python3"
        echo "使用虚拟环境: $PYTHON_CMD"
        return 0
    fi
    
    # 虚拟环境不存在，询问是否创建
    echo ""
    echo "⚠ 未发现虚拟环境 ($VENV_PATH)"
    echo "建议使用虚拟环境来隔离Python依赖"
    echo ""
    
    # 检查是否在交互式终端中
    if [ -t 0 ]; then
        echo "是否创建虚拟环境? (y/n) [推荐: y]"
        read -r response
        
        if [[ "$response" =~ ^[Yy]$ ]]; then
            create_virtual_environment
        else
            echo "继续使用系统Python: $PYTHON_CMD"
            echo "注意: 建议后续使用虚拟环境"
        fi
    else
        # 非交互式环境，自动创建虚拟环境
        echo "非交互式环境，自动创建虚拟环境..."
        create_virtual_environment
    fi
}

# 创建虚拟环境
# 创建虚拟环境
create_virtual_environment() {
    local VENV_PATH="$SCRIPT_DIR/.venv"
    local BASE_PYTHON=""

    echo "正在准备创建虚拟环境..."

    # 优先寻找 pyenv 安装的 Python 版本
    if command -v pyenv &> /dev/null; then
        # 尝试获取 pyenv 本地设置的版本 (例如 3.14.2)
        BASE_PYTHON=$(pyenv which python)
        echo "发现 pyenv，将基于 $(python --version) 创建环境"
    else
        BASE_PYTHON="python3"
        echo "未发现 pyenv，使用系统 Python3"
    fi

    # 检查基础 Python 是否可用
    if ! $BASE_PYTHON --version &> /dev/null; then
        echo "错误: 找不到可用的 Python 解释器"
        exit 1
    fi

    # 创建虚拟环境
    $BASE_PYTHON -m venv "$VENV_PATH" || {
        echo "错误: 创建虚拟环境失败"
        echo "提示: 请检查是否安装了 python3-venv (sudo apt install python3-venv)"
        exit 1
    }

    # 更新 PYTHON_CMD 为新创建的环境路径
    PYTHON_CMD="$VENV_PATH/bin/python"
    
    echo "✓ 虚拟环境创建成功: $VENV_PATH"
    echo "✓ 解释器路径: $PYTHON_CMD"

    # 后续安装依赖的逻辑保持不变...
    echo "正在升级 pip 并安装依赖..."
    "$PYTHON_CMD" -m pip install --upgrade pip --quiet
    if [ -f "$SCRIPT_DIR/requirements.txt" ]; then
        "$PYTHON_CMD" -m pip install -r "$SCRIPT_DIR/requirements.txt"
    fi
}

start() {
    # 先检查PID文件和运行中的进程（在修改PYTHON_CMD之前）
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if ps -p "$PID" > /dev/null 2>&1; then
            echo "监控程序已在运行 (PID: $PID)"
            return 1
        else
            echo "删除无效的PID文件"
            rm -f "$PID_FILE"
        fi
    fi
    
    # 检查是否有监控程序在运行但没有PID文件（使用通用模式匹配）
    RUNNING_PID=$(pgrep -f "python.*$MONITOR_SCRIPT" | head -1)
    if [ -n "$RUNNING_PID" ]; then
        echo "发现监控程序已在运行但没有PID文件 (PID: $RUNNING_PID)"
        echo "正在补充PID文件..."
        echo "$RUNNING_PID" > "$PID_FILE"
        echo "监控程序状态已恢复 (PID: $RUNNING_PID)"
        echo "运行日志: $SCRIPT_DIR/urls.log"
        return 0
    fi
    
    # 检查和创建虚拟环境
    check_and_setup_venv
    
    echo "启动视频监控程序..."
    cd "$SCRIPT_DIR"
    nohup "$PYTHON_CMD" "$MONITOR_SCRIPT" > /dev/null 2>&1 &
    PID=$!
    echo $PID > "$PID_FILE"
    echo "监控程序已启动 (PID: $PID)"
    echo "运行日志: $SCRIPT_DIR/urls.log"
}

start_foreground() {
    # 先检查是否已有监控程序在运行（在修改PYTHON_CMD之前）
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if ps -p "$PID" > /dev/null 2>&1; then
            echo "监控程序已在运行 (PID: $PID)"
            return 1
        else
            echo "删除无效的PID文件"
            rm -f "$PID_FILE"
        fi
    fi

    # 检查是否有监控程序在运行但没有PID文件（使用通用模式匹配）
    RUNNING_PID=$(pgrep -f "python.*$MONITOR_SCRIPT" | head -1)
    if [ -n "$RUNNING_PID" ]; then
        echo "发现监控程序已在运行 (PID: $RUNNING_PID)"
        echo "请先停止现有程序或使用 status 命令查看状态"
        return 1
    fi

    # 检查和创建虚拟环境
    check_and_setup_venv

    echo "在前台启动视频监控程序..."
    cd "$SCRIPT_DIR"
    exec "$PYTHON_CMD" "$MONITOR_SCRIPT"
}

dev() {
    # 开发模式：运行单次检查后退出
    echo "====== 开发模式 ======"
    echo "运行单次检查后退出，不等待下次检查时间..."
    echo ""

    # 检查和创建虚拟环境
    check_and_setup_venv

    cd "$SCRIPT_DIR"

    # 检查必要的环境变量
    if [ ! -f ".env" ]; then
        echo "⚠ 警告: 未找到 .env 文件"
        echo "请确保已设置以下环境变量:"
        echo "  - GIST_ID: GitHub Gist ID"
        echo "  - GITHUB_TOKEN: GitHub Token"
        echo "  - BILIBILI_UID: Bilibili用户UID"
        echo "  - BARK_DEVICE_KEY: Bark推送设备密钥 (可选)"
        echo ""
        echo "是否继续运行? (y/n)"
        read -r response
        if [[ ! "$response" =~ ^[Yy]$ ]]; then
            echo "已取消运行"
            return 1
        fi
    fi

    # 运行开发模式
    echo "启动开发模式检查..."
    echo "=========================================="

    # 设置环境变量（从.env文件加载）
    if [ -f ".env" ]; then
        set -a
        source ".env"
        set +a
    fi

    # 运行监控程序（开发模式）
    "$PYTHON_CMD" "$MONITOR_SCRIPT" --dev

    local exit_code=$?
    echo ""
    echo "=========================================="

    if [ $exit_code -eq 0 ]; then
        echo "✅ 开发模式运行完成"
        echo "提示: 配置文件未被修改，可安全地继续开发或调试"
    else
        echo "❌ 开发模式运行失败 (退出码: $exit_code)"
        echo "请检查错误信息或运行: $0 test 进行配置检查"
        return $exit_code
    fi
}

# 通用的参数传递函数，支持向Python脚本传递参数
run_with_args() {
    local args=("$@")

    if [ ${#args[@]} -eq 0 ]; then
        echo "用法: $0 run [python参数...]"
        echo ""
        echo "示例:"
        echo "  $0 run --dev              # 运行开发模式"
        echo "  $0 run --help             # 查看Python脚本帮助"
        exit 1
    fi

    # 检查和创建虚拟环境
    check_and_setup_venv

    cd "$SCRIPT_DIR"

    echo "运行监控程序 (参数: ${args[*]})..."
    "$PYTHON_CMD" "$MONITOR_SCRIPT" "${args[@]}"
}

stop() {
    if [ ! -f "$PID_FILE" ]; then
        # 没有PID文件，检查是否有监控程序在运行（使用通用模式匹配）
        RUNNING_PID=$(pgrep -f "python.*$MONITOR_SCRIPT" | head -1)
        if [ -n "$RUNNING_PID" ]; then
            echo "发现监控程序在运行但没有PID文件 (PID: $RUNNING_PID)"
            echo "停止监控程序 (PID: $RUNNING_PID)..."
            kill "$RUNNING_PID"
            
            # 等待进程结束
            for i in {1..10}; do
                if ! ps -p "$RUNNING_PID" > /dev/null 2>&1; then
                    break
                fi
                sleep 1
            done
            
            # 强制杀死进程
            if ps -p "$RUNNING_PID" > /dev/null 2>&1; then
                echo "强制停止进程..."
                kill -9 "$RUNNING_PID"
            fi
            
            echo "监控程序已停止"
            return 0
        else
            echo "监控程序未运行"
            return 1
        fi
    fi
    
    PID=$(cat "$PID_FILE")
    if ps -p "$PID" > /dev/null 2>&1; then
        echo "停止监控程序 (PID: $PID)..."
        kill "$PID"
        
        # 等待进程结束
        for i in {1..10}; do
            if ! ps -p "$PID" > /dev/null 2>&1; then
                break
            fi
            sleep 1
        done
        
        # 强制杀死进程
        if ps -p "$PID" > /dev/null 2>&1; then
            echo "强制停止进程..."
            kill -9 "$PID"
        fi
        
        rm -f "$PID_FILE"
        echo "监控程序已停止"
    else
        echo "进程不存在，删除PID文件"
        rm -f "$PID_FILE"
        
        # 再次检查是否有其他监控程序在运行（使用通用模式匹配）
        RUNNING_PID=$(pgrep -f "python.*$MONITOR_SCRIPT" | head -1)
        if [ -n "$RUNNING_PID" ]; then
            echo "发现其他监控程序在运行 (PID: $RUNNING_PID)，正在停止..."
            kill "$RUNNING_PID"
            
            # 等待进程结束
            for i in {1..10}; do
                if ! ps -p "$RUNNING_PID" > /dev/null 2>&1; then
                    break
                fi
                sleep 1
            done
            
            # 强制杀死进程
            if ps -p "$RUNNING_PID" > /dev/null 2>&1; then
                echo "强制停止进程..."
                kill -9 "$RUNNING_PID"
            fi
            
            echo "监控程序已停止"
        fi
    fi
}

status() {
    echo "====== 监控程序状态 ======"
    
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if ps -p "$PID" > /dev/null 2>&1; then
            echo "✓ 监控程序正在运行 (PID: $PID)"
            
            # 显示进程信息
            echo ""
            echo "进程信息:"
            ps -p "$PID" -o pid,ppid,cmd,etime,pcpu,pmem --no-headers | while read line; do
                echo "  $line"
            done
            
            # 显示运行时间
            START_TIME=$(ps -p "$PID" -o lstart --no-headers 2>/dev/null)
            if [ -n "$START_TIME" ]; then
                echo "  启动时间: $START_TIME"
            fi
            
        else
            echo "✗ 监控程序未运行 (PID文件存在但进程不存在)"
            rm -f "$PID_FILE"
            
            # 检查是否有其他监控程序在运行（使用通用模式匹配）
            RUNNING_PID=$(pgrep -f "python.*$MONITOR_SCRIPT" | head -1)
            if [ -n "$RUNNING_PID" ]; then
                echo "⚠ 发现监控程序在运行但没有PID文件 (PID: $RUNNING_PID)"
                echo "正在自动修复PID文件..."
                echo "$RUNNING_PID" > "$PID_FILE"
                echo "✓ PID文件已修复"
                PID="$RUNNING_PID"
            else
                echo ""
                echo "建议运行: $0 start (启动监控程序)"
                return 1
            fi
        fi
    else
        # 没有PID文件，检查是否有监控程序在运行（使用通用模式匹配）
        RUNNING_PID=$(pgrep -f "python.*$MONITOR_SCRIPT" | head -1)
        if [ -n "$RUNNING_PID" ]; then
            echo "⚠ 监控程序正在运行但没有PID文件 (PID: $RUNNING_PID)"
            echo "正在自动修复PID文件..."
            echo "$RUNNING_PID" > "$PID_FILE"
            echo "✓ PID文件已修复"
            PID="$RUNNING_PID"
            
            # 显示进程信息
            echo ""
            echo "进程信息:"
            ps -p "$PID" -o pid,ppid,cmd,etime,pcpu,pmem --no-headers | while read line; do
                echo "  $line"
            done
        else
            echo "✗ 监控程序未运行"
            echo ""
            echo "建议运行: $0 start (启动监控程序)"
            return 1
        fi
    fi
    
    echo ""
    echo "====== 配置信息 ======"
    
    # 显示检查频率
    if [ -f "$SCRIPT_DIR/check_frequency.conf" ]; then
        next_check_timestamp=$(cat "$SCRIPT_DIR/check_frequency.conf" 2>/dev/null)
        if [[ "$next_check_timestamp" =~ ^[0-9]+$ ]] && [ "$next_check_timestamp" -gt 0 ]; then
            current_timestamp=$(date +%s)
            next_check_time=$(date -d "@$next_check_timestamp" "+%Y年%m月%d日 %H:%M:%S")
            time_diff=$((next_check_timestamp - current_timestamp))
            if [ "$time_diff" -gt 0 ]; then
                hours=$((time_diff / 3600))
                minutes=$(((time_diff % 3600) / 60))
                if [ "$hours" -gt 0 ]; then
                    remaining="${hours}小时${minutes}分钟后"
                else
                    remaining="${minutes}分钟后"
                fi
                echo "下次检查时间: $next_check_time ($remaining)"
            else
                echo "下次检查时间: $next_check_time (已过期，应立即检查)"
            fi
        else
            echo "下次检查时间: 未配置"
        fi
    else
        echo "下次检查时间: 未配置"
    fi
    
    # 显示Python环境
    echo "Python解释器: $PYTHON_CMD"
    
    # 显示文件状态
    echo ""
    echo "====== 文件状态 ======"
    
    # PID文件
    if [ -f "$PID_FILE" ]; then
        echo "✓ PID文件: $PID_FILE"
    else
        echo "✗ PID文件: 不存在"
    fi
    
    # 日志文件
    if [ -f "$SCRIPT_DIR/urls.log" ]; then
        LOG_SIZE=$(ls -lh "$SCRIPT_DIR/urls.log" | awk '{print $5}')
        echo "✓ 运行日志: $SCRIPT_DIR/urls.log (大小: $LOG_SIZE)"
    else
        echo "✗ 运行日志: 不存在"
    fi
    
    # Cookies文件
    if [ -f "$SCRIPT_DIR/cookies.txt" ]; then
        if [ -s "$SCRIPT_DIR/cookies.txt" ]; then
            echo "✓ Cookies文件: 存在且非空"
        else
            echo "⚠ Cookies文件: 存在但为空"
        fi
    else
        echo "✗ Cookies文件: 不存在"
    fi
    
    # 显示最近的活动
    echo ""
    echo "====== 最近活动 ======"
    
    # 最后更新时间
    if [ -f "$SCRIPT_DIR/last_update.timestamp" ]; then
        LAST_UPDATE=$(cat "$SCRIPT_DIR/last_update.timestamp" 2>/dev/null)
        if [ -n "$LAST_UPDATE" ] && [[ "$LAST_UPDATE" =~ ^[0-9]+$ ]]; then
            current_timestamp=$(date +%s)
            last_check_time=$(date -d "@$LAST_UPDATE" "+%Y年%m月%d日 %H:%M:%S")
            time_diff=$((current_timestamp - LAST_UPDATE))
            if [ "$time_diff" -lt 60 ]; then
                ago="${time_diff}秒前"
            elif [ "$time_diff" -lt 3600 ]; then
                minutes=$((time_diff / 60))
                ago="${minutes}分钟前"
            elif [ "$time_diff" -lt 86400 ]; then
                hours=$((time_diff / 3600))
                minutes=$(((time_diff % 3600) / 60))
                if [ "$minutes" -gt 0 ]; then
                    ago="${hours}小时${minutes}分钟前"
                else
                    ago="${hours}小时前"
                fi
            else
                days=$((time_diff / 86400))
                ago="${days}天前"
            fi
            echo "最后检查时间: $last_check_time ($ago)"
        fi
    fi
    
    # 最近的日志
    if [ -f "$SCRIPT_DIR/urls.log" ]; then
        echo "最近的运行日志:"
        tail -3 "$SCRIPT_DIR/urls.log" | sed 's/^/  /'
        echo ""
        echo "查看更多日志: $0 logs [行数]"
        echo "实时查看日志: $0 follow"
    else
        echo "无运行日志"
    fi
    
    return 0
}

logs() {
    local lines=${1:-50}
    if [ -f "$SCRIPT_DIR/urls.log" ]; then
        echo "显示最近 $lines 行运行日志:"
        tail -n "$lines" "$SCRIPT_DIR/urls.log"
    else
        echo "日志文件不存在"
    fi
}

follow_logs() {
    if [ -f "$SCRIPT_DIR/urls.log" ]; then
        echo "实时查看运行日志 (Ctrl+C 退出):"
        tail -f "$SCRIPT_DIR/urls.log"
    else
        echo "日志文件不存在"
    fi
}

test_config() {
    # 初始化Python命令路径
    init_python_cmd
    
    echo "====== 配置和依赖检查 ======"
    
    cd "$SCRIPT_DIR"
    
    local all_ok=true
    
    echo ""
    echo "1. 文件检查:"
    
    # 检查主脚本
    if [ -f "$MONITOR_SCRIPT" ]; then
        echo "  ✓ 监控脚本: $MONITOR_SCRIPT"
    else
        echo "  ✗ 监控脚本: $MONITOR_SCRIPT (不存在)"
        all_ok=false
    fi
    
    # 检查cookies文件
    if [ -f "cookies.txt" ]; then
        if [ -s "cookies.txt" ]; then
            COOKIE_COUNT=$(wc -l < "cookies.txt" 2>/dev/null || echo "0")
            echo "  ✓ cookies.txt: 存在且非空 ($COOKIE_COUNT 行)"
        else
            echo "  ⚠ cookies.txt: 存在但为空"
            echo "    提示: 从浏览器导出cookies到此文件"
            echo "    Chrome: 开发者工具 -> Application -> Cookies -> 复制"
            echo "    Firefox: 开发者工具 -> 存储 -> Cookies -> 复制"
        fi
    else
        echo "  ✗ cookies.txt: 不存在"
        echo "    提示: 需要从浏览器导出cookies文件"
        echo "    1. 打开浏览器开发者工具"
        echo "    2. 访问目标网站"
        echo "    3. 复制cookies到 cookies.txt 文件"
        all_ok=false
    fi
    
    # 检查配置文件
    if [ -f "check_frequency.conf" ]; then
        frequency=$(cat "check_frequency.conf" 2>/dev/null)
        if [[ "$frequency" =~ ^[0-9]+$ ]] && [ "$frequency" -gt 0 ]; then
            echo "  ✓ 检查频率配置: $frequency 分钟"
        else
            echo "  ⚠ 检查频率配置: 格式不正确 ($frequency)"
            echo "    提示: 应该是大于0的数字"
        fi
    else
        echo "  ⚠ 检查频率配置: 不存在 (将使用默认值)"
        echo "    提示: 创建 check_frequency.conf 文件并输入检查间隔(分钟)"
    fi
    
    echo ""
    echo "2. Python环境检查:"
    
    # 检查Python解释器
    if command -v "$PYTHON_CMD" &> /dev/null; then
        PYTHON_VERSION=$("$PYTHON_CMD" --version 2>&1)
        echo "  ✓ Python解释器: $PYTHON_CMD ($PYTHON_VERSION)"
        
        # 检查是否使用虚拟环境
# 检查Python解释器
    if command -v "$PYTHON_CMD" &> /dev/null; then
        PYTHON_VERSION=$("$PYTHON_CMD" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")' 2>/dev/null)
        echo "  ✓ Python解释器: $PYTHON_CMD (版本: $PYTHON_VERSION)"
        
        # 1. 检查是否为本地 .venv
        if [[ "$PYTHON_CMD" == *".venv"* ]]; then
            echo "  ✓ 运行环境: 本地虚拟环境 (.venv)"
        # 2. 检查是否为 pyenv 环境
        elif command -v pyenv &> /dev/null && pyenv prefix &> /dev/null; then
            echo "  ✓ 运行环境: pyenv 托管环境 ($(pyenv version-name))"
        else
            echo "  ⚠ 运行环境: 系统全局 Python"
            echo "    提示: 建议使用 pyenv 或虚拟环境隔离依赖"
        fi

        # 3. 针对 3.14.2 的版本专项检查
        if [ "$PYTHON_VERSION" != "3.14.2" ]; then
            echo "  ⚠ 版本提醒: 当前运行版本为 $PYTHON_VERSION，而非推荐的 3.14.2"
            echo "    修复: 运行 'pyenv local 3.14.2' 并重建虚拟环境"
        fi
    else
        echo "  ✗ Python解释器: $PYTHON_CMD (不可用)"
        if command -v pyenv &> /dev/null; then
            echo "    提示: 发现 pyenv，请尝试安装版本: pyenv install 3.14.2"
        else
            echo "    提示: 安装 Python: sudo apt install python3"
        fi
        all_ok=false
    fi  
    echo "3. 依赖检查:"
    
    # 检查Python依赖
    "$PYTHON_CMD" -c "
import sys
import subprocess

# 检查requests
try:
    import requests
    print('  ✓ requests 模块: 已安装 (版本: ' + requests.__version__ + ')')
except ImportError:
    print('  ✗ requests 模块: 未安装')
    print('    提示: pip install requests')
    sys.exit(1)

# 检查其他可能的依赖
optional_modules = ['urllib3', 'json', 'time', 'os', 're']
for module in optional_modules:
    try:
        __import__(module)
        print(f'  ✓ {module} 模块: 可用')
    except ImportError:
        print(f'  ⚠ {module} 模块: 不可用')
" 2>/dev/null || {
        echo "  ✗ Python依赖检查失败"
        echo "    提示: 安装依赖: pip install -r requirements.txt"
        all_ok=false
    }
    
    # 检查yt-dlp
    if command -v yt-dlp &> /dev/null; then
        YT_DLP_VERSION=$(yt-dlp --version 2>/dev/null)
        echo "  ✓ yt-dlp: 可用 (版本: $YT_DLP_VERSION)"
        
        # 测试yt-dlp基本功能
        if yt-dlp --help > /dev/null 2>&1; then
            echo "  ✓ yt-dlp: 功能正常"
        else
            echo "  ⚠ yt-dlp: 可能存在问题"
        fi
    else
        echo "  ✗ yt-dlp: 未安装"
        echo "    提示: 安装yt-dlp:"
        echo "    方法1: pip install yt-dlp"
        echo "    方法2: sudo apt install yt-dlp"
        echo "    方法3: 从GitHub下载最新版本"
        all_ok=false
    fi
    
    echo ""
    echo "4. 系统检查:"
    
    # 检查磁盘空间
    DISK_USAGE=$(df "$SCRIPT_DIR" | tail -1 | awk '{print $5}' | sed 's/%//')
    if [ "$DISK_USAGE" -lt 90 ]; then
        echo "  ✓ 磁盘空间: 充足 (已用 $DISK_USAGE%)"
    else
        echo "  ⚠ 磁盘空间: 不足 (已用 $DISK_USAGE%)"
        echo "    提示: 清理日志文件或增加磁盘空间"
    fi
    
    # 检查网络连接
    if ping -c 1 8.8.8.8 > /dev/null 2>&1; then
        echo "  ✓ 网络连接: 正常"
    else
        echo "  ⚠ 网络连接: 可能存在问题"
        echo "    提示: 检查网络设置"
    fi
    
    # 检查权限
    if [ -w "$SCRIPT_DIR" ]; then
        echo "  ✓ 写入权限: 正常"
    else
        echo "  ✗ 写入权限: 不足"
        echo "    提示: 检查目录权限: chmod 755 $SCRIPT_DIR"
        all_ok=false
    fi
    
    echo ""
    echo "5. 运行建议:"
    
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if ps -p "$PID" > /dev/null 2>&1; then
            echo "  ✓ 监控程序: 正在运行"
            echo "    查看状态: $0 status"
            echo "    查看日志: $0 logs"
        else
            echo "  ⚠ 监控程序: PID文件存在但进程未运行"
            echo "    建议操作: $0 start"
        fi
    else
        # 使用通用模式匹配检查监控进程
        RUNNING_PID=$(pgrep -f "python.*$MONITOR_SCRIPT" | head -1)
        if [ -n "$RUNNING_PID" ]; then
            echo "  ⚠ 监控程序: 运行中但无PID文件"
            echo "    建议操作: $0 start (恢复管理)"
        else
            echo "  ⚠ 监控程序: 未运行"
            echo "    建议操作: $0 start"
        fi
    fi
    
    echo ""
    if [ "$all_ok" = true ]; then
        echo "====== 检查完成: ✓ 所有检查通过 ======"
        echo "系统已准备就绪，可以启动监控程序"
        return 0
    else
        echo "====== 检查完成: ⚠ 发现问题 ======"
        echo "请根据上述提示解决问题后再启动监控程序"
        return 1
    fi
}

case "$1" in
    start)
        start
        ;;
    start-foreground|foreground)
        start_foreground
        ;;
    dev)
        dev
        ;;
    run)
        shift
        run_with_args "$@"
        ;;
    stop)
        stop
        ;;
    restart)
        stop
        sleep 2
        start
        ;;
    status)
        status
        ;;
    logs)
        logs "$2"
        ;;
    follow|tail)
        follow_logs
        ;;
    test)
        test_config
        ;;
    *)
        echo "用法: $0 {start|start-foreground|dev|run|stop|restart|status|logs [行数]|follow|test}"
        echo ""
        echo "命令说明:"
        echo "  start            - 后台启动监控程序"
        echo "  start-foreground - 前台启动监控程序（用于systemd）"
        echo "  dev              - 开发模式：运行单次检查后退出"
        echo "  run [args]       - 运行监控程序并传递参数"
        echo "  stop             - 停止监控程序"
        echo "  restart          - 重启监控程序"
        echo "  status           - 查看运行状态"
        echo "  logs [n]         - 查看最近n行日志 (默认50行)"
        echo "  follow           - 实时查看日志"
        echo "  test             - 检查配置和依赖"
        echo ""
        echo "示例:"
        echo "  $0 start                    # 后台启动监控"
        echo "  $0 dev                      # 开发模式运行"
        echo "  $0 run --dev                # 传递参数运行"
        echo "  $0 logs 100                 # 查看最近100行日志"
        echo "  $0 follow                   # 实时查看日志"
        exit 1
        ;;
esac
