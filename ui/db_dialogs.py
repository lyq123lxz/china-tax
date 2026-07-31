import asyncio
import time
from pathlib import Path
import pandas as pd
from nicegui import ui, events

from ui.app_state import AppState
import config.paths as paths
import config.db_config as db_config
from utils.sys_utils import create_zip_archive
from ui.sys_logs import log_action

class DBTestDialog:
    def __init__(self, state: AppState) -> None:
        self.state = state
        self.dialog = None
        self.build()
        
    def build(self) -> None:
        with ui.dialog() as self.dialog:
            with ui.card().classes("w-[500px] p-6 gap-4 bg-white rounded-xl shadow-2xl"):
                with ui.row().classes("w-full justify-between items-center"):
                    with ui.row().classes("items-center gap-2"):
                        ui.icon("dns", size="1.8rem").classes("text-indigo-600")
                        ui.label("数据库连接与状态控制台").classes("text-lg font-bold text-slate-800")
                    ui.button(icon="close", on_click=self.dialog.close).props("flat round dense").classes("text-slate-400")
                
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
                    ui.button("取消", on_click=self.dialog.close).props("flat").classes("text-slate-500 text-sm")
                    ui.button("测试物理连接", on_click=perform_db_connection_test).classes(
                        "bg-indigo-600 hover:bg-indigo-700 text-white px-4 py-2 rounded-lg text-sm font-semibold shadow-sm"
                    )

    def open(self) -> None:
        self.dialog.open()


class ArchiveDialog:
    def __init__(self, state: AppState) -> None:
        self.state = state
        self.dialog = None
        self.archive_table = None
        self.build()
        
    def build(self) -> None:
        with ui.dialog() as self.dialog:
            with ui.card().classes("w-[720px] max-w-full p-6 gap-4 bg-white rounded-xl shadow-2xl"):
                with ui.row().classes("w-full justify-between items-center"):
                    with ui.row().classes("items-center gap-2"):
                        ui.icon("archive", size="1.8rem").classes("text-indigo-600")
                        ui.label("国家标准税务历史档案库控制面板").classes("text-lg font-bold text-slate-800")
                    ui.button(icon="close", on_click=self.dialog.close).props("flat round dense").classes("text-slate-400")
                
                ui.separator()
                
                ui.label("历史归档说明：可一键将当前所有的核算记录冻结打包，并在本地历史归档表 history_archives 中登记备案。").classes("text-xs text-slate-500")
                
                columns = [
                    {"name": "archive_name", "label": "归档包文件名", "field": "archive_name", "align": "left"},
                    {"name": "operator", "label": "归档负责人", "field": "operator", "align": "center"},
                    {"name": "created_at", "label": "归档时间", "field": "created_at", "align": "center"}
                ]
                
                self.archive_table = ui.table(columns=columns, rows=[], row_key="id", selection="single").classes("w-full max-h-60 text-xs shadow-sm rounded-lg")
                
                def download_selected_archive():
                    selected = self.archive_table.selected
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
                        
                        import core.validator as tax_val
                        cursor.execute("SELECT taxpayer_name, credit_code, income, deductions, tax_payable, tax_type, created_at FROM tax_records")
                        rows = cursor.fetchall()
                        
                        archive_dir = paths.OUTPUT_DIR / "archives"
                        archive_dir.mkdir(parents=True, exist_ok=True)
                        
                        timestamp_file = time.strftime("%Y%m%d_%H%M%S")
                        excel_path = archive_dir / f"tax_backup_{timestamp_file}.xlsx"
                        
                        df = pd.DataFrame([{
                            "纳税人姓名/企业名": r[0], "信用代码/证件": r[1], "年所得收入": float(tax_val.clean_numeric_string(str(r[2]))),
                            "扣除项": float(tax_val.clean_numeric_string(str(r[3]))), "核定税额": float(tax_val.clean_numeric_string(str(r[4]))), "税种": r[5], "时间": r[6]
                        } for r in rows])
                        df.to_excel(excel_path, index=False)
                        
                        zip_name = f"archive_batch_{timestamp_file}.zip"
                        zip_file_path = archive_dir / zip_name
                        
                        await asyncio.to_thread(create_zip_archive, [excel_path], zip_file_path)
                        
                        if excel_path.exists():
                            excel_path.unlink()
                            
                        created_at = time.strftime("%Y-%m-%d %H:%M:%S")
                        cursor.execute(
                            "INSERT INTO history_archives (archive_name, file_path, operator, created_at) VALUES (?, ?, ?, ?)",
                            (zip_name, str(zip_file_path), "智能税务终端", created_at)
                        )
                        conn.commit()
                        conn.close()
                        
                        ui.notify(f"归档封包 {zip_name} 建立成功并落盘存档！", type="positive", position="top")
                        log_action(f"建立归档封包并写入 history_archives: {zip_name}")
                        await self.refresh_archive_table()
                    except Exception as err:
                        ui.notify(f"建立归档失败: {str(err)}", type="negative", position="top")
                        
                with ui.row().classes("w-full justify-between mt-2"):
                    with ui.row().classes("gap-2"):
                        ui.button("📦 封存归档当前数据", on_click=do_new_archive).classes("bg-indigo-600 hover:bg-indigo-700 text-white px-3 py-1.5 rounded-lg text-sm")
                        ui.button("📥 下载选中的历史归档", on_click=download_selected_archive).classes("bg-emerald-600 hover:bg-emerald-700 text-white px-3 py-1.5 rounded-lg text-sm")
                    ui.button("关闭", on_click=self.dialog.close).props("flat").classes("text-slate-500 text-sm")

    async def open(self) -> None:
        await self.refresh_archive_table()
        self.dialog.open()

    async def refresh_archive_table(self) -> None:
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
                        rel_path = resolved.relative_to(paths.BASE_DIR)
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
            self.archive_table.rows = archive_rows
            self.archive_table.update()
        except Exception as err:
            ui.notify(f"载入归档失败: {str(err)}", type="negative", position="top")


class ConfigViewDialog:
    def __init__(self, state: AppState) -> None:
        self.state = state
        self.dialog = None
        self.build()
        
    def build(self) -> None:
        with ui.dialog() as self.dialog:
            with ui.card().classes("w-[650px] p-6 gap-4 bg-white rounded-xl shadow-2xl"):
                with ui.row().classes("w-full justify-between items-center"):
                    with ui.row().classes("items-center gap-2"):
                        ui.icon("settings_suggest", size="1.8rem").classes("text-indigo-600")
                        ui.label("国家标准所得税计算参数与税率规范").classes("text-lg font-bold text-slate-800")
                    ui.button(icon="close", on_click=self.dialog.close).props("flat round dense").classes("text-slate-400")
                
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

    def open(self) -> None:
        self.dialog.open()
