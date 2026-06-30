import asyncio
import fnmatch
from pathlib import Path
from nicegui import ui
import config.paths as paths
from utils.pdf_md import PDFBatchParser, ParserProgress
from utils.report_generator import generate_pdf_conversion_report, generate_md_csv_conversion_report
from utils.sys_utils import create_zip_archive
import utils.md_csv as md_csv
from ui.sys_logs import log_action

async def run_pdf_to_md_conversion(self) -> None:
    if not self.pdf_file_select or not self.client_pdf_select or not self.pdf_progress or not self.pdf_status or not self.pdf_log_board or not self.pdf_log_container:
        return
        
    mode = self.pdf_source_type.value
    preserve_files = []
    if mode == "server":
        selected = self.pdf_file_select.value
        path_str = self.pdf_local_dir_input.value if self.pdf_local_dir_input and self.pdf_local_dir_input.value else str(paths.INPUT_PDF_DIR)
        input_dir = Path(path_str)
        if not input_dir.exists():
            input_dir.mkdir(parents=True, exist_ok=True)
        if selected == "[全部PDF文件]":
            try:
                preserve_files = [input_dir / f.name for f in input_dir.iterdir() if f.is_file() and f.suffix.lower() == ".pdf"]
            except Exception:
                pass
        elif selected:
            preserve_files = [input_dir / selected]
    else:
        selected = self.client_pdf_select.value
        input_dir = paths.INPUT_PDF_DIR / "client_pdf_temp"
        if not input_dir.exists():
            input_dir.mkdir(parents=True, exist_ok=True)
        if selected == "[全部已上传PDF文件]":
            try:
                preserve_files = [input_dir / f.name for f in input_dir.iterdir() if f.is_file() and f.suffix.lower() == ".pdf"]
            except Exception:
                pass
        elif selected:
            preserve_files = [input_dir / selected]

    self.pdf_progress.set_value(0.0)
    self.pdf_progress.visible = True
    self.pdf_status.visible = True
    self.pdf_log_board.visible = True
    self.pdf_log_container.clear()
    self.pdf_status.set_text("正在启动 PDF 解析与勾稽关系校验...")
    
    self.pdf_download_container.clear()
    self.pdf_download_container.visible = False
    
    all_audit_logs = []

    def on_progress(progress: ParserProgress) -> None:
        try:
            if self.pdf_progress and self.pdf_status:
                file_idx = progress.current_file_idx
                total_files = progress.total_files
                page_num = progress.current_page
                total_pages = progress.total_pages
                message = progress.status_msg
                audit_logs = progress.audit_alerts
                
                if audit_logs:
                    for log in audit_logs:
                        if log.get("type") != "MD转CSV":
                            all_audit_logs.append(log)
                
                if total_files > 0 and total_pages > 0:
                    current_progress = (file_idx - 1) / total_files + (page_num / total_pages) / total_files
                    self.pdf_progress.set_value(current_progress)
                    self.pdf_status.set_text(f"文件 ({file_idx}/{total_files}) - {message}")
                else:
                    self.pdf_status.set_text(message)
        except (RuntimeError, ValueError, KeyError) as ui_err:
            print(f"[PDF Progress UI Warning] {ui_err}")
            
        try:
            if self.pdf_log_container and self.pdf_log_board:
                for log in progress.audit_alerts:
                    status = log.get("status")
                    if status == "success":
                        bg_color, text_color, icon = "bg-emerald-950/40 border-emerald-500/30", "text-emerald-400", "✅"
                        animate_class = ""
                    elif status == "warning":
                        bg_color, text_color, icon = "bg-amber-950/40 border-amber-500/30", "text-amber-400", "⚠️"
                        animate_class = ""
                    elif status == "NEED_VISUAL_REVIEW":
                        bg_color, text_color, icon = "bg-indigo-950/60 border-indigo-500/40", "text-indigo-300", "👁️"
                        animate_class = "animate-pulse font-semibold"
                    else:
                        bg_color, text_color, icon = "bg-rose-950/40 border-rose-500/30", "text-rose-400", "❌"
                        animate_class = ""
                        
                    page_suffix = f" P.{log['page']}" if "page" in log else ""
                    file_name = log.get("file", "Unknown")
                    log_type = log.get("type", "None")
                    log_msg = log.get("message", "")
                    
                    with self.pdf_log_container:
                        with ui.row().classes(f"w-full items-center p-2 rounded-lg border {bg_color} text-xs font-mono {animate_class}"):
                            ui.label(icon).classes("mr-1")
                            ui.label(f"[{file_name}{page_suffix}]").classes("font-bold text-slate-300 mr-2")
                            ui.label(f"【{log_type}】").classes("font-semibold mr-2")
                            ui.label(log_msg).classes(text_color)
                            
                ui.run_javascript(f"document.getElementById('{self.pdf_log_board.id}').scrollTop = document.getElementById('{self.pdf_log_board.id}').scrollHeight")
        except (RuntimeError, ValueError, KeyError) as ui_err:
            print(f"[PDF Alert Row UI Warning] {ui_err}")

    output_md_files: list[Path] = []
    try:
        if mode == "server":
            report_out_md_dir = paths.OUTPUT_MD_DIR
        else:
            report_out_md_dir = paths.OUTPUT_MD_DIR / "client_pdf_out"
        report_out_md_dir.mkdir(parents=True, exist_ok=True)

        if mode == "server":
            selected = self.pdf_file_select.value
            path_str = self.pdf_local_dir_input.value if self.pdf_local_dir_input and self.pdf_local_dir_input.value else str(paths.INPUT_PDF_DIR)
            input_dir = Path(path_str)
            if not input_dir.exists():
                input_dir.mkdir(parents=True, exist_ok=True)
            
            parser = PDFBatchParser(input_dir=input_dir, output_dir=report_out_md_dir)
            if selected == "[全部PDF文件]":
                output_files = await parser.parse_all(progress_callback=on_progress)
                for out_path in output_files:
                    out_path_obj = Path(out_path).resolve()
                    if out_path_obj.exists():
                        output_md_files.append(out_path_obj)
            else:
                if not selected:
                    raise FileNotFoundError("未选择任何待解析的 PDF 文件！")
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
            selected = self.client_pdf_select.value
            input_dir = paths.INPUT_PDF_DIR / "client_pdf_temp"
            if not input_dir.exists():
                input_dir.mkdir(parents=True, exist_ok=True)
            
            parser = PDFBatchParser(input_dir=input_dir, output_dir=report_out_md_dir)
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
                if not selected:
                    raise FileNotFoundError("未选择任何待解析的已上传 PDF 文件！")
                file_path = input_dir / selected
                if file_path.exists():
                    out_path = await parser.parse_file(file_path, 1, 1, progress_callback=on_progress)
                    out_path_obj = Path(out_path).resolve()
                    if out_path_obj.exists():
                        output_md_files.append(out_path_obj)
                    ui.notify(f"解析成功！已暫存至後端。", type="positive", position="top")
                else:
                    raise FileNotFoundError(f"文件不存在: {selected}")
        
        report_file = generate_pdf_conversion_report(all_audit_logs, report_out_md_dir)
        
        zip_file_path = report_out_md_dir / "parsed_markdown_files.zip"
        if output_md_files:
            if zip_file_path.exists():
                zip_file_path.unlink()
            await asyncio.to_thread(create_zip_archive, output_md_files, zip_file_path)
        
        with self.pdf_download_container:
            try:
                rel_report = report_file.relative_to(paths.BASE_DIR)
                report_url = f"/download/{rel_report.as_posix()}"
                ui.link("📊 下載 MD 審計報告 (report.md)", report_url, new_tab=True).classes(
                    "bg-indigo-600 hover:bg-indigo-700 text-white text-xs px-3 py-1.5 rounded-lg font-semibold shadow-sm no-underline"
                )
            except ValueError:
                pass
            
            if zip_file_path.exists():
                try:
                    rel_zip = zip_file_path.relative_to(paths.BASE_DIR)
                    zip_url = f"/download/{rel_zip.as_posix()}"
                    ui.link("📦 下载全部 MD 解析件 (ZIP)", zip_url, new_tab=True).classes(
                        "bg-amber-600 hover:bg-amber-700 text-white text-xs px-3 py-1.5 rounded-lg font-semibold shadow-sm no-underline font-bold"
                    )
                except ValueError:
                    pass
                    
        self.pdf_download_container.visible = True
        self.pdf_status.set_text("PDF 转 Markdown 转换全部完成！")
        log_action(f"PDF 转 Markdown 解析全部成功。生成了 {len(output_md_files)} 个 Markdown 文件。")
    except Exception as err:
        try:
            self.pdf_status.set_text(f"解析失败: {str(err)}")
            ui.notify(f"解析失败: {str(err)}", type="negative", position="top")
        except (RuntimeError, ValueError, KeyError) as ui_err:
            print(f"[PDF Error UI Warning] {ui_err}")
    finally:
        await asyncio.sleep(5)
        try:
            if self.pdf_progress:
                self.pdf_progress.visible = False
            if self.pdf_status:
                self.pdf_status.visible = False
        except (RuntimeError, ValueError, KeyError) as ui_err:
            print(f"[PDF Finally UI Warning] {ui_err}")

