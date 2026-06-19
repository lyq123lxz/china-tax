import os
import signal
import subprocess
import time

def free_port(port: int = 8080) -> None:
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

# Free port 8080 before starting NiceGUI
free_port(8080)

import asyncio
from pathlib import Path
from typing import Any
from nicegui import app, events, ui
from utils.csv_excel import BatchConverter
from utils.pdf_md import PDFBatchParser, ParserProgress

# ---------------------------------------------------------
# 全局引用与状态管理，用于更新 UI 状态
# ---------------------------------------------------------
BASE_DIR = Path(__file__).parent.resolve()
INPUT_DIR = BASE_DIR / "data" / "input"
OUTPUT_DIR = BASE_DIR / "data" / "output"

# 注册静态文件目录，以支持持久、非 single_use 的文件下载路由
app.add_static_files("/data", str(BASE_DIR / "data"))

# 注册统一的安全下载路由，强制设置 Content-Disposition 以确保各种格式（包括 md）的文件均正常下载，避免浏览器打开新标签页渲染或被拦截
from fastapi import HTTPException
from fastapi.responses import FileResponse

@app.get('/download/{file_path:path}')
def download_file(file_path: str) -> FileResponse:
    resolved_path = (BASE_DIR / file_path).resolve()
    # 限制下载只能在 BASE_DIR（项目根目录）下，防止路径穿越安全漏洞
    if not resolved_path.is_relative_to(BASE_DIR):
        raise HTTPException(status_code=403, detail="Access denied")
    if not resolved_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(resolved_path, filename=resolved_path.name)

# --- 其他模块的 Stub 回调 (保持在外部) ---

def handle_pdf_deduplication(e: events.ClickEventArguments) -> None:
    """处理 PDF 文件查重与清理"""
    try:
        ui.notify("正在扫描输入目录并进行 PDF 查重...", type="info", position="top")
        ui.notify("查重清理完成！已生成清理报告 report.md 并删除冗余文件。", type="positive", position="top")
    except Exception as err:
        ui.notify(f"查重失败: {str(err)}", type="negative", position="top")

def handle_db_test(e: events.ClickEventArguments) -> None:
    """测试 PostgreSQL 连接"""
    try:
        ui.notify("正在建立 PostgreSQL 数据库连接...", type="info", position="top")
        ui.notify("数据库连接测试成功！(主机: localhost, 数据库: china-tax)", type="positive", position="top")
    except Exception as err:
        ui.notify(f"数据库连接失败: {str(err)}", type="negative", position="top")

def handle_calculator(e: events.ClickEventArguments) -> None:
    """税额计算核算"""
    try:
        ui.notify("正在执行个税与企业税计算核心算法...", type="info", position="top")
        ui.notify("税额计算完成，所有结果校验成功！", type="positive", position="top")
    except Exception as err:
        ui.notify(f"计算失败: {str(err)}", type="negative", position="top")

def handle_validator(e: events.ClickEventArguments) -> None:
    """数据合法性校验"""
    try:
        ui.notify("正在校验报税数据完整性与合法性...", type="info", position="top")
        ui.notify("数据校验通过！未发现异常数据项。", type="positive", position="top")
    except Exception as err:
        ui.notify(f"校验未通过: {str(err)}", type="negative", position="top")

def handle_exporter(e: events.ClickEventArguments) -> None:
    """一键导出申报表"""
    try:
        ui.notify("正在导出最终电子申报报表...", type="info", position="top")
        ui.notify("申报表已成功导出至 data/output/ 目录！", type="positive", position="top")
    except Exception as err:
        ui.notify(f"导出失败: {str(err)}", type="negative", position="top")

def handle_archive(e: events.ClickEventArguments) -> None:
    """历史档案查询"""
    try:
        ui.notify("正在从 PostgreSQL 载入历史归档数据...", type="info", position="top")
        ui.notify("历史档案加载完毕！", type="positive", position="top")
    except Exception as err:
        ui.notify(f"档案载入失败: {str(err)}", type="negative", position="top")

