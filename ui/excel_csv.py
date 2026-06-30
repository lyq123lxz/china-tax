import asyncio
from pathlib import Path
from nicegui import ui, events
from ui.app_state import AppState
import config.paths as paths
from utils.excel_csv import ExcelToCsvConverter
from utils.report_generator import generate_csv_excel_report
from utils.sys_utils import create_zip_archive
from ui.sys_logs import log_action

class ExcelCSVDialog:
    def __init__(self, state: AppState) -> None:
        self.state = state
        self.dialog = None
        self.last_excel_upload_time = 0.0
        
        self.excel_file_select = None
        self.client_excel_file_select = None
        self.excel_dialog_progress = None
        self.excel_dialog_status = None
        self.excel_local_dir_input = None
        self.excel_source_type = None
        self.excel_download_container = None
        self.excel_report_preview = None
        self.build()
        
    def build(self) -> None:
        with ui.dialog() as self.dialog:
            with ui.card().classes("w-[580px] p-6 gap-4 bg-white rounded-xl shadow-2xl"):
                with ui.row().classes("w-full justify-between items-center"):
                    with ui.row().classes("items-center gap-2"):
                        ui.icon("table_view", size="1.8rem").classes("text-teal-600")
                        ui.label("Excel → CSV 无损拆分转换控制台").classes("text-lg font-bold text-slate-800")
                    ui.button(icon="close", on_click=self.dialog.close).props("flat round dense").classes("text-slate-400")

                ui.separator()

                ui.label("步骤 1：选择文件存储位置环境").classes("text-xs font-bold text-slate-500 uppercase tracking-wide")
                self.excel_source_type = ui.toggle(
                    options={"server": "本机/Linux后端", "client": "浏览器客户端"},
                    value="server"
                ).classes("w-full")

                with ui.column().classes("w-full gap-3") as excel_server_section:
                    ui.label("本机 Excel 文件夹绝对路径").classes("text-xs font-bold text-slate-500 uppercase tracking-wide")
                    self.excel_local_dir_input = ui.input(
                        label="输入 Linux 后端 Excel 所在的文件夹路径",
                        value=str(paths.INPUT_EXCEL_DIR),
                        on_change=self.refresh_excel_file_list
                    ).classes("w-full")

                    ui.label("选择待转换的 Excel 文件").classes("text-xs font-bold text-slate-500 uppercase tracking-wide")
                    self.excel_file_select = ui.select(
                        options=["[全部Excel文件]"],
                        value="[全部Excel文件]",
                        label="待转换的 Excel 文件 (支持 .xlsx / .xls / .xlsm)"
                    ).classes("w-full")

                with ui.column().classes("w-full gap-3") as excel_client_section:
                    ui.label("选择并上传客户端电脑的 Excel 文件").classes("text-xs font-bold text-slate-500 uppercase tracking-wide")
                    ui.upload(
                        label="可拖拽 Excel 文件至此处上传（.xlsx / .xls / .xlsm）",
                        auto_upload=True,
                        multiple=True,
                        on_upload=self.on_excel_upload
                    ).classes("w-full border border-dashed border-slate-200 rounded-xl p-1").props("accept=.xlsx,.xls,.xlsm,.xlsb")

                    ui.label("选择已上传的 Excel 文件").classes("text-xs font-bold text-slate-500 uppercase tracking-wide")
                    self.client_excel_file_select = ui.select(
                        options=["[全部已上传Excel文件]"],
                        value="[全部已上传Excel文件]",
                        label="选择已上传 of Excel 文件"
                    ).classes("w-full")

                excel_server_section.bind_visibility_from(self.excel_source_type, "value", value="server")
                excel_client_section.bind_visibility_from(self.excel_source_type, "value", value="client")

                with ui.row().classes("w-full items-start gap-2 p-3 bg-teal-50 rounded-lg border border-teal-200"):
                    ui.icon("info", size="1rem").classes("text-teal-600 mt-0.5 shrink-0")
                    ui.label(
                        "多 Sheet 自动拆分：单 Sheet 输出「原文件名.csv」；多 Sheet 分别输出「原文件名_工作表名.csv」。"
                        "所有数值以字符串读取，发票号/纳税人识别号等长数字不会丢失前导零。"
                    ).classes("text-xs text-teal-700 leading-relaxed")

                self.excel_dialog_progress = ui.linear_progress(value=0.0, show_value=False).classes("w-full rounded-full")
                self.excel_dialog_progress.visible = False
                self.excel_dialog_status = ui.label("等待启动...").classes("text-xs text-slate-500 font-mono")
                self.excel_dialog_status.visible = False

                self.excel_download_container = ui.row().classes("w-full justify-center gap-2 mt-2")
                self.excel_download_container.visible = False

                self.excel_report_preview = ui.markdown().classes("w-full p-3 bg-slate-50 border border-slate-200 rounded-lg text-xs max-h-40 overflow-y-auto mt-2")
                self.excel_report_preview.visible = False

                with ui.row().classes("w-full justify-end gap-2 mt-4"):
                    ui.button("取消", on_click=self.dialog.close).props("flat").classes("text-slate-500 text-sm")
                    ui.button("Excel → CSV 转换", on_click=self.run_excel_to_csv_conversion).classes(
                        "bg-teal-600 hover:bg-teal-700 text-white px-5 py-2.5 rounded-lg text-sm font-semibold shadow-sm"
                    )

    def open(self) -> None:
        self.refresh_excel_file_list()
        self.dialog.open()

    def update_paths(self) -> None:
        if self.excel_local_dir_input:
            self.excel_local_dir_input.set_value(str(paths.INPUT_EXCEL_DIR))
        self.refresh_excel_file_list()

    def refresh_excel_file_list(self) -> None:
        if self.excel_file_select:
            path_str = (
                self.excel_local_dir_input.value
                if self.excel_local_dir_input and self.excel_local_dir_input.value
                else str(paths.INPUT_EXCEL_DIR)
            )
            input_dir = Path(path_str)
            try:
                if input_dir.exists() and input_dir.is_dir():
                    files = [
                        f.name
                        for f in input_dir.iterdir()
                        if f.is_file() and f.suffix.lower() in {".xlsx", ".xls", ".xlsm", ".xlsb"}
                    ]
                    self.excel_file_select.options = ["[全部Excel文件]"] + files
                else:
                    self.excel_file_select.options = ["[全部Excel文件]"]
            except Exception:
                self.excel_file_select.options = ["[全部Excel文件]"]
            self.excel_file_select.update()

    async def on_excel_upload(self, e: events.UploadEventArguments) -> None:
        try:
            import time
            input_dir = paths.INPUT_EXCEL_DIR / "client_temp"
            input_dir.mkdir(parents=True, exist_ok=True)

            now = time.time()
            if now - self.last_excel_upload_time > 2.0:
                for f in input_dir.iterdir():
                    if f.is_file() and f.name != ".gitkeep":
                        try:
                            f.unlink()
                        except Exception:
                            pass
                if self.client_excel_file_select:
                    self.client_excel_file_select.options = ["[全部已上传Excel文件]"]
                    self.client_excel_file_select.value = "[全部已上传Excel文件]"
                    self.client_excel_file_select.update()
                if self.excel_download_container:
                    self.excel_download_container.clear()
                    self.excel_download_container.visible = False
                if self.excel_dialog_progress:
                    self.excel_dialog_progress.set_value(0.0)
                    self.excel_dialog_progress.visible = False
                if self.excel_dialog_status:
                    self.excel_dialog_status.set_text("")
                    self.excel_dialog_status.visible = False
            self.last_excel_upload_time = now

            file_path = input_dir / Path(e.file.name).name
            data = await e.file.read()
            file_path.write_bytes(data)
            ui.notify(f"Excel 文件 {Path(e.file.name).name} 上传成功！", type="positive", position="top")

            files = [
                f.name
                for f in input_dir.iterdir()
                if f.is_file() and f.suffix.lower() in {".xlsx", ".xls", ".xlsm", ".xlsb"}
            ]
            self.client_excel_file_select.options = ["[全部已上传Excel文件]"] + files
            self.client_excel_file_select.value = "[全部已上传Excel文件]"
            self.client_excel_file_select.update()
        except Exception as err:
            ui.notify(f"文件保存失败: {str(err)}", type="negative", position="top")

    async def run_excel_to_csv_conversion(self) -> None:
        if not self.excel_file_select or not self.excel_dialog_progress or not self.excel_dialog_status:
            return

        mode = self.excel_source_type.value

        self.excel_dialog_progress.set_value(0.0)
        self.excel_dialog_progress.visible = True
        self.excel_dialog_status.visible = True
        self.excel_dialog_status.set_text("正在启动 Excel → CSV 转换...")

        self.excel_download_container.clear()
        self.excel_download_container.visible = False
        
        if self.excel_report_preview:
            self.excel_report_preview.visible = False
            self.excel_report_preview.set_content("")

        excel_conversion_logs: list[dict] = []
        output_csv_files: list[Path] = []

        def on_excel_progress(
            current: int, total: int, file_name: str, success: bool, message: str
        ) -> None:
            try:
                if self.excel_dialog_progress and self.excel_dialog_status:
                    if total > 0:
                        self.excel_dialog_progress.set_value(current / total)
                        self.excel_dialog_status.set_text(f"进度 ({current}/{total}): {file_name}")
                    else:
                        self.excel_dialog_status.set_text(message)
                    ui.notify(message, type="positive" if success else "negative", position="top")
            except (RuntimeError, ValueError, KeyError) as ui_err:
                print(f"[Excel Progress UI Warning] {ui_err}")
            if file_name:
                excel_conversion_logs.append({
                    "file": file_name,
                    "status": "success" if success else "failed",
                    "message": message,
                })

        try:
            if mode == "server":
                out_zip_dir = paths.OUTPUT_CSV_DIR
                path_str = (
                    self.excel_local_dir_input.value
                    if self.excel_local_dir_input and self.excel_local_dir_input.value
                    else str(paths.INPUT_EXCEL_DIR)
                )
                input_dir = Path(path_str)
                selected = self.excel_file_select.value

                converter = ExcelToCsvConverter(input_dir=input_dir, output_dir=out_zip_dir)

                if selected == "[全部Excel文件]":
                    files = [
                        f for f in input_dir.iterdir()
                        if f.is_file() and f.suffix.lower() in {".xlsx", ".xls", ".xlsm", ".xlsb"}
                    ]
                    total = len(files)
                    for idx, fp in enumerate(files, start=1):
                        conv_paths = await converter.convert_file(
                            excel_path=fp,
                            out_dir=out_zip_dir,
                            progress_callback=on_excel_progress,
                            file_idx=idx,
                            total_files=total,
                        )
                        output_csv_files.extend(conv_paths)
                        await asyncio.sleep(0.05)
                else:
                    fp = input_dir / selected
                    if not fp.exists():
                        raise FileNotFoundError(f"文件不存在: {selected}")
                    conv_paths = await converter.convert_file(
                        excel_path=fp,
                        out_dir=out_zip_dir,
                        progress_callback=on_excel_progress,
                        file_idx=1,
                        total_files=1,
                    )
                    output_csv_files.extend(conv_paths)
            else:
                out_zip_dir = paths.OUTPUT_CSV_DIR / "client_temp"
                input_dir = paths.INPUT_EXCEL_DIR / "client_temp"
                out_zip_dir.mkdir(parents=True, exist_ok=True)
                selected = self.client_excel_file_select.value

                converter = ExcelToCsvConverter(input_dir=input_dir, output_dir=out_zip_dir)

                if selected == "[全部已上传Excel文件]":
                    files = [
                        f for f in input_dir.iterdir()
                        if f.is_file() and f.suffix.lower() in {".xlsx", ".xls", ".xlsm", ".xlsb"}
                    ]
                    total = len(files)
                    if total == 0:
                        on_excel_progress(0, 0, "", True, "未找到任何已上传的 Excel 文件。")
                        return
                    for idx, fp in enumerate(files, start=1):
                        conv_paths = await converter.convert_file(
                            excel_path=fp,
                            out_dir=out_zip_dir,
                            progress_callback=on_excel_progress,
                            file_idx=idx,
                            total_files=total,
                        )
                        output_csv_files.extend(conv_paths)
                        await asyncio.sleep(0.05)
                else:
                    fp = input_dir / selected
                    if not fp.exists():
                        raise FileNotFoundError(f"文件不存在: {selected}")
                    conv_paths = await converter.convert_file(
                        excel_path=fp,
                        out_dir=out_zip_dir,
                        progress_callback=on_excel_progress,
                        file_idx=1,
                        total_files=1,
                    )
                    output_csv_files.extend(conv_paths)

            report_file = None
            if excel_conversion_logs:
                report_file = generate_csv_excel_report(excel_conversion_logs, out_zip_dir, direction="Excel ➔ CSV (多Sheet无损拆分)")
                try:
                    rel_report = report_file.relative_to(paths.BASE_DIR)
                    with self.excel_download_container:
                        ui.link("📊 下载转换报告 (report.md)",
                                f"/download/{rel_report.as_posix()}",
                                new_tab=True).classes(
                            "bg-indigo-600 hover:bg-indigo-700 text-white text-xs "
                            "px-3 py-1.5 rounded-lg font-semibold shadow-sm no-underline"
                        )
                except ValueError:
                    pass

                if report_file and report_file.exists() and self.excel_report_preview:
                    try:
                        report_text = report_file.read_text(encoding="utf-8")
                        self.excel_report_preview.set_content(report_text)
                        self.excel_report_preview.visible = True
                    except Exception:
                        pass

            if output_csv_files:
                zip_path = out_zip_dir / "excel_to_csv_files.zip"
                try:
                    if zip_path.exists():
                        zip_path.unlink()
                except Exception:
                    pass
                
                files_to_zip = list(output_csv_files)
                if report_file and report_file.exists():
                    files_to_zip.append(report_file)
                    
                await asyncio.to_thread(create_zip_archive, files_to_zip, zip_path)
                if zip_path.exists():
                    try:
                        rel_zip = zip_path.relative_to(paths.BASE_DIR)
                        with self.excel_download_container:
                            ui.link("📦 下载全部 CSV 文件 (ZIP)",
                                    f"/download/{rel_zip.as_posix()}",
                                    new_tab=True).classes(
                                "bg-amber-600 hover:bg-amber-700 text-white text-xs "
                                "px-3 py-1.5 rounded-lg font-semibold shadow-sm no-underline font-bold"
                            )
                    except ValueError:
                        pass

            if excel_conversion_logs or output_csv_files:
                self.excel_download_container.visible = True

            self.excel_dialog_status.set_text(
                f"转换完成！共生成 {len(output_csv_files)} 个 CSV 文件。"
            )
            log_action(f"模块 1 (Excel→CSV) 转换成功，生成了 {len(output_csv_files)} 个 CSV 文件。")

        except Exception as err:
            try:
                self.excel_dialog_status.set_text(f"转换失败: {str(err)}")
                ui.notify(f"转换失败: {str(err)}", type="negative", position="top")
            except (RuntimeError, ValueError, KeyError) as ui_err:
                print(f"[Excel Error UI Warning] {ui_err}")
        finally:
            await asyncio.sleep(3)
            try:
                if self.excel_dialog_progress:
                    self.excel_dialog_progress.visible = False
                if self.excel_dialog_status:
                    self.excel_dialog_status.visible = False
            except (RuntimeError, ValueError, KeyError) as ui_err:
                print(f"[Excel Finally UI Warning] {ui_err}")