async def run_md_to_csv_conversion(self) -> None:
    if not self.pdf_progress or not self.pdf_status or not self.pdf_log_board or not self.pdf_log_container or not self.pdf_download_container:
        return
        
    mode = self.pdf_source_type.value
    
    if mode == "server":
        report_out_md_dir = paths.OUTPUT_MD_DIR
        report_out_csv_dir = paths.OUTPUT_CSV_DIR
    else:
        report_out_md_dir = paths.OUTPUT_MD_DIR / "client_pdf_out"
        report_out_csv_dir = paths.OUTPUT_CSV_DIR / "client_pdf_out"
        
    if not report_out_md_dir.exists():
        report_out_md_dir.mkdir(parents=True, exist_ok=True)
    if not report_out_csv_dir.exists():
        report_out_csv_dir.mkdir(parents=True, exist_ok=True)
        
    md_files = []
    seen_names = set()
    
    dirs_to_scan = []
    if mode == "server":
        dirs_to_scan = [paths.OUTPUT_MD_DIR, paths.OUTPUT_MD_DIR / "client_pdf_out"]
    else:
        dirs_to_scan = [paths.OUTPUT_MD_DIR / "client_pdf_out", paths.OUTPUT_MD_DIR]
        
    for folder in dirs_to_scan:
        if not folder.exists():
            continue
        for f in folder.iterdir():
            if not f.is_file():
                continue
            name_lower = f.name.lower()
            if f.suffix.lower() == ".zip" or "zip" in name_lower:
                continue
            if fnmatch.fnmatch(name_lower, "report*.md"):
                continue
            if f.suffix.lower() == ".md":
                if f.name not in seen_names:
                    md_files.append(f)
                    seen_names.add(f.name)
    
    if not md_files:
        ui.notify("⚠️ 在输出目录中未发现任何待转换的 Markdown 文件。请先执行 'PDF 转 MD'。", type="warning", position="top")
        self.pdf_status.set_text("转换终止：未发现 .md 文件")
        return
        
    self.pdf_progress.set_value(0.0)
    self.pdf_progress.visible = True
    self.pdf_status.visible = True
    self.pdf_log_board.visible = True
    self.pdf_log_container.clear()
    self.pdf_status.set_text("正在启动 Markdown 转 CSV 阶段...")
    
    self.pdf_download_container.clear()
    self.pdf_download_container.visible = False
    
    all_csv_audit_logs = []
    output_csv_files = []
    
    def on_csv_progress(progress: ParserProgress) -> None:
        try:
            if self.pdf_progress and self.pdf_status:
                file_idx = progress.current_file_idx
                total_files = progress.total_files
                page_num = progress.current_page
                total_pages = progress.total_pages
                message = progress.status_msg
                
                if total_files > 0 and total_pages > 0:
                    current_progress = (file_idx - 1) / total_files + (page_num / total_pages) / total_files
                    self.pdf_progress.set_value(current_progress)
                    self.pdf_status.set_text(f"文件 ({file_idx}/{total_files}) - {message}")
                else:
                    self.pdf_status.set_text(message)
        except (RuntimeError, ValueError, KeyError) as ui_err:
            print(f"[CSV Progress UI Warning] {ui_err}")
                
        try:
            if self.pdf_log_container and self.pdf_log_board:
                for log in progress.audit_alerts:
                    status = log.get("status")
                    if status == "success":
                        bg_color, text_color, icon = "bg-emerald-950/40 border-emerald-500/30", "text-emerald-400", "✅"
                    elif status == "warning":
                        bg_color, text_color, icon = "bg-amber-950/40 border-amber-500/30", "text-amber-400", "⚠️"
                    else:
                        bg_color, text_color, icon = "bg-rose-950/40 border-rose-500/30", "text-rose-400", "❌"
                        
                    page_suffix = f" P.{log['page']}" if "page" in log else ""
                    file_name = log.get("file", "Unknown")
                    log_type = log.get("type", "None")
                    log_msg = log.get("message", "")
                    
                    with self.pdf_log_container:
                        with ui.row().classes(f"w-full items-center p-2 rounded-lg border {bg_color} text-xs font-mono"):
                            ui.label(icon).classes("mr-1")
                            ui.label(f"[{file_name}{page_suffix}]").classes("font-bold text-slate-300 mr-2")
                            ui.label(f"【{log_type}】").classes("font-semibold mr-2")
                            ui.label(log_msg).classes(text_color)
                            
                ui.run_javascript(f"document.getElementById('{self.pdf_log_board.id}').scrollTop = document.getElementById('{self.pdf_log_board.id}').scrollHeight")
        except (RuntimeError, ValueError, KeyError) as ui_err:
            print(f"[CSV Alert Row UI Warning] {ui_err}")

    try:
        total_files = len(md_files)
        for idx, md_file in enumerate(md_files, start=1):
            csv_file_path = report_out_csv_dir / f"{md_file.stem}.csv"
            on_csv_progress(ParserProgress(
                current_file_idx=idx,
                total_files=total_files,
                current_page=50,
                total_pages=100,
                status_msg=f"正在将 {md_file.name} 转换为 CSV...",
                audit_alerts=[]
            ))
            
            csv_alerts = await asyncio.to_thread(md_csv.convert_md_to_csv, md_file, csv_file_path)
            
            if csv_file_path.exists():
                output_csv_files.append(csv_file_path)
            all_csv_audit_logs.extend(csv_alerts)
            
            on_csv_progress(ParserProgress(
                current_file_idx=idx,
                total_files=total_files,
                current_page=100,
                total_pages=100,
                status_msg=f"✅ {md_file.name} 转换为 CSV 完成！",
                audit_alerts=csv_alerts
            ))
            await asyncio.sleep(0.05)
            
        csv_report_file = generate_md_csv_conversion_report(all_csv_audit_logs, report_out_csv_dir)
        
        zip_csv_file_path = report_out_csv_dir / "parsed_csv_files.zip"
        if output_csv_files:
            try:
                if zip_csv_file_path.exists():
                    zip_csv_file_path.unlink()
            except Exception as zip_err:
                print(f"删除旧 ZIP 归档失败: {zip_err}")
            await asyncio.to_thread(create_zip_archive, output_csv_files, zip_csv_file_path)
            
        with self.pdf_download_container:
            try:
                rel_csv_report = csv_report_file.relative_to(paths.BASE_DIR)
                csv_report_url = f"/download/{rel_csv_report.as_posix()}"
                ui.link("📊 下載 CSV 轉換報告 (report.md)", csv_report_url, new_tab=True).classes(
                    "bg-teal-600 hover:bg-teal-700 text-white text-xs px-3 py-1.5 rounded-lg font-semibold shadow-sm no-underline"
                )
            except ValueError:
                pass
            
            if zip_csv_file_path.exists():
                try:
                    rel_csv_zip = zip_csv_file_path.relative_to(paths.BASE_DIR)
                    csv_zip_url = f"/download/{rel_csv_zip.as_posix()}"
                    ui.link("📦 下载全部 CSV 转换件 (ZIP)", csv_zip_url, new_tab=True).classes(
                        "bg-emerald-600 hover:bg-emerald-700 text-white text-xs px-3 py-1.5 rounded-lg font-semibold shadow-sm no-underline font-bold"
                    )
                except ValueError:
                    pass
                    
        self.pdf_download_container.visible = True
        self.pdf_status.set_text("Markdown 转 CSV 转换全部完成！")
        log_action(f"Markdown 转 CSV 转换全部成功。生成了 {len(output_csv_files)} 个 CSV 文件。")
    except Exception as err:
        try:
            self.pdf_status.set_text(f"转换失败: {str(err)}")
            ui.notify(f"转换失败: {str(err)}", type="negative", position="top")
        except (RuntimeError, ValueError, KeyError) as ui_err:
            print(f"[CSV Error UI Warning] {ui_err}")
    finally:
        await asyncio.sleep(5)
        try:
            if self.pdf_progress:
                self.pdf_progress.visible = False
            if self.pdf_status:
                self.pdf_status.visible = False
        except (RuntimeError, ValueError, KeyError) as ui_err:
            print(f"[CSV Finally UI Warning] {ui_err}")
