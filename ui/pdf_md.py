import asyncio
from pathlib import Path
from nicegui import ui, events
from ui.app_state import AppState
import config.paths as paths
from ui.sys_logs import log_action

from .pdf_md_converters import run_pdf_to_md_conversion, run_md_to_csv_conversion

class PDFMDDialog:
    # Bind conversion methods
    run_pdf_to_md_conversion = run_pdf_to_md_conversion
    run_md_to_csv_conversion = run_md_to_csv_conversion

    def __init__(self, state: AppState) -> None:
        self.state = state
        self.dialog = None
        self.last_pdf_upload_time = 0.0
        
        self.pdf_file_select = None
        self.client_pdf_select = None
        self.pdf_progress = None
        self.pdf_status = None
        self.pdf_local_dir_input = None
        self.pdf_source_type = None
        self.pdf_log_board = None
        self.pdf_log_container = None
        self.pdf_download_container = None
        self.build()
        
    def build(self) -> None:
        with ui.dialog() as self.dialog:
            with ui.card().classes("w-[800px] max-w-full p-6 gap-4 bg-white rounded-xl shadow-2xl"):
                with ui.row().classes("w-full justify-between items-center"):
                    with ui.row().classes("items-center gap-2"):
                        ui.icon("description", size="1.8rem").classes("text-indigo-600")
                        ui.label("PDF 结单提取控制台").classes("text-lg font-bold text-slate-800")
                    ui.button(icon="close", on_click=self.dialog.close).props("flat round dense").classes("text-slate-400")
                
                ui.separator()
                
                ui.label("步骤 1：选择文件存储位置环境").classes("text-xs font-bold text-slate-500 uppercase tracking-wide")
                self.pdf_source_type = ui.toggle(
                    options={
                        "server": "本机/Linux后端",
                        "client": "浏览器客户端"
                    },
                    value="server"
                ).classes("w-full")
                
                # --- 本机/后端服务器 区域 ---
                with ui.column().classes("w-full gap-3") as server_section:
                    ui.label("本机 PDF 文件夹绝对路径").classes("text-xs font-bold text-slate-500 uppercase tracking-wide")
                    self.pdf_local_dir_input = ui.input(
                        label="输入 Linux 后端 PDF 账单所在的文件夹路径",
                        value=str(paths.INPUT_PDF_DIR),
                        on_change=self.refresh_pdf_list
                    ).classes("w-full")
                    
                    ui.label("选择待解析的 PDF 文件").classes("text-xs font-bold text-slate-500 uppercase tracking-wide")
                    self.pdf_file_select = ui.select(
                        options=["[全部PDF文件]"],
                        value="[全部PDF文件]",
                        label="选择待解析的 PDF 文件"
                    ).classes("w-full")
                    
                # --- 浏览器客户端 区域 ---
                with ui.column().classes("w-full gap-3") as client_section:
                    ui.label("选择并上传客户端电脑的 PDF 文件").classes("text-xs font-bold text-slate-500 uppercase tracking-wide")
                    ui.upload(
                        label="可拖拽 PDF 文件至此处上传",
                        auto_upload=True,
                        multiple=True,
                        on_upload=self.on_pdf_upload
                    ).classes("w-full border border-dashed border-slate-200 rounded-xl p-1").props("accept=.pdf")
                    
                    ui.label("选择已上传的 PDF 账单").classes("text-xs font-bold text-slate-500 uppercase tracking-wide")
                    self.client_pdf_select = ui.select(
                        options=["[全部已上传PDF文件]"],
                        value="[全部已上传PDF文件]",
                        label="选择已上传 of PDF 账单"
                    ).classes("w-full")
                    
                server_section.bind_visibility_from(self.pdf_source_type, "value", value="server")
                client_section.bind_visibility_from(self.pdf_source_type, "value", value="client")
                
                with ui.row().classes("w-full items-start gap-2 p-3 bg-indigo-50 rounded-lg border border-indigo-200"):
                    ui.icon("info", size="1rem").classes("text-indigo-600 mt-0.5 shrink-0")
                    ui.label(
                        "对账审计防线：内置自适应表格提取引擎、三层漏斗防线（防重叠去重、多行缝合、降级备用）、双重勾稽核查对账。自动将结单结构化转化为 Markdown，并可一键转换为标准的 CSV 交易清单。"
                    ).classes("text-xs text-indigo-700 leading-relaxed")
                    
                self.pdf_progress = ui.linear_progress(value=0.0, show_value=False).classes("w-full rounded-full")
                self.pdf_progress.visible = False
                self.pdf_status = ui.label("等待启动...").classes("text-xs text-slate-500 font-mono")
                self.pdf_status.visible = False
                
                # 新增：运行审计日志看板
                with ui.card().classes("w-full h-40 p-3 bg-slate-950 text-slate-200 rounded-xl overflow-y-auto border border-slate-800") as log_board:
                    self.pdf_log_container = ui.column().classes("w-full gap-1 mt-1")
                    self.pdf_log_board = log_board
                self.pdf_log_board.visible = False
                
                self.pdf_download_container = ui.row().classes("w-full justify-center gap-2 mt-2")
                self.pdf_download_container.visible = False
                
                with ui.row().classes("w-full justify-end gap-2 mt-4"):
                    ui.button("取消", on_click=self.dialog.close).props("flat").classes("text-slate-500 text-sm")
                    ui.button("执行 PDF ➔ MD", on_click=self.run_pdf_to_md_conversion).classes(
                        "bg-indigo-600 hover:bg-indigo-700 text-white px-4 py-2.5 rounded-lg text-xs font-semibold shadow-sm"
                    )
                    ui.button("执行 MD ➔ CSV", on_click=self.run_md_to_csv_conversion).classes(
                        "bg-teal-600 hover:bg-teal-700 text-white px-4 py-2.5 rounded-lg text-xs font-semibold shadow-sm"
                    )

    def open(self) -> None:
        self.refresh_pdf_list()
        self.dialog.open()

    def update_paths(self) -> None:
        if self.pdf_local_dir_input:
            self.pdf_local_dir_input.set_value(str(paths.INPUT_PDF_DIR))
        self.refresh_pdf_list()

    def refresh_pdf_list(self) -> None:
        if self.pdf_file_select:
            path_str = self.pdf_local_dir_input.value if self.pdf_local_dir_input and self.pdf_local_dir_input.value else str(paths.INPUT_PDF_DIR)
            input_dir = Path(path_str)
            try:
                if input_dir.exists() and input_dir.is_dir():
                    files = [f.name for f in input_dir.iterdir() if f.is_file() and f.suffix.lower() == ".pdf"]
                    self.pdf_file_select.options = ["[全部PDF文件]"] + files
                else:
                    self.pdf_file_select.options = ["[全部PDF文件]"]
            except Exception:
                self.pdf_file_select.options = ["[全部PDF文件]"]
            self.pdf_file_select.update()

    async def on_pdf_upload(self, e: events.UploadEventArguments) -> None:
        try:
            import time
            input_dir = paths.INPUT_PDF_DIR / "client_pdf_temp"
            input_dir.mkdir(parents=True, exist_ok=True)
            
            now = time.time()
            if now - self.last_pdf_upload_time > 2.0:
                for f in input_dir.iterdir():
                    if f.is_file() and f.name != ".gitkeep":
                        try:
                            f.unlink()
                        except Exception:
                            pass
                if self.client_pdf_select:
                    self.client_pdf_select.options = ["[全部已上传PDF文件]"]
                    self.client_pdf_select.value = "[全部已上传PDF文件]"
                    self.client_pdf_select.update()
                if self.pdf_download_container:
                    self.pdf_download_container.clear()
                    self.pdf_download_container.visible = False
                if self.pdf_progress:
                    self.pdf_progress.set_value(0.0)
                    self.pdf_progress.visible = False
                if self.pdf_status:
                    self.pdf_status.set_text("")
                    self.pdf_status.visible = False
                if self.pdf_log_container:
                    self.pdf_log_container.clear()
                if self.pdf_log_board:
                    self.pdf_log_board.visible = False
            self.last_pdf_upload_time = now

            file_path = input_dir / Path(e.file.name).name
            data = await e.file.read()
            file_path.write_bytes(data)
            ui.notify(f"PDF 文件 {Path(e.file.name).name} 上传成功！已暂存至后端。", type="positive", position="top")
            
            files = [f.name for f in input_dir.iterdir() if f.is_file() and f.suffix.lower() == ".pdf"]
            self.client_pdf_select.options = ["[全部已上传PDF文件]"] + files
            self.client_pdf_select.value = "[全部已上传PDF文件]"
            self.client_pdf_select.update()
        except Exception as err:
            ui.notify(f"PDF 保存失败: {str(err)}", type="negative", position="top")
