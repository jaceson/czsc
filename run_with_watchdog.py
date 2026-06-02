#!/usr/bin/env python3
import os
import sys
import time
import json
import shutil
import subprocess
import threading
import logging
import signal

WORKDIR = os.path.dirname(os.path.abspath(__file__))
TIMEOUT = 60
SCRIPT = "czsc_daily_stock.py"
VENV_DIR = os.path.join(WORKDIR, "venv")
CACHE_DIR = os.path.join(WORKDIR, "data", ".cache")
STOCK_LIST_FILE = os.path.join(WORKDIR, "data", "sh_sz_stock.json")
LOG_FILE = os.path.join(WORKDIR, "data", "czsc_watchdog.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(message)s",
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler()],
)
log = logging.getLogger(__name__)


def find_python():
    for c in [
        os.path.join(VENV_DIR, "bin", "python3"),
        os.path.join(VENV_DIR, "bin", "python"),
        "python3",
    ]:
        if c == "python3" or os.path.isfile(c):
            return c
    return "python3"


def count_cache_files():
    if not os.path.isdir(CACHE_DIR):
        return 0
    return len([f for f in os.listdir(CACHE_DIR) if f.endswith('.csv')])

def load_stock_count():
    with open(STOCK_LIST_FILE) as f:
        return len(json.load(f))


def main():
    os.chdir(WORKDIR)
    python = find_python()
    total_stocks = load_stock_count()
    log.info(f"目标股票总数: {total_stocks}")

    restart_count = 0
    args = sys.argv[1:]

    signal.signal(signal.SIGINT, lambda *_: sys.exit(0))
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))

    while True:
        restart_count += 1
        log.info(f"启动 {SCRIPT} (第 {restart_count} 次)")

        proc = subprocess.Popen(
            [python, "-u", SCRIPT] + args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

        last_file_count = 0
        last_change_time = time.time()

        def reader():
            for line in proc.stdout:
                print(line, end="", flush=True)

        t = threading.Thread(target=reader, daemon=True)
        t.start()

        while t.is_alive():
            current_count = count_cache_files()
            if current_count > last_file_count:
                log.info(f".cache 文件数: {current_count}/{total_stocks}")
                last_file_count = current_count
                last_change_time = time.time()

            if current_count >= total_stocks:
                log.info(f".cache 文件数 {current_count} 已达目标 {total_stocks}，等待进程自然结束")
                break

            elapsed = time.time() - last_change_time
            if elapsed > TIMEOUT:
                log.warning(f"已 {TIMEOUT}s 无新文件生成 ({current_count}/{total_stocks})，终止 PID={proc.pid}")
                proc.kill()
                break

            time.sleep(2)

        if proc.stdout:
            proc.stdout.close()
        t.join(timeout=5)
        proc.wait()

        exit_code = proc.returncode
        log.info(f"{SCRIPT} 已退出 (exit code: {exit_code})")

        if count_cache_files() >= total_stocks:
            log.info("全部股票数据已缓存完成，退出")
            break

        log.info(f"缓存未完成 ({count_cache_files()}/{total_stocks})，重启中...")
        time.sleep(3)


if __name__ == "__main__":
    main()
