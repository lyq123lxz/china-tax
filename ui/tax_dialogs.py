import asyncio
import time
from pathlib import Path
import pandas as pd
from nicegui import ui, events

from ui.app_state import AppState
import config.paths as paths
import config.db_config as db_config
import core.validator as tax_val
import core.calculator as tax_calc
from utils.sys_utils import create_zip_archive
from ui.sys_logs import log_action

class CalculatorDialog:
    def __init__(self, state: AppState) -> None:
        self.state = state
        self.dialog = None
        self.build()
        
    def build(self) -> None:
        with ui.dialog() as self.dialog:
            with ui.card().classes("w-[550px] p-6 gap-4 bg-white rounded-xl shadow-2xl"):
                with ui.row().classes("w-full justify-between items-center"):
                    with ui.row().classes("items-center gap-2"):
                        ui.icon("calculate", size="1.8rem").classes("text-indigo-600")
                        ui.label("个税与企业所得税核算控制台").classes("text-lg font-bold text-slate-800")
                    ui.button(icon="close", on_click=self.dialog.close).props("flat round dense").classes("text-slate-400")
                
                ui.separator()
                
                calc_type = ui.toggle(
                    options={"individual": "个人所得税 (Comprehensive)", "corporate": "企业所得税 (CIT)"},
                    value="individual"
                ).classes("w-full")
                
                taxpayer_name_input = ui.input("纳税人名称", placeholder="请输入企业名或个人姓名").classes("w-full")
                taxpayer_id_input = ui.input("纳税人识别号 / 证件号", placeholder="请输入18位身份证号或社会信用代码").classes("w-full")
                
                with ui.column().classes("w-full gap-3") as ind_fields:
                    calc_income = ui.input("年收入总额 (元)", value="120000").classes("w-full")
                    calc_deductions = ui.input("各项免税与专项附加扣除总额 (元)", value="24000").classes("w-full")
                    
                with ui.column().classes("w-full gap-3") as corp_fields:
                    corp_profit = ui.input("纳税调整后所得 (利润额) (元)", value="500000").classes("w-full")
                    corp_high_tech = ui.checkbox("属于国家重点扶持的高新技术企业").classes("mt-2")
                    
                ind_fields.bind_visibility_from(calc_type, "value", value="individual")
                corp_fields.bind_visibility_from(calc_type, "value", value="corporate")
                
                results_box = ui.column().classes("w-full p-4 bg-slate-50 border border-slate-200 rounded-lg gap-2 mt-2")
                results_box.visible = False
                
                async def run_calculation():
                    try:
                        name = taxpayer_name_input.value.strip()
                        tax_id = taxpayer_id_input.value.strip()
                        
                        if not name or not tax_id:
                            ui.notify("请填写纳税人名称与识别号", type="warning", position="top")
                            return
                            
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
                            ui.button("💾 将核算数据保存入库", on_click=save_record).classes(
                                "w-full bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg py-2 mt-2 text-sm font-semibold"
                            )
                            
                        results_box.visible = True
                        log_action(f"个税/企业税核算成功: 纳税人={name}, 应纳税={res['tax_payable']}")
                    except Exception as calc_err:
                        ui.notify(f"核算失败，请核对输入数值: {str(calc_err)}", type="negative", position="top")
                
                with ui.row().classes("w-full justify-end gap-2 mt-2"):
                    ui.button("取消", on_click=self.dialog.close).props("flat").classes("text-slate-500 text-sm")
                    ui.button("开始核算", on_click=run_calculation).classes(
                        "bg-indigo-600 hover:bg-indigo-700 text-white px-4 py-2 rounded-lg text-sm font-semibold shadow-sm"
                    )

    def open(self) -> None:
        self.dialog.open()


