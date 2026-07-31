import os
import signal
import subprocess
import time
import zipfile
import shutil
from pathlib import Path
import config.paths as paths

def free_port(port: int = 28888) -> None:
    """If the port is occupied, find the process holding it, its parent, and kill them to release the port."""
    my_pid = os.getpid()
    my_ppid = os.getppid()
    try:
        # Use lsof to find PIDs holding the port
        result = subprocess.run(
            ["lsof", "-t", f"-i:{port}"],
            capture_output=True,
            text=True,
            check=False
        )
        pids = [int(p) for p in result.stdout.strip().split() if p.isdigit()]
        
        target_pids = set()
        for pid in pids:
            if pid != my_pid and pid != my_ppid:
                target_pids.add(pid)
                # Find its parent PID to also kill the Uvicorn reloader parent
                try:
                    with open(f"/proc/{pid}/stat", "r") as f:
                        parts = f.read().rsplit(")", 1)[1].split()
                        ppid = int(parts[1])
                        if ppid > 1 and ppid != my_pid and ppid != my_ppid:
                            target_pids.add(ppid)
                except Exception:
                    pass
                    
        if target_pids:
            print(f"[China-Tax Startup] Port {port} is occupied. Cleaning up processes: {target_pids}...")
            for pid in target_pids:
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            # Give the OS a moment to release the port
            time.sleep(0.5)
    except Exception as e:
        print(f"[China-Tax Startup] Failed to check/free port {port}: {e}")

def create_zip_archive(files: list[Path], output_zip_path: Path) -> None:
    """將檔案打包成一個 ZIP 壓縮檔。"""
    with zipfile.ZipFile(output_zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for file in files:
            if file.exists() and file.is_file():
                zipf.write(file, arcname=file.name)

def clear_data_directories(preserve_files: list[Path] = None, clear_archives: bool = False) -> None:
    """清理输入输出目录及临时文件夹，防止运行前后文件混淆。支持指定保留某些活动文件。"""
    preserve_paths = {Path(p).resolve() for p in (preserve_files or [])}
    
    def _clean_subdir(dir_path: Path) -> None:
        for item in dir_path.iterdir():
            if item.name == ".gitkeep":
                continue
            if item.is_file():
                if item.resolve() in preserve_paths:
                    continue
                try:
                    item.unlink()
                except Exception as e:
                    print(f"删除文件 {item} 失败: {e}")
            elif item.is_dir():
                _clean_subdir(item)
        try:
            if dir_path.name != "archives" and not any(dir_path.iterdir()):
                dir_path.rmdir()
        except Exception:
            pass

    data_root = paths.BASE_DIR / "data"
    if data_root.exists():
        for item in data_root.iterdir():
            if item.is_dir():
                try:
                    if item.name == "archives" and not clear_archives:
                        continue
                    _clean_subdir(item)
                    # 清理後如果目錄為空，則將其刪除
                    if not any(item.iterdir()):
                        item.rmdir()
                except Exception as e:
                    print(f"清理 {item} 失败: {e}")

    # 確保當前活動的輸入輸出目錄存在（若已經設定了金融機構）
    if paths.INPUT_DIR and "unselected" not in str(paths.INPUT_DIR):
        paths.INPUT_DIR.mkdir(parents=True, exist_ok=True)
    if paths.OUTPUT_DIR and "unselected" not in str(paths.OUTPUT_DIR):
        paths.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
