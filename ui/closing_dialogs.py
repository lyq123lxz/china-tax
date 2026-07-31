import asyncio
from pathlib import Path
from nicegui import ui, events
from ui.app_state import AppState
import config.paths as paths
import utils.md_closing as md_closing
import utils.csv_closing as csv_closing
from utils.sys_utils import create_zip_archive
from ui.sys_logs import log_action

class MDClosingDialog:
    def __init__(self, state: AppState) -> None:
        self.state = state
        self.dialog = None
        self.md_closing_uploaded_files: list[tuple[str, bytes]] = []
        
        self.md_closing_progress = None
        self.md_closing_status = None
        self.md_closing_download_container = None
        self.md_closing_start_date = None
        self.md_closing_end_date = None
        self.build()
        
    def build(self) -> None:
        with ui.dialog() as self.dialog:
            with ui.card().classes("w-[600px] p-6 gap-4 bg-white rounded-xl shadow-2xl"):
                with ui.row().classes("w-full justify-between items-center"):
                    with ui.row().classes("items-center gap-2"):
                        ui.icon("filter_alt", size="1.8rem").classes("text-indigo-600")
                        ui.label("md平仓成交数据整理控制台").classes("text-lg font-bold text-slate-800")
                    ui.button(icon="close", on_click=self.dialog.close).props("flat round dense").classes("text-slate-400")
                
                ui.separator()
                
                ui.label("步骤 1：设定整理交易的时间段 (选填，留空代表不限制)").classes("text-xs font-bold text-slate-500 uppercase tracking-wide")
                with ui.row().classes("w-full gap-4"):
                    self.md_closing_start_date = ui.input(
                        label="开始日期 (格式: YYYY-MM-DD)",
                        placeholder="例如: 2026-01-01"
                    ).classes("flex-1")
                    self.md_closing_end_date = ui.input(
                        label="结束日期 (格式: YYYY-MM-DD)",
                        placeholder="例如: 2026-12-31"
                    ).classes("flex-1")
                    
                ui.label("步骤 2：上传 Markdown 交易明细文件 (.md)").classes("text-xs font-bold text-slate-500 uppercase tracking-wide")
                ui.upload(
                    label="选择或拖拽 Markdown 文件进行上传（支持多文件）",
                    auto_upload=True,
                    multiple=True,
                    on_upload=self.on_md_upload
                ).classes("w-full border border-dashed border-slate-200 rounded-xl p-1").props("accept=.md")
                
                with ui.row().classes("w-full items-start gap-2 p-3 bg-indigo-50 rounded-lg border border-indigo-200"):
                    ui.icon("info", size="1rem").classes("text-indigo-600 mt-0.5 shrink-0")
                    ui.label(
                        "平仓整理系统：智能识别成交动作并自动进行开平仓方向核算，剔除未成交/废单干扰，导出包含「开平仓混合总表」、「纯开仓表」、「纯平仓表」的 Excel 账单。"
                    ).classes("text-xs text-indigo-700 leading-relaxed")
                    
                self.md_closing_progress = ui.linear_progress(value=0.0, show_value=False).classes("w-full rounded-full")
                self.md_closing_progress.visible = False
                self.md_closing_status = ui.label("等待上传文件...").classes("text-xs text-slate-500 font-mono")
                self.md_closing_status.visible = False
                
                self.md_closing_download_container = ui.row().classes("w-full justify-center gap-2 mt-2")
                self.md_closing_download_container.visible = False
                
                with ui.row().classes("w-full justify-end gap-2 mt-4"):
                    ui.button("取消", on_click=self.dialog.close).props("flat").classes("text-slate-500 text-sm")
                    ui.button("开始提取与整理", on_click=self.run_md_closing_organization).classes(
                        "bg-indigo-600 hover:bg-indigo-700 text-white px-5 py-2.5 rounded-lg text-sm font-semibold shadow-sm"
                    )

    def open(self) -> None:
        self.md_closing_uploaded_files = []
        if self.md_closing_download_container:
            self.md_closing_download_container.clear()
            self.md_closing_download_container.visible = False
        if self.md_closing_progress:
            self.md_closing_progress.set_value(0.0)
            self.md_closing_progress.visible = False
        if self.md_closing_status:
            self.md_closing_status.set_text("等待上传与整理...")
            self.md_closing_status.visible = False
        self.dialog.open()

    async def on_md_upload(self, e: events.UploadEventArguments) -> None:
        try:
            data = await e.file.read()
            self.md_closing_uploaded_files.append((Path(e.file.name).name, data))
            ui.notify(f"Markdown 文件 {Path(e.file.name).name} 上传并暂存成功！", type="positive", position="top")
        except Exception as err:
            ui.notify(f"上传失败: {str(err)}", type="negative", position="top")

    async def run_md_closing_organization(self) -> None:
        if not self.md_closing_uploaded_files:
            ui.notify("请先上传至少一个 Markdown 交易明细文件！", type="warning", position="top")
            return
            
        self.md_closing_progress.set_value(0.0)
        self.md_closing_progress.visible = True
        self.md_closing_status.visible = True
        self.md_closing_status.set_text("正在提取并整理平仓成交明细...")
        
        self.md_closing_download_container.clear()
        self.md_closing_download_container.visible = False
        
        start_date = None
        end_date = None
        if self.md_closing_start_date.value:
            start_date = md_closing.parse_date(self.md_closing_start_date.value)
        if self.md_closing_end_date.value:
            end_date = md_closing.parse_date(self.md_closing_end_date.value)
            
        all_closing_trades = []
        all_open_trades = []
        all_close_trades = []
        all_headers = []
        
        try:
            for file_name, file_bytes in self.md_closing_uploaded_files:
                md_content = file_bytes.decode("utf-8", errors="ignore")
                tables = md_closing.parse_markdown_tables(md_content)
                trades_all, trades_open, trades_close, headers = md_closing.extract_closing_trades(tables, start_date, end_date)
                
                for t in trades_all:
                    t["来自文件"] = file_name
                for t in trades_open:
                    t["来自文件"] = file_name
                for t in trades_close:
                    t["来自文件"] = file_name
                    
                all_closing_trades.extend(trades_all)
                all_open_trades.extend(trades_open)
                all_close_trades.extend(trades_close)
                
                for h in headers:
                    if h not in all_headers:
                        all_headers.append(h)
                
            self.md_closing_progress.set_value(0.5)
            self.md_closing_status.set_text("正在生成 Excel 整理表与审计报告...")
            
            out_dir = paths.OUTPUT_DIR / "closing_summary"
            out_dir.mkdir(parents=True, exist_ok=True)
            
            excel_path, report_path = await asyncio.to_thread(
                md_closing.generate_closing_report,
                all_closing_trades,
                all_open_trades,
                all_close_trades,
                all_headers,
                out_dir,
                self.md_closing_start_date.value or "",
                self.md_closing_end_date.value or ""
            )
            
            zip_file_path = out_dir / "organized_closing_data.zip"
            if zip_file_path.exists():
                zip_file_path.unlink()
                
            await asyncio.to_thread(create_zip_archive, [excel_path], zip_file_path)
            
            self.md_closing_progress.set_value(1.0)
            self.md_closing_status.set_text(f"平仓数据整理完成！匹配到 {len(all_close_trades)} 笔平仓成交 (总记录 {len(all_closing_trades)} 笔)。")
            
            try:
                rel_report = report_path.relative_to(paths.BASE_DIR)
                report_url = f"/download/{rel_report.as_posix()}"
                with self.md_closing_download_container:
                    ui.link("📊 下载整理报告 (report.md)", report_url, new_tab=True).classes(
                        "bg-indigo-600 hover:bg-indigo-700 text-white text-xs px-3 py-1.5 rounded-lg font-semibold shadow-sm no-underline"
                    )
            except ValueError:
                pass
                
            if zip_file_path.exists():
                try:
                    rel_zip = zip_file_path.relative_to(paths.BASE_DIR)
                    zip_url = f"/download/{rel_zip.as_posix()}"
                    with self.md_closing_download_container:
                        ui.link("📦 下载全部整理件 (ZIP 打包档)", zip_url, new_tab=True).classes(
                            "bg-amber-600 hover:bg-amber-700 text-white text-xs px-3 py-1.5 rounded-lg font-semibold shadow-sm no-underline font-bold"
                        )
                except ValueError:
                    pass
                    
            self.md_closing_download_container.visible = True
            ui.notify(f"整理成功！提取出 {len(all_closing_trades)} 笔平仓成交数据。", type="positive", position="top")
            log_action(f"模块 11 执行成功：时间段为 {self.md_closing_start_date.value or '未限定'} - {self.md_closing_end_date.value or '未限定'}，匹配到 {len(all_closing_trades)} 笔平仓明细并已生成 ZIP")
            
        except Exception as err:
            self.md_closing_status.set_text(f"整理失败: {str(err)}")
            ui.notify(f"数据整理失败: {str(err)}", type="negative", position="top")
            
        finally:
            await asyncio.sleep(5)
            if self.md_closing_progress:
                self.md_closing_progress.visible = False
            if self.md_closing_status:
                self.md_closing_status.visible = False


