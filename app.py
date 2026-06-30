import os
import signal
import subprocess
import time
import warnings
import asyncio
from pathlib import Path
from typing import Any
from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from nicegui import app, events, ui

# 忽略 openpyxl 样式相关的 UserWarning，防止缺少默认样式引起日志输出或在严格警告模式下报错
warnings.filterwarnings("ignore", category=UserWarning, module="openpyxl")

# Import system utils and paths configuration
import config.paths as paths
from utils.sys_utils import free_port, create_zip_archive, clear_data_directories

# Free port 28888 before starting NiceGUI
free_port(28888)

# Initialize database tables on startup
import config.db_config as db_config
db_config.init_db()

# Import UI components and state
from ui import (
    AppState, log_action, SystemLogsDialog, CSVExcelDialog, ExcelCSVDialog,
    PDFDedupDialog, PDFMDDialog, MDClosingDialog, CSVClosingDialog,
    DBTestDialog, CalculatorDialog, ValidatorDialog, ExporterDialog, ArchiveDialog, ConfigViewDialog
)

# Register static files directory and secure download route
app.add_static_files("/data", str(paths.BASE_DIR / "data"))

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
    resolved_path = (paths.BASE_DIR / file_path).resolve()
    if not resolved_path.is_relative_to(paths.BASE_DIR):
        raise HTTPException(status_code=403, detail="Access denied")
    if not resolved_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(resolved_path, filename=resolved_path.name)