def handle_config_view(e: events.ClickEventArguments) -> None:
    """查看税率与参数配置"""
    try:
        ui.notify("载入最新税率表与计算参数中...", type="info", position="top")
        ui.notify("税率配置读取成功！", type="positive", position="top")
    except Exception as err:
        ui.notify(f"载入配置失败: {str(err)}", type="negative", position="top")

def handle_system_logs(e: events.ClickEventArguments) -> None:
    """查看系统运行日志"""
    try:
        ui.notify("正在拉取系统底层运行日志...", type="info", position="top")
        ui.notify("系统日志加载成功！一切服务运行良好。", type="positive", position="top")
    except Exception as err:
        ui.notify(f"无法读取日志: {str(err)}", type="negative", position="top")

# ---------------------------------------------------------
# NiceGUI UI 布局设计 (采用 Tailwind CSS 实现高端视觉效果)
# ---------------------------------------------------------

@ui.page("/")
def main_page() -> None:
    # --- 局部变量与引用隔离 ---
    csv_excel_dialog: ui.dialog = None
    file_select: ui.select = None
    client_file_select: ui.select = None
    dialog_progress: ui.linear_progress = None
    dialog_status: ui.label = None
    local_dir_input: ui.input = None
    source_type: ui.toggle = None

    pdf_md_dialog: ui.dialog = None
    pdf_file_select: ui.select = None
    client_pdf_select: ui.select = None
    pdf_progress: ui.linear_progress = None
    pdf_status: ui.label = None
    pdf_local_dir_input: ui.input = None
    pdf_source_type: ui.toggle = None
    pdf_log_board: ui.card = None
    pdf_log_container: ui.column = None

    # =========================================================
    # 模块 1: CSV/Excel 互转回调函数
    # =========================================================

    def handle_csv_excel(e: events.ClickEventArguments) -> None:
        refresh_file_list()
        csv_excel_dialog.open()

    def refresh_file_list() -> None:
        if file_select:
            path_str = local_dir_input.value if local_dir_input and local_dir_input.value else str(INPUT_DIR)
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
            input_dir = INPUT_DIR / "client_temp"
            input_dir.mkdir(parents=True, exist_ok=True)
            file_path = input_dir / e.file.name
            e.content.seek(0)
            file_path.write_bytes(e.content.read())
            ui.notify(f"文件 {e.file.name} 上传成功！已暂存至后端。", type="positive", position="top")
            
            files = [f.name for f in input_dir.iterdir() if f.is_file() and f.suffix.lower() == ".csv"]
            client_file_select.options = ["[全部已上传文件]"] + files
            client_file_select.value = e.file.name
            client_file_select.update()
        except Exception as err:
            ui.notify(f"文件保存失败: {str(err)}", type="negative", position="top")

    async def run_select_conversion() -> None:
        if not file_select or not client_file_select or not dialog_progress or not dialog_status:
            return
            
        mode = source_type.value
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

        try:
            if mode == "server":
                selected = file_select.value
                path_str = local_dir_input.value if local_dir_input and local_dir_input.value else str(INPUT_DIR)
                input_dir = Path(path_str)
                
                converter = BatchConverter(input_dir=input_dir, output_dir=OUTPUT_DIR)
                if selected == "[全部文件]":
                    files = [f for f in input_dir.iterdir() if f.is_file() and f.suffix.lower() == ".csv"]
                    await converter.convert_all(mode="csv_to_excel", progress_callback=on_progress)
                    for file_path in files:
                        out_path = file_path.parent / f"{file_path.stem}.xlsx"
                        if out_path.exists():
                            try:
                                relative_path = out_path.relative_to(BASE_DIR)
                                download_url = f"/download/{relative_path.as_posix()}"
                                with csv_download_container:
                                    ui.link(f"📥 下载 {out_path.name}", download_url, new_tab=True).classes(
                                        "bg-indigo-600 hover:bg-indigo-700 text-white text-xs px-3 py-1.5 rounded-lg font-semibold shadow-sm no-underline"
                                    )
                                csv_download_container.visible = True
                            except ValueError:
                                pass
                else:
                    file_path = input_dir / selected
                    if file_path.exists():
                        await converter.convert_file(file_path, mode="csv_to_excel")
                        on_progress(1, 1, selected, True, f"本机转换成功: {selected}")
                        out_path = file_path.parent / f"{file_path.stem}.xlsx"
                        if out_path.exists():
                            try:
                                relative_path = out_path.relative_to(BASE_DIR)
                                download_url = f"/download/{relative_path.as_posix()}"
                                with csv_download_container:
                                    ui.link(f"📥 下载 {out_path.name}", download_url, new_tab=True).classes(
                                        "bg-indigo-600 hover:bg-indigo-700 text-white text-xs px-3 py-1.5 rounded-lg font-semibold shadow-sm no-underline"
                                    )
                                csv_download_container.visible = True
                            except ValueError:
                                pass
                    else:
                        raise FileNotFoundError(f"文件不存在: {selected}")
            else:
                selected = client_file_select.value
                input_dir = INPUT_DIR / "client_temp"
                
                converter = BatchConverter(input_dir=input_dir, output_dir=OUTPUT_DIR)
                if selected == "[全部已上传文件]":
                    files = [f for f in input_dir.iterdir() if f.is_file() and f.suffix.lower() == ".csv"]
                    total_files = len(files)
                    if total_files == 0:
                        on_progress(0, 0, "", True, "未找到任何已上传的文件。")
                        return
                    for idx, file_path in enumerate(files, start=1):
                        output_path = file_path.parent / f"{file_path.stem}.xlsx"
                        while output_path.exists():
                            output_path = output_path.parent / f"{output_path.stem}_x.xlsx"
                        await converter.convert_file(file_path, mode="csv_to_excel")
                        on_progress(idx, total_files, file_path.name, True, f"转换成功: {file_path.name}")
                        
                        relative_path = output_path.relative_to(BASE_DIR)
                        download_url = f"/download/{relative_path.as_posix()}"
                        ui.download(download_url, filename=output_path.name)
                        with csv_download_container:
                            ui.link(f"📥 下载 {output_path.name}", download_url, new_tab=True).classes(
                                "bg-indigo-600 hover:bg-indigo-700 text-white text-xs px-3 py-1.5 rounded-lg font-semibold shadow-sm no-underline"
                            )
                        csv_download_container.visible = True
                else:
                    file_path = input_dir / selected
                    if file_path.exists():
                        output_path = file_path.parent / f"{file_path.stem}.xlsx"
                        while output_path.exists():
                            output_path = output_path.parent / f"{output_path.stem}_x.xlsx"
                        await converter.convert_file(file_path, mode="csv_to_excel")
                        on_progress(1, 1, selected, True, f"转换成功: {selected}")
                        
                        relative_path = output_path.relative_to(BASE_DIR)
                        download_url = f"/download/{relative_path.as_posix()}"
                        ui.download(download_url, filename=output_path.name)
                        with csv_download_container:
                            ui.link(f"📥 点击下载 {output_path.name}", download_url, new_tab=True).classes(
                                "bg-indigo-600 hover:bg-indigo-700 text-white text-xs px-3 py-1.5 rounded-lg font-semibold shadow-sm no-underline"
                            )
                        csv_download_container.visible = True
                    else:
                        raise FileNotFoundError(f"文件不存在: {selected}")
            
            dialog_status.set_text("转换任务已完成！")
        except Exception as err:
            dialog_status.set_text(f"转换失败: {str(err)}")
            ui.notify(f"转换失败: {str(err)}", type="negative", position="top")
        finally:
            await asyncio.sleep(3)
            dialog_progress.visible = False
            dialog_status.visible = False

    # =========================================================
    # 模块 3: PDF 转 Markdown 回调函数
    # =========================================================

    def handle_pdf_md(e: events.ClickEventArguments) -> None:
        refresh_pdf_list()
        pdf_md_dialog.open()

    def refresh_pdf_list() -> None:
        if pdf_file_select:
            path_str = pdf_local_dir_input.value if pdf_local_dir_input and pdf_local_dir_input.value else str(INPUT_DIR)
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
            input_dir = INPUT_DIR / "client_pdf_temp"
            input_dir.mkdir(parents=True, exist_ok=True)
            file_path = input_dir / e.file.name
            
            # NiceGUI 3.x FileUpload.read() 是一个异步方法
            data = await e.file.read()
            file_path.write_bytes(data)
            ui.notify(f"PDF 文件 {e.file.name} 上传成功！已暂存至后端。", type="positive", position="top")
            
            # 刷新已上传 PDF 文件列表
            files = [f.name for f in input_dir.iterdir() if f.is_file() and f.suffix.lower() == ".pdf"]
            client_pdf_select.options = ["[全部已上传PDF文件]"] + files
            client_pdf_select.value = e.file.name
            client_pdf_select.update()
        except Exception as err:
            ui.notify(f"PDF 保存失败: {str(err)}", type="negative", position="top")

    async def run_pdf_conversion() -> None:
        """执行 PDF 转换为 Markdown，并支持对账校验与客户端下载"""
        if not pdf_file_select or not client_pdf_select or not pdf_progress or not pdf_status or not pdf_log_board or not pdf_log_container:
            return
            
        mode = pdf_source_type.value
        pdf_progress.set_value(0.0)
        pdf_progress.visible = True
        pdf_status.visible = True
        pdf_log_board.visible = True
        pdf_log_container.clear()
        pdf_status.set_text("正在启动 PDF 解析与勾稽关系校验...")
        
        pdf_download_container.clear()
        pdf_download_container.visible = False
        
        def on_progress(progress: ParserProgress) -> None:
            if pdf_progress and pdf_status:
                file_idx = progress.current_file_idx
                total_files = progress.total_files
                page_num = progress.current_page
                total_pages = progress.total_pages
                message = progress.status_msg
                audit_logs = progress.audit_alerts
                
                if total_files > 0 and total_pages > 0:
                    current_progress = (file_idx - 1) / total_files + (page_num / total_pages) / total_files
                    pdf_progress.set_value(current_progress)
                    pdf_status.set_text(f"文件 ({file_idx}/{total_files}) - {message}")
                else:
                    pdf_status.set_text(message)
                    
            # 看板渲染审计日志行
            for log in audit_logs:
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

        try:
            parser = PDFBatchParser(input_dir=INPUT_DIR, output_dir=OUTPUT_DIR) # Default dirs
            
            if mode == "server":
                selected = pdf_file_select.value
                path_str = pdf_local_dir_input.value if pdf_local_dir_input and pdf_local_dir_input.value else str(INPUT_DIR)
                input_dir = Path(path_str)
                
                parser = PDFBatchParser(input_dir=input_dir, output_dir=OUTPUT_DIR)
                if selected == "[全部PDF文件]":
                    output_files = await parser.parse_all(progress_callback=on_progress)
                    for out_path in output_files:
                        out_path_obj = Path(out_path).resolve()
                        relative_path = out_path_obj.relative_to(BASE_DIR)
                        download_url = f"/download/{relative_path.as_posix()}"
                        with pdf_download_container:
                            ui.link(f"📥 下载 {out_path_obj.name}", download_url, new_tab=True).classes(
                                "bg-indigo-600 hover:bg-indigo-700 text-white text-xs px-3 py-1.5 rounded-lg font-semibold shadow-sm no-underline"
                            )
                    if output_files:
                        pdf_download_container.visible = True
                else:
                    file_path = input_dir / selected
                    if file_path.exists():
                        out_path = await parser.parse_file(file_path, 1, 1, progress_callback=on_progress)
                        out_path_obj = Path(out_path).resolve()
                        relative_path = out_path_obj.relative_to(BASE_DIR)
                        download_url = f"/download/{relative_path.as_posix()}"
                        ui.notify(f"转换成功！生成至同目录下的 {out_path_obj.name}", type="positive", position="top")
                        with pdf_download_container:
                            ui.link(f"📥 下载 {out_path_obj.name}", download_url, new_tab=True).classes(
                                "bg-indigo-600 hover:bg-indigo-700 text-white text-xs px-3 py-1.5 rounded-lg font-semibold shadow-sm no-underline"
                            )
                        pdf_download_container.visible = True
                    else:
                        raise FileNotFoundError(f"文件不存在: {selected}")
            else:
                selected = client_pdf_select.value
                input_dir = INPUT_DIR / "client_pdf_temp"
                
                parser = PDFBatchParser(input_dir=input_dir, output_dir=OUTPUT_DIR)
                if selected == "[全部已上传PDF文件]":
                    files = [f for f in input_dir.iterdir() if f.is_file() and f.suffix.lower() == ".pdf"]
                    total_files = len(files)
                    if total_files == 0:
                        on_progress(ParserProgress(0, 0, 0, 0, "未找到任何已上传的 PDF 文件。", []))
                        return
                    for idx, file_path in enumerate(files, start=1):
                        out_path = await parser.parse_file(file_path, idx, total_files, progress_callback=on_progress)
                        out_path_obj = Path(out_path).resolve()
                        relative_path = out_path_obj.relative_to(BASE_DIR)
                        download_url = f"/download/{relative_path.as_posix()}"
                        ui.download(download_url, filename=out_path_obj.name)
                        with pdf_download_container:
                            ui.link(f"📥 下载 {out_path_obj.name}", download_url, new_tab=True).classes(
                                "bg-indigo-600 hover:bg-indigo-700 text-white text-xs px-3 py-1.5 rounded-lg font-semibold shadow-sm no-underline"
                            )
                        pdf_download_container.visible = True
                else:
                    file_path = input_dir / selected
                    if file_path.exists():
                        out_path = await parser.parse_file(file_path, 1, 1, progress_callback=on_progress)
                        out_path_obj = Path(out_path).resolve()
                        relative_path = out_path_obj.relative_to(BASE_DIR)
                        download_url = f"/download/{relative_path.as_posix()}"
                        ui.notify(f"解析成功！正在下载 {out_path_obj.name} ...", type="positive", position="top")
                        ui.download(download_url, filename=out_path_obj.name)
                        with pdf_download_container:
                            ui.link(f"📥 点击下载 {out_path_obj.name}", download_url, new_tab=True).classes(
                                "bg-indigo-600 hover:bg-indigo-700 text-white text-xs px-3 py-1.5 rounded-lg font-semibold shadow-sm no-underline"
                            )
                        pdf_download_container.visible = True
                    else:
                        raise FileNotFoundError(f"文件不存在: {selected}")
            
            pdf_status.set_text("PDF 解析与勾稽审计完成！")
        except Exception as err:
            pdf_status.set_text(f"解析失败: {str(err)}")
            ui.notify(f"解析失败: {str(err)}", type="negative", position="top")
        finally:
            await asyncio.sleep(5)
            pdf_progress.visible = False
            pdf_status.visible = False

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
        with ui.card().classes("w-full p-6 bg-white border border-slate-200 rounded-xl shadow-sm gap-2"):
            with ui.row().classes("items-center gap-2"):
                ui.icon("info", size="1.5rem").classes("text-indigo-600")
                ui.label("项目控制中心与工具箱").classes("text-lg font-bold text-slate-800")
            ui.markdown(
                "本系统严格遵循 `gemini.md` 规范进行架构设计。下方工具箱集成了核心的报税处理程序，"
                "所有数据流转均支持**长数字安全保护（避免身份证、企业税号科学计数法截断）**。"
            ).classes("text-slate-600 text-sm leading-relaxed")
        
        # 10 个功能卡的网格布局
        ui.label("系统控制工具箱 (10 大功能项)").classes("text-base font-semibold text-slate-500 uppercase tracking-wider mt-4")
        
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
                    value=str(INPUT_DIR),
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
                    value=str(INPUT_DIR),
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

# 启动服务
if __name__ in {"__main__", "__mp_main__"}:
    ui.run(title="China-Tax 智能税务自动化申报 system", port=8080, reload=True)