class CSVClosingDialog:
    def __init__(self, state: AppState) -> None:
        self.state = state
        self.dialog = None
        self.csv_closing_uploaded_files: list[tuple[str, bytes]] = []
        
        self.csv_closing_progress = None
        self.csv_closing_status = None
        self.csv_closing_download_container = None
        self.csv_closing_start_date = None
        self.csv_closing_end_date = None
        self.build()
        
    def build(self) -> None:
        with ui.dialog() as self.dialog:
            with ui.card().classes("w-[600px] p-6 gap-4 bg-white rounded-xl shadow-2xl"):
                with ui.row().classes("w-full justify-between items-center"):
                    with ui.row().classes("items-center gap-2"):
                        ui.icon("filter_alt", size="1.8rem").classes("text-indigo-600")
                        ui.label("CSV 平仓成交数据整理控制台").classes("text-lg font-bold text-slate-800")
                    ui.button(icon="close", on_click=self.dialog.close).props("flat round dense").classes("text-slate-400")
                
                ui.separator()
                
                ui.label("步骤 1：设定整理交易的时间段 (选填，留空代表不限制)").classes("text-xs font-bold text-slate-500 uppercase tracking-wide")
                with ui.row().classes("w-full gap-4"):
                    self.csv_closing_start_date = ui.input(
                        label="开始日期 (格式: YYYY-MM-DD)",
                        placeholder="例如: 2026-01-01"
                    ).classes("flex-1")
                    self.csv_closing_end_date = ui.input(
                        label="结束日期 (格式: YYYY-MM-DD)",
                        placeholder="例如: 2026-12-31"
                    ).classes("flex-1")
                    
                ui.label("步骤 2：上传 CSV 交易明细文件 (.csv)").classes("text-xs font-bold text-slate-500 uppercase tracking-wide")
                ui.upload(
                    label="选择并上传 CSV 文件整理明细（支持多文件上传）",
                    auto_upload=True,
                    multiple=True,
                    on_upload=self.on_csv_upload_closing
                ).classes("w-full border border-dashed border-slate-200 rounded-xl p-1").props("accept=.csv")
                
                with ui.row().classes("w-full items-start gap-2 p-3 bg-indigo-50 rounded-lg border border-indigo-200"):
                    ui.icon("info", size="1rem").classes("text-indigo-600 mt-0.5 shrink-0")
                    ui.label(
                        "CSV 平仓整理原理：对上传的 CSV 表格段落进行动态隔离与数据合并，通过对账勾稽导出含有开平仓比对结果的标准化 Excel 报表。"
                    ).classes("text-xs text-indigo-700 leading-relaxed")
                    
                self.csv_closing_progress = ui.linear_progress(value=0.0, show_value=False).classes("w-full rounded-full")
                self.csv_closing_progress.visible = False
                self.csv_closing_status = ui.label("等待上传文件...").classes("text-xs text-slate-500 font-mono")
                self.csv_closing_status.visible = False
                
                self.csv_closing_download_container = ui.row().classes("w-full justify-center gap-2 mt-2")
                self.csv_closing_download_container.visible = False
                
                with ui.row().classes("w-full justify-end gap-2 mt-4"):
                    ui.button("取消", on_click=self.dialog.close).props("flat").classes("text-slate-500 text-sm")
                    ui.button("开始提取与整理", on_click=self.run_csv_closing_organization).classes(
                        "bg-indigo-600 hover:bg-indigo-700 text-white px-5 py-2.5 rounded-lg text-sm font-semibold shadow-sm"
                    )

    def open(self) -> None:
        self.csv_closing_uploaded_files = []
        if self.csv_closing_download_container:
            self.csv_closing_download_container.clear()
            self.csv_closing_download_container.visible = False
        if self.csv_closing_progress:
            self.csv_closing_progress.set_value(0.0)
            self.csv_closing_progress.visible = False
        if self.csv_closing_status:
            self.csv_closing_status.set_text("等待上传与整理...")
            self.csv_closing_status.visible = False
        self.dialog.open()

    async def on_csv_upload_closing(self, e: events.UploadEventArguments) -> None:
        try:
            data = await e.file.read()
            self.csv_closing_uploaded_files.append((Path(e.file.name).name, data))
            ui.notify(f"CSV 文件 {Path(e.file.name).name} 上传并暂存成功！", type="positive", position="top")
        except Exception as err:
            ui.notify(f"上传失败: {str(err)}", type="negative", position="top")

    async def run_csv_closing_organization(self) -> None:
        if not self.csv_closing_uploaded_files:
            ui.notify("请先上传至少一个 CSV 交易明细文件！", type="warning", position="top")
            return
            
        self.csv_closing_progress.set_value(0.0)
        self.csv_closing_progress.visible = True
        self.csv_closing_status.visible = True
        self.csv_closing_status.set_text("正在提取并整理平仓成交明细...")
        
        self.csv_closing_download_container.clear()
        self.csv_closing_download_container.visible = False
        
        start_date = None
        end_date = None
        if self.csv_closing_start_date.value:
            start_date = csv_closing.parse_date(self.csv_closing_start_date.value)
        if self.csv_closing_end_date.value:
            end_date = csv_closing.parse_date(self.csv_closing_end_date.value)
            
        all_closing_trades = []
        all_open_trades = []
        all_close_trades = []
        all_headers = []
        
        try:
            for file_name, file_bytes in self.csv_closing_uploaded_files:
                csv_content = file_bytes.decode("utf-8", errors="ignore")
                tables = csv_closing.parse_csv_tables(csv_content)
                trades_all, trades_open, trades_close, headers = csv_closing.extract_closing_trades(tables, start_date, end_date)
                
                for t in trades_all:
                    t["来自文件"] = file_name
                for t in trades_open:
                    t["来自文件"] = file_name
                for t in trades_close:
                    t["来自文件"] = file_name
                    
                all_closing_trades.extend(trades_all)
                all_open_trades.extend(trades_open)
                all_close_trades.extend(trades_close)
                
                for h in headers:
                    if h not in all_headers:
                        all_headers.append(h)
                
            self.csv_closing_progress.set_value(0.5)
            self.csv_closing_status.set_text("正在生成 Excel 整理表与审计报告...")
            
            out_dir = paths.OUTPUT_DIR / "closing_summary_csv"
            out_dir.mkdir(parents=True, exist_ok=True)
            
            excel_path, report_path = await asyncio.to_thread(
                csv_closing.generate_closing_report,
                all_closing_trades,
                all_open_trades,
                all_close_trades,
                all_headers,
                out_dir,
                self.csv_closing_start_date.value or "",
                self.csv_closing_end_date.value or ""
            )
            
            zip_file_path = out_dir / "organized_closing_data_csv.zip"
            if zip_file_path.exists():
                try:
                    zip_file_path.unlink()
                except Exception as zip_err:
                    print(f"删除旧 ZIP 归档失败: {zip_err}")
                
            await asyncio.to_thread(create_zip_archive, [excel_path], zip_file_path)
            
            self.csv_closing_progress.set_value(1.0)
            self.csv_closing_status.set_text(f"平仓数据整理完成！匹配到 {len(all_close_trades)} 笔平仓成交 (总记录 {len(all_closing_trades)} 笔)。")
            
            try:
                rel_report = report_path.relative_to(paths.BASE_DIR)
                report_url = f"/download/{rel_report.as_posix()}"
                with self.csv_closing_download_container:
                    ui.link("📊 下载整理报告 (report.md)", report_url, new_tab=True).classes(
                        "bg-indigo-600 hover:bg-indigo-700 text-white text-xs px-3 py-1.5 rounded-lg font-semibold shadow-sm no-underline"
                    )
            except ValueError:
                pass
                
            if zip_file_path.exists():
                try:
                    rel_zip = zip_file_path.relative_to(paths.BASE_DIR)
                    zip_url = f"/download/{rel_zip.as_posix()}"
                    with self.csv_closing_download_container:
                        ui.link("📦 下载全部整理件 (ZIP 打包档)", zip_url, new_tab=True).classes(
                            "bg-amber-600 hover:bg-amber-700 text-white text-xs px-3 py-1.5 rounded-lg font-semibold shadow-sm no-underline font-bold"
                        )
                except ValueError:
                    pass
                    
            self.csv_closing_download_container.visible = True
            ui.notify(f"整理成功！提取出 {len(all_closing_trades)} 笔平仓成交数据。", type="positive", position="top")
            log_action(f"模块 12 执行成功：时间段为 {self.csv_closing_start_date.value or '未限定'} - {self.csv_closing_end_date.value or '未限定'}，匹配到 {len(all_closing_trades)} 笔平仓明细并已生成 ZIP")
            
        except Exception as err:
            self.csv_closing_status.set_text(f"整理失败: {str(err)}")
            ui.notify(f"数据整理失败: {str(err)}", type="negative", position="top")
            
        finally:
            await asyncio.sleep(5)
            if self.csv_closing_progress:
                self.csv_closing_progress.visible = False
            if self.csv_closing_status:
                self.csv_closing_status.visible = False
