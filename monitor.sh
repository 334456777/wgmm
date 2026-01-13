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
create_virtual_environment() {
    local VENV_PATH="$SCRIPT_DIR/.venv"
    local BASE_PYTHON=""

    echo "正在准备创建虚拟环境..."

    # 优先寻找 pyenv 安装的 Python 版本
    if command -v pyenv &> /dev/null; then
        # 尝试获取 pyenv 本地设置的版本
        BASE_PYTHON=$(pyenv which python)
        echo "发现 pyenv，将基于 $($BASE_PYTHON --version) 创建环境"
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
        echo "提示: 请检查是否安装了 python3-venv"
        exit 1
    }

    # 更新 PYTHON_CMD 为新创建的环境路径
    PYTHON_CMD="$VENV_PATH/bin/python"
    
    echo "✓ 虚拟环境创建成功: $VENV_PATH"
    
    # 升级pip并安装依赖
    echo "正在升级 pip 并安装依赖..."
    "$PYTHON_CMD" -m pip install --upgrade pip --quiet
    if [ -f "$SCRIPT_DIR/requirements.txt" ]; then
        "$PYTHON_CMD" -m pip install -r "$SCRIPT_DIR/requirements.txt"
    fi
}

start() {
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if ps -p "$PID" > /dev/null 2>&1; then
            echo "监控程序已在运行 (PID: $PID)"
            return 1
        else
            rm -f "$PID_FILE"
        fi
    fi
    
    RUNNING_PID=$(pgrep -f "python.*$MONITOR_SCRIPT" | head -1)
    if [ -n "$RUNNING_PID" ]; then
        echo "$RUNNING_PID" > "$PID_FILE"
        echo "监控程序状态已恢复 (PID: $RUNNING_PID)"
        return 0
    fi
    
    check_and_setup_venv
    
    echo "启动视频监控程序..."
    cd "$SCRIPT_DIR"
    nohup "$PYTHON_CMD" "$MONITOR_SCRIPT" > /dev/null 2>&1 &
    PID=$!
    echo $PID > "$PID_FILE"
    echo "监控程序已启动 (PID: $PID)"
}

start_foreground() {
    check_and_setup_venv
    echo "在前台启动视频监控程序..."
    cd "$SCRIPT_DIR"
    exec "$PYTHON_CMD" "$MONITOR_SCRIPT"
}

stop() {
    RUNNING_PID=$(pgrep -f "python.*$MONITOR_SCRIPT" | head -1)
    if [ -n "$RUNNING_PID" ]; then
        echo "停止监控程序 (PID: $RUNNING_PID)..."
        kill "$RUNNING_PID"
        rm -f "$PID_FILE"
        echo "监控程序已停止"
    else
        echo "监控程序未运行"
    fi
}

status() {
    echo "====== 监控程序状态 ======"
    init_python_cmd
    
    RUNNING_PID=$(pgrep -f "python.*$MONITOR_SCRIPT" | head -1)
    if [ -n "$RUNNING_PID" ]; then
        echo "✓ 监控程序正在运行 (PID: $RUNNING_PID)"
        echo "Python解释器: $PYTHON_CMD"
    else
        echo "✗ 监控程序未运行"
    fi
}

test_config() {
    init_python_cmd
    echo "====== 配置和依赖检查 ======"
    cd "$SCRIPT_DIR"
    local all_ok=true
    
    echo ""
    echo "1. 文件检查:"
    [ -f "$MONITOR_SCRIPT" ] && echo "  ✓ 监控脚本: 存在" || { echo "  ✗ 监控脚本: 不存在"; all_ok=false; }
    
    echo ""
    echo "2. Python环境检查:"
    if command -v "$PYTHON_CMD" &> /dev/null; then
        # 获取精确版本号
        PYTHON_VERSION=$("$PYTHON_CMD" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")' 2>/dev/null)
        echo "  ✓ Python解释器: $PYTHON_CMD (版本: $PYTHON_VERSION)"
        
        if [[ "$PYTHON_CMD" == *".venv"* ]]; then
            echo "  ✓ 运行环境: 本地虚拟环境 (.venv)"
        elif command -v pyenv &> /dev/null && pyenv prefix &> /dev/null; then
            echo "  ✓ 运行环境: pyenv 托管环境 ($(pyenv version-name))"
        else
            echo "  ⚠ 运行环境: 系统全局 Python"
        fi

        if [ "$PYTHON_VERSION" != "3.14.2" ]; then
            echo "  ⚠ 版本提醒: 当前为 $PYTHON_VERSION，建议使用 3.14.2"
        fi
    else
        echo "  ✗ Python解释器: 不可用"
        all_ok=false
    fi

    echo ""
    echo "3. 依赖检查:"
    "$PYTHON_CMD" -c "import requests; print('  ✓ requests 模块: 已安装')" 2>/dev/null || { echo "  ✗ requests 未安装"; all_ok=false; }
    command -v yt-dlp &> /dev/null && echo "  ✓ yt-dlp: 已安装" || { echo "  ✗ yt-dlp: 未安装"; all_ok=false; }

    echo ""
    if [ "$all_ok" = true ]; then
        echo "====== 检查完成: ✓ 所有检查通过 ======"
    else
        echo "====== 检查完成: ⚠ 发现问题 ======"
    fi
}

# 简化的日志查看功能
logs() { tail -n "${1:-50}" "$SCRIPT_DIR/urls.log"; }

case "$1" in
    start) start ;;
    stop) stop ;;
    status) status ;;
    test) test_config ;;
    logs) logs "$2" ;;
    *) echo "用法: $0 {start|stop|status|test|logs}" ;;
esac