@ui.page("/")
def main_page() -> None:
    # Initialize session-isolated AppState
    state = AppState()
    
    # Instantiate UI Dialog Components
    state.csv_excel = CSVExcelDialog(state)
    state.excel_csv = ExcelCSVDialog(state)
    state.pdf_dedup = PDFDedupDialog(state)
    state.pdf_md = PDFMDDialog(state)
    state.closing_md = MDClosingDialog(state)
    state.closing_csv = CSVClosingDialog(state)
    state.sys_logs = SystemLogsDialog(state)
    
    # DB/Tax Tool Dialogs
    state.db_test = DBTestDialog(state)
    state.calculator = CalculatorDialog(state)
    state.validator = ValidatorDialog(state)
    state.exporter = ExporterDialog(state)
    state.archive = ArchiveDialog(state)
    state.config_view = ConfigViewDialog(state)

    # --- Local Dialog Callbacks ---
    def handle_pdf_deduplication(e) -> None:
        state.pdf_dedup.open()

    def handle_csv_excel(e) -> None:
        state.csv_excel.open()

    def handle_excel_csv(e) -> None:
        state.excel_csv.open()

    def handle_pdf_md(e) -> None:
        state.pdf_md.open()

    def handle_db_test(e) -> None:
        state.db_test.open()

    def handle_calculator(e) -> None:
        state.calculator.open()

    def handle_validator(e) -> None:
        state.validator.open()

    def handle_exporter(e) -> None:
        state.exporter.open()

    def handle_archive(e) -> None:
        state.archive.open()

    def handle_config_view(e) -> None:
        state.config_view.open()

    def handle_system_logs(e) -> None:
        state.sys_logs.open()

    def handle_md_closing(e) -> None:
        state.closing_md.open()

    def handle_csv_closing(e) -> None:
        state.closing_csv.open()

    # --- Broker directory isolation popup handler ---
    async def prompt_bank_name():
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
                    paths.update_active_paths(val)
                    if bank_name_input:
                        bank_name_input.set_value(val)
                    
                    # Create directories and refresh lists
                    paths.INPUT_PDF_DIR.mkdir(parents=True, exist_ok=True)
                    paths.INPUT_CSV_DIR.mkdir(parents=True, exist_ok=True)
                    paths.INPUT_EXCEL_DIR.mkdir(parents=True, exist_ok=True)
                    paths.INPUT_MD_DIR.mkdir(parents=True, exist_ok=True)
                    paths.OUTPUT_PDF_DIR.mkdir(parents=True, exist_ok=True)
                    paths.OUTPUT_PDF_DECRYPT_DIR.mkdir(parents=True, exist_ok=True)
                    paths.OUTPUT_CSV_DIR.mkdir(parents=True, exist_ok=True)
                    paths.OUTPUT_EXCEL_DIR.mkdir(parents=True, exist_ok=True)
                    paths.OUTPUT_MD_DIR.mkdir(parents=True, exist_ok=True)
                    
                    # Update paths of nested components
                    state.csv_excel.update_paths()
                    state.excel_csv.update_paths()
                    state.pdf_dedup.update_paths()
                    state.pdf_md.update_paths()
                        
                    log_action(f"初始化目錄隔離：金融機構={val} -> 輸入目錄={paths.INPUT_DIR}, 輸出目錄={paths.OUTPUT_DIR}")
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
        
        paths.update_active_paths(bank_name)
        
        paths.INPUT_PDF_DIR.mkdir(parents=True, exist_ok=True)
        paths.INPUT_CSV_DIR.mkdir(parents=True, exist_ok=True)
        paths.INPUT_EXCEL_DIR.mkdir(parents=True, exist_ok=True)
        paths.INPUT_MD_DIR.mkdir(parents=True, exist_ok=True)
        paths.OUTPUT_PDF_DIR.mkdir(parents=True, exist_ok=True)
        paths.OUTPUT_PDF_DECRYPT_DIR.mkdir(parents=True, exist_ok=True)
        paths.OUTPUT_CSV_DIR.mkdir(parents=True, exist_ok=True)
        paths.OUTPUT_EXCEL_DIR.mkdir(parents=True, exist_ok=True)
        paths.OUTPUT_MD_DIR.mkdir(parents=True, exist_ok=True)
        
        state.csv_excel.update_paths()
        state.excel_csv.update_paths()
        state.pdf_dedup.update_paths()
        state.pdf_md.update_paths()
            
        log_action(f"切換隔離目錄：券商/銀行名={bank_name} -> 輸入目錄={paths.INPUT_DIR}, 輸出目錄={paths.OUTPUT_DIR}")

    # --- Page UI Layout ---
    ui.query("body").classes("bg-slate-50 font-sans")
    
    with ui.header().classes("w-full bg-gradient-to-r from-slate-900 via-indigo-950 to-slate-900 text-white p-4 shadow-lg flex justify-between items-center"):
        with ui.row().classes("items-center gap-3"):
            ui.icon("analytics", size="2rem").classes("text-indigo-400 animate-pulse")
            ui.label("China-Tax 智能税务自动化申报系统").classes("text-xl font-bold tracking-wide")
        ui.label("v3.0 Beta (NiceGUI / Python 3.14)").classes("text-sm text-slate-400 font-mono")
        
    with ui.column().classes("w-full max-w-7xl mx-auto p-6 gap-6"):
        with ui.card().classes("w-full p-6 bg-white border border-slate-200 rounded-xl shadow-sm gap-4"):
            with ui.row().classes("w-full justify-between items-center gap-4 flex-wrap md:flex-nowrap"):
                with ui.column().classes("gap-2 flex-grow"):
                    with ui.row().classes("items-center gap-2"):
                        ui.icon("info", size="1.5rem").classes("text-indigo-600")
                        ui.label("项目控制中心与工具箱").classes("text-lg font-bold text-slate-800")
                    ui.markdown(
                        "1. **系统架构**: 本系统严格遵循 `gemini.md` 规范进行架构设计。\n"
                        "2. **功能：**: 本系统2各主要功能：一、实现pdf、md、csv、excel格式互转；二、帮助计算各类报税\n"
                        "3. **数字安全**: 下方工具箱集成了核心的报税处理程序，所有数据流转均支持**长数字安全保护（避免身份证、企业税号科学计数法截断）**。\n"
                        "4. **证券基金报税**: 证券基金报税使用模块 1、2、3、11、12 即可整理出成交明细。\n"
                        "5. **模块协同对账**: 模块 11、12 功能相同，区别是使用的文件类型不同，并互为校验。"
                    ).classes("text-slate-600 text-sm leading-relaxed")
                
                with ui.card().classes("w-full md:w-auto p-4 bg-slate-50 border border-slate-200 rounded-xl gap-2 min-w-[280px] shadow-inner"):
                    with ui.row().classes("items-center gap-1.5"):
                        ui.icon("cleaning_services", size="1.2rem").classes("text-amber-500")
                        ui.label("缓存与临时目录控制").classes("text-xs font-bold text-slate-700 uppercase tracking-wide")
                    
                    bank_name_input = ui.input(
                        label="银行及券商名称 (目录隔离)",
                        placeholder="例如：招商银行 / 中信证券",
                    ).classes("w-full text-xs").on("blur", on_bank_name_change).on("keydown.enter", on_bank_name_change)
                    
                    dir_check_label = ui.label("").classes("text-xs text-slate-400 whitespace-pre-wrap leading-snug font-mono")
                    
                    def refresh_dir_check():
                        lines = []
                        dirs_to_check = [
                            ("PDF 输入", paths.INPUT_PDF_DIR),
                            ("CSV 输入", paths.INPUT_CSV_DIR),
                            ("Exl 输入", paths.INPUT_EXCEL_DIR),
                            ("MD  输入", paths.INPUT_MD_DIR),
                            ("PDF 输出", paths.OUTPUT_PDF_DIR),
                            ("CSV 输出", paths.OUTPUT_CSV_DIR),
                            ("Exl 输出", paths.OUTPUT_EXCEL_DIR),
                            ("MD  输出", paths.OUTPUT_MD_DIR),
                        ]
                        for name, d in dirs_to_check:
                            if d and d.exists():
                                files = [f for f in d.rglob("*") if f.is_file()]
                                total_bytes = sum(f.stat().st_size for f in files)
                                if total_bytes >= 1024 * 1024:
                                    size_str = f"{total_bytes / 1024 / 1024:.1f}MB"
                                elif total_bytes >= 1024:
                                    size_str = f"{total_bytes / 1024:.1f}KB"
                                else:
                                    size_str = f"{total_bytes}B"
                                lines.append(f"{name}: {len(files)}个文件  {size_str}")
                            else:
                                lines.append(f"{name}: 目录不存在")
                        dir_check_label.set_text("\n".join(lines))
                        
                    ui.button("🔍 检查目录状态", on_click=refresh_dir_check).classes(
                        "w-full bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-bold py-2 px-3 rounded-lg shadow-sm"
                    )
                    
                    def manual_clear():
                        clear_data_directories(clear_archives=False)
                        for d in [
                            paths.INPUT_PDF_DIR, paths.INPUT_CSV_DIR, paths.INPUT_EXCEL_DIR, paths.INPUT_MD_DIR,
                            paths.OUTPUT_PDF_DIR, paths.OUTPUT_PDF_DECRYPT_DIR,
                            paths.OUTPUT_CSV_DIR, paths.OUTPUT_EXCEL_DIR, paths.OUTPUT_MD_DIR,
                        ]:
                            if d:
                                try:
                                    d.mkdir(parents=True, exist_ok=True)
                                except Exception:
                                    pass
                        refresh_dir_check()
                        ui.notify("已成功清理后端 data 目录下的所有子目录与暂存文件！", type="positive", position="top")
                        log_action("手动执行后端 data 目录所有子目录文件清理。")
                        
                    ui.button("🧹 一键清空后端文件", on_click=manual_clear).classes(
                        "w-full bg-indigo-50 hover:bg-indigo-100 text-indigo-700 text-xs font-bold py-2 px-3 rounded-lg shadow-sm"
                    )

        ui.label("系统控制工具箱 (12 大功能项)").classes("text-base font-semibold text-slate-500 uppercase tracking-wider mt-4")
        
        with ui.grid().classes("grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6 w-full"):
            with ui.card().classes("hover:shadow-md transition-all duration-300 border border-slate-200 rounded-xl p-5 flex flex-col justify-between h-48 bg-white"):
                with ui.column().classes("gap-1"):
                    ui.label("1. PDF 文件查重").classes("font-bold text-slate-800 text-base")
                    ui.label("扫描输入目录，智能去重多余 PDF 报税文件，并导出清理结果报告。").classes("text-xs text-slate-500")
                ui.button("开始查重", on_click=handle_pdf_deduplication).classes("w-full bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg py-2 text-sm font-semibold shadow-sm")
                
            with ui.card().classes("hover:shadow-md transition-all duration-300 border border-slate-200 rounded-xl p-5 flex flex-col justify-between h-48 bg-white"):
                with ui.column().classes("gap-1 w-full"):
                    ui.label("2. CSV ↔ Excel 互转").classes("font-bold text-slate-800 text-base")
                    ui.label("支持无损批量互转，保留发票号等长数字前导零；Excel 多 Sheet 自动拆分为独立 CSV。").classes("text-xs text-slate-500")
                with ui.row().classes("w-full gap-2"):
                    ui.button("CSV → Excel", on_click=handle_csv_excel).classes("flex-1 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg py-2 text-xs font-semibold shadow-sm")
                    ui.button("Excel → CSV", on_click=handle_excel_csv).classes("flex-1 bg-teal-600 hover:bg-teal-700 text-white rounded-lg py-2 text-xs font-semibold shadow-sm")
                    
            with ui.card().classes("hover:shadow-md transition-all duration-300 border border-slate-200 rounded-xl p-5 flex flex-col justify-between h-48 bg-white"):
                with ui.column().classes("gap-1"):
                    ui.label("3. PDF 结单提取").classes("font-bold text-slate-800 text-base")
                    ui.label("将 PDF 格式的报税单/结单结构化转化为 Markdown 格式，并提取交易数据转换为 CSV 档案。").classes("text-xs text-slate-500")
                with ui.row().classes("w-full gap-2"):
                    ui.button("PDF 转 MD", on_click=handle_pdf_md).classes("flex-1 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg py-2 text-xs font-semibold shadow-sm")
                    ui.button("MD 转 CSV", on_click=handle_pdf_md).classes("flex-1 bg-teal-600 hover:bg-teal-700 text-white rounded-lg py-2 text-xs font-semibold shadow-sm")
                    
            with ui.card().classes("hover:shadow-md transition-all duration-300 border border-slate-200 rounded-xl p-5 flex flex-col justify-between h-48 bg-white"):
                with ui.column().classes("gap-1"):
                    ui.label("4. 数据库连接").classes("font-bold text-slate-800 text-base")
                    ui.label("测试 PostgreSQL 核心档案库的连通性与配置可用状态。").classes("text-xs text-slate-500")
                ui.button("测试连接", on_click=handle_db_test).classes("w-full bg-slate-700 hover:bg-slate-800 text-white rounded-lg py-2 text-sm font-semibold")
                
            with ui.card().classes("hover:shadow-md transition-all duration-300 border border-slate-200 rounded-xl p-5 flex flex-col justify-between h-48 bg-white"):
                with ui.column().classes("gap-1"):
                    ui.label("5. 税额智能计算").classes("font-bold text-slate-800 text-base")
                    ui.label("执行个税、企业税等核心计算公式与多场景比对。").classes("text-xs text-slate-500")
                ui.button("核算税额", on_click=handle_calculator).classes("w-full bg-slate-700 hover:bg-slate-800 text-white rounded-lg py-2 text-sm font-semibold")
                
            with ui.card().classes("hover:shadow-md transition-all duration-300 border border-slate-200 rounded-xl p-5 flex flex-col justify-between h-48 bg-white"):
                with ui.column().classes("gap-1"):
                    ui.label("6. 申报合法性校验").classes("font-bold text-slate-800 text-base")
                    ui.label("快速校验报税数据是否存在逻辑漏洞、格式错误或非法数字。").classes("text-xs text-slate-500")
                ui.button("校验数据", on_click=handle_validator).classes("w-full bg-slate-700 hover:bg-slate-800 text-white rounded-lg py-2 text-sm font-semibold")
                
            with ui.card().classes("hover:shadow-md transition-all duration-300 border border-slate-200 rounded-xl p-5 flex flex-col justify-between h-48 bg-white"):
                with ui.column().classes("gap-1"):
                    ui.label("7. 一键生成申报表").classes("font-bold text-slate-800 text-base")
                    ui.label("打包已核算的数据，导出为符合国税标准的电子申报文件。").classes("text-xs text-slate-500")
                ui.button("导出报表", on_click=handle_exporter).classes("w-full bg-slate-700 hover:bg-slate-800 text-white rounded-lg py-2 text-sm font-semibold")
                
            with ui.card().classes("hover:shadow-md transition-all duration-300 border border-slate-200 rounded-xl p-5 flex flex-col justify-between h-48 bg-white"):
                with ui.column().classes("gap-1"):
                    ui.label("8. 历史归档查询").classes("font-bold text-slate-800 text-base")
                    ui.label("检索和浏览已归档的历史年度纳税记录与申报文件。").classes("text-xs text-slate-500")
                ui.button("浏览归档", on_click=handle_archive).classes("w-full bg-slate-700 hover:bg-slate-800 text-white rounded-lg py-2 text-sm font-semibold")
                
            with ui.card().classes("hover:shadow-md transition-all duration-300 border border-slate-200 rounded-xl p-5 flex flex-col justify-between h-48 bg-white"):
                with ui.column().classes("gap-1"):
                    ui.label("9. 税率参数配置").classes("font-bold text-slate-800 text-base")
                    ui.label("配置或调整各年度各税种的税率速算扣除数及减免参数。").classes("text-xs text-slate-500")
                ui.button("配置参数", on_click=handle_config_view).classes("w-full bg-slate-700 hover:bg-slate-800 text-white rounded-lg py-2 text-sm font-semibold")
                
            with ui.card().classes("hover:shadow-md transition-all duration-300 border border-slate-200 rounded-xl p-5 flex flex-col justify-between h-48 bg-white"):
                with ui.column().classes("gap-1"):
                    ui.label("10. 运行状态与日志").classes("font-bold text-slate-800 text-base")
                    ui.label("监控当前服务的运行状态并实时查阅核心操作日志。").classes("text-xs text-slate-500")
                ui.button("查阅日志", on_click=handle_system_logs).classes("w-full bg-slate-700 hover:bg-slate-800 text-white rounded-lg py-2 text-sm font-semibold")
                
            with ui.card().classes("hover:shadow-md transition-all duration-300 border border-slate-200 rounded-xl p-5 flex flex-col justify-between h-48 bg-white"):
                with ui.column().classes("gap-1"):
                    ui.label("11. md平仓交易整理").classes("font-bold text-slate-800 text-base")
                    ui.label("上传指定 Markdown 账单文件，按指定时间段提取整理平仓成交的标的，输出 Excel。").classes("text-xs text-slate-500")
                ui.button("整理平仓数据", on_click=handle_md_closing).classes("w-full bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg py-2 text-sm font-semibold shadow-sm")
                
            with ui.card().classes("hover:shadow-md transition-all duration-300 border border-slate-200 rounded-xl p-5 flex flex-col justify-between h-48 bg-white"):
                with ui.column().classes("gap-1"):
                    ui.label("12. CSV 平仓交易整理").classes("font-bold text-slate-800 text-base")
                    ui.label("上传指定 CSV 账单文件，按指定时间段提取整理平仓成交的标的，输出 Excel。").classes("text-xs text-slate-500")
                ui.button("整理 CSV 平仓数据", on_click=handle_csv_closing).classes("w-full bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg py-2 text-sm font-semibold shadow-sm")

    # Initial prompt for bank name directory isolation
    ui.timer(0.1, prompt_bank_name, once=True)

# Run server
if __name__ in {"__main__", "__mp_main__"}:
    ui.run(title="China-Tax 智能税务自动化申报 system", port=28888, reload=True)
