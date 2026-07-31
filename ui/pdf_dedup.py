import asyncio
from pathlib import Path
from nicegui import ui, events
from ui.app_state import AppState
import config.paths as paths
from utils.pdf_check import PDFDeduplicator
from utils.report_generator import generate_audit_report
from utils.sys_utils import create_zip_archive
from ui.sys_logs import log_action

class PDFDedupDialog:
    def __init__(self, state: AppState) -> None:
        self.state = state
        self.dialog = None
        self.last_pdf_dedup_upload_time = 0.0
        
        self.pdf_dedup_file_select = None
        self.client_pdf_dedup_select = None
        self.pdf_dedup_progress = None
        self.pdf_dedup_status = None
        self.pdf_dedup_local_dir_input = None
        self.pdf_dedup_out_dir_input = None
        self.pdf_dedup_source_type = None
        self.pdf_dedup_passwords_input = None
        self.pdf_dedup_table = None
        self.pdf_dedup_results_container = None
        self.pdf_dedup_download_container = None
        self.build()
        
    def build(self) -> None:
        with ui.dialog() as self.dialog:
            with ui.card().classes("w-[920px] max-w-full p-6 gap-4 bg-white rounded-xl shadow-2xl"):
                with ui.row().classes("w-full justify-between items-center"):
                    with ui.row().classes("items-center gap-2"):
                        ui.icon("find_in_page", size="1.8rem").classes("text-indigo-600")
                        ui.label("PDF 查重与去密控制台").classes("text-lg font-bold text-slate-800")
                    ui.button(icon="close", on_click=self.dialog.close).props("flat round dense").classes("text-slate-400")
                
                ui.separator()
                
                ui.label("步骤 1：选择文件存储位置环境").classes("text-xs font-bold text-slate-500 uppercase tracking-wide")
                self.pdf_dedup_source_type = ui.toggle(
                    options={
                        "server": "本机/Linux后端",
                        "client": "浏览器客户端"
                    },
                    value="server"
                ).classes("w-full")
                
                # --- 本机/后端服务器 区域 ---
                with ui.column().classes("w-full gap-3") as server_section:
                    with ui.row().classes("w-full gap-4"):
                        self.pdf_dedup_local_dir_input = ui.input(
                            label="输入 Linux 后端 PDF 待处理的文件夹路径",
                            value=str(paths.INPUT_PDF_DIR),
                            on_change=self.refresh_pdf_dedup_list
                        ).classes("flex-1")
                        self.pdf_dedup_out_dir_input = ui.input(
                            label="去密后 PDF 存放的文件夹路径",
                            value=str(paths.OUTPUT_PDF_DECRYPT_DIR)
                        ).classes("flex-1")
                    
                    ui.label("选择待处理的 PDF 文件").classes("text-xs font-bold text-slate-500 uppercase tracking-wide")
                    self.pdf_dedup_file_select = ui.select(
                        options=["[全部PDF文件]"],
                        value="[全部PDF文件]",
                        label="选择待处理的 PDF 文件"
                    ).classes("w-full")
                    
                # --- 浏览器客户端 区域 ---
                with ui.column().classes("w-full gap-3") as client_section:
                    ui.label("选择并上传客户端电脑的 PDF 文件").classes("text-xs font-bold text-slate-500 uppercase tracking-wide")
                    ui.upload(
                        label="可拖拽 PDF 文件至此处上传",
                        auto_upload=True,
                        multiple=True,
                        on_upload=self.on_pdf_dedup_upload
                    ).classes("w-full border border-dashed border-slate-200 rounded-xl p-1").props("accept=.pdf")
                    
                    ui.label("选择已上传的 PDF 账单").classes("text-xs font-bold text-slate-500 uppercase tracking-wide")
                    self.client_pdf_dedup_select = ui.select(
                        options=["[全部已上傳PDF文件]"],
                        value="[全部已上傳PDF文件]",
                        label="选择已上传的 PDF 账单"
                    ).classes("w-full")
                    
                server_section.bind_visibility_from(self.pdf_dedup_source_type, "value", value="server")
                client_section.bind_visibility_from(self.pdf_dedup_source_type, "value", value="client")
                
                # 新增密碼輸入框
                self.pdf_dedup_passwords_input = ui.input(
                    label="PDF 解密密码（选填，多个密码请用英文逗号分隔）",
                    placeholder="例如: 123456, pwd888, mysecret"
                ).classes("w-full")
                
                with ui.row().classes("w-full items-start gap-2 p-3 bg-indigo-50 rounded-lg border border-indigo-200"):
                    ui.icon("info", size="1rem").classes("text-indigo-600 mt-0.5 shrink-0")
                    ui.label(
                        "查重及去密原理：支持多密码批处理解密；若 PDF 未加密则直接处理。对解密后的 PDF 流进行 SHA-256 哈希比对，智能跳过重复下载的账单，并保留唯一件于 output/pdf 目录下。"
                    ).classes("text-xs text-indigo-700 leading-relaxed")
                    
                self.pdf_dedup_progress = ui.linear_progress(value=0.0, show_value=False).classes("w-full rounded-full")
                self.pdf_dedup_progress.visible = False
                self.pdf_dedup_status = ui.label("等待启动...").classes("text-xs text-slate-500 font-mono")
                self.pdf_dedup_status.visible = False
                
                # 去密查重结果表格
                with ui.column().classes("w-full gap-2") as self.pdf_dedup_results_container:
                    ui.label("查重与去密审计结果").classes("text-xs font-bold text-slate-700 uppercase tracking-wide")
                    columns = [
                        {"name": "file_name", "label": "文件名", "field": "file_name", "align": "left"},
                        {"name": "file_size_kb", "label": "大小(KB)", "field": "file_size_kb", "align": "right"},
                        {"name": "encryption_status", "label": "加密状态", "field": "encryption_status", "align": "center"},
                        {"name": "sha256_short", "label": "SHA-256", "field": "sha256_short", "align": "center"},
                        {"name": "status", "label": "唯一性", "field": "status", "align": "center"},
                        {"name": "action", "label": "处理动作", "field": "action", "align": "center"},
                    ]
                    self.pdf_dedup_table = ui.table(columns=columns, rows=[], row_key='file_name').classes("w-full max-h-60 overflow-y-auto")
                self.pdf_dedup_results_container.visible = False
                
                self.pdf_dedup_download_container = ui.row().classes("w-full justify-center gap-2 mt-2")
                self.pdf_dedup_download_container.visible = False
                
                with ui.row().classes("w-full justify-end gap-2 mt-4"):
                    ui.button("取消", on_click=self.dialog.close).props("flat").classes("text-slate-500 text-sm")
                    ui.button("开始查重与去密", on_click=self.run_pdf_deduplication).classes(
                        "bg-indigo-600 hover:bg-indigo-700 text-white px-5 py-2.5 rounded-lg text-sm font-semibold shadow-sm"
                    )

    def open(self) -> None:
        self.refresh_pdf_dedup_list()
        self.dialog.open()

    def update_paths(self) -> None:
        if self.pdf_dedup_local_dir_input:
            self.pdf_dedup_local_dir_input.set_value(str(paths.INPUT_PDF_DIR))
        if self.pdf_dedup_out_dir_input:
            self.pdf_dedup_out_dir_input.set_value(str(paths.OUTPUT_PDF_DECRYPT_DIR))
        self.refresh_pdf_dedup_list()

    def refresh_pdf_dedup_list(self) -> None:
        if self.pdf_dedup_file_select:
            path_str = self.pdf_dedup_local_dir_input.value if self.pdf_dedup_local_dir_input and self.pdf_dedup_local_dir_input.value else str(paths.INPUT_PDF_DIR)
            input_dir = Path(path_str)
            try:
                if input_dir.exists() and input_dir.is_dir():
                    files = [f.name for f in input_dir.iterdir() if f.is_file() and f.suffix.lower() == ".pdf"]
                    self.pdf_dedup_file_select.options = ["[全部PDF文件]"] + files
                else:
                    self.pdf_dedup_file_select.options = ["[全部PDF文件]"]
            except Exception:
                self.pdf_dedup_file_select.options = ["[全部PDF文件]"]
            self.pdf_dedup_file_select.update()

    async def on_pdf_dedup_upload(self, e: events.UploadEventArguments) -> None:
        try:
            import time
            input_dir = paths.INPUT_PDF_DIR / "client_dedup_temp"
            input_dir.mkdir(parents=True, exist_ok=True)
            
            now = time.time()
            if now - self.last_pdf_dedup_upload_time > 2.0:
                for f in input_dir.iterdir():
                    if f.is_file() and f.name != ".gitkeep":
                        try:
                            f.unlink()
                        except Exception:
                            pass
                if self.client_pdf_dedup_select:
                    self.client_pdf_dedup_select.options = ["[全部已上傳PDF文件]"]
                    self.client_pdf_dedup_select.value = "[全部已上傳PDF文件]"
                    self.client_pdf_dedup_select.update()
                if self.pdf_dedup_download_container:
                    self.pdf_dedup_download_container.clear()
                    self.pdf_dedup_download_container.visible = False
                if self.pdf_dedup_progress:
                    self.pdf_dedup_progress.set_value(0.0)
                    self.pdf_dedup_progress.visible = False
                if self.pdf_dedup_status:
                    self.pdf_dedup_status.set_text("")
                    self.pdf_dedup_status.visible = False
                if self.pdf_dedup_table:
                    self.pdf_dedup_table.rows = []
                    self.pdf_dedup_table.update()
                if self.pdf_dedup_results_container:
                    self.pdf_dedup_results_container.visible = False
            self.last_pdf_dedup_upload_time = now

            file_path = input_dir / Path(e.file.name).name
            data = await e.file.read()
            file_path.write_bytes(data)
            ui.notify(f"PDF 文件 {Path(e.file.name).name} 上傳成功！已暫存至後端。", type="positive", position="top")
            
            files = [f.name for f in input_dir.iterdir() if f.is_file() and f.suffix.lower() == ".pdf"]
            self.client_pdf_dedup_select.options = ["[全部已上傳PDF文件]"] + files
            self.client_pdf_dedup_select.value = "[全部已上傳PDF文件]"
            self.client_pdf_dedup_select.update()
        except Exception as err:
            ui.notify(f"PDF 保存失敗: {str(err)}", type="negative", position="top")

    async def run_pdf_deduplication(self) -> None:
        if not self.pdf_dedup_file_select or not self.client_pdf_dedup_select or not self.pdf_dedup_progress or not self.pdf_dedup_status or not self.pdf_dedup_table:
            return
            
        mode = self.pdf_dedup_source_type.value
        preserve_files = []
        if mode == "server":
            selected = self.pdf_dedup_file_select.value
            path_str = self.pdf_dedup_local_dir_input.value if self.pdf_dedup_local_dir_input and self.pdf_dedup_local_dir_input.value else str(paths.INPUT_PDF_DIR)
            input_dir = Path(path_str)
            if selected == "[全部PDF文件]":
                try:
                    preserve_files = [input_dir / f.name for f in input_dir.iterdir() if f.is_file() and f.suffix.lower() == ".pdf"]
                except Exception:
                    pass
            elif selected:
                preserve_files = [input_dir / selected]
        else:
            selected = self.client_pdf_dedup_select.value
            input_dir = paths.INPUT_PDF_DIR / "client_dedup_temp"
            if selected == "[全部已上傳PDF文件]":
                try:
                    preserve_files = [input_dir / f.name for f in input_dir.iterdir() if f.is_file() and f.suffix.lower() == ".pdf"]
                except Exception:
                    pass
            elif selected:
                preserve_files = [input_dir / selected]

        self.pdf_dedup_progress.set_value(0.0)
        self.pdf_dedup_progress.visible = True
        self.pdf_dedup_status.visible = True
        self.pdf_dedup_status.set_text("正在啟動 PDF 查重與去密批次處理...")
        
        self.pdf_dedup_download_container.clear()
        self.pdf_dedup_download_container.visible = False
        self.pdf_dedup_table.rows = []
        self.pdf_dedup_table.update()
        self.pdf_dedup_results_container.visible = False
        
        pwd_str = self.pdf_dedup_passwords_input.value or ""
        passwords = [p.strip() for p in pwd_str.split(",") if p.strip()]

        def on_progress(ratio: float, msg: str) -> None:
            try:
                if self.pdf_dedup_progress and self.pdf_dedup_status:
                    self.pdf_dedup_progress.set_value(ratio)
                    self.pdf_dedup_status.set_text(msg)
            except (RuntimeError, ValueError, KeyError) as ui_err:
                print(f"[PDF Dedup Progress UI Warning] {ui_err}")

        try:
            if mode == "server":
                out_dir = paths.OUTPUT_PDF_DIR
                decrypt_path_str = self.pdf_dedup_out_dir_input.value if self.pdf_dedup_out_dir_input and self.pdf_dedup_out_dir_input.value else str(paths.OUTPUT_PDF_DECRYPT_DIR)
                decrypt_dir = Path(decrypt_path_str)
                report_out_dir = paths.OUTPUT_PDF_DIR
            else:
                out_dir = paths.OUTPUT_PDF_DIR / "client_dedup_out"
                decrypt_dir = paths.OUTPUT_PDF_DECRYPT_DIR / "client_dedup_out"
                report_out_dir = paths.OUTPUT_PDF_DIR / "client_dedup_out"
            
            out_dir.mkdir(parents=True, exist_ok=True)
            decrypt_dir.mkdir(parents=True, exist_ok=True)
            report_out_dir.mkdir(parents=True, exist_ok=True)
            dedup = PDFDeduplicator(output_dir=out_dir, decrypt_dir=decrypt_dir)
            
            if mode == "server":
                selected = self.pdf_dedup_file_select.value
                path_str = self.pdf_dedup_local_dir_input.value if self.pdf_dedup_local_dir_input and self.pdf_dedup_local_dir_input.value else str(paths.INPUT_PDF_DIR)
                input_dir = Path(path_str)
                
                if selected == "[全部PDF文件]":
                    files = [input_dir / f.name for f in input_dir.iterdir() if f.is_file() and f.suffix.lower() == ".pdf"]
                else:
                    files = [input_dir / selected] if selected else []
            else:
                selected = self.client_pdf_dedup_select.value
                input_dir = paths.INPUT_PDF_DIR / "client_dedup_temp"
                
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
            
            report_file = generate_audit_report(results, report_out_dir)
            
            for r in results:
                sha = r.get("sha256")
                r["sha256_short"] = f"{sha[:12]}..." if sha else "None"
            
            self.pdf_dedup_table.rows = results
            self.pdf_dedup_table.update()
            self.pdf_dedup_results_container.visible = True
            
            try:
                rel_report = report_file.relative_to(paths.BASE_DIR)
                report_url = f"/download/{rel_report.as_posix()}"
                with self.pdf_dedup_download_container:
                    ui.link("📊 下載審計報告 (report.md)", report_url, new_tab=True).classes(
                        "bg-indigo-600 hover:bg-indigo-700 text-white text-xs px-3 py-1.5 rounded-lg font-semibold shadow-sm no-underline"
                    )
            except ValueError:
                pass

            kept_files = []
            for r in results:
                if r["status"] == "Unique" and r["action"] in ("Kept (已保留)", "Kept (已保留並去密)"):
                    saved_file = out_dir / r["file_name"]
                    if saved_file.exists():
                        kept_files.append(saved_file)

            if kept_files:
                zip_file_path = (paths.OUTPUT_PDF_DIR if mode == "server" else paths.OUTPUT_PDF_DIR / "client_dedup_out") / "deduplicated_files.zip"
                if zip_file_path.exists():
                    zip_file_path.unlink()
                
                await asyncio.to_thread(create_zip_archive, kept_files, zip_file_path)
                
                if zip_file_path.exists():
                    try:
                        rel_zip = zip_file_path.relative_to(paths.BASE_DIR)
                        zip_url = f"/download/{rel_zip.as_posix()}"
                        with self.pdf_dedup_download_container:
                            ui.link("📦 下載全部保留件 (ZIP 打包檔)", zip_url, new_tab=True).classes(
                                "bg-amber-600 hover:bg-amber-700 text-white text-xs px-3 py-1.5 rounded-lg font-semibold shadow-sm no-underline font-bold"
                            )
                    except ValueError:
                        pass
                                
            self.pdf_dedup_download_container.visible = True
            self.pdf_dedup_status.set_text("PDF 查重與去密處理完成！")
            ui.notify("查重清理完成！已生成審計報告並去密保留唯一件。", type="positive", position="top")
        except Exception as err:
            try:
                self.pdf_dedup_status.set_text(f"查重失敗: {str(err)}")
                ui.notify(f"查重失敗: {str(err)}", type="negative", position="top")
            except (RuntimeError, ValueError, KeyError) as ui_err:
                print(f"[PDF Dedup Error UI Warning] {ui_err}")
        finally:
            await asyncio.sleep(5)
            try:
                if self.pdf_dedup_progress:
                    self.pdf_dedup_progress.visible = False
                if self.pdf_dedup_status:
                    self.pdf_dedup_status.visible = False
            except (RuntimeError, ValueError, KeyError) as ui_err:
                print(f"[PDF Dedup Finally UI Warning] {ui_err}")
