import asyncio
from pathlib import Path
from nicegui import ui, events
from ui.app_state import AppState
import config.paths as paths
from utils.csv_excel import BatchConverter
from utils.report_generator import generate_csv_excel_report
from utils.sys_utils import create_zip_archive
from ui.sys_logs import log_action

class CSVExcelDialog:
    def __init__(self, state: AppState) -> None:
        self.state = state
        self.dialog = None
        self.last_csv_upload_time = 0.0
        
        self.file_select = None
        self.client_file_select = None
        self.dialog_progress = None
        self.dialog_status = None
        self.local_dir_input = None
        self.source_type = None
        self.csv_download_container = None
        self.csv_report_preview = None
        self.build()
        
    def build(self) -> None:
        with ui.dialog() as self.dialog:
            with ui.card().classes("w-[550px] p-6 gap-4 bg-white rounded-xl shadow-2xl"):
                with ui.row().classes("w-full justify-between items-center"):
                    with ui.row().classes("items-center gap-2"):
                        ui.icon("swap_horiz", size="1.8rem").classes("text-indigo-600")
                        ui.label("CSV & Excel 互转控制台").classes("text-lg font-bold text-slate-800")
                    ui.button(icon="close", on_click=self.dialog.close).props("flat round dense").classes("text-slate-400")
                
                ui.separator()
                
                ui.label("步骤 1：选择文件存储位置环境").classes("text-xs font-bold text-slate-500 uppercase tracking-wide")
                self.source_type = ui.toggle(
                    options={
                        "server": "本机/Linux后端",
                        "client": "浏览器客户端"
                    },
                    value="server"
                ).classes("w-full")
                
                with ui.column().classes("w-full gap-3") as server_section:
                    ui.label("本机文件夹绝对路径").classes("text-xs font-bold text-slate-500 uppercase tracking-wide")
                    self.local_dir_input = ui.input(
                        label="输入 Linux 后端 CSV 所在的文件夹路径",
                        value=str(paths.INPUT_CSV_DIR),
                        on_change=self.refresh_file_list
                    ).classes("w-full")
                    
                    ui.label("选择待转换的 CSV 文件").classes("text-xs font-bold text-slate-500 uppercase tracking-wide")
                    self.file_select = ui.select(
                        options=["[全部文件]"],
                        value="[全部文件]",
                        label="选择后端的 CSV 文件"
                    ).classes("w-full")
                    
                with ui.column().classes("w-full gap-3") as client_section:
                    ui.label("选择并上传客户端电脑的 CSV 文件").classes("text-xs font-bold text-slate-500 uppercase tracking-wide")
                    ui.upload(
                        label="可拖拽 CSV 文件至此处上传",
                        auto_upload=True,
                        multiple=True,
                        on_upload=self.on_file_upload
                    ).classes("w-full border border-dashed border-slate-200 rounded-xl p-1").props("accept=.csv")
                    
                    ui.label("选择已上传的 CSV 账单").classes("text-xs font-bold text-slate-500 uppercase tracking-wide")
                    self.client_file_select = ui.select(
                        options=["[全部已上传文件]"],
                        value="[全部已上传文件]",
                        label="选择已上传 of CSV 账单"
                    ).classes("w-full")
                    
                server_section.bind_visibility_from(self.source_type, "value", value="server")
                client_section.bind_visibility_from(self.source_type, "value", value="client")
                
                with ui.row().classes("w-full items-start gap-2 p-3 bg-indigo-50 rounded-lg border border-indigo-200"):
                    ui.icon("info", size="1rem").classes("text-indigo-600 mt-0.5 shrink-0")
                    ui.label(
                        "无损数值转换：强制对所有单元格以字符串读取。企业社会信用代码、发票号、身份证、银行账号等长数字不会丢失前导零，绝对避免科学计数法截断。"
                    ).classes("text-xs text-indigo-700 leading-relaxed")
                    
                self.dialog_progress = ui.linear_progress(value=0.0, show_value=False).classes("w-full rounded-full")
                self.dialog_progress.visible = False
                self.dialog_status = ui.label("等待启动...").classes("text-xs text-slate-500 font-mono")
                self.dialog_status.visible = False
                
                self.csv_download_container = ui.row().classes("w-full justify-center gap-2 mt-2")
                self.csv_download_container.visible = False
                
                self.csv_report_preview = ui.markdown().classes("w-full p-3 bg-slate-50 border border-slate-200 rounded-lg text-xs max-h-40 overflow-y-auto mt-2")
                self.csv_report_preview.visible = False
                
                with ui.row().classes("w-full justify-end gap-2 mt-4"):
                    ui.button("取消", on_click=self.dialog.close).props("flat").classes("text-slate-500 text-sm")
                    ui.button("CSV → Excel 转换", on_click=self.run_select_conversion).classes(
                        "bg-indigo-600 hover:bg-indigo-700 text-white px-5 py-2.5 rounded-lg text-sm font-semibold shadow-sm"
                    )

    def open(self) -> None:
        self.refresh_file_list()
        self.dialog.open()

    def update_paths(self) -> None:
        if self.local_dir_input:
            self.local_dir_input.set_value(str(paths.INPUT_CSV_DIR))
        self.refresh_file_list()

    def refresh_file_list(self) -> None:
        if self.file_select:
            path_str = self.local_dir_input.value if self.local_dir_input and self.local_dir_input.value else str(paths.INPUT_CSV_DIR)
            input_dir = Path(path_str)
            try:
                if input_dir.exists() and input_dir.is_dir():
                    files = [f.name for f in input_dir.iterdir() if f.is_file() and f.suffix.lower() == ".csv"]
                    self.file_select.options = ["[全部文件]"] + files
                else:
                    self.file_select.options = ["[全部文件]"]
            except Exception:
                self.file_select.options = ["[全部文件]"]
            self.file_select.update()

    async def on_file_upload(self, e: events.UploadEventArguments) -> None:
        try:
            import time
            input_dir = paths.INPUT_CSV_DIR / "client_temp"
            input_dir.mkdir(parents=True, exist_ok=True)
            
            now = time.time()
            if now - self.last_csv_upload_time > 2.0:
                for f in input_dir.iterdir():
                    if f.is_file() and f.name != ".gitkeep":
                        try:
                            f.unlink()
                        except Exception:
                            pass
                if self.client_file_select:
                    self.client_file_select.options = ["[全部已上传文件]"]
                    self.client_file_select.value = "[全部已上传文件]"
                    self.client_file_select.update()
                if self.csv_download_container:
                    self.csv_download_container.clear()
                    self.csv_download_container.visible = False
                if self.csv_report_preview:
                    self.csv_report_preview.visible = False
                    self.csv_report_preview.set_content("")
                if self.dialog_progress:
                    self.dialog_progress.set_value(0.0)
                    self.dialog_progress.visible = False
                if self.dialog_status:
                    self.dialog_status.set_text("")
                    self.dialog_status.visible = False
            self.last_csv_upload_time = now

            file_path = input_dir / Path(e.file.name).name
            data = await e.file.read()
            file_path.write_bytes(data)
            ui.notify(f"文件 {Path(e.file.name).name} 上传成功！已暂存至后端。", type="positive", position="top")
            
            files = [f.name for f in input_dir.iterdir() if f.is_file() and f.suffix.lower() == ".csv"]
            self.client_file_select.options = ["[全部已上传文件]"] + files
            self.client_file_select.value = "[全部已上传文件]"
            self.client_file_select.update()
        except Exception as err:
            ui.notify(f"文件保存失败: {str(err)}", type="negative", position="top")

    async def run_select_conversion(self) -> None:
        if not self.file_select or not self.client_file_select or not self.dialog_progress or not self.dialog_status:
            return
            
        mode = self.source_type.value
        preserve_files = []
        if mode == "server":
            selected = self.file_select.value
            path_str = self.local_dir_input.value if self.local_dir_input and self.local_dir_input.value else str(paths.INPUT_CSV_DIR)
            input_dir = Path(path_str)
            if selected == "[全部文件]":
                try:
                    preserve_files = [input_dir / f.name for f in input_dir.iterdir() if f.is_file() and f.suffix.lower() == ".csv"]
                except Exception:
                    pass
            elif selected:
                preserve_files = [input_dir / selected]
        else:
            selected = self.client_file_select.value
            input_dir = paths.INPUT_CSV_DIR / "client_temp"
            if selected == "[全部已上传文件]":
                try:
                    preserve_files = [input_dir / f.name for f in input_dir.iterdir() if f.is_file() and f.suffix.lower() == ".csv"]
                except Exception:
                    pass
            elif selected:
                preserve_files = [input_dir / selected]

        self.dialog_progress.set_value(0.0)
        self.dialog_progress.visible = True
        self.dialog_status.visible = True
        self.dialog_status.set_text("正在启动转换...")
        
        self.csv_download_container.clear()
        self.csv_download_container.visible = False
        
        if self.csv_report_preview:
            self.csv_report_preview.visible = False
            self.csv_report_preview.set_content("")
        
        def on_progress(current: int, total: int, file_name: str, success: bool, message: str) -> None:
            try:
                if self.dialog_progress and self.dialog_status:
                    if total > 0:
                        self.dialog_progress.set_value(current / total)
                        self.dialog_status.set_text(f"进度 ({current}/{total}): {file_name}")
                    else:
                        self.dialog_status.set_text(message)
                    ui.notify(message, type="positive" if success else "negative", position="top")
            except RuntimeError as e:
                if "deleted" not in str(e) and "parent element" not in str(e):
                    raise
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
                out_zip_dir = paths.OUTPUT_EXCEL_DIR
            else:
                out_zip_dir = paths.OUTPUT_EXCEL_DIR / "client_temp"
            out_zip_dir.mkdir(parents=True, exist_ok=True)

            if mode == "server":
                selected = self.file_select.value
                path_str = self.local_dir_input.value if self.local_dir_input and self.local_dir_input.value else str(paths.INPUT_CSV_DIR)
                input_dir = Path(path_str)
                
                converter = BatchConverter(input_dir=input_dir, output_dir=paths.OUTPUT_EXCEL_DIR)
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
                selected = self.client_file_select.value
                input_dir = paths.INPUT_CSV_DIR / "client_temp"
                
                converter = BatchConverter(input_dir=input_dir, output_dir=paths.OUTPUT_EXCEL_DIR)
                if selected == "[全部已上传文件]":
                    files = [f for f in input_dir.iterdir() if f.is_file() and f.suffix.lower() == ".csv"]
                    total_files = len(files)
                    if total_files == 0:
                        on_progress(0, 0, "", True, "未找到任何已上传的文件。")
                        return
                    for idx, file_path in enumerate(files, start=1):
                        try:
                            try:
                                out_path = await converter.convert_file(file_path, mode="csv_to_excel")
                                on_progress(idx, total_files, file_path.name, True, f"转换成功: {file_path.name}")
                                if out_path.exists():
                                    output_files.append(out_path)
                            except Exception as e:
                                on_progress(idx, total_files, file_path.name, False, f"转换失败: {str(e)}")
                        finally:
                            await asyncio.sleep(0.05)
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
            
            report_file = None
            if conversion_logs:
                report_file = generate_csv_excel_report(conversion_logs, out_zip_dir, direction="CSV ➔ Excel (无损数值转换)")
                try:
                    rel_report = report_file.relative_to(paths.BASE_DIR)
                    report_url = f"/download/{rel_report.as_posix()}"
                    with self.csv_download_container:
                        ui.link("📊 下载转换报告 (report.md)", report_url, new_tab=True).classes(
                            "bg-indigo-600 hover:bg-indigo-700 text-white text-xs px-3 py-1.5 rounded-lg font-semibold shadow-sm no-underline"
                        )
                except ValueError:
                    pass
                
                if report_file and report_file.exists() and self.csv_report_preview:
                    try:
                        report_text = report_file.read_text(encoding="utf-8")
                        self.csv_report_preview.set_content(report_text)
                        self.csv_report_preview.visible = True
                    except Exception:
                        pass

            if output_files:
                zip_file_path = out_zip_dir / "converted_files.zip"
                if zip_file_path.exists():
                    zip_file_path.unlink()
                
                files_to_zip = list(output_files)
                if report_file and report_file.exists():
                    files_to_zip.append(report_file)
                    
                await asyncio.to_thread(create_zip_archive, files_to_zip, zip_file_path)
                
                if zip_file_path.exists():
                    try:
                        rel_zip = zip_file_path.relative_to(paths.BASE_DIR)
                        zip_url = f"/download/{rel_zip.as_posix()}"
                        with self.csv_download_container:
                            ui.link("📦 下载全部转换件 (ZIP 打包档)", zip_url, new_tab=True).classes(
                                "bg-amber-600 hover:bg-amber-700 text-white text-xs px-3 py-1.5 rounded-lg font-semibold shadow-sm no-underline font-bold"
                            )
                    except ValueError:
                        pass
            
            try:
                if conversion_logs or output_files:
                    self.csv_download_container.visible = True
                self.dialog_status.set_text("转换任务已完成！")
            except RuntimeError as e:
                if "deleted" not in str(e) and "parent element" not in str(e):
                    raise
        except Exception as err:
            try:
                self.dialog_status.set_text(f"转换失败: {str(err)}")
                ui.notify(f"转换失败: {str(err)}", type="negative", position="top")
            except RuntimeError:
                pass
        finally:
            try:
                await asyncio.sleep(3)
                self.dialog_progress.visible = False
                self.dialog_status.visible = False
            except RuntimeError:
                pass
