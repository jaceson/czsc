#!/bin/bash
# 监控 .cache 目录文件数量，超过 TIMEOUT 无新文件则重启进程
# 当 .cache 文件数等于股票总数时，等待进程自然结束并退出
# 数据缓存完成后继续执行 CZSCStragegy_OversoldRebound.py
# 用法: ./run_with_watchdog.sh [参数...]

TIMEOUT=60
SCRIPT="czsc_daily_stock.py"
VENV_DIR="./venv"
CACHE_DIR="./data/.cache"
STOCK_LIST_FILE="./data/sh_sz_stock.json"
LOG_FILE="./data/czsc_watchdog.log"
WORKDIR="$(cd "$(dirname "$0")" && pwd)"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

count_cache_files() {
    if [ -d "$CACHE_DIR" ]; then
        ls "$CACHE_DIR"/*.csv 2>/dev/null | wc -l
    else
        echo 0
    fi
}


load_stock_count() {
    python3 -c "import json; print(len(json.load(open('$STOCK_LIST_FILE'))))"
}

cd "$WORKDIR" || exit 1

> "$LOG_FILE"

# 传参 1 时优先清理缓存数据，确保重新拉取最新行情
clear_cache() {
    if [ -d "$CACHE_DIR" ]; then
        local n
        n=$(ls "$CACHE_DIR"/*.csv 2>/dev/null | wc -l)
        # 避免误删．DS_Store 等非缓存文件
        rm -f "$CACHE_DIR"/*.csv
        log "已清理 $CACHE_DIR 缓存文件 $n 个"
    fi
}

# 消费第一个参数：传入 1 则清理缓存，其余参数继续传给主脚本
if [ "${1:-}" = "1" ]; then
    clear_cache
    shift
fi

total_stocks=$(load_stock_count)
log "目标股票总数: $total_stocks"

restart_count=0
PYTHON="python3"
if [ -f "$VENV_DIR/bin/activate" ]; then
    . "$VENV_DIR/bin/activate"
fi

while true; do
    restart_count=$((restart_count + 1))
    log "启动 $SCRIPT (第 $restart_count 次)"


    $PYTHON "$SCRIPT" "$@" &
    PID=$!

    last_file_count=0
    last_change_time=$(date +%s)

    while kill -0 $PID 2>/dev/null; do
        sleep 2
        current_count=$(count_cache_files)
        if [ "$current_count" -gt "$last_file_count" ]; then
            log ".cache 文件数: $current_count/$total_stocks"
            last_file_count=$current_count
            last_change_time=$(date +%s)
        fi

        if [ "$current_count" -ge "$total_stocks" ]; then
            log ".cache 文件数 $current_count 已达目标 $total_stocks，等待进程自然结束"
            break
        fi

        now=$(date +%s)
        elapsed=$((now - last_change_time))
        if (( elapsed > TIMEOUT )); then
            log "已 ${TIMEOUT}s 无新文件生成 (${current_count}/${total_stocks})，终止 PID=$PID"
            kill -9 $PID 2>/dev/null
            wait $PID 2>/dev/null
            break
        fi
    done

    wait $PID 2>/dev/null
    exit_code=$?
    log "$SCRIPT 已退出 (exit code: $exit_code)"

    if [ "$(count_cache_files)" -ge "$total_stocks" ]; then
        log "全部股票数据已缓存完成，退出"
        break
    fi

    log "缓存未完成 ($(count_cache_files)/${total_stocks})，重启中..."
    sleep 3
done

if [ "$(count_cache_files)" -lt "$total_stocks" ]; then
    log "缓存未完成 ($(count_cache_files)/${total_stocks})，跳过策略执行"
    exit 1
fi

# 数据缓存完成后执行超跌反弹策略
STRATEGY="CZSCStragegy_OversoldRebound.py"
log "开始执行 $STRATEGY"
$PYTHON "$STRATEGY"
STRATEGY_EXIT=$?
log "$STRATEGY 执行完成 (exit code: $STRATEGY_EXIT)"
exit $STRATEGY_EXIT