class ValidatorDialog:
    def __init__(self, state: AppState) -> None:
        self.state = state
        self.dialog = None
        self.val_table = None
        self.build()
        
    def build(self) -> None:
        with ui.dialog() as self.dialog:
            with ui.card().classes("w-[780px] max-w-full p-6 gap-4 bg-white rounded-xl shadow-2xl"):
                with ui.row().classes("w-full justify-between items-center"):
                    with ui.row().classes("items-center gap-2"):
                        ui.icon("verified_user", size="1.8rem").classes("text-indigo-600")
                        ui.label("申报数据合法性校验与深度审计控制台").classes("text-lg font-bold text-slate-800")
                    ui.button(icon="close", on_click=self.dialog.close).props("flat round dense").classes("text-slate-400")
                
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
                
                self.val_table = ui.table(columns=columns, rows=[], row_key="id").classes("w-full max-h-60 text-xs shadow-sm rounded-lg")
                
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
                                "income": f"¥{float(tax_val.clean_numeric_string(str(income))):,.2f}",
                                "tax_payable": f"¥{float(tax_val.clean_numeric_string(str(tax_payable))):,.2f}",
                                "status": status,
                                "details": details
                            })
                            
                        self.val_table.rows = validated_rows
                        self.val_table.update()
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
                        self.val_table.rows = []
                        self.val_table.update()
                        ui.notify("申报库历史数据已清空！", type="positive", position="top")
                        log_action("用户触发清空 tax_records 表全部记录")
                    except Exception as err:
                        ui.notify(f"清空失败: {str(err)}", type="negative", position="top")
                
                with ui.row().classes("w-full justify-between mt-2"):
                    ui.button("🧹 清空数据库记录", on_click=clear_all_records).classes("bg-rose-600 hover:bg-rose-700 text-white px-3 py-1.5 rounded-lg text-sm")
                    with ui.row().classes("gap-2"):
                        ui.button("关闭", on_click=self.dialog.close).props("flat").classes("text-slate-500 text-sm")
                        ui.button("开始全量国标校验", on_click=run_data_validation).classes(
                            "bg-indigo-600 hover:bg-indigo-700 text-white px-4 py-2 rounded-lg text-sm font-semibold"
                        )

    def open(self) -> None:
        self.dialog.open()


class ExporterDialog:
    def __init__(self, state: AppState) -> None:
        self.state = state
        self.dialog = None
        self.build()
        
    def build(self) -> None:
        with ui.dialog() as self.dialog:
            with ui.card().classes("w-[500px] p-6 gap-4 bg-white rounded-xl shadow-2xl"):
                with ui.row().classes("w-full justify-between items-center"):
                    with ui.row().classes("items-center gap-2"):
                        ui.icon("cloud_download", size="1.8rem").classes("text-indigo-600")
                        ui.label("国家标准申报表导出中心").classes("text-lg font-bold text-slate-800")
                    ui.button(icon="close", on_click=self.dialog.close).props("flat round dense").classes("text-slate-400")
                
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
                        
                        ind_data = []
                        corp_data = []
                        
                        for name, credit_code, income, deductions, tax_payable, tax_type, created_at in rows:
                            val_res = tax_val.validate_declaration_data(name, credit_code, income, deductions)
                            if not val_res["is_valid"]:
                                continue
                                
                            record = {
                                "纳税人名称/单位": name,
                                "信用代码/身份证": credit_code,
                                "收入所得总额": float(tax_val.clean_numeric_string(str(income))),
                                "允许扣除总额": float(tax_val.clean_numeric_string(str(deductions))),
                                "核算应纳税额": float(tax_val.clean_numeric_string(str(tax_payable))),
                                "税收分类": "个人所得税" if tax_type == "individual" else "企业所得税",
                                "核算时间": created_at
                            }
                            if tax_type == "individual":
                                ind_data.append(record)
                            else:
                                corp_data.append(record)
                        
                        paths.OUTPUT_EXCEL_DIR.mkdir(parents=True, exist_ok=True)
                        exported_files = []
                        
                        if ind_data:
                            ind_path = paths.OUTPUT_EXCEL_DIR / "individual_declarations.xlsx"
                            pd.DataFrame(ind_data).to_excel(ind_path, index=False)
                            exported_files.append(ind_path)
                        
                        if corp_data:
                            corp_path = paths.OUTPUT_EXCEL_DIR / "corporate_declarations.xlsx"
                            pd.DataFrame(corp_data).to_excel(corp_path, index=False)
                            exported_files.append(corp_path)
                            
                        if not exported_files:
                            ui.notify("没有校验通过的数据，未生成任何申报文件！", type="negative", position="top")
                            return
                        
                        zip_path = paths.OUTPUT_EXCEL_DIR / "declaration_reports.zip"
                        if zip_path.exists():
                            zip_path.unlink()
                            
                        await asyncio.to_thread(create_zip_archive, exported_files, zip_path)
                        
                        if zip_path.exists():
                            rel_zip = zip_path.relative_to(paths.BASE_DIR)
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
                    ui.button("取消", on_click=self.dialog.close).props("flat").classes("text-slate-500 text-sm")
                    ui.button("开始打包导出", on_click=run_export_and_pack).classes(
                        "bg-indigo-600 hover:bg-indigo-700 text-white px-4 py-2 rounded-lg text-sm font-semibold shadow-sm"
                    )

    def open(self) -> None:
        self.dialog.open()
