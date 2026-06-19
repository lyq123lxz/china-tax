import os
import signal
import subprocess
import time
import zipfile

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

# Free port 28888 before starting NiceGUI
free_port(28888)

import asyncio
from pathlib import Path
from typing import Any
from nicegui import app, events, ui
from utils.csv_excel import BatchConverter
from utils.pdf_md import PDFBatchParser, ParserProgress
from utils.pdf_check import PDFDeduplicator
import utils.md_closing as md_closing

# ---------------------------------------------------------
# 全局引用与状态管理，用于更新 UI 状态
# ---------------------------------------------------------
BASE_DIR = Path(__file__).parent.resolve()
# 預設初始化為未選擇狀態的虛擬路徑，但不在硬碟上建立它
INPUT_DIR = BASE_DIR / "data" / "unselected" / "input"
OUTPUT_DIR = BASE_DIR / "data" / "unselected" / "output"
INPUT_PDF_DIR = INPUT_DIR / "pdf"
INPUT_CSV_DIR = INPUT_DIR / "csv"
INPUT_EXCEL_DIR = INPUT_DIR / "excel"
INPUT_MD_DIR = INPUT_DIR / "md"
OUTPUT_PDF_DIR = OUTPUT_DIR / "pdf"
OUTPUT_PDF_DECRYPT_DIR = OUTPUT_DIR / "pdf-Decrypt"
OUTPUT_CSV_DIR = OUTPUT_DIR / "csv"
OUTPUT_EXCEL_DIR = OUTPUT_DIR / "excel"
OUTPUT_MD_DIR = OUTPUT_DIR / "md"

def update_active_paths(bank_name: str) -> None:
    """根据银行/券商名称动态更新全局的输入与输出目录变量，并确保这些目录存在"""
    global INPUT_DIR, OUTPUT_DIR
    global INPUT_PDF_DIR, INPUT_CSV_DIR, INPUT_EXCEL_DIR, INPUT_MD_DIR
    global OUTPUT_PDF_DIR, OUTPUT_PDF_DECRYPT_DIR, OUTPUT_CSV_DIR, OUTPUT_EXCEL_DIR, OUTPUT_MD_DIR
    
    clean_name = "".join(c for c in bank_name if c.isalnum() or c in ("-", "_", " ")).strip()
    if not clean_name:
        raise ValueError("金融機構名稱不得為空")
        
    INPUT_DIR = BASE_DIR / "data" / clean_name / "input"
    OUTPUT_DIR = BASE_DIR / "data" / clean_name / "output"
        
    INPUT_PDF_DIR = INPUT_DIR / "pdf"
    INPUT_CSV_DIR = INPUT_DIR / "csv"
    INPUT_EXCEL_DIR = INPUT_DIR / "excel"
    INPUT_MD_DIR = INPUT_DIR / "md"
    OUTPUT_PDF_DIR = OUTPUT_DIR / "pdf"
    OUTPUT_PDF_DECRYPT_DIR = OUTPUT_DIR / "pdf-Decrypt"
    OUTPUT_CSV_DIR = OUTPUT_DIR / "csv"
    OUTPUT_EXCEL_DIR = OUTPUT_DIR / "excel"
    OUTPUT_MD_DIR = OUTPUT_DIR / "md"

# 注册静态文件目录，以支持持久、非 single_use 的文件下载路由
app.add_static_files("/data", str(BASE_DIR / "data"))

# 注册统一的安全下载路由，强制设置 Content-Disposition 以确保各种格式（包括 md）的文件均正常下载，避免浏览器打开新标签页渲染或被拦截
from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

@app.exception_handler(RuntimeError)
async def runtime_error_handler(request: Request, exc: RuntimeError) -> JSONResponse:
    if "has been deleted" in str(exc):
        print(f"[NiceGUI Stale Client Request] Ignored RuntimeError for deleted client on route: {request.url.path}")
        return JSONResponse(
            status_code=400,
            content={"detail": "The client this element belongs to has been deleted. Please refresh the page."}
        )
    raise exc

@app.get('/download/{file_path:path}')
def download_file(file_path: str) -> FileResponse:
    resolved_path = (BASE_DIR / file_path).resolve()
    # 限制下载只能在 BASE_DIR（项目根目录）下，防止路径穿越安全漏洞
    if not resolved_path.is_relative_to(BASE_DIR):
        raise HTTPException(status_code=403, detail="Access denied")
    if not resolved_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(resolved_path, filename=resolved_path.name)

# --- 其它輔助工具函數 ---

def generate_audit_report(results: list[dict[str, Any]], output_dir: Path) -> Path:
    """生成 PDF 查重去密編制審計報告到指定目錄。"""
    report_path = output_dir / "report.md"
    
    total = len(results)
    unique = sum(1 for r in results if r["status"] == "Unique")
    duplicates = sum(1 for r in results if r["status"] == "Duplicate")
    errors = sum(1 for r in results if r["status"] == "Error")
    saved_kb = sum(r["file_size_kb"] for r in results if r["status"] == "Duplicate")
    
    decrypted_success = sum(1 for r in results if r["encryption_status"] == "Decrypted (解密成功)")
    decrypted_failed = sum(1 for r in results if r["encryption_status"] == "Failed (解密失敗)")
    no_password_needed = sum(1 for r in results if r["encryption_status"] == "No Password (無密碼)")
    
    lines = [
        "# PDF 查重與去密編制審計報告",
        f"\n**產生時間**: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "\n## 1. 執行摘要",
        f"- **總處理檔案數**: {total} 個",
        f"- **解密成功件數**: {decrypted_success} 個",
        f"- **解密失敗件數**: {decrypted_failed} 個 (密碼錯誤或檔案損壞)",
        f"- **無需解密件數**: {no_password_needed} 個 (未加密檔)",
        f"- **唯一保留件數**: {unique} 個 (包含去密成功件)",
        f"- **重複跳過件數**: {duplicates} 個",
        f"- **錯誤/忽略件數**: {errors} 個",
        f"- **節省磁碟空間**: {saved_kb:.2f} KB",
        "\n## 2. 審計明細清單",
        "| 檔案名稱 | 大小 (KB) | 加密狀態 | SHA-256 | 查重狀態 | 處理動作 | 母本引用 |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |"
    ]
    for r in results:
        sha = r["sha256"][:12] + "..." if r["sha256"] else "None"
        dup_of = r["duplicate_of"] if r["duplicate_of"] else "None"
        lines.append(
            f"| {r['file_name']} | {r['file_size_kb']} | {r['encryption_status']} | `{sha}` | {r['status']} | {r['action']} | {dup_of} |"
        )
    
    output_dir.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return report_path

def generate_pdf_conversion_report(all_alerts: list[dict[str, Any]], output_dir: Path) -> Path:
    """生成 PDF 轉 Markdown 解析與對賬勾稽審計報告。"""
    report_path = output_dir / "report.md"
    
    total_alerts = len(all_alerts)
    errors = sum(1 for a in all_alerts if a.get("status") == "error")
    warnings = sum(1 for a in all_alerts if a.get("status") == "warning")
    reviews = sum(1 for a in all_alerts if a.get("status") == "NEED_VISUAL_REVIEW")
    successes = sum(1 for a in all_alerts if a.get("status") == "success")
    
    # 篩選出需要人工審核的警告/異常
    manual_reviews = [a for a in all_alerts if a.get("status") in ("warning", "NEED_VISUAL_REVIEW", "error")]
    
    lines = [
        "# PDF 轉 Markdown 解析與對賬勾稽審計報告",
        f"\n**產生時間**: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "\n## 1. 執行摘要",
        f"- **總審計警示數**: {total_alerts} 處",
        f"- **勾稽成功件數**: {successes} 處",
        f"- **人工視覺覆核 (NEED_VISUAL_REVIEW)**: {reviews} 處",
        f"- **對賬警告件數**: {warnings} 處",
        f"- **解析錯誤件數**: {errors} 處",
        "\n## 2. 需要人工審核的勾稽與警示清單"
    ]
    
    if manual_reviews:
        lines.extend([
            "| 檔案名稱 | 頁碼 | 警示類型 | 警示狀態 | 警示訊息 |",
            "| :--- | :--- | :--- | :--- | :--- |"
        ])
        for a in manual_reviews:
            lines.append(
                f"| {a.get('file', 'Unknown')} | {a.get('page', 0)} | {a.get('type', 'None')} | {a.get('status', 'info')} | {a.get('message', '').replace('|', 'I')} |"
            )
    else:
        lines.append("\n🟢 **恭喜，未發現需要人工審核的勾稽異常或警告項目。**")
        
    lines.extend([
        "\n## 3. 全量審計明细清單",
        "| 檔案名稱 | 頁碼 | 警示類型 | 警示狀態 | 警示訊息 |",
        "| :--- | :--- | :--- | :--- | :--- |"
    ])
    for a in all_alerts:
        lines.append(
            f"| {a.get('file', 'Unknown')} | {a.get('page', 0)} | {a.get('type', 'None')} | {a.get('status', 'info')} | {a.get('message', '').replace('|', 'I')} |"
        )
        
    output_dir.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return report_path

def generate_csv_excel_report(all_logs: list[dict[str, Any]], output_dir: Path) -> Path:
    """生成 CSV/Excel 互转审计与转换报告。"""
    report_path = output_dir / "report.md"
    
    total = len(all_logs)
    successes = sum(1 for a in all_logs if a.get("status") == "success")
    errors = sum(1 for a in all_logs if a.get("status") == "failed")
    
    lines = [
        "# CSV 与 Excel 转换对账审计报告",
        f"\n**产生时间**: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "\n## 1. 运行摘要",
        f"- **总处理文件数**: {total} 个",
        f"- **转换成功数**: {successes} 个",
        f"- **转换失败数**: {errors} 个",
        "\n## 2. 转换明细清单",
        "| 序号 | 原始文件名 | 转换状态 | 提示信息 |",
        "| :--- | :--- | :--- | :--- |"
    ]
    for idx, a in enumerate(all_logs, start=1):
        lines.append(
            f"| {idx} | {a.get('file', 'Unknown')} | {a.get('status', 'info')} | {a.get('message', '').replace('|', 'I')} |"
        )
        
    output_dir.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return report_path

