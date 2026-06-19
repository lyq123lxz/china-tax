"""
utils/pdf_md.py
中國稅務系統財務對賬級 PDF 轉 Markdown 工具（NiceGUI 非同步版）
"""

import asyncio
import re
from dataclasses import dataclass, field
from collections.abc import Callable
from pathlib import Path
from typing import Any
import pandas as pd
import pdfplumber

def clean_commas_from_number(val: str) -> str:
    """
    如果字符串是一个带有千分位逗号的数字，则清洗掉其中的逗号。
    例如：'13,649.60' -> '13649.60', '1,500' -> '1500'
    """
    val_strip = val.strip()
    if not val_strip:
        return val
    # 匹配带千分位逗号的数字，包括前导正负号、货币符号及小数。用外层括号捕获整个前缀。
    pattern = r'^(([+\-]|[$¥]|SGD|USD|\s)*)(\d{1,3}(,\d{3})+)(\.\d+)?$'
    match = re.match(pattern, val_strip, re.IGNORECASE)
    if match:
        prefix = match.group(1) or ""
        number_part = match.group(3).replace(",", "")
        suffix = match.group(5) or ""
        return f"{prefix}{number_part}{suffix}".strip()
    return val


@dataclass(frozen=True)
class ParserProgress:
    """非同步進度與審計日誌強型別契約"""
    current_file_idx: int
    total_files: int
    current_page: int
    total_pages: int
    status_msg: str
    audit_alerts: list[dict[str, Any]] = field(default_factory=list)

class PDFBatchParser:
    """PDF 批量解析與財務對賬勾稽審計類"""

    def __init__(self, input_dir: Path | str, output_dir: Path | str) -> None:
        self.input_dir: Path = Path(input_dir).resolve()
        self.output_dir: Path = Path(output_dir).resolve()

    def _deduplicate_chars(self, chars: list[dict[str, Any]], x_tol: float = 0.5, y_tol: float = 0.5) -> list[dict[str, Any]]:
        """去除 PDF 中由於粗體字等原因產生的微小位移重複字元"""
        unique_chars = []
        sorted_chars = sorted(chars, key=lambda c: (c["top"], c["x0"]))
        for char in sorted_chars:
            is_dup = False
            for existing in reversed(unique_chars[-20:]):
                if (
                    existing["text"] == char["text"]
                    and abs(existing["top"] - char["top"]) < y_tol
                    and abs(existing["x0"] - char["x0"]) < x_tol
                ):
                    is_dup = True
                    break
            if not is_dup:
                unique_chars.append(char)
        return unique_chars

    def _merge_chars_to_words(self, chars: list[dict[str, Any]], x_tolerance: float = 3.0) -> list[dict[str, Any]]:
        """将同一行内水平相邻的字符拼接成单词块，以避免无边框表格列切分时切断单词"""
        if not chars:
            return []
        sorted_chars = sorted(chars, key=lambda c: (c["top"], c["x0"]))
        word_chars = []
        
        current_word = None
        for char in sorted_chars:
            if current_word is None:
                current_word = dict(char)
                continue
                
            same_line = abs(char["top"] - current_word["top"]) < 2.0
            close_x = (char["x0"] - current_word["x1"]) < x_tolerance
            
            if same_line and close_x:
                current_word["text"] += char["text"]
                current_word["x1"] = max(current_word["x1"], char["x1"])
                current_word["bottom"] = max(current_word["bottom"], char["bottom"])
                current_word["top"] = min(current_word["top"], char["top"])
            else:
                word_chars.append(current_word)
                current_word = dict(char)
                
        if current_word:
            word_chars.append(current_word)
        return word_chars

    def _is_valid_table(self, table: list[list[str | None]]) -> bool:
        """
        验证提取出的表格是否为含有实质财务数据的有效表格。
        必须有至少 2 行 2 列，且非空单元格占比超过 15%。
        """
        if not table or len(table) < 2:
            return False
        col_count = len(table[0])
        if col_count < 2:
            return False
            
        total_cells = len(table) * col_count
        non_empty = sum(1 for row in table for cell in row if cell is not None and str(cell).strip() != "")
        return (non_empty / total_cells) > 0.15

    def _execute_visual_fallback(self, page: pdfplumber.page.Page, page_idx: int) -> str:
        """私有降级方法：当检测为扫描件/图片时，预留调用视觉模型的接口"""
        fallback_msg = f"\n\n<!-- PAGE START: P.{page_idx} -->\n### 原始PDF页码: P.{page_idx}\n"
        fallback_msg += "> [!WARNING]\n"
        fallback_msg += f"> **[OCR] 侦测到第 P.{page_idx} 页为扫描件或纯图片，已启用防线降级。等待视觉 AI 二次复核。**\n"
        fallback_msg += f"\n<!-- PAGE END: P.{page_idx} -->\n\n"
        return fallback_msg

    def optimize_broker_table(self, table: list[list[str | None]]) -> list[list[str]]:
        """券商長文本折行強健縫合演算法"""
        if not table:
            return []
            
        new_table: list[list[str]] = []
        headers = [str(h).strip() for h in table[0]]
        
        # 動態識別描述列、日期列以及金融數字列
        desc_idx = 1
        date_idx = 0
        
        headers_lower = [h.lower() for h in headers]
        for idx, h in enumerate(headers_lower):
            if any(kw in h for kw in ["date", "time", "日期", "时间"]):
                date_idx = idx
                break
        for idx, h in enumerate(headers_lower):
            if idx != date_idx and any(kw in h for kw in ["desc", "symbol", "asset", "name", "security", "details", "comment", "名称", "证券", "描述", "资产", "说明", "备注", "代码"]):
                desc_idx = idx
                break
                
        for row in table:
            cleaned_row = [str(cell).strip() if cell is not None else "" for cell in row]
            
            if not new_table:
                new_table.append(cleaned_row)
                continue
                
            # 啟發式縫合：判斷當前行是否為純文本折行殘肢
            has_text_desc = bool(cleaned_row[desc_idx]) if desc_idx < len(cleaned_row) else False
            has_date = bool(cleaned_row[date_idx]) if date_idx < len(cleaned_row) else False
            
            # 金融數字列：除了描述列和日期列以外的其他列有數值
            has_numbers = False
            for idx, cell in enumerate(cleaned_row):
                if idx != desc_idx and idx != date_idx and cell != "":
                    has_numbers = True
                    break
            
            if len(new_table) > 1 and has_text_desc and not has_numbers and not has_date:
                # 拼回上一行的描述列尾部
                if len(new_table[-1]) > max(desc_idx, date_idx):
                    if new_table[-1][desc_idx]:
                        new_table[-1][desc_idx] += " " + cleaned_row[desc_idx]
                    else:
                        new_table[-1][desc_idx] = cleaned_row[desc_idx]
                continue
                
            new_table.append(cleaned_row)
        return new_table

    def _run_financial_audit(self, table: list[list[str]], file_name: str, page_num: int) -> list[dict[str, Any]]:
        """雙重財務勾稽引擎：行級運算校驗與總結算對賬"""
        alerts = []
        if len(table) < 2:
            return alerts

        headers = [str(h).strip().lower() for h in table[0]]
        qty_idx = -1
        price_idx = -1
        amount_idx = -1
        
        # Heuristic search for quantity, price, amount
        for idx, h in enumerate(headers):
            if any(kw in h for kw in ["qty", "quantity", "数量", "成交股数", "股数", "单位"]):
                qty_idx = idx
            elif any(kw in h for kw in ["price", "price/share", "单价", "价格", "成交价格", "成交均价"]):
                price_idx = idx
            elif any(kw in h for kw in ["amount", "net amount", "金额", "总金额", "结算金额", "成交金额", "发生金额"]) and "fee" not in h and "commission" not in h:
                amount_idx = idx

        def parse_val(val: str) -> float | None:
            s = val.strip()
            cleaned = s.replace("$", "").replace("¥", "").replace("£", "").replace("€", "").replace("￥", "").replace(",", "").strip()
            for currency in ("SGD", "USD", "HKD", "EUR", "CNY", "GBP", "CAD", "AUD", "NZD", "JPY", "KRW", "TWD", "元", "股", "万", "亿"):
                cleaned = cleaned.replace(currency, "").replace(currency.lower(), "")
            cleaned = cleaned.strip()
            if not cleaned:
                return None
            if cleaned.startswith("(") and cleaned.endswith(")") and len(cleaned) > 2:
                cleaned = "-" + cleaned[1:-1]
            try:
                if cleaned.endswith("-") and len(cleaned) > 1:
                    cleaned = "-" + cleaned[:-1]
                return float(cleaned)
            except ValueError:
                return None

        total_keywords = ["total", "合计", "结余", "余额", "小计", "subtotal", "sum", "balance"]
        def is_total_row(row: list[str]) -> bool:
            return any(any(kw in str(cell).lower() for kw in total_keywords) for cell in row)

        # 邏輯一（行級勾稽）：數量 * 價格 == 金額
        if qty_idx != -1 and price_idx != -1 and amount_idx != -1:
            for r_idx, row in enumerate(table[1:], start=1):
                if is_total_row(row):
                    continue
                if qty_idx < len(row) and price_idx < len(row) and amount_idx < len(row):
                    qty = parse_val(row[qty_idx])
                    price = parse_val(row[price_idx])
                    amount = parse_val(row[amount_idx])
                    if qty is not None and price is not None and amount is not None:
                        expected = abs(qty * price)
                        actual = abs(amount)
                        # 驗算 |數量 * 價格| - |總金額| < 0.01
                        if abs(expected - actual) >= 0.01:
                            alerts.append({
                                "file": file_name,
                                "page": page_num,
                                "type": "行级勾稽",
                                "status": "warning",
                                "message": f"行級勾稽警告：第 {r_idx} 行數量 ({qty}) * 價格 ({price}) = {expected:.2f}，但金額為 {amount}，相差 {abs(expected - actual):.2f}。",
                                "msg": f"行級勾稽警告：第 {r_idx} 行數量 ({qty}) * 價格 ({price}) = {expected:.2f}，但金額為 {amount}，相差 {abs(expected - actual):.2f}。"
                            })

        # 邏輯二（表級勾稽）：明細加總 == 合計行
        detail_amount_sum = 0.0
        has_any_amount = False
        total_row_found = False
        total_row_val = 0.0
        
        for row in table[1:]:
            if is_total_row(row):
                if amount_idx != -1 and amount_idx < len(row):
                    val = parse_val(row[amount_idx])
                    if val is not None:
                        total_row_found = True
                        total_row_val = val
            else:
                if amount_idx != -1 and amount_idx < len(row):
                    val = parse_val(row[amount_idx])
                    if val is not None:
                        detail_amount_sum += val
                        has_any_amount = True
                        
        if total_row_found and has_any_amount:
            if abs(detail_amount_sum - total_row_val) >= 0.05:
                alerts.append({
                    "file": file_name,
                    "page": page_num,
                    "type": "表级勾稽",
                    "status": "warning",
                    "message": f"表級勾稽警告：明細金額加總 ({detail_amount_sum:.2f}) 與合計行 ({total_row_val:.2f}) 不符，差值 {abs(detail_amount_sum - total_row_val):.2f}。",
                    "msg": f"表級勾稽警告：明細金額加總 ({detail_amount_sum:.2f}) 與合計行 ({total_row_val:.2f}) 不符，差值 {abs(detail_amount_sum - total_row_val):.2f}。"
                })
                
        return alerts

    def _parse_page_sync(self, page: pdfplumber.page.Page, p_idx: int, file_name: str) -> tuple[str, list[dict[str, Any]]]:
        """同步解析单页 PDF，返回 (page_markdown, page_alerts)"""
        page_alerts: list[dict[str, Any]] = []
        try:
            # 1. 提取並去重字元，拼接單詞塊
            if "char" in page.objects:
                unique_chars = self._deduplicate_chars(page.objects["char"])
                page.objects["char"] = self._merge_chars_to_words(unique_chars)
            
            raw_text = page.extract_text() or ""
            
            # 1. 智慧路由第一防線 (判斷掃描件)
            if len(raw_text.strip()) < 20:
                fallback_md = self._execute_visual_fallback(page, p_idx)
                page_alerts.append({
                    "file": file_name,
                    "page": p_idx,
                    "type": "智能路由",
                    "status": "NEED_VISUAL_REVIEW",
                    "message": "页面字元数少于 20，判定为扫描件或纯图片。建议启动视觉 AI 二次复核。",
                    "msg": "页面字元数少于 20，判定为扫描件或纯图片。建议启动视觉 AI 二次复核。"
                })
                return fallback_md, page_alerts
            
            # 2. 自適應表格雙層策略恢復
            tables = page.find_tables()
            valid_tables = []
            
            for table in tables:
                # 裁剪坐標安全校驗与溢出修正
                x0, top, x1, bottom = table.bbox
                x0 = max(0.0, min(x0, float(page.width)))
                top = max(0.0, min(top, float(page.height)))
                x1 = max(0.0, min(x1, float(page.width)))
                bottom = max(0.0, min(bottom, float(page.height)))
                
                if x1 <= x0 or bottom <= top:
                    continue
                    
                cropped = page.crop((x0, top, x1, bottom))
                borderless_settings = {
                    "vertical_strategy": "text",
                    "horizontal_strategy": "text",
                    "min_words_vertical": 1,
                    "snap_x_tolerance": 3,
                    "snap_y_tolerance": 3,
                }
                t_extracted = cropped.extract_table(table_settings=borderless_settings)
                
                if not t_extracted or not self._is_valid_table(t_extracted):
                    t_extracted = cropped.extract_table()
                    
                if t_extracted and self._is_valid_table(t_extracted):
                    valid_tables.append(t_extracted)
            
            page_md_blocks = []
            if valid_tables:
                for table in valid_tables:
                    # 3. 執行折行縫合
                    optimized_table = self.optimize_broker_table(table)
                    if not optimized_table or len(optimized_table) < 2:
                        continue
                    
                    # 4. 進行內存財務勾稽
                    audit_res = self._run_financial_audit(optimized_table, file_name, p_idx)
                    page_alerts.extend(audit_res)
                    
                    # 5. 轉換為帶有原始頁碼列的 Markdown 表格
                    headers = list(optimized_table[0]) + ["原始PDF頁碼"]
                    rows = []
                    for row in optimized_table[1:]:
                        cleaned_row = [clean_commas_from_number(cell) for cell in row]
                        cleaned_row.append(f"P.{p_idx}")
                        rows.append(cleaned_row)
                    
                    df = pd.DataFrame(rows, columns=headers)
                    page_md_blocks.append(df.to_markdown(index=False))
                    
                # 成功解析表格且无勾稽警告时，添加一条“对账勾稽成功”通知，确保看板有显示
                if not page_alerts:
                    page_alerts.append({
                        "file": file_name,
                        "page": p_idx,
                        "type": "财务对账",
                        "status": "success",
                        "message": "对账勾稽校验成功，未发现异常数据。",
                        "msg": "对账勾稽校验成功，未发现异常数据。"
                    })
            else:
                # 採用純文本提取
                page_md_blocks.append(raw_text)
                page_alerts.append({
                    "file": file_name,
                    "page": p_idx,
                    "type": "自适应提取",
                    "status": "success",
                    "message": "自适应提取：未检测到有效表格结构，采用纯文本提取。",
                    "msg": "自适应提取：未检测到有效表格结构，采用纯文本提取。"
                })
                
            # 注入頁碼與標籤
            page_md = f"\n\n### 原始PDF頁碼: P.{p_idx}\n" + "\n\n".join(page_md_blocks) + f"\n\n<!-- PAGE END: P.{p_idx} -->\n"
            return page_md, page_alerts
            
        except Exception as page_err:
            error_md = f"\n> ⚠️ [原始PDF第 P.{p_idx} 頁解析失敗，已自動跳過。錯誤: {page_err}]\n"
            crash_alert = [{
                "file": file_name,
                "page": p_idx,
                "type": "页面崩溃",
                "status": "error",
                "message": f"第 P.{p_idx} 頁解析失敗，已自動跳過。錯誤: {page_err}",
                "msg": str(page_err)
            }]
            return error_md, crash_alert

    async def parse_file(
        self,
        file_path: Path,
        file_idx: int,
        total_files: int,
        progress_callback: Callable[[ParserProgress], None] | None
    ) -> str:
        """非同步解析單個 PDF，具備單頁異常防禦與頁碼錨定注入"""
        output_path = self.output_dir / f"{file_path.stem}.md"
        page_markdowns: list[str] = []
        file_alerts: list[dict[str, Any]] = []
        
        file_name = file_path.name
        
        # 1. 开启 pdfplumber 读取
        def open_pdf():
            return pdfplumber.open(file_path)
            
        pdf = await asyncio.to_thread(open_pdf)
        total_pages = len(pdf.pages)
        
        try:
            for p_idx, page in enumerate(pdf.pages, start=1):
                # 2. 分页调度后台线程执行，防止主界面卡顿
                page_md, page_alerts = await asyncio.to_thread(
                    self._parse_page_sync, page, p_idx, file_name
                )
                page_markdowns.append(page_md)
                file_alerts.extend(page_alerts)
                
                # 3. 触发 NiceGUI 进度回调，此时运行在主线程 (含有完整的 client 上下文)
                if progress_callback:
                    progress_callback(ParserProgress(
                        current_file_idx=file_idx,
                        total_files=total_files,
                        current_page=p_idx,
                        total_pages=total_pages,
                        status_msg=f"正在解析 {file_name} 第 {p_idx}/{total_pages} 頁...",
                        audit_alerts=page_alerts
                    ))
        finally:
            pdf.close()
            
        full_markdown = "\n\n".join(page_markdowns)
        
        # 4. 异步写入输出文件
        def write_file() -> None:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            output_path.write_text(full_markdown, encoding="utf-8")
            
        await asyncio.to_thread(write_file)
        
        # 5. 触发最终完工回调
        if progress_callback:
            progress_callback(ParserProgress(
                current_file_idx=file_idx,
                total_files=total_files,
                current_page=100,
                total_pages=100,
                status_msg=f"✅ 文件 {file_name} 解析完成！發現 {len(file_alerts)} 處對賬警告。",
                audit_alerts=[]
            ))
            
        return str(output_path)

    async def parse_all(
        self,
        progress_callback: Callable[[ParserProgress], None] | None = None
    ) -> list[str]:
        """非同步批量並行/序列解析 input_dir 下的所有 PDF 賬單"""
        files = [f for f in self.input_dir.iterdir() if f.is_file() and f.suffix.lower() == ".pdf"]
        total_files = len(files)
        output_files: list[str] = []
        
        if total_files == 0:
            if progress_callback:
                progress_callback(ParserProgress(0, 0, 0, 0, "⚠️ 未在輸入目錄中找到待處理的 PDF 文件。", []))
            return []
            
        for idx, file_path in enumerate(files, start=1):
            try:
                out_path = await self.parse_file(file_path, idx, total_files, progress_callback)
                output_files.append(out_path)
            except Exception as err:
                if progress_callback:
                    progress_callback(ParserProgress(
                        current_file_idx=idx,
                        total_files=total_files,
                        current_page=0,
                        total_pages=0,
                        status_msg=f"❌ 文件 {file_path.name} 嚴重轉換失敗。原因: {err}",
                        audit_alerts=[{
                            "file": file_path.name,
                            "page": 0,
                            "type": "文件崩溃",
                            "status": "error",
                            "message": f"文件嚴重轉換失敗: {err}",
                            "msg": str(err)
                        }]
                    ))
        return output_files