def create_zip_archive(files: list[Path], output_zip_path: Path) -> None:
    """將保存 Jun 唯一件 PDF 檔案打包成一個 ZIP 壓縮檔。"""
    with zipfile.ZipFile(output_zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for file in files:
            if file.exists() and file.is_file():
                zipf.write(file, arcname=file.name)

def clear_data_directories(preserve_files: list[Path] = None, clear_archives: bool = False) -> None:
    """清理输入输出目录及临时文件夹，防止运行前后文件混淆。支持指定保留某些活动文件。"""
    import shutil
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

    data_root = BASE_DIR / "data"
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
    if INPUT_DIR and "unselected" not in str(INPUT_DIR):
        INPUT_DIR.mkdir(parents=True, exist_ok=True)
    if OUTPUT_DIR and "unselected" not in str(OUTPUT_DIR):
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


import config.db_config as db_config
import config.tax_rates as tax_rates
import core.calculator as tax_calc
import core.validator as tax_val

# Initialize database tables on startup
db_config.init_db()

# 全局审计日志缓存
system_logs_list: list[str] = []

def log_action(action: str) -> None:
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    entry = f"[{timestamp}] {action}"
    system_logs_list.append(entry)
    print(entry)

# ---------------------------------------------------------
# NiceGUI UI 布局设计 (采用 Tailwind CSS 实现高端视觉效果)
# ---------------------------------------------------------

@ui.page("/")
def main_page() -> None:
    # --- 局部变量与引用隔离 ---
    last_csv_upload_time = 0.0
    last_pdf_dedup_upload_time = 0.0
    last_pdf_upload_time = 0.0

    auto_clear_switch: ui.switch = None
    bank_name_input: ui.input = None
    csv_excel_dialog: ui.dialog = None
    file_select: ui.select = None
    client_file_select: ui.select = None
    dialog_progress: ui.linear_progress = None
    dialog_status: ui.label = None
    local_dir_input: ui.input = None
    source_type: ui.toggle = None
    csv_download_container: ui.row = None

    pdf_md_dialog: ui.dialog = None
    pdf_file_select: ui.select = None
    client_pdf_select: ui.select = None
    pdf_progress: ui.linear_progress = None
    pdf_status: ui.label = None
    pdf_local_dir_input: ui.input = None
    pdf_source_type: ui.toggle = None
    pdf_log_board: ui.card = None
    pdf_log_container: ui.column = None
    pdf_download_container: ui.row = None

    pdf_dedup_dialog: ui.dialog = None
    pdf_dedup_file_select: ui.select = None
    client_pdf_dedup_select: ui.select = None
    pdf_dedup_progress: ui.linear_progress = None
    pdf_dedup_status: ui.label = None
    pdf_dedup_local_dir_input: ui.input = None
    pdf_dedup_out_dir_input: ui.input = None
    pdf_dedup_source_type: ui.toggle = None
    pdf_dedup_passwords_input: ui.input = None
    pdf_dedup_table: ui.table = None
    pdf_dedup_results_container: ui.column = None
    pdf_dedup_download_container: ui.row = None

    # --- 新增模块的对话框隔离变量 ---
    db_dialog: ui.dialog = None
    calc_dialog: ui.dialog = None
    val_dialog: ui.dialog = None
    exp_dialog: ui.dialog = None
    archive_dialog: ui.dialog = None
    config_view_dialog: ui.dialog = None
    system_logs_dialog: ui.dialog = None
    md_closing_dialog: ui.dialog = None
    md_closing_progress: ui.linear_progress = None
    md_closing_status: ui.label = None
    md_closing_download_container: ui.row = None
    md_closing_start_date: ui.input = None
    md_closing_end_date: ui.input = None
    md_closing_uploaded_files: list[tuple[str, bytes]] = []


    # =========================================================
    # 模块 1: CSV/Excel 互转回调函数
    # =========================================================

    def handle_csv_excel(e: events.ClickEventArguments) -> None:
        refresh_file_list()
        csv_excel_dialog.open()

    def refresh_file_list() -> None:
        if file_select:
            path_str = local_dir_input.value if local_dir_input and local_dir_input.value else str(INPUT_CSV_DIR)
            input_dir = Path(path_str)
            try:
                if input_dir.exists() and input_dir.is_dir():
                    files = [f.name for f in input_dir.iterdir() if f.is_file() and f.suffix.lower() == ".csv"]
                    file_select.options = ["[全部文件]"] + files
                else:
                    file_select.options = ["[全部文件]"]
            except Exception:
                file_select.options = ["[全部文件]"]
            file_select.update()

    async def on_file_upload(e: events.UploadEventArguments) -> None:
        try:
            import time
            nonlocal last_csv_upload_time
            input_dir = INPUT_CSV_DIR / "client_temp"
            input_dir.mkdir(parents=True, exist_ok=True)
            
            # 若為新上傳階段（與上次上傳間隔 > 2 秒），則清空原來的上傳文件及記錄
            now = time.time()
            if now - last_csv_upload_time > 2.0:
                # 1. 刪除 client_temp 底下的舊檔案
                for f in input_dir.iterdir():
                    if f.is_file() and f.name != ".gitkeep":
                        try:
                            f.unlink()
                        except Exception:
                            pass
                # 2. 清空下拉選單
                if client_file_select:
                    client_file_select.options = ["[全部已上传文件]"]
                    client_file_select.value = "[全部已上传文件]"
                    client_file_select.update()
                # 3. 清空下載容器與進度條
                if csv_download_container:
                    csv_download_container.clear()
                    csv_download_container.visible = False
                if dialog_progress:
                    dialog_progress.set_value(0.0)
                    dialog_progress.visible = False
                if dialog_status:
                    dialog_status.set_text("")
                    dialog_status.visible = False
            last_csv_upload_time = now

            file_path = input_dir / e.file.name
            data = await e.file.read()
            file_path.write_bytes(data)
            ui.notify(f"文件 {e.file.name} 上传成功！已暂存至后端。", type="positive", position="top")
            
            files = [f.name for f in input_dir.iterdir() if f.is_file() and f.suffix.lower() == ".csv"]
            client_file_select.options = ["[全部已上传文件]"] + files
            client_file_select.value = "[全部已上传文件]"
            client_file_select.update()
        except Exception as err:
            ui.notify(f"文件保存失败: {str(err)}", type="negative", position="top")

    async def run_select_conversion() -> None:
        if not file_select or not client_file_select or not dialog_progress or not dialog_status:
            return
            
        mode = source_type.value
        
        # 收集当前需要保留的文件以防在清理时被误删
        preserve_files = []
        if mode == "server":
            selected = file_select.value
            path_str = local_dir_input.value if local_dir_input and local_dir_input.value else str(INPUT_CSV_DIR)
            input_dir = Path(path_str)
            if selected == "[全部文件]":
                try:
                    preserve_files = [input_dir / f.name for f in input_dir.iterdir() if f.is_file() and f.suffix.lower() == ".csv"]
                except Exception:
                    pass
            elif selected:
                preserve_files = [input_dir / selected]
        else:
            selected = client_file_select.value
            input_dir = INPUT_CSV_DIR / "client_temp"
            if selected == "[全部已上传文件]":
                try:
                    preserve_files = [input_dir / f.name for f in input_dir.iterdir() if f.is_file() and f.suffix.lower() == ".csv"]
                except Exception:
                    pass
            elif selected:
                preserve_files = [input_dir / selected]

        if auto_clear_switch and auto_clear_switch.value:
            clear_data_directories(preserve_files=preserve_files, clear_archives=False)
            log_action("模块 1 执行前已自动清空历史临时文件。")

        dialog_progress.set_value(0.0)
        dialog_progress.visible = True
        dialog_status.visible = True
        dialog_status.set_text("正在启动转换...")
        
        csv_download_container.clear()
        csv_download_container.visible = False
        
        def on_progress(current: int, total: int, file_name: str, success: bool, message: str) -> None:
            if dialog_progress and dialog_status:
                if total > 0:
                    dialog_progress.set_value(current / total)
                    dialog_status.set_text(f"进度 ({current}/{total}): {file_name}")
                else:
                    dialog_status.set_text(message)
            ui.notify(message, type="positive" if success else "negative", position="top")
            if file_name:
                conversion_logs.append({
                    "file": file_name,
                    "status": "success" if success else "failed",
                    "message": message
                })

        output_files: list[Path] = []
        conversion_logs = []
        try:
            if mode == "server":
                out_zip_dir = OUTPUT_EXCEL_DIR
            else:
                out_zip_dir = OUTPUT_EXCEL_DIR / "client_temp"
            out_zip_dir.mkdir(parents=True, exist_ok=True)

            if mode == "server":
                selected = file_select.value
                path_str = local_dir_input.value if local_dir_input and local_dir_input.value else str(INPUT_CSV_DIR)
                input_dir = Path(path_str)
                
                converter = BatchConverter(input_dir=input_dir, output_dir=OUTPUT_EXCEL_DIR)
                if selected == "[全部文件]":
                    converted_paths = await converter.convert_all(mode="csv_to_excel", progress_callback=on_progress)
                    for out_path in converted_paths:
                        if out_path.exists():
                            output_files.append(out_path)
                else:
                    file_path = input_dir / selected
                    if file_path.exists():
                        try:
                            out_path = await converter.convert_file(file_path, mode="csv_to_excel")
                            on_progress(1, 1, selected, True, f"本机转换成功: {selected}")
                            if out_path.exists():
                                output_files.append(out_path)
                        except Exception as e:
                            on_progress(1, 1, selected, False, f"本机转换失败: {str(e)}")
                            raise e
                    else:
                        raise FileNotFoundError(f"文件不存在: {selected}")
            else:
                selected = client_file_select.value
                input_dir = INPUT_CSV_DIR / "client_temp"
                
                converter = BatchConverter(input_dir=input_dir, output_dir=OUTPUT_EXCEL_DIR)
                if selected == "[全部已上传文件]":
                    files = [f for f in input_dir.iterdir() if f.is_file() and f.suffix.lower() == ".csv"]
                    total_files = len(files)
                    if total_files == 0:
                        on_progress(0, 0, "", True, "未找到任何已上传的文件。")
                        return
                    for idx, file_path in enumerate(files, start=1):
                        try:
                            out_path = await converter.convert_file(file_path, mode="csv_to_excel")
                            on_progress(idx, total_files, file_path.name, True, f"转换成功: {file_path.name}")
                            if out_path.exists():
                                output_files.append(out_path)
                        except Exception as e:
                            on_progress(idx, total_files, file_path.name, False, f"转换失败: {str(e)}")
                else:
                    file_path = input_dir / selected
                    if file_path.exists():
                        try:
                            out_path = await converter.convert_file(file_path, mode="csv_to_excel")
                            on_progress(1, 1, selected, True, f"转换成功: {selected}")
                            if out_path.exists():
                                output_files.append(out_path)
                        except Exception as e:
                            on_progress(1, 1, selected, False, f"转换失败: {str(e)}")
                            raise e
                    else:
                        raise FileNotFoundError(f"文件不存在: {selected}")
            
            # 生成 report.md 并提供下载
            if conversion_logs:
                report_file = generate_csv_excel_report(conversion_logs, out_zip_dir)
                try:
                    rel_report = report_file.relative_to(BASE_DIR)
                    report_url = f"/download/{rel_report.as_posix()}"
                    with csv_download_container:
                        ui.link("📊 下载转换报告 (report.md)", report_url, new_tab=True).classes(
                            "bg-indigo-600 hover:bg-indigo-700 text-white text-xs px-3 py-1.5 rounded-lg font-semibold shadow-sm no-underline"
                        )
                except ValueError:
                    pass

            # 如果有转换成果文件，則打包為單一 ZIP
            if output_files:
                zip_file_path = out_zip_dir / "converted_files.zip"
                if zip_file_path.exists():
                    zip_file_path.unlink()
                
                await asyncio.to_thread(create_zip_archive, output_files, zip_file_path)
                
                if zip_file_path.exists():
                    try:
                        rel_zip = zip_file_path.relative_to(BASE_DIR)
                        zip_url = f"/download/{rel_zip.as_posix()}"
                        with csv_download_container:
                            ui.link("📦 下载全部转换件 (ZIP 打包档)", zip_url, new_tab=True).classes(
                                "bg-amber-600 hover:bg-amber-700 text-white text-xs px-3 py-1.5 rounded-lg font-semibold shadow-sm no-underline font-bold"
                            )
                    except ValueError:
                        pass
            
            if conversion_logs or output_files:
                csv_download_container.visible = True

            dialog_status.set_text("转换任务已完成！")
        except Exception as err:
            dialog_status.set_text(f"转换失败: {str(err)}")
            ui.notify(f"转换失败: {str(err)}", type="negative", position="top")
        finally:
            await asyncio.sleep(3)
            dialog_progress.visible = False
            dialog_status.visible = False

    # =========================================================
    # 模組 2: PDF 查重與去密回調函數
    # =========================================================

    def handle_pdf_deduplication(e: events.ClickEventArguments) -> None:
        refresh_pdf_dedup_list()
        pdf_dedup_dialog.open()

    def refresh_pdf_dedup_list() -> None:
        if pdf_dedup_file_select:
            path_str = pdf_dedup_local_dir_input.value if pdf_dedup_local_dir_input and pdf_dedup_local_dir_input.value else str(INPUT_PDF_DIR)
            input_dir = Path(path_str)
            try:
                if input_dir.exists() and input_dir.is_dir():
                    files = [f.name for f in input_dir.iterdir() if f.is_file() and f.suffix.lower() == ".pdf"]
                    pdf_dedup_file_select.options = ["[全部PDF文件]"] + files
                else:
                    pdf_dedup_file_select.options = ["[全部PDF文件]"]
            except Exception:
                pdf_dedup_file_select.options = ["[全部PDF文件]"]
            pdf_dedup_file_select.update()

    async def on_pdf_dedup_upload(e: events.UploadEventArguments) -> None:
        try:
            import time
            nonlocal last_pdf_dedup_upload_time
            input_dir = INPUT_PDF_DIR / "client_dedup_temp"
            input_dir.mkdir(parents=True, exist_ok=True)
            
            # 若為新上傳階段（與上次上傳間隔 > 2 秒），則清空原來的上傳文件及記錄
            now = time.time()
            if now - last_pdf_dedup_upload_time > 2.0:
                # 1. 刪除 client_dedup_temp 底下的舊檔案
                for f in input_dir.iterdir():
                    if f.is_file() and f.name != ".gitkeep":
                        try:
                            f.unlink()
                        except Exception:
                            pass
                # 2. 清空下拉選單
                if client_pdf_dedup_select:
                    client_pdf_dedup_select.options = ["[全部已上傳PDF文件]"]
                    client_pdf_dedup_select.value = "[全部已上傳PDF文件]"
                    client_pdf_dedup_select.update()
                # 3. 清空查重結果表格與下載容器等記錄
                if pdf_dedup_download_container:
                    pdf_dedup_download_container.clear()
                    pdf_dedup_download_container.visible = False
                if pdf_dedup_progress:
                    pdf_dedup_progress.set_value(0.0)
                    pdf_dedup_progress.visible = False
                if pdf_dedup_status:
                    pdf_dedup_status.set_text("")
                    pdf_dedup_status.visible = False
                if pdf_dedup_table:
                    pdf_dedup_table.rows = []
                    pdf_dedup_table.update()
                if pdf_dedup_results_container:
                    pdf_dedup_results_container.visible = False
            last_pdf_dedup_upload_time = now

            file_path = input_dir / e.file.name
            data = await e.file.read()
            file_path.write_bytes(data)
            ui.notify(f"PDF 文件 {e.file.name} 上傳成功！已暫存至後端。", type="positive", position="top")
            
            files = [f.name for f in input_dir.iterdir() if f.is_file() and f.suffix.lower() == ".pdf"]
            client_pdf_dedup_select.options = ["[全部已上傳PDF文件]"] + files
            client_pdf_dedup_select.value = "[全部已上傳PDF文件]"
            client_pdf_dedup_select.update()
        except Exception as err:
            ui.notify(f"PDF 保存失敗: {str(err)}", type="negative", position="top")

    async def run_pdf_deduplication() -> None:
        if not pdf_dedup_file_select or not client_pdf_dedup_select or not pdf_dedup_progress or not pdf_dedup_status or not pdf_dedup_table:
            return
            
        mode = pdf_dedup_source_type.value
        
        # 收集当前需要保留的文件以防在清理时被误删
        preserve_files = []
        if mode == "server":
            selected = pdf_dedup_file_select.value
            path_str = pdf_dedup_local_dir_input.value if pdf_dedup_local_dir_input and pdf_dedup_local_dir_input.value else str(INPUT_PDF_DIR)
            input_dir = Path(path_str)
            if selected == "[全部PDF文件]":
                try:
                    preserve_files = [input_dir / f.name for f in input_dir.iterdir() if f.is_file() and f.suffix.lower() == ".pdf"]
                except Exception:
                    pass
            elif selected:
                preserve_files = [input_dir / selected]
        else:
            selected = client_pdf_dedup_select.value
            input_dir = INPUT_PDF_DIR / "client_dedup_temp"
            if selected == "[全部已上傳PDF文件]":
                try:
                    preserve_files = [input_dir / f.name for f in input_dir.iterdir() if f.is_file() and f.suffix.lower() == ".pdf"]
                except Exception:
                    pass
            elif selected:
                preserve_files = [input_dir / selected]

        if auto_clear_switch and auto_clear_switch.value:
            clear_data_directories(preserve_files=preserve_files, clear_archives=False)
            log_action("模組 2 執行前已自動清空歷史臨時文件。")

        pdf_dedup_progress.set_value(0.0)
        pdf_dedup_progress.visible = True
        pdf_dedup_status.visible = True
        pdf_dedup_status.set_text("正在啟動 PDF 查重與去密批次處理...")
        
        pdf_dedup_download_container.clear()
        pdf_dedup_download_container.visible = False
        pdf_dedup_table.rows = []
        pdf_dedup_table.update()
        pdf_dedup_results_container.visible = False
        
        # 整理密碼
        pwd_str = pdf_dedup_passwords_input.value or ""
        passwords = [p.strip() for p in pwd_str.split(",") if p.strip()]

        def on_progress(ratio: float, msg: str) -> None:
            if pdf_dedup_progress and pdf_dedup_status:
                pdf_dedup_progress.set_value(ratio)
                pdf_dedup_status.set_text(msg)

        try:
            if mode == "server":
                out_dir = OUTPUT_PDF_DIR
                decrypt_path_str = pdf_dedup_out_dir_input.value if pdf_dedup_out_dir_input and pdf_dedup_out_dir_input.value else str(OUTPUT_PDF_DECRYPT_DIR)
                decrypt_dir = Path(decrypt_path_str)
                report_out_dir = OUTPUT_MD_DIR
            else:
                out_dir = OUTPUT_PDF_DIR / "client_dedup_out"
                decrypt_dir = OUTPUT_PDF_DECRYPT_DIR / "client_dedup_out"
                report_out_dir = OUTPUT_MD_DIR / "client_dedup_out"
            
            out_dir.mkdir(parents=True, exist_ok=True)
            decrypt_dir.mkdir(parents=True, exist_ok=True)
            report_out_dir.mkdir(parents=True, exist_ok=True)
            dedup = PDFDeduplicator(output_dir=out_dir, decrypt_dir=decrypt_dir)
            
            if mode == "server":
                selected = pdf_dedup_file_select.value
                path_str = pdf_dedup_local_dir_input.value if pdf_dedup_local_dir_input and pdf_dedup_local_dir_input.value else str(INPUT_PDF_DIR)
                input_dir = Path(path_str)
                
                if selected == "[全部PDF文件]":
                    files = [input_dir / f.name for f in input_dir.iterdir() if f.is_file() and f.suffix.lower() == ".pdf"]
                else:
                    files = [input_dir / selected] if selected else []
            else:
                selected = client_pdf_dedup_select.value
                input_dir = INPUT_PDF_DIR / "client_dedup_temp"
                
                if selected == "[全部已上傳PDF文件]":
                    files = [input_dir / f.name for f in input_dir.iterdir() if f.is_file() and f.suffix.lower() == ".pdf"]
                else:
                    files = [input_dir / selected] if selected else []

            if not files:
                on_progress(1.0, "未找到任何待處理的 PDF 檔案")
                return

            results = await dedup.process_deduplication(
                file_paths=files,
                passwords=passwords,
                progress_callback=on_progress
            )
            
            # 生成 report.md 審計報告并保存在 output 目录下
            report_file = generate_audit_report(results, report_out_dir)
            
            # Format fields for table display
            for r in results:
                sha = r.get("sha256")
                r["sha256_short"] = f"{sha[:12]}..." if sha else "None"
            
            # 更新 NiceGUI Table
            pdf_dedup_table.rows = results
            pdf_dedup_table.update()
            pdf_dedup_results_container.visible = True
            
            # 下載報告按鈕
            try:
                rel_report = report_file.relative_to(BASE_DIR)
                report_url = f"/download/{rel_report.as_posix()}"
                with pdf_dedup_download_container:
                    ui.link("📊 下載審計報告 (report.md)", report_url, new_tab=True).classes(
                        "bg-indigo-600 hover:bg-indigo-700 text-white text-xs px-3 py-1.5 rounded-lg font-semibold shadow-sm no-underline"
                    )
            except ValueError:
                pass

            # 收集去密唯一件
            kept_files = []
            for r in results:
                if r["status"] == "Unique" and r["action"] in ("Kept (已保留)", "Kept (已保留並去密)"):
                    saved_file = out_dir / r["file_name"]
                    if saved_file.exists():
                        kept_files.append(saved_file)

            # 如果有保留唯一件，則打包為單一 ZIP
            if kept_files:
                zip_file_path = (OUTPUT_PDF_DIR if mode == "server" else OUTPUT_PDF_DIR / "client_dedup_out") / "deduplicated_files.zip"
                if zip_file_path.exists():
                    zip_file_path.unlink()
                
                # 異步打包 ZIP 存檔，避免阻塞前端主線程
                await asyncio.to_thread(create_zip_archive, kept_files, zip_file_path)
                
                if zip_file_path.exists():
                    try:
                        rel_zip = zip_file_path.relative_to(BASE_DIR)
                        zip_url = f"/download/{rel_zip.as_posix()}"
                        with pdf_dedup_download_container:
                            ui.link("📦 下載全部保留件 (ZIP 打包檔)", zip_url, new_tab=True).classes(
                                "bg-amber-600 hover:bg-amber-700 text-white text-xs px-3 py-1.5 rounded-lg font-semibold shadow-sm no-underline font-bold"
                            )
                    except ValueError:
                        pass
                                
            pdf_dedup_download_container.visible = True
            pdf_dedup_status.set_text("PDF 查重與去密處理完成！")
            ui.notify("查重清理完成！已生成審計報告並去密保留唯一件。", type="positive", position="top")
        except Exception as err:
            pdf_dedup_status.set_text(f"查重失敗: {str(err)}")
            ui.notify(f"查重失敗: {str(err)}", type="negative", position="top")
        finally:
            await asyncio.sleep(5)
            if pdf_dedup_progress:
                pdf_dedup_progress.visible = False
            if pdf_dedup_status:
                pdf_dedup_status.visible = False

    # =========================================================
    # 模块 3: PDF 转 Markdown 回调函数
    # =========================================================

    def handle_pdf_md(e: events.ClickEventArguments) -> None:
        refresh_pdf_list()
        pdf_md_dialog.open()

    def refresh_pdf_list() -> None:
        if pdf_file_select:
            path_str = pdf_local_dir_input.value if pdf_local_dir_input and pdf_local_dir_input.value else str(INPUT_PDF_DIR)
            input_dir = Path(path_str)
            try:
                if input_dir.exists() and input_dir.is_dir():
                    files = [f.name for f in input_dir.iterdir() if f.is_file() and f.suffix.lower() == ".pdf"]
                    pdf_file_select.options = ["[全部PDF文件]"] + files
                else:
                    pdf_file_select.options = ["[全部PDF文件]"]
            except Exception:
                pdf_file_select.options = ["[全部PDF文件]"]
            pdf_file_select.update()

    async def on_pdf_upload(e: events.UploadEventArguments) -> None:
        """处理用户上传 PDF 账单"""
        try:
            import time
            nonlocal last_pdf_upload_time
            input_dir = INPUT_PDF_DIR / "client_pdf_temp"
            input_dir.mkdir(parents=True, exist_ok=True)
            
            # 若為新上傳階段（與上次上傳間隔 > 2 秒），則清空原來的上傳文件及記錄
            now = time.time()
            if now - last_pdf_upload_time > 2.0:
                # 1. 刪除 client_pdf_temp 底下的舊檔案
                for f in input_dir.iterdir():
                    if f.is_file() and f.name != ".gitkeep":
                        try:
                            f.unlink()
                        except Exception:
                            pass
                # 2. 清空下拉選單
                if client_pdf_select:
                    client_pdf_select.options = ["[全部已上传PDF文件]"]
                    client_pdf_select.value = "[全部已上传PDF文件]"
                    client_pdf_select.update()
                # 3. 清空日誌與下載容器等記錄
                if pdf_download_container:
                    pdf_download_container.clear()
                    pdf_download_container.visible = False
                if pdf_progress:
                    pdf_progress.set_value(0.0)
                    pdf_progress.visible = False
                if pdf_status:
                    pdf_status.set_text("")
                    pdf_status.visible = False
                if pdf_log_container:
                    pdf_log_container.clear()
                if pdf_log_board:
                    pdf_log_board.visible = False
            last_pdf_upload_time = now

            file_path = input_dir / e.file.name
            
            # NiceGUI 3.x FileUpload.read() 是一个异步方法
            data = await e.file.read()
            file_path.write_bytes(data)
            ui.notify(f"PDF 文件 {e.file.name} 上传成功！已暂存至后端。", type="positive", position="top")
            
            # 刷新已上传 PDF 文件列表
            files = [f.name for f in input_dir.iterdir() if f.is_file() and f.suffix.lower() == ".pdf"]
            client_pdf_select.options = ["[全部已上传PDF文件]"] + files
            client_pdf_select.value = "[全部已上传PDF文件]"
            client_pdf_select.update()
        except Exception as err:
            ui.notify(f"PDF 保存失败: {str(err)}", type="negative", position="top")

    async def run_pdf_conversion() -> None:
        """执行 PDF 转换为 Markdown，并支持对账校验与客户端下载"""
        if not pdf_file_select or not client_pdf_select or not pdf_progress or not pdf_status or not pdf_log_board or not pdf_log_container:
            return
            
        mode = pdf_source_type.value
        
        # 收集当前需要保留的文件以防在清理时被误删
        preserve_files = []
        if mode == "server":
            selected = pdf_file_select.value
            path_str = pdf_local_dir_input.value if pdf_local_dir_input and pdf_local_dir_input.value else str(INPUT_PDF_DIR)
            input_dir = Path(path_str)
            if selected == "[全部PDF文件]":
                try:
                    preserve_files = [input_dir / f.name for f in input_dir.iterdir() if f.is_file() and f.suffix.lower() == ".pdf"]
                except Exception:
                    pass
            elif selected:
                preserve_files = [input_dir / selected]
        else:
            selected = client_pdf_select.value
            input_dir = INPUT_PDF_DIR / "client_pdf_temp"
            if selected == "[全部已上传PDF文件]":
                try:
                    preserve_files = [input_dir / f.name for f in input_dir.iterdir() if f.is_file() and f.suffix.lower() == ".pdf"]
                except Exception:
                    pass
            elif selected:
                preserve_files = [input_dir / selected]

        if auto_clear_switch and auto_clear_switch.value:
            clear_data_directories(preserve_files=preserve_files, clear_archives=False)
            log_action("模块 3 执行前已自动清空历史临时文件。")

        pdf_progress.set_value(0.0)
        pdf_progress.visible = True
        pdf_status.visible = True
        pdf_log_board.visible = True
        pdf_log_container.clear()
        pdf_status.set_text("正在启动 PDF 解析与勾稽关系校验...")
        
        pdf_download_container.clear()
        pdf_download_container.visible = False
        
        all_audit_logs = []

        def on_progress(progress: ParserProgress) -> None:
            if pdf_progress and pdf_status:
                file_idx = progress.current_file_idx
                total_files = progress.total_files
                page_num = progress.current_page
                total_pages = progress.total_pages
                message = progress.status_msg
                audit_logs = progress.audit_alerts
                
                if audit_logs:
                    all_audit_logs.extend(audit_logs)
                
                if total_files > 0 and total_pages > 0:
                    current_progress = (file_idx - 1) / total_files + (page_num / total_pages) / total_files
                    pdf_progress.set_value(current_progress)
                    pdf_status.set_text(f"文件 ({file_idx}/{total_files}) - {message}")
                else:
                    pdf_status.set_text(message)
                    
            # 看板渲染审计日志行
            for log in progress.audit_alerts:
                if log["status"] == "success":
                    bg_color, text_color, icon = "bg-emerald-950/40 border-emerald-500/30", "text-emerald-400", "✅"
                    animate_class = ""
                elif log["status"] == "warning":
                    bg_color, text_color, icon = "bg-amber-950/40 border-amber-500/30", "text-amber-400", "⚠️"
                    animate_class = ""
                elif log["status"] == "NEED_VISUAL_REVIEW":
                    bg_color, text_color, icon = "bg-indigo-950/60 border-indigo-500/40", "text-indigo-300", "👁️"
                    animate_class = "animate-pulse font-semibold"
                else:
                    bg_color, text_color, icon = "bg-rose-950/40 border-rose-500/30", "text-rose-400", "❌"
                    animate_class = ""
                    
                with pdf_log_container:
                    with ui.row().classes(f"w-full items-center p-2 rounded-lg border {bg_color} text-xs font-mono {animate_class}"):
                        ui.label(icon).classes("mr-1")
                        ui.label(f"[{log['file']} P.{log['page']}]").classes("font-bold text-slate-300 mr-2")
                        ui.label(f"【{log['type']}】").classes("font-semibold mr-2")
                        ui.label(log["message"]).classes(text_color)
                        
                # 滚动至看板底部
                ui.run_javascript(f"document.getElementById('{pdf_log_board.id}').scrollTop = document.getElementById('{pdf_log_board.id}').scrollHeight")

        output_md_files: list[Path] = []
        try:
            parser = PDFBatchParser(input_dir=INPUT_PDF_DIR, output_dir=OUTPUT_MD_DIR) # Default dirs
            
            if mode == "server":
                selected = pdf_file_select.value
                path_str = pdf_local_dir_input.value if pdf_local_dir_input and pdf_local_dir_input.value else str(INPUT_PDF_DIR)
                input_dir = Path(path_str)
                
                parser = PDFBatchParser(input_dir=input_dir, output_dir=OUTPUT_MD_DIR)
                if selected == "[全部PDF文件]":
                    output_files = await parser.parse_all(progress_callback=on_progress)
                    for out_path in output_files:
                        out_path_obj = Path(out_path).resolve()
                        if out_path_obj.exists():
                            output_md_files.append(out_path_obj)
                else:
                    file_path = input_dir / selected
                    if file_path.exists():
                        out_path = await parser.parse_file(file_path, 1, 1, progress_callback=on_progress)
                        out_path_obj = Path(out_path).resolve()
                        if out_path_obj.exists():
                            output_md_files.append(out_path_obj)
                        ui.notify(f"解析成功！已生成至 {out_path_obj.name}", type="positive", position="top")
                    else:
                        raise FileNotFoundError(f"文件不存在: {selected}")
            else:
                selected = client_pdf_select.value
                input_dir = INPUT_PDF_DIR / "client_pdf_temp"
                
                parser = PDFBatchParser(input_dir=input_dir, output_dir=OUTPUT_MD_DIR)
                if selected == "[全部已上传PDF文件]":
                    files = [f for f in input_dir.iterdir() if f.is_file() and f.suffix.lower() == ".pdf"]
                    total_files = len(files)
                    if total_files == 0:
                        on_progress(ParserProgress(0, 0, 0, 0, "未找到任何已上传的 PDF 文件。", []))
                        return
                    for idx, file_path in enumerate(files, start=1):
                        out_path = await parser.parse_file(file_path, idx, total_files, progress_callback=on_progress)
                        out_path_obj = Path(out_path).resolve()
                        if out_path_obj.exists():
                            output_md_files.append(out_path_obj)
                else:
                    file_path = input_dir / selected
                    if file_path.exists():
                        out_path = await parser.parse_file(file_path, 1, 1, progress_callback=on_progress)
                        out_path_obj = Path(out_path).resolve()
                        if out_path_obj.exists():
                            output_md_files.append(out_path_obj)
                        ui.notify(f"解析成功！已暫存至後端。", type="positive", position="top")
                    else:
                        raise FileNotFoundError(f"文件不存在: {selected}")
            
            # 定義報告輸出目錄
            if mode == "server":
                report_out_dir = OUTPUT_MD_DIR
            else:
                report_out_dir = OUTPUT_MD_DIR / "client_pdf_out"
            
            # 生成 report.md 審計報告并提供下載
            report_file = generate_pdf_conversion_report(all_audit_logs, report_out_dir)
            try:
                rel_report = report_file.relative_to(BASE_DIR)
                report_url = f"/download/{rel_report.as_posix()}"
                with pdf_download_container:
                    ui.link("📊 下載審計報告 (report.md)", report_url, new_tab=True).classes(
                        "bg-indigo-600 hover:bg-indigo-700 text-white text-xs px-3 py-1.5 rounded-lg font-semibold shadow-sm no-underline"
                    )
            except ValueError:
                pass

            # 如果有生成的 Markdown 文件，則打包為單一 ZIP
            if output_md_files:
                if mode == "server":
                    out_zip_dir = OUTPUT_MD_DIR
                else:
                    out_zip_dir = OUTPUT_MD_DIR / "client_pdf_out"
                out_zip_dir.mkdir(parents=True, exist_ok=True)
                zip_file_path = out_zip_dir / "parsed_markdown_files.zip"
                if zip_file_path.exists():
                    zip_file_path.unlink()
                
                await asyncio.to_thread(create_zip_archive, output_md_files, zip_file_path)
                
                if zip_file_path.exists():
                    try:
                        rel_zip = zip_file_path.relative_to(BASE_DIR)
                        zip_url = f"/download/{rel_zip.as_posix()}"
                        with pdf_download_container:
                            ui.link("📦 下载全部解析件 (ZIP 打包档)", zip_url, new_tab=True).classes(
                                "bg-amber-600 hover:bg-amber-700 text-white text-xs px-3 py-1.5 rounded-lg font-semibold shadow-sm no-underline font-bold"
                            )
                    except ValueError:
                        pass
                pdf_download_container.visible = True
            
            pdf_status.set_text("PDF 解析与勾稽审计完成！")
        except Exception as err:
            pdf_status.set_text(f"解析失败: {str(err)}")
            ui.notify(f"解析失败: {str(err)}", type="negative", position="top")
        finally:
            await asyncio.sleep(5)
            pdf_progress.visible = False
            pdf_status.visible = False

    # =========================================================
    # 模块 11: 平仓数据整理回调函数
    # =========================================================
    def handle_md_closing(e: events.ClickEventArguments) -> None:
        nonlocal md_closing_uploaded_files
        md_closing_uploaded_files = []
        if md_closing_download_container:
            md_closing_download_container.clear()
            md_closing_download_container.visible = False
        if md_closing_progress:
            md_closing_progress.set_value(0.0)
            md_closing_progress.visible = False
        if md_closing_status:
            md_closing_status.set_text("等待上传与整理...")
            md_closing_status.visible = False
        md_closing_dialog.open()

    async def on_md_upload(e: events.UploadEventArguments) -> None:
        try:
            nonlocal md_closing_uploaded_files
            data = await e.file.read()
            md_closing_uploaded_files.append((e.file.name, data))
            ui.notify(f"Markdown 文件 {e.file.name} 上传并暂存成功！", type="positive", position="top")
        except Exception as err:
            ui.notify(f"上传失败: {str(err)}", type="negative", position="top")

    async def run_md_closing_organization() -> None:
        nonlocal md_closing_uploaded_files
        if not md_closing_uploaded_files:
            ui.notify("请先上传至少一个 Markdown 交易明细文件！", type="warning", position="top")
            return
            
        md_closing_progress.set_value(0.0)
        md_closing_progress.visible = True
        md_closing_status.visible = True
        md_closing_status.set_text("正在提取并整理平仓成交明细...")
        
        md_closing_download_container.clear()
        md_closing_download_container.visible = False
        
        start_date = None
        end_date = None
        if md_closing_start_date.value:
            start_date = md_closing.parse_date(md_closing_start_date.value)
        if md_closing_end_date.value:
            end_date = md_closing.parse_date(md_closing_end_date.value)
            
        all_closing_trades = []
        
        try:
            for file_name, file_bytes in md_closing_uploaded_files:
                md_content = file_bytes.decode("utf-8", errors="ignore")
                tables = md_closing.parse_markdown_tables(md_content)
                trades = md_closing.extract_closing_trades(tables, start_date, end_date)
                for t in trades:
                    t["来自文件"] = file_name
                all_closing_trades.extend(trades)
                
            md_closing_progress.set_value(0.5)
            md_closing_status.set_text("正在生成 Excel 整理表与审计报告...")
            
            out_dir = OUTPUT_DIR / "closing_summary"
            out_dir.mkdir(parents=True, exist_ok=True)
            
            excel_path, report_path = await asyncio.to_thread(
                md_closing.generate_closing_report,
                all_closing_trades,
                out_dir,
                md_closing_start_date.value or "",
                md_closing_end_date.value or ""
            )
            
            zip_file_path = out_dir / "organized_closing_data.zip"
            if zip_file_path.exists():
                zip_file_path.unlink()
                
            await asyncio.to_thread(create_zip_archive, [excel_path], zip_file_path)
            
            md_closing_progress.set_value(1.0)
            md_closing_status.set_text(f"平仓数据整理完成！匹配到 {len(all_closing_trades)} 笔平仓成交。")
            
            try:
                rel_report = report_path.relative_to(BASE_DIR)
                report_url = f"/download/{rel_report.as_posix()}"
                with md_closing_download_container:
                    ui.link("📊 下载整理报告 (report.md)", report_url, new_tab=True).classes(
                        "bg-indigo-600 hover:bg-indigo-700 text-white text-xs px-3 py-1.5 rounded-lg font-semibold shadow-sm no-underline"
                    )
            except ValueError:
                pass
                
            if zip_file_path.exists():
                try:
                    rel_zip = zip_file_path.relative_to(BASE_DIR)
                    zip_url = f"/download/{rel_zip.as_posix()}"
                    with md_closing_download_container:
                        ui.link("📦 下载全部整理件 (ZIP 打包档)", zip_url, new_tab=True).classes(
                            "bg-amber-600 hover:bg-amber-700 text-white text-xs px-3 py-1.5 rounded-lg font-semibold shadow-sm no-underline font-bold"
                        )
                except ValueError:
                    pass
                    
            md_closing_download_container.visible = True
            ui.notify(f"整理成功！提取出 {len(all_closing_trades)} 笔平仓成交数据。", type="positive", position="top")
            log_action(f"模块 11 执行成功：时间段为 {md_closing_start_date.value or '未限定'} - {md_closing_end_date.value or '未限定'}，匹配到 {len(all_closing_trades)} 笔平仓明细并已生成 ZIP")
            
        except Exception as err:
            md_closing_status.set_text(f"整理失败: {str(err)}")
            ui.notify(f"数据整理失败: {str(err)}", type="negative", position="top")
            
        finally:
            await asyncio.sleep(5)
            if md_closing_progress:
                md_closing_progress.visible = False
            if md_closing_status:
                md_closing_status.visible = False

    # =========================================================
    # 智能控制台回调函数与辅助方法 (新模块集成)
    # =========================================================
    sys_log_board: ui.card = None

    def handle_db_test(e: events.ClickEventArguments) -> None:
        db_dialog.open()

    def handle_calculator(e: events.ClickEventArguments) -> None:
        calc_dialog.open()

    def handle_validator(e: events.ClickEventArguments) -> None:
        val_dialog.open()

    def handle_exporter(e: events.ClickEventArguments) -> None:
        exp_dialog.open()

    async def handle_archive(e: events.ClickEventArguments) -> None:
        await refresh_archive_table()
        archive_dialog.open()

    def handle_config_view(e: events.ClickEventArguments) -> None:
        config_view_dialog.open()

    def handle_system_logs(e: events.ClickEventArguments) -> None:
        refresh_logs()
        system_logs_dialog.open()

    async def refresh_archive_table() -> None:
        try:
            conn = db_config.get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT id, archive_name, file_path, operator, created_at FROM history_archives ORDER BY id DESC")
            rows = cursor.fetchall()
            conn.close()
            
            archive_rows = []
            for row in rows:
                aid, name, path, operator, created_at = row
                download_url = "#"
                try:
                    resolved = Path(path)
                    if resolved.exists():
                        rel_path = resolved.relative_to(BASE_DIR)
                        download_url = f"/download/{rel_path.as_posix()}"
                except Exception:
                    pass
                    
                archive_rows.append({
                    "id": aid,
                    "archive_name": name,
                    "file_path": path,
                    "operator": operator,
                    "created_at": created_at,
                    "download_url": download_url
                })
            archive_table.rows = archive_rows
            archive_table.update()
        except Exception as err:
            ui.notify(f"载入归档失败: {str(err)}", type="negative", position="top")

    def refresh_logs() -> None:
        if system_logs_container:
            system_logs_container.clear()
            for log_entry in system_logs_list:
                with system_logs_container:
                    ui.label(log_entry).classes("text-xs font-mono text-emerald-400")
            if sys_log_board:
                ui.run_javascript(f"document.getElementById('{sys_log_board.id}').scrollTop = document.getElementById('{sys_log_board.id}').scrollHeight")

    # --- 页面 UI 布局 ---
    
    # 全局背景和字体样式
    ui.query("body").classes("bg-slate-50 font-sans")
    
    # 顶部导航栏 (采用渐变深色背景，突显专业性)
    with ui.header().classes("w-full bg-gradient-to-r from-slate-900 via-indigo-950 to-slate-900 text-white p-4 shadow-lg flex justify-between items-center"):
        with ui.row().classes("items-center gap-3"):
            ui.icon("analytics", size="2rem").classes("text-indigo-400 animate-pulse")
            ui.label("China-Tax 智能税务自动化申报系统").classes("text-xl font-bold tracking-wide")
        ui.label("v2.0 Beta (NiceGUI / Python 3.14)").classes("text-sm text-slate-400 font-mono")
        
    # 主体内容区域
    with ui.column().classes("w-full max-w-7xl mx-auto p-6 gap-6"):
        
        # 欢迎与规范概述卡片
        with ui.card().classes("w-full p-6 bg-white border border-slate-200 rounded-xl shadow-sm gap-4"):
            with ui.row().classes("w-full justify-between items-center gap-4 flex-wrap md:flex-nowrap"):
                with ui.column().classes("gap-2 flex-grow"):
                    with ui.row().classes("items-center gap-2"):
                        ui.icon("info", size="1.5rem").classes("text-indigo-600")
                        ui.label("项目控制中心与工具箱").classes("text-lg font-bold text-slate-800")
                    ui.markdown(
                        "本系统严格遵循 `gemini.md` 规范进行架构设计。下方工具箱集成了核心的报税处理程序，"
                        "所有数据流转均支持**长数字安全保护（避免身份证、企业税号科学计数法截断）**。"
                    ).classes("text-slate-600 text-sm leading-relaxed")
                
                # 数据缓存与临时文件清理控制面板
                with ui.card().classes("w-full md:w-auto p-4 bg-slate-50 border border-slate-200 rounded-xl gap-2 min-w-[280px] shadow-inner"):
                    with ui.row().classes("items-center gap-1.5"):
                        ui.icon("cleaning_services", size="1.2rem").classes("text-amber-500")
                        ui.label("缓存与临时目录控制").classes("text-xs font-bold text-slate-700 uppercase tracking-wide")
                    
                    async def prompt_bank_name():
                        nonlocal bank_name_input
                        with ui.dialog().props('persistent') as dialog, ui.card().classes('p-6 w-96 gap-4'):
                            ui.label('🔑 啟用目錄隔離系統').classes('text-lg font-bold text-slate-800')
                            ui.label('請先輸入金融機構名稱（如：富途證券 / 招商銀行），系統將為此機構建立獨立的資料夾隔離環境。').classes('text-xs text-slate-500')
                            
                            name_input = ui.input(
                                label='金融機構名稱',
                                placeholder='例如：富途證券 / 招商銀行',
                                validation={'名稱不能為空': lambda v: bool(v and v.strip())}
                            ).classes('w-full')
                            
                            def on_confirm():
                                val = name_input.value
                                if val and val.strip():
                                    update_active_paths(val)
                                    if bank_name_input:
                                        bank_name_input.set_value(val)
                                    
                                    # 建立目錄
                                    INPUT_PDF_DIR.mkdir(parents=True, exist_ok=True)
                                    INPUT_CSV_DIR.mkdir(parents=True, exist_ok=True)
                                    INPUT_EXCEL_DIR.mkdir(parents=True, exist_ok=True)
                                    INPUT_MD_DIR.mkdir(parents=True, exist_ok=True)
                                    OUTPUT_PDF_DIR.mkdir(parents=True, exist_ok=True)
                                    OUTPUT_PDF_DECRYPT_DIR.mkdir(parents=True, exist_ok=True)
                                    OUTPUT_CSV_DIR.mkdir(parents=True, exist_ok=True)
                                    OUTPUT_EXCEL_DIR.mkdir(parents=True, exist_ok=True)
                                    OUTPUT_MD_DIR.mkdir(parents=True, exist_ok=True)
                                    
                                    # 更新所有路徑輸入框
                                    if local_dir_input:
                                        local_dir_input.set_value(str(INPUT_CSV_DIR))
                                    if pdf_dedup_local_dir_input:
                                        pdf_dedup_local_dir_input.set_value(str(INPUT_PDF_DIR))
                                    if pdf_dedup_out_dir_input:
                                        pdf_dedup_out_dir_input.set_value(str(OUTPUT_PDF_DECRYPT_DIR))
                                    if pdf_local_dir_input:
                                        pdf_local_dir_input.set_value(str(INPUT_PDF_DIR))
                                        
                                    # 刷新清單
                                    try:
                                        refresh_file_list()
                                        refresh_pdf_dedup_list()
                                        refresh_pdf_list()
                                    except Exception:
                                        pass
                                        
                                    log_action(f"初始化目錄隔離：金融機構={val} -> 輸入目錄={INPUT_DIR}, 輸出目錄={OUTPUT_DIR}")
                                    dialog.close()
                                else:
                                    ui.notify('請輸入有效的機構名稱！', type='warning')
                                    
                            ui.button('確認並進入系統', on_click=on_confirm).classes('w-full bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg py-2')
                            name_input.on('keydown.enter', on_confirm)
                            
                        dialog.open()

                    def on_bank_name_change(e):
                        bank_name = (e.value if hasattr(e, 'value') else e.sender.value) or ""
                        clean_name = "".join(c for c in bank_name if c.isalnum() or c in ("-", "_", " ")).strip()
                        if not clean_name:
                            ui.notify("⚠️ 金融機構名稱不能為空！", type="warning", position="top")
                            ui.timer(0.1, prompt_bank_name, once=True)
                            return
                        
                        update_active_paths(bank_name)
                        
                        # 建立券商目錄下的格式子目錄
                        INPUT_PDF_DIR.mkdir(parents=True, exist_ok=True)
                        INPUT_CSV_DIR.mkdir(parents=True, exist_ok=True)
                        INPUT_EXCEL_DIR.mkdir(parents=True, exist_ok=True)
                        INPUT_MD_DIR.mkdir(parents=True, exist_ok=True)
                        OUTPUT_PDF_DIR.mkdir(parents=True, exist_ok=True)
                        OUTPUT_PDF_DECRYPT_DIR.mkdir(parents=True, exist_ok=True)
                        OUTPUT_CSV_DIR.mkdir(parents=True, exist_ok=True)
                        OUTPUT_EXCEL_DIR.mkdir(parents=True, exist_ok=True)
                        OUTPUT_MD_DIR.mkdir(parents=True, exist_ok=True)
                        
                        # 动态更新各模块输入/输出路径文本框的值
                        if local_dir_input:
                            local_dir_input.set_value(str(INPUT_CSV_DIR))
                        if pdf_dedup_local_dir_input:
                            pdf_dedup_local_dir_input.set_value(str(INPUT_PDF_DIR))
                        if pdf_dedup_out_dir_input:
                            pdf_dedup_out_dir_input.set_value(str(OUTPUT_PDF_DECRYPT_DIR))
                        if pdf_local_dir_input:
                            pdf_local_dir_input.set_value(str(INPUT_PDF_DIR))
                            
                        # 刷新所有文件列表
                        try:
                            refresh_file_list()
                            refresh_pdf_dedup_list()
                            refresh_pdf_list()
                        except Exception:
                            pass
                            
                        log_action(f"切换隔离目录：券商/银行名={bank_name} -> 输入目录={INPUT_DIR}, 输出目录={OUTPUT_DIR}")

                    bank_name_input = ui.input(
                        label="银行及券商名称 (目录隔离)",
                        placeholder="例如：招商银行 / 中信证券",
                    ).classes("w-full text-xs").on("blur", on_bank_name_change).on("keydown.enter", on_bank_name_change)
                    
                    auto_clear_switch = ui.switch("启动模块时清空历史文件", value=False).classes("text-xs text-slate-600")
                    
                    def manual_clear():
                        clear_data_directories(clear_archives=False)
                        ui.notify("已成功清理后端 data 目錄下的所有子目錄與暫存檔案！", type="positive", position="top")
                        log_action("手动执行后端 data 目录所有子目录文件清理。")
                        
                    ui.button("🧹 一键清空后端文件", on_click=manual_clear).classes(
                        "w-full bg-indigo-50 hover:bg-indigo-100 text-indigo-700 text-xs font-bold py-2 px-3 rounded-lg shadow-sm"
                    )
        
        # 11 个功能卡的网格布局
        ui.label("系统控制工具箱 (11 大功能项)").classes("text-base font-semibold text-slate-500 uppercase tracking-wider mt-4")
        
        with ui.grid().classes("grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6 w-full"):
            
            # --- 核心规划工具 1: CSV/Excel 转换 ---
            with ui.card().classes("hover:shadow-md transition-all duration-300 border border-slate-200 rounded-xl p-5 flex flex-col justify-between h-48 bg-white"):
                with ui.column().classes("gap-1 w-full"):
                    ui.label("1. CSV & Excel 互转").classes("font-bold text-slate-800 text-base")
                    ui.label("支持选择单个或批量 CSV 文件进行无损 Excel 格式互转，防长数字字段精度丢失。").classes("text-xs text-slate-500")
                ui.button("启动转换", on_click=handle_csv_excel).classes("w-full bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg py-2 text-sm font-semibold shadow-sm")

            # --- 核心规划工具 2: PDF 查重删除 ---
            with ui.card().classes("hover:shadow-md transition-all duration-300 border border-slate-200 rounded-xl p-5 flex flex-col justify-between h-48 bg-white"):
                with ui.column().classes("gap-1"):
                    ui.label("2. PDF 文件查重").classes("font-bold text-slate-800 text-base")
                    ui.label("扫描输入目录，智能去重多余 PDF 报税文件，并导出清理结果报告。").classes("text-xs text-slate-500")
                ui.button("开始查重", on_click=handle_pdf_deduplication).classes("w-full bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg py-2 text-sm font-semibold shadow-sm")

            # --- 核心规划工具 3: PDF 转 Markdown ---
            with ui.card().classes("hover:shadow-md transition-all duration-300 border border-slate-200 rounded-xl p-5 flex flex-col justify-between h-48 bg-white"):
                with ui.column().classes("gap-1"):
                    ui.label("3. PDF 结单提取").classes("font-bold text-slate-800 text-base")
                    ui.label("将 PDF 格式的报税单/结单结构化转化为 Markdown 格式，便于系统自动分析和入库。").classes("text-xs text-slate-500")
                ui.button("启动解析", on_click=handle_pdf_md).classes("w-full bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg py-2 text-sm font-semibold shadow-sm")

            # --- 功能 4: 数据库连接测试 ---
            with ui.card().classes("hover:shadow-md transition-all duration-300 border border-slate-200 rounded-xl p-5 flex flex-col justify-between h-48 bg-white"):
                with ui.column().classes("gap-1"):
                    ui.label("4. 数据库连接").classes("font-bold text-slate-800 text-base")
                    ui.label("测试 PostgreSQL 核心档案库的连通性与配置可用状态。").classes("text-xs text-slate-500")
                ui.button("测试连接", on_click=handle_db_test).classes("w-full bg-slate-700 hover:bg-slate-800 text-white rounded-lg py-2 text-sm font-semibold")

            # --- 功能 5: 税额智能计算 ---
            with ui.card().classes("hover:shadow-md transition-all duration-300 border border-slate-200 rounded-xl p-5 flex flex-col justify-between h-48 bg-white"):
                with ui.column().classes("gap-1"):
                    ui.label("5. 税额智能计算").classes("font-bold text-slate-800 text-base")
                    ui.label("执行个税、企业税等核心计算公式与多场景比对。").classes("text-xs text-slate-500")
                ui.button("核算税额", on_click=handle_calculator).classes("w-full bg-slate-700 hover:bg-slate-800 text-white rounded-lg py-2 text-sm font-semibold")

            # --- 功能 6: 数据合法性校验 ---
            with ui.card().classes("hover:shadow-md transition-all duration-300 border border-slate-200 rounded-xl p-5 flex flex-col justify-between h-48 bg-white"):
                with ui.column().classes("gap-1"):
                    ui.label("6. 申报合法性校验").classes("font-bold text-slate-800 text-base")
                    ui.label("快速校验报税数据是否存在逻辑漏洞、格式错误或非法数字。").classes("text-xs text-slate-500")
                ui.button("校验数据", on_click=handle_validator).classes("w-full bg-slate-700 hover:bg-slate-800 text-white rounded-lg py-2 text-sm font-semibold")

            # --- 功能 7: 一键生成申报表 ---
            with ui.card().classes("hover:shadow-md transition-all duration-300 border border-slate-200 rounded-xl p-5 flex flex-col justify-between h-48 bg-white"):
                with ui.column().classes("gap-1"):
                    ui.label("7. 一键生成申报表").classes("font-bold text-slate-800 text-base")
                    ui.label("打包已核算的数据，导出为符合国税标准的电子申报文件。").classes("text-xs text-slate-500")
                ui.button("导出报表", on_click=handle_exporter).classes("w-full bg-slate-700 hover:bg-slate-800 text-white rounded-lg py-2 text-sm font-semibold")

            # --- 功能 8: 历史档案数据查询 ---
            with ui.card().classes("hover:shadow-md transition-all duration-300 border border-slate-200 rounded-xl p-5 flex flex-col justify-between h-48 bg-white"):
                with ui.column().classes("gap-1"):
                    ui.label("8. 历史归档查询").classes("font-bold text-slate-800 text-base")
                    ui.label("检索和浏览已归档的历史年度纳税记录与申报文件。").classes("text-xs text-slate-500")
                ui.button("浏览归档", on_click=handle_archive).classes("w-full bg-slate-700 hover:bg-slate-800 text-white rounded-lg py-2 text-sm font-semibold")

            # --- 功能 9: 税率表与参数配置 ---
            with ui.card().classes("hover:shadow-md transition-all duration-300 border border-slate-200 rounded-xl p-5 flex flex-col justify-between h-48 bg-white"):
                with ui.column().classes("gap-1"):
                    ui.label("9. 税率参数配置").classes("font-bold text-slate-800 text-base")
                    ui.label("配置或调整各年度各税种的税率速算扣除数及减免参数。").classes("text-xs text-slate-500")
                ui.button("配置参数", on_click=handle_config_view).classes("w-full bg-slate-700 hover:bg-slate-800 text-white rounded-lg py-2 text-sm font-semibold")

            # --- 功能 10: 系统状态与运行日志 ---
            with ui.card().classes("hover:shadow-md transition-all duration-300 border border-slate-200 rounded-xl p-5 flex flex-col justify-between h-48 bg-white"):
                with ui.column().classes("gap-1"):
                    ui.label("10. 运行状态与日志").classes("font-bold text-slate-800 text-base")
                    ui.label("监控当前服务的运行状态并实时查阅核心操作日志。").classes("text-xs text-slate-500")
                ui.button("查阅日志", on_click=handle_system_logs).classes("w-full bg-slate-700 hover:bg-slate-800 text-white rounded-lg py-2 text-sm font-semibold")

            # --- 功能 11: 平仓数据整理 ---
            with ui.card().classes("hover:shadow-md transition-all duration-300 border border-slate-200 rounded-xl p-5 flex flex-col justify-between h-48 bg-white"):
                with ui.column().classes("gap-1"):
                    ui.label("11. 平仓交易整理").classes("font-bold text-slate-800 text-base")
                    ui.label("上传指定 Markdown 账单文件，按指定时间段提取整理平仓成交的标的，输出 Excel。").classes("text-xs text-slate-500")
                ui.button("整理平仓数据", on_click=handle_md_closing).classes("w-full bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg py-2 text-sm font-semibold shadow-sm")

    # --- CSV/Excel 转换交互对话框 (Dialog) ---
    with ui.dialog() as csv_excel_dialog:
        with ui.card().classes("w-[550px] p-6 gap-4 bg-white rounded-xl shadow-2xl"):
            with ui.row().classes("w-full justify-between items-center"):
                with ui.row().classes("items-center gap-2"):
                    ui.icon("swap_horiz", size="1.8rem").classes("text-indigo-600")
                    ui.label("CSV & Excel 互转控制台").classes("text-lg font-bold text-slate-800")
                ui.button(icon="close", on_click=csv_excel_dialog.close).props("flat round dense").classes("text-slate-400")
            
            ui.separator()
            
            ui.label("步骤 1：选择文件存储位置环境").classes("text-xs font-bold text-slate-500 uppercase tracking-wide")
            # 来源选择切换
            source_type = ui.toggle(
                options={
                    "server": "本机/Linux后端",
                    "client": "浏览器客户端"
                },
                value="server"
            ).classes("w-full")
            
            # --- 本机/后端服务器 区域 ---
            with ui.column().classes("w-full gap-3") as server_section:
                ui.label("本机文件夹绝对路径").classes("text-xs font-bold text-slate-500 uppercase tracking-wide")
                local_dir_input = ui.input(
                    label="输入 Linux 后端 CSV 所在的文件夹路径",
                    value=str(INPUT_CSV_DIR),
                    on_change=refresh_file_list
                ).classes("w-full")
                
                ui.label("选择待转换的文件").classes("text-xs font-bold text-slate-500 uppercase tracking-wide")
                file_select = ui.select(
                    options=["[全部文件]"],
                    value="[全部文件]",
                    label="待转换的 CSV 文件"
                ).classes("w-full")

            # --- 浏览器客户端 区域 ---
            with ui.column().classes("w-full gap-3") as client_section:
                ui.label("选择并上传客户端电脑的 CSV 文件").classes("text-xs font-bold text-slate-500 uppercase tracking-wide")
                ui.upload(
                    label="可拖拽客户端 CSV 文件至此处上传",
                    auto_upload=True,
                    multiple=True,
                    on_upload=on_file_upload
                ).classes("w-full border border-dashed border-slate-200 rounded-xl p-1").props("accept=.csv")
                
                ui.label("选择已上传的客户端文件").classes("text-xs font-bold text-slate-500 uppercase tracking-wide")
                client_file_select = ui.select(
                    options=["[全部已上传文件]"],
                    value="[全部已上传文件]",
                    label="待转换的已上传文件"
                ).classes("w-full")

            # 动态绑定显示隐藏
            server_section.bind_visibility_from(source_type, "value", value="server")
            client_section.bind_visibility_from(source_type, "value", value="client")
            
            # 进度指示器
            dialog_progress = ui.linear_progress(value=0.0, show_value=False).classes("w-full rounded-full")
            dialog_progress.visible = False
            dialog_status = ui.label("等待启动...").classes("text-xs text-slate-500 font-mono")
            dialog_status.visible = False
            
            # 下载链接容器
            csv_download_container = ui.row().classes("w-full justify-center gap-2 mt-2")
            csv_download_container.visible = False
            
            # 底部动作栏
            with ui.row().classes("w-full justify-end gap-2 mt-4"):
                ui.button("取消", on_click=csv_excel_dialog.close).props("flat").classes("text-slate-500 text-sm")
                ui.button("开始无损转换", on_click=run_select_conversion).classes("bg-indigo-600 hover:bg-indigo-700 text-white px-5 py-2.5 rounded-lg text-sm font-semibold shadow-sm")

    # --- PDF/Markdown 转换与对账对话框 (Dialog) ---
    with ui.dialog() as pdf_md_dialog:
        with ui.card().classes("w-[650px] p-6 gap-4 bg-white rounded-xl shadow-2xl"):
            with ui.row().classes("w-full justify-between items-center"):
                with ui.row().classes("items-center gap-2"):
                    ui.icon("description", size="1.8rem").classes("text-indigo-600")
                    ui.label("PDF 结单提取与对账控制台").classes("text-lg font-bold text-slate-800")
                ui.button(icon="close", on_click=pdf_md_dialog.close).props("flat round dense").classes("text-slate-400")
            
            ui.separator()
            
            ui.label("步骤 1：选择文件存储位置环境").classes("text-xs font-bold text-slate-500 uppercase tracking-wide")
            pdf_source_type = ui.toggle(
                options={
                    "server": "本机/Linux后端",
                    "client": "浏览器客户端"
                },
                value="server"
            ).classes("w-full")
            
            # --- 本机/后端服务器 区域 ---
            with ui.column().classes("w-full gap-3") as pdf_server_section:
                ui.label("本机 PDF 文件夹路径").classes("text-xs font-bold text-slate-500 uppercase tracking-wide")
                pdf_local_dir_input = ui.input(
                    label="输入 Linux 后端 PDF 所在的文件夹路径",
                    value=str(INPUT_PDF_DIR),
                    on_change=refresh_pdf_list
                ).classes("w-full")
                
                ui.label("选择待转换的 PDF").classes("text-xs font-bold text-slate-500 uppercase tracking-wide")
                pdf_file_select = ui.select(
                    options=["[全部PDF文件]"],
                    value="[全部PDF文件]",
                    label="待解析的 PDF 文件"
                ).classes("w-full")

            # --- 浏览器客户端 区域 ---
            with ui.column().classes("w-full gap-3") as pdf_client_section:
                ui.label("选择并上传客户端电脑的 PDF 账单").classes("text-xs font-bold text-slate-500 uppercase tracking-wide")
                ui.upload(
                    label="可拖拽客户端 PDF 文件至此处上传",
                    auto_upload=True,
                    multiple=True,
                    on_upload=on_pdf_upload
                ).classes("w-full border border-dashed border-slate-200 rounded-xl p-1").props("accept=.pdf")
                
                ui.label("选择已上传的 PDF 账单").classes("text-xs font-bold text-slate-500 uppercase tracking-wide")
                client_pdf_select = ui.select(
                    options=["[全部已上传PDF文件]"],
                    value="[全部已上传PDF文件]",
                    label="待解析的已上传 PDF"
                ).classes("w-full")

            # 动态绑定显示隐藏
            pdf_server_section.bind_visibility_from(pdf_source_type, "value", value="server")
            pdf_client_section.bind_visibility_from(pdf_source_type, "value", value="client")
            
            # 进度与状态
            pdf_progress = ui.linear_progress(value=0.0, show_value=False).classes("w-full rounded-full")
            pdf_progress.visible = False
            pdf_status = ui.label("等待启动...").classes("text-xs text-slate-500 font-mono")
            pdf_status.visible = False
            
            # 下载链接容器
            pdf_download_container = ui.row().classes("w-full justify-center gap-2 mt-2")
            pdf_download_container.visible = False
            
            # 滚动对账审计日志看板
            with ui.card().classes("w-full h-60 p-4 bg-slate-900 text-slate-100 rounded-xl overflow-y-auto") as pdf_log_board:
                ui.label("🔍 财务对账勾稽审计看板").classes("text-xs font-bold text-slate-400 border-b border-slate-800 pb-2 w-full")
                pdf_log_container = ui.column().classes("w-full gap-1.5 mt-2")
            pdf_log_board.visible = False

            # 底部动作栏
            with ui.row().classes("w-full justify-end gap-2 mt-4"):
                ui.button("取消", on_click=pdf_md_dialog.close).props("flat").classes("text-slate-500 text-sm")
                ui.button("开始解析与对账", on_click=run_pdf_conversion).classes("bg-indigo-600 hover:bg-indigo-700 text-white px-5 py-2.5 rounded-lg text-sm font-semibold shadow-sm")

    # --- PDF 查重與去密對話框 (Dialog) ---
    with ui.dialog() as pdf_dedup_dialog:
        with ui.card().classes("w-[700px] max-w-full p-6 gap-4 bg-white rounded-xl shadow-2xl"):
            with ui.row().classes("w-full justify-between items-center"):
                with ui.row().classes("items-center gap-2"):
                    ui.icon("find_in_page", size="1.8rem").classes("text-indigo-600")
                    ui.label("PDF 查重與去密編制控制台").classes("text-lg font-bold text-slate-800")
                ui.button(icon="close", on_click=pdf_dedup_dialog.close).props("flat round dense").classes("text-slate-400")
            
            ui.separator()
            
            ui.label("步驟 1：選擇檔案來源環境").classes("text-xs font-bold text-slate-500 uppercase tracking-wide")
            pdf_dedup_source_type = ui.toggle(
                options={
                    "server": "本機/Linux後端",
                    "client": "瀏覽器用戶端"
                },
                value="server"
            ).classes("w-full")
            
            ui.label("步驟 2：設定可能使用的解密密碼").classes("text-xs font-bold text-slate-500 uppercase tracking-wide")
            pdf_dedup_passwords_input = ui.input(
                label="解密密碼列表 (多個密碼請以英文逗號分隔，最多支援 3 個)",
                placeholder="例如: 123456, pwd_abc, mysecret"
            ).classes("w-full")
            
            # --- 本機/後端伺服器 區域 ---
            with ui.column().classes("w-full gap-3") as pdf_dedup_server_section:
                ui.label("本機輸入與輸出路徑").classes("text-xs font-bold text-slate-500 uppercase tracking-wide")
                pdf_dedup_local_dir_input = ui.input(
                    label="輸入 Linux 後端 PDF 所在的資料夾路徑",
                    value=str(INPUT_PDF_DIR),
                    on_change=refresh_pdf_dedup_list
                ).classes("w-full")
                
                pdf_dedup_out_dir_input = ui.input(
                    label="輸入去密後唯一件儲存路徑",
                    value=str(OUTPUT_PDF_DIR)
                ).classes("w-full")
                
                ui.label("選擇單一待處理檔案 (預設為全部件)").classes("text-xs font-bold text-slate-500 uppercase tracking-wide")
                pdf_dedup_file_select = ui.select(
                    options=["[全部PDF文件]"],
                    value="[全部PDF文件]",
                    label="待處理的 PDF 檔案"
                ).classes("w-full")

            # --- 瀏覽器用戶端 區域 ---
            with ui.column().classes("w-full gap-3") as pdf_dedup_client_section:
                ui.label("上傳用戶端 PDF 檔案").classes("text-xs font-bold text-slate-500 uppercase tracking-wide")
                ui.upload(
                    label="可拖曳 PDF 檔案至此處批次上傳",
                    auto_upload=True,
                    multiple=True,
                    on_upload=on_pdf_dedup_upload
                ).classes("w-full border border-dashed border-slate-200 rounded-xl p-1").props("accept=.pdf")
                
                ui.label("選擇已上傳檔案 (預設為全部件)").classes("text-xs font-bold text-slate-500 uppercase tracking-wide")
                client_pdf_dedup_select = ui.select(
                    options=["[全部已上傳PDF文件]"],
                    value="[全部已上傳PDF文件]",
                    label="待處理的已上傳 PDF"
                ).classes("w-full")

            # 動態綁定顯示隱藏
            pdf_dedup_server_section.bind_visibility_from(pdf_dedup_source_type, "value", value="server")
            pdf_dedup_client_section.bind_visibility_from(pdf_dedup_source_type, "value", value="client")
            
            # 進度與狀態
            pdf_dedup_progress = ui.linear_progress(value=0.0, show_value=False).classes("w-full rounded-full")
            pdf_dedup_progress.visible = False
            pdf_dedup_status = ui.label("等待啟動...").classes("text-xs text-slate-500 font-mono")
            pdf_dedup_status.visible = False
            
            # 下載連結容器
            pdf_dedup_download_container = ui.row().classes("w-full justify-center gap-2 mt-2")
            pdf_dedup_download_container.visible = False

            # 審計結果表格區
            with ui.column().classes("w-full gap-1.5 mt-2 overflow-x-auto") as pdf_dedup_results_container:
                ui.label("🔍 審計明細結果表").classes("text-xs font-bold text-slate-400 border-b border-slate-100 pb-2 w-full")
                columns = [
                    {'name': 'file_name', 'label': '檔案名稱', 'field': 'file_name', 'required': True, 'align': 'left'},
                    {'name': 'file_size_kb', 'label': '大小 (KB)', 'field': 'file_size_kb', 'sortable': True},
                    {'name': 'encryption_status', 'label': '加密狀態', 'field': 'encryption_status', 'align': 'center'},
                    {'name': 'sha256', 'label': 'SHA-256 (首12位)', 'field': 'sha256_short', 'align': 'left'},
                    {'name': 'status', 'label': '查重狀態', 'field': 'status', 'align': 'center'},
                    {'name': 'action', 'label': '處理動作', 'field': 'action', 'align': 'center'},
                    {'name': 'duplicate_of', 'label': '母本引用', 'field': 'duplicate_of', 'align': 'left'}
                ]
                pdf_dedup_table = ui.table(columns=columns, rows=[], row_key='file_name').classes("w-full max-h-60 text-xs shadow-sm rounded-lg")
            pdf_dedup_results_container.visible = False
            
            # 底部動作欄
            with ui.row().classes("w-full justify-end gap-2 mt-4"):
                ui.button("取消", on_click=pdf_dedup_dialog.close).props("flat").classes("text-slate-500 text-sm")
                ui.button("開始查重與去密", on_click=run_pdf_deduplication).classes("bg-indigo-600 hover:bg-indigo-700 text-white px-5 py-2.5 rounded-lg text-sm font-semibold shadow-sm")

    # --- 数据库连接测试对话框 (Dialog) ---
    with ui.dialog() as db_dialog:
        with ui.card().classes("w-[500px] p-6 gap-4 bg-white rounded-xl shadow-2xl"):
            with ui.row().classes("w-full justify-between items-center"):
                with ui.row().classes("items-center gap-2"):
                    ui.icon("dns", size="1.8rem").classes("text-indigo-600")
                    ui.label("数据库连接与状态控制台").classes("text-lg font-bold text-slate-800")
                ui.button(icon="close", on_click=db_dialog.close).props("flat round dense").classes("text-slate-400")
            
            ui.separator()
            
            ui.label("PostgreSQL 物理参数配置").classes("text-xs font-bold text-slate-500 uppercase tracking-wide")
            db_host_input = ui.input("主机地址 (Host)", value="localhost").classes("w-full")
            db_port_input = ui.input("端口号 (Port)", value="5432").classes("w-full")
            db_name_input = ui.input("数据库名称 (Database)", value="china-tax").classes("w-full")
            db_user_input = ui.input("用户名 (User)", value="postgres").classes("w-full")
            
            db_test_progress = ui.linear_progress(value=0.0, show_value=False).classes("w-full rounded-full")
            db_test_progress.visible = False
            db_test_status = ui.label("等待连接测试...").classes("text-xs text-slate-500 font-mono")
            
            async def perform_db_connection_test():
                db_test_progress.visible = True
                db_test_progress.set_value(0.5)
                db_test_status.set_text("正在测试与 PostgreSQL 远程端通信...")
                log_action(f"发起数据库物理连接测试: host={db_host_input.value}, database={db_name_input.value}")
                
                res = await db_config.test_pg_connection(
                    host=db_host_input.value,
                    dbname=db_name_input.value,
                    user=db_user_input.value,
                    port=int(db_port_input.value)
                )
                db_test_progress.set_value(1.0)
                db_test_status.set_text(res["message"])
                if res["success"]:
                    ui.notify(res["message"], type="positive", position="top")
                    log_action(f"数据库物理连接测试成功: {res['message']}")
                else:
                    ui.notify(res["message"], type="negative", position="top")
                    log_action(f"数据库物理连接测试失败: {res['message']}")
                
                await asyncio.sleep(2.5)
                db_test_progress.visible = False
            
            with ui.row().classes("w-full justify-end gap-2 mt-2"):
                ui.button("取消", on_click=db_dialog.close).props("flat").classes("text-slate-500 text-sm")
                ui.button("测试物理连接", on_click=perform_db_connection_test).classes("bg-indigo-600 hover:bg-indigo-700 text-white px-4 py-2 rounded-lg text-sm font-semibold shadow-sm")

    # --- 个税与企业税核算对话框 (Dialog) ---
    with ui.dialog() as calc_dialog:
        with ui.card().classes("w-[550px] p-6 gap-4 bg-white rounded-xl shadow-2xl"):
            with ui.row().classes("w-full justify-between items-center"):
                with ui.row().classes("items-center gap-2"):
                    ui.icon("calculate", size="1.8rem").classes("text-indigo-600")
                    ui.label("个税与企业所得税核算控制台").classes("text-lg font-bold text-slate-800")
                ui.button(icon="close", on_click=calc_dialog.close).props("flat round dense").classes("text-slate-400")
            
            ui.separator()
            
            calc_type = ui.toggle(
                options={"individual": "个人所得税 (Comprehensive)", "corporate": "企业所得税 (CIT)"},
                value="individual"
            ).classes("w-full")
            
            taxpayer_name_input = ui.input("纳税人名称", placeholder="请输入企业名或个人姓名").classes("w-full")
            taxpayer_id_input = ui.input("纳税人识别号 / 证件号", placeholder="请输入18位身份证号或社会信用代码").classes("w-full")
            
            # 个人所得税字段
            with ui.column().classes("w-full gap-3") as ind_fields:
                calc_income = ui.input("年收入总额 (元)", value="120000").classes("w-full")
                calc_deductions = ui.input("各项免税与专项附加扣除总额 (元)", value="24000").classes("w-full")
                
            # 企业所得税字段
            with ui.column().classes("w-full gap-3") as corp_fields:
                corp_profit = ui.input("纳税调整后所得 (利润额) (元)", value="500000").classes("w-full")
                corp_high_tech = ui.checkbox("属于国家重点扶持的高新技术企业").classes("mt-2")
                
            ind_fields.bind_visibility_from(calc_type, "value", value="individual")
            corp_fields.bind_visibility_from(calc_type, "value", value="corporate")
            
            # 结果显示面板
            results_box = ui.column().classes("w-full p-4 bg-slate-50 border border-slate-200 rounded-lg gap-2 mt-2")
            results_box.visible = False
            
            async def run_calculation():
                try:
                    name = taxpayer_name_input.value.strip()
                    tax_id = taxpayer_id_input.value.strip()
                    
                    if not name or not tax_id:
                        ui.notify("请填写纳税人名称与识别号", type="warning", position="top")
                        return
                        
                    # 强校验识别号
                    val_res = tax_val.validate_taxpayer_id(tax_id)
                    if not val_res["valid"]:
                        ui.notify(f"识别号 '{tax_id}' 不符合国家标准规范，请核对！", type="negative", position="top")
                        return
                    
                    results_box.clear()
                    t_type = calc_type.value
                    
                    if t_type == "individual":
                        inc = calc_income.value.strip()
                        ded = calc_deductions.value.strip()
                        res = tax_calc.calculate_individual_tax(inc, ded)
                        with results_box:
                            ui.label("📊 应纳税额综合核算结果").classes("text-xs font-bold text-slate-400 uppercase")
                            ui.label(f"申报人: {name} (类型: {val_res['type']})").classes("text-sm text-slate-700")
                            ui.label(f"年应纳税所得额: ¥{res['taxable_income']}").classes("text-sm text-slate-700")
                            ui.label(f"适用所得税率区间: {res['tax_rate']} (速算扣除数: ¥{res['quick_deduction']})").classes("text-sm text-slate-700")
                            ui.label(f"应缴个人所得税款: ¥{res['tax_payable']}").classes("text-lg font-bold text-indigo-600")
                    else:
                        prof = corp_profit.value.strip()
                        tech = corp_high_tech.value
                        res = tax_calc.calculate_corporate_tax(prof, tech)
                        with results_box:
                            ui.label("📊 企业所得税综合核算结果").classes("text-xs font-bold text-slate-400 uppercase")
                            ui.label(f"申报企业: {name} (类型: {val_res['type']})").classes("text-sm text-slate-700")
                            ui.label(f"享受税收优惠分类: {res['company_type']}").classes("text-sm text-slate-700")
                            ui.label(f"适用企业所得税率: {res['tax_rate']}").classes("text-sm text-slate-700")
                            ui.label(f"应纳税所得额(调整后所得): ¥{res['taxable_income']}").classes("text-sm text-slate-700")
                            ui.label(f"应交企业所得税款: ¥{res['tax_payable']}").classes("text-lg font-bold text-indigo-600")
                            
                    async def save_record():
                        try:
                            conn = db_config.get_connection()
                            cursor = conn.cursor()
                            timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
                            
                            income_val = calc_income.value if t_type == "individual" else corp_profit.value
                            deduct_val = calc_deductions.value if t_type == "individual" else "0.00"
                            
                            cursor.execute(
                                "INSERT INTO tax_records (taxpayer_name, credit_code, income, deductions, tax_payable, tax_type, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                                (name, tax_id, income_val, deduct_val, res["tax_payable"], t_type, timestamp)
                            )
                            conn.commit()
                            conn.close()
                            ui.notify("申报记录保存成功，已同步落库！", type="positive", position="top")
                            log_action(f"保存计算历史数据至 tax_records: name={name}, tax_payable={res['tax_payable']}")
                            results_box.visible = False
                        except Exception as save_err:
                            ui.notify(f"数据入库失败: {str(save_err)}", type="negative", position="top")
                            
                    with results_box:
                        ui.button("💾 将核算数据保存入库", on_click=save_record).classes("w-full bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg py-2 mt-2 text-sm font-semibold")
                        
                    results_box.visible = True
                    log_action(f"个税/企业税核算成功: 纳税人={name}, 应纳税={res['tax_payable']}")
                except Exception as calc_err:
                    ui.notify(f"核算失败，请核对输入数值: {str(calc_err)}", type="negative", position="top")
            
            with ui.row().classes("w-full justify-end gap-2 mt-2"):
                ui.button("取消", on_click=calc_dialog.close).props("flat").classes("text-slate-500 text-sm")
                ui.button("开始核算", on_click=run_calculation).classes("bg-indigo-600 hover:bg-indigo-700 text-white px-4 py-2 rounded-lg text-sm font-semibold shadow-sm")

    # --- 数据合法性国标审计校验对话框 (Dialog) ---
    with ui.dialog() as val_dialog:
        with ui.card().classes("w-[780px] max-w-full p-6 gap-4 bg-white rounded-xl shadow-2xl"):
            with ui.row().classes("w-full justify-between items-center"):
                with ui.row().classes("items-center gap-2"):
                    ui.icon("verified_user", size="1.8rem").classes("text-indigo-600")
                    ui.label("申报数据合法性校验与深度审计控制台").classes("text-lg font-bold text-slate-800")
                ui.button(icon="close", on_click=val_dialog.close).props("flat round dense").classes("text-slate-400")
            
            ui.separator()
            
            ui.label("审计说明：提取目前本地申报记录库中的全部信息，进行国标校检（GB32100企业信用代码、GB11643身份证校验算法）与应纳税额勾稽关系校验。").classes("text-xs text-slate-500")
            
            columns = [
                {"name": "taxpayer_name", "label": "纳税人姓名/企业名", "field": "taxpayer_name", "align": "left"},
                {"name": "credit_code", "label": "信用代码/证件号", "field": "credit_code", "align": "left"},
                {"name": "income", "label": "申报收入金额", "field": "income", "sortable": True},
                {"name": "tax_payable", "label": "已算税额 (元)", "field": "tax_payable", "sortable": True},
                {"name": "status", "label": "国标审计状态", "field": "status", "align": "center"},
                {"name": "details", "label": "详细审计结果说明", "field": "details", "align": "left"}
            ]
            
            val_table = ui.table(columns=columns, rows=[], row_key="id").classes("w-full max-h-60 text-xs shadow-sm rounded-lg")
            
            async def run_data_validation():
                try:
                    conn = db_config.get_connection()
                    cursor = conn.cursor()
                    cursor.execute("SELECT id, taxpayer_name, credit_code, income, deductions, tax_payable, tax_type FROM tax_records")
                    rows = cursor.fetchall()
                    conn.close()
                    
                    if not rows:
                        ui.notify("申报历史数据库中暂无记录！", type="warning", position="top")
                        return
                    
                    validated_rows = []
                    valid_cnt = 0
                    invalid_cnt = 0
                    
                    for row in rows:
                        rid, name, credit_code, income, deductions, tax_payable, tax_type = row
                        
                        val_res = tax_val.validate_declaration_data(name, credit_code, income, deductions)
                        
                        if val_res["is_valid"]:
                            status = "🟢 审核通过"
                            details = f"证件合规 ({val_res['type']})"
                            valid_cnt += 1
                        else:
                            status = "🔴 审计异常"
                            details = " | ".join(val_res["errors"])
                            invalid_cnt += 1
                            
                        validated_rows.append({
                            "id": rid,
                            "taxpayer_name": name,
                            "credit_code": credit_code,
                            "income": f"¥{float(income):,.2f}",
                            "tax_payable": f"¥{float(tax_payable):,.2f}",
                            "status": status,
                            "details": details
                        })
                        
                    val_table.rows = validated_rows
                    val_table.update()
                    ui.notify(f"全量审计校验完成！通过: {valid_cnt} 件，发现异常: {invalid_cnt} 件", type="positive" if invalid_cnt == 0 else "warning", position="top")
                    log_action(f"全库数据审计校验: 总数={len(rows)}, 合格={valid_cnt}, 异常={invalid_cnt}")
                except Exception as err:
                    ui.notify(f"数据读取校验失败: {str(err)}", type="negative", position="top")
            
            async def clear_all_records():
                try:
                    conn = db_config.get_connection()
                    cursor = conn.cursor()
                    cursor.execute("DELETE FROM tax_records")
                    conn.commit()
                    conn.close()
                    val_table.rows = []
                    val_table.update()
                    ui.notify("申报库历史数据已清空！", type="positive", position="top")
                    log_action("用户触发清空 tax_records 表全部记录")
                except Exception as err:
                    ui.notify(f"清空失败: {str(err)}", type="negative", position="top")
            
            with ui.row().classes("w-full justify-between mt-2"):
                ui.button("🧹 清空数据库记录", on_click=clear_all_records).classes("bg-rose-600 hover:bg-rose-700 text-white px-3 py-1.5 rounded-lg text-sm")
                with ui.row().classes("gap-2"):
                    ui.button("关闭", on_click=val_dialog.close).props("flat").classes("text-slate-500 text-sm")
                    ui.button("开始全量国标校验", on_click=run_data_validation).classes("bg-indigo-600 hover:bg-indigo-700 text-white px-4 py-2 rounded-lg text-sm font-semibold")

    # --- 申报表一键导出与打包对话框 (Dialog) ---
    with ui.dialog() as exp_dialog:
        with ui.card().classes("w-[500px] p-6 gap-4 bg-white rounded-xl shadow-2xl"):
            with ui.row().classes("w-full justify-between items-center"):
                with ui.row().classes("items-center gap-2"):
                    ui.icon("cloud_download", size="1.8rem").classes("text-indigo-600")
                    ui.label("国家标准申报表导出中心").classes("text-lg font-bold text-slate-800")
                ui.button(icon="close", on_click=exp_dialog.close).props("flat round dense").classes("text-slate-400")
            
            ui.separator()
            
            ui.label("系统将打包当前数据库中所有审计通过的报税数据，自动按个税和企业所得税分流生成 XLSX 表单，并执行 ZIP 打包后供一键下载。").classes("text-xs text-slate-500")
            
            exp_download_container = ui.row().classes("w-full justify-center gap-2 mt-2")
            exp_download_container.visible = False
            
            async def run_export_and_pack():
                exp_download_container.clear()
                exp_download_container.visible = False
                
                try:
                    conn = db_config.get_connection()
                    cursor = conn.cursor()
                    cursor.execute("SELECT taxpayer_name, credit_code, income, deductions, tax_payable, tax_type, created_at FROM tax_records")
                    rows = cursor.fetchall()
                    conn.close()
                    
                    if not rows:
                        ui.notify("申报历史数据库中暂无记录，无法导出！", type="warning", position="top")
                        return
                    
                    import pandas as pd
                    ind_data = []
                    corp_data = []
                    
                    for name, credit_code, income, deductions, tax_payable, tax_type, created_at in rows:
                        val_res = tax_val.validate_declaration_data(name, credit_code, income, deductions)
                        if not val_res["is_valid"]:
                            continue # 过滤未通过审计的异常脏数据
                            
                        record = {
                            "纳税人名称/单位": name,
                            "信用代码/身份证": credit_code,
                            "收入所得总额": float(income),
                            "允许扣除总额": float(deductions),
                            "核算应纳税额": float(tax_payable),
                            "税收分类": "个人所得税" if tax_type == "individual" else "企业所得税",
                            "核算时间": created_at
                        }
                        if tax_type == "individual":
                            ind_data.append(record)
                        else:
                            corp_data.append(record)
                    
                    OUTPUT_EXCEL_DIR.mkdir(parents=True, exist_ok=True)
                    exported_files = []
                    
                    if ind_data:
                        ind_path = OUTPUT_EXCEL_DIR / "individual_declarations.xlsx"
                        pd.DataFrame(ind_data).to_excel(ind_path, index=False)
                        exported_files.append(ind_path)
                    
                    if corp_data:
                        corp_path = OUTPUT_EXCEL_DIR / "corporate_declarations.xlsx"
                        pd.DataFrame(corp_data).to_excel(corp_path, index=False)
                        exported_files.append(corp_path)
                        
                    if not exported_files:
                        ui.notify("没有校验通过的数据，未生成任何申报文件！", type="negative", position="top")
                        return
                    
                    zip_path = OUTPUT_EXCEL_DIR / "declaration_reports.zip"
                    if zip_path.exists():
                        zip_path.unlink()
                        
                    await asyncio.to_thread(create_zip_archive, exported_files, zip_path)
                    
                    if zip_path.exists():
                        rel_zip = zip_path.relative_to(BASE_DIR)
                        zip_url = f"/download/{rel_zip.as_posix()}"
                        with exp_download_container:
                            ui.link("📦 一键下载国家标准申报表 (ZIP 包)", zip_url, new_tab=True).classes(
                                "bg-amber-600 hover:bg-amber-700 text-white text-xs px-4 py-2 rounded-lg font-semibold shadow-sm no-underline font-bold"
                            )
                        exp_download_container.visible = True
                        ui.notify("申报表打包生成成功！", type="positive", position="top")
                        log_action(f"一键打包导出 XLSX 申报成果完成: {zip_path.name}")
                except Exception as err:
                    ui.notify(f"导出打包失败: {str(err)}", type="negative", position="top")
            
            with ui.row().classes("w-full justify-end gap-2 mt-2"):
                ui.button("取消", on_click=exp_dialog.close).props("flat").classes("text-slate-500 text-sm")
                ui.button("开始打包导出", on_click=run_export_and_pack).classes("bg-indigo-600 hover:bg-indigo-700 text-white px-4 py-2 rounded-lg text-sm font-semibold shadow-sm")

    # --- 历史成果文件归档对话框 (Dialog) ---
    with ui.dialog() as archive_dialog:
        with ui.card().classes("w-[720px] max-w-full p-6 gap-4 bg-white rounded-xl shadow-2xl"):
            with ui.row().classes("w-full justify-between items-center"):
                with ui.row().classes("items-center gap-2"):
                    ui.icon("archive", size="1.8rem").classes("text-indigo-600")
                    ui.label("国家标准税务历史档案库控制面板").classes("text-lg font-bold text-slate-800")
                ui.button(icon="close", on_click=archive_dialog.close).props("flat round dense").classes("text-slate-400")
            
            ui.separator()
            
            ui.label("历史归档说明：可一键将当前所有的核算记录冻结打包，并在本地历史归档表 history_archives 中登记备案。").classes("text-xs text-slate-500")
            
            columns = [
                {"name": "archive_name", "label": "归档包文件名", "field": "archive_name", "align": "left"},
                {"name": "operator", "label": "归档负责人", "field": "operator", "align": "center"},
                {"name": "created_at", "label": "归档时间", "field": "created_at", "align": "center"}
            ]
            
            archive_table = ui.table(columns=columns, rows=[], row_key="id", selection="single").classes("w-full max-h-60 text-xs shadow-sm rounded-lg")
            
            def download_selected_archive():
                selected = archive_table.selected
                if not selected:
                    ui.notify("请在下方列表中点击勾选一条历史归档记录进行下载！", type="warning", position="top")
                    return
                row = selected[0]
                if row["download_url"] != "#":
                    ui.download(row["download_url"], filename=row["archive_name"])
                    ui.notify(f"开始下载归档文件: {row['archive_name']}", type="info", position="top")
                    log_action(f"下载历史归档包: {row['archive_name']}")
                else:
                    ui.notify("对应的归档物理文件不存在，可能已被清理！", type="negative", position="top")
            
            async def do_new_archive():
                try:
                    conn = db_config.get_connection()
                    cursor = conn.cursor()
                    cursor.execute("SELECT count(*) FROM tax_records")
                    cnt = cursor.fetchone()[0]
                    
                    if cnt == 0:
                        ui.notify("当前申报数据为空，无法执行封存归档！", type="warning", position="top")
                        conn.close()
                        return
                    
                    import pandas as pd
                    cursor.execute("SELECT taxpayer_name, credit_code, income, deductions, tax_payable, tax_type, created_at FROM tax_records")
                    rows = cursor.fetchall()
                    
                    archive_dir = OUTPUT_DIR / "archives"
                    archive_dir.mkdir(parents=True, exist_ok=True)
                    
                    timestamp_file = time.strftime("%Y%m%d_%H%M%S")
                    excel_path = archive_dir / f"tax_backup_{timestamp_file}.xlsx"
                    
                    df = pd.DataFrame([{
                        "纳税人姓名/企业名": r[0], "信用代码/证件": r[1], "年所得收入": float(r[2]),
                        "扣除项": float(r[3]), "核定税额": float(r[4]), "税种": r[5], "时间": r[6]
                    } for r in rows])
                    df.to_excel(excel_path, index=False)
                    
                    zip_name = f"archive_batch_{timestamp_file}.zip"
                    zip_file_path = archive_dir / zip_name
                    
                    await asyncio.to_thread(create_zip_archive, [excel_path], zip_file_path)
                    
                    if excel_path.exists():
                        excel_path.unlink() # 清理临时中转 excel
                        
                    created_at = time.strftime("%Y-%m-%d %H:%M:%S")
                    cursor.execute(
                        "INSERT INTO history_archives (archive_name, file_path, operator, created_at) VALUES (?, ?, ?, ?)",
                        (zip_name, str(zip_file_path), "智能税务终端", created_at)
                    )
                    conn.commit()
                    conn.close()
                    
                    ui.notify(f"归档封包 {zip_name} 建立成功并落盘存档！", type="positive", position="top")
                    log_action(f"建立归档封包并写入 history_archives: {zip_name}")
                    await refresh_archive_table()
                except Exception as err:
                    ui.notify(f"建立归档失败: {str(err)}", type="negative", position="top")
                    
            with ui.row().classes("w-full justify-between mt-2"):
                with ui.row().classes("gap-2"):
                    ui.button("📦 封存归档当前数据", on_click=do_new_archive).classes("bg-indigo-600 hover:bg-indigo-700 text-white px-3 py-1.5 rounded-lg text-sm")
                    ui.button("📥 下载选中的历史归档", on_click=download_selected_archive).classes("bg-emerald-600 hover:bg-emerald-700 text-white px-3 py-1.5 rounded-lg text-sm")
                ui.button("关闭", on_click=archive_dialog.close).props("flat").classes("text-slate-500 text-sm")

    # --- 国家最新标准税率参数配置对话框 (Dialog) ---
    with ui.dialog() as config_view_dialog:
        with ui.card().classes("w-[650px] p-6 gap-4 bg-white rounded-xl shadow-2xl"):
            with ui.row().classes("w-full justify-between items-center"):
                with ui.row().classes("items-center gap-2"):
                    ui.icon("settings_suggest", size="1.8rem").classes("text-indigo-600")
                    ui.label("国家标准所得税计算参数与税率规范").classes("text-lg font-bold text-slate-800")
                ui.button(icon="close", on_click=config_view_dialog.close).props("flat round dense").classes("text-slate-400")
            
            ui.separator()
            
            with ui.tabs().classes("w-full") as tax_tabs:
                ind_tab = ui.tab("个人所得税综合所得税率")
                corp_tab = ui.tab("企业所得税分类税率")
                
            with ui.tab_panels(tax_tabs, value=ind_tab).classes("w-full"):
                with ui.tab_panel(ind_tab).classes("gap-3"):
                    ui.label("个税起征点（综合所得免征额）：60,000 元/年 (5,000 元/月)").classes("text-xs font-bold text-slate-500 uppercase tracking-wide")
                    
                    brackets_data = [
                        {"range": "全年应纳税所得额 <= 36,000 元的部分", "rate": "3%", "deduction": "¥0.00"},
                        {"range": "超过 36,000 元至 144,000 元的部分", "rate": "10%", "deduction": "¥2,520.00"},
                        {"range": "超过 144,000 元至 300,000 元的部分", "rate": "20%", "deduction": "¥16,920.00"},
                        {"range": "超过 300,000 元至 420,000 元的部分", "rate": "25%", "deduction": "¥31,920.00"},
                        {"range": "超过 420,000 元至 660,000 元的部分", "rate": "30%", "deduction": "¥52,920.00"},
                        {"range": "超过 660,000 元至 960,000 元的部分", "rate": "35%", "deduction": "¥85,920.00"},
                        {"range": "超过 960,000 元的部分", "rate": "45%", "deduction": "¥181,920.00"},
                    ]
                    brackets_cols = [
                        {"name": "range", "label": "全年应纳税所得额级距", "field": "range", "align": "left"},
                        {"name": "rate", "label": "税率", "field": "rate", "align": "center"},
                        {"name": "deduction", "label": "速算扣除数", "field": "deduction", "align": "right"}
                    ]
                    ui.table(columns=brackets_cols, rows=brackets_data, row_key="range").classes("w-full text-xs")
                    
                with ui.tab_panel(corp_tab).classes("gap-3"):
                    ui.label("中华人民共和国企业所得税分类税率与小微企业判定").classes("text-xs font-bold text-slate-500 uppercase tracking-wide")
                    
                    corp_data = [
                        {"rule": "标准普通所得税率企业", "rate": "25%"},
                        {"rule": "国家级重点高新技术企业认证优惠", "rate": "15%"},
                        {"rule": "小型微利企业税收减免优惠 (应纳税所得额 <= 300万)", "rate": "5% (应纳税所得额减按25%后以20%税率计税)"}
                    ]
                    corp_cols = [
                        {"name": "rule", "label": "企业所得税分类适用条件", "field": "rule", "align": "left"},
                        {"name": "rate", "label": "实际所得税负率", "field": "rate", "align": "center"}
                    ]
                    ui.table(columns=corp_cols, rows=corp_data, row_key="rule").classes("w-full text-xs")
                    
            with ui.row().classes("w-full justify-end mt-2"):
                ui.button("关闭", on_click=config_view_dialog.close).props("flat").classes("text-slate-500 text-sm")

    # --- 系统运行底层日志对话框 (Dialog) ---
    with ui.dialog() as system_logs_dialog:
        with ui.card().classes("w-[650px] p-6 gap-4 bg-white rounded-xl shadow-2xl"):
            with ui.row().classes("w-full justify-between items-center"):
                with ui.row().classes("items-center gap-2"):
                    ui.icon("receipt_long", size="1.8rem").classes("text-indigo-600")
                    ui.label("系统审计与运行监控监控日志").classes("text-lg font-bold text-slate-800")
                ui.button(icon="close", on_click=system_logs_dialog.close).props("flat round dense").classes("text-slate-400")
            
            ui.separator()
            
            with ui.card().classes("w-full h-80 p-4 bg-slate-900 text-slate-100 rounded-xl overflow-y-auto") as log_board:
                system_logs_container = ui.column().classes("w-full gap-1 mt-1")
                sys_log_board = log_board
                
            with ui.row().classes("w-full justify-end mt-2"):
                ui.button("关闭", on_click=system_logs_dialog.close).props("flat").classes("text-slate-500 text-sm")

    # --- 模块 11: 平仓交易整理对话框 (Dialog) ---
    with ui.dialog() as md_closing_dialog:
        with ui.card().classes("w-[600px] p-6 gap-4 bg-white rounded-xl shadow-2xl"):
            with ui.row().classes("w-full justify-between items-center"):
                with ui.row().classes("items-center gap-2"):
                    ui.icon("filter_alt", size="1.8rem").classes("text-indigo-600")
                    ui.label("平仓成交数据整理控制台").classes("text-lg font-bold text-slate-800")
                ui.button(icon="close", on_click=md_closing_dialog.close).props("flat round dense").classes("text-slate-400")
            
            ui.separator()
            
            ui.label("步骤 1：设定整理交易的时间段 (选填，留空代表不限制)").classes("text-xs font-bold text-slate-500 uppercase tracking-wide")
            with ui.row().classes("w-full gap-4"):
                md_closing_start_date = ui.input(
                    label="开始日期 (格式: YYYY-MM-DD)",
                    placeholder="例如: 2026-01-01"
                ).classes("flex-1")
                md_closing_end_date = ui.input(
                    label="结束日期 (格式: YYYY-MM-DD)",
                    placeholder="例如: 2026-06-30"
                ).classes("flex-1")
                
            ui.label("步骤 2：上传包含交易流水的 Markdown (.md) 文件").classes("text-xs font-bold text-slate-500 uppercase tracking-wide")
            ui.upload(
                label="拖拽或选择模块 3 转换出的 Markdown 成果文件",
                auto_upload=True,
                multiple=True,
                on_upload=on_md_upload
            ).classes("w-full border border-dashed border-slate-200 rounded-xl p-1").props("accept=.md")
            
            # 进度与状态
            md_closing_progress = ui.linear_progress(value=0.0, show_value=False).classes("w-full rounded-full")
            md_closing_progress.visible = False
            md_closing_status = ui.label("等待启动...").classes("text-xs text-slate-500 font-mono")
            md_closing_status.visible = False
            
            # 下载容器 (报告 + 单一 ZIP 文件)
            md_closing_download_container = ui.row().classes("w-full justify-center gap-2 mt-2")
            md_closing_download_container.visible = False
            
            # 底部动作栏
            with ui.row().classes("w-full justify-end gap-2 mt-4"):
                ui.button("取消", on_click=md_closing_dialog.close).props("flat").classes("text-slate-500 text-sm")
                ui.button("开始提取与整理", on_click=run_md_closing_organization).classes("bg-indigo-600 hover:bg-indigo-700 text-white px-5 py-2.5 rounded-lg text-sm font-semibold shadow-sm")

    # 頁面載入時強制彈窗輸入機構名稱
    ui.timer(0.1, prompt_bank_name, once=True)

# 启动服务

# 启动服务
if __name__ in {"__main__", "__mp_main__"}:
    ui.run(title="China-Tax 智能税务自动化申报 system", port=28888, reload=True)
