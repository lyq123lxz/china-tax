"""
utils/csv_closing.py
CSV 平仓交易提取与整理工具 (模块 12)
支持指定时间段过滤，分析平仓成交的标的并生成 Excel 报告。
遵循 CSV 文件中的原始列字段与顺序，如为英文列名则显示为中英双语。
自动匹配平仓标的与其对应的开仓记录（支持买入开仓、卖空开仓、IPO开仓等）。
生成含有 3 张工作表（总表、只有开仓、只有平仓）的 Excel 账单。
"""

import re
import csv
import io
import warnings
from pathlib import Path
from datetime import datetime
import pandas as pd
from typing import Any

# 忽略 openpyxl 样式相关的 UserWarning，防止缺少默认样式引起日志输出或在严格警告模式下报错
warnings.filterwarnings("ignore", category=UserWarning, module="openpyxl")

# 常用英文列名到中英双语的映射
BILINGUAL_MAP = {
    "date": "Date (日期)",
    "time": "Time (时间)",
    "qty": "Quantity (数量)",
    "quantity": "Quantity (数量)",
    "price": "Price (单价)",
    "price/share": "Price/Share (单价)",
    "amount": "Amount (成交金额)",
    "net amount": "Net Amount (发生金额)",
    "desc": "Description (描述)",
    "description": "Description (描述)",
    "symbol": "Symbol (标的代码)",
    "security": "Security (证券名称)",
    "name": "Name (名称)",
    "type": "Type (类型)",
    "action": "Action (操作/方向)",
    "side": "Side (买卖方向)",
    "activity": "Activity (交易活动)",
    "direction": "Direction (方向)",
    "commission": "Commission (佣金/手续费)",
    "fee": "Fee (费用)",
    "fees": "Fees (费用)",
    "currency": "Currency (币种)",
    "balance": "Balance (余额)",
}

def contains_chinese(s: str) -> bool:
    """判断字符串中是否包含中文字符"""
    return any('\u4e00' <= char <= '\u9fff' for char in s)

def to_bilingual_header(h: str) -> str:
    """如果列名是纯英文，则转换成中英双语，否则保持原样"""
    h_clean = h.strip()
    if not h_clean:
        return ""
    if contains_chinese(h_clean):
        return h_clean
        
    h_lower = h_clean.lower()
    if h_lower in BILINGUAL_MAP:
        return BILINGUAL_MAP[h_lower]
        
    for key, bilingual in BILINGUAL_MAP.items():
        if key in h_lower:
            trans = bilingual.split('(')[1]
            return f"{h_clean} ({trans}"
            
    return h_clean

def parse_date(date_str: str) -> datetime | None:
    """提取并解析各种日期格式"""
    if not date_str:
        return None
    # 替换中文年月日为标准分隔符，点替换为横杠
    cleaned = date_str.replace("年", "-").replace("月", "-").replace("日", "").strip()
    cleaned = re.sub(r'\s+', ' ', cleaned)
    cleaned = cleaned.replace(".", "-")
    
    # 优先解析 2026-01-01 等常见格式
    for fmt in (
        "%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%d-%m-%Y", "%Y%m%d",
        "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M"
    ):
        try:
            return datetime.strptime(cleaned, fmt)
        except ValueError:
            continue
            
    # 正则提取
    m = re.search(r'(\d{4})[-/](\d{1,2})[-/](\d{1,2})', cleaned)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
            
    return None

def is_date(val: str) -> bool:
    """粗略判断一个字符串是否包含日期"""
    cleaned = val.strip()
    # 支持 - / . 和中文年月日
    if re.search(r'\d{4}[-/.]\d{1,2}[-/.]\d{1,2}', cleaned):
        return True
    if re.search(r'\d{1,2}[-/.]\d{1,2}[-/.]\d{4}', cleaned):
        return True
    if re.search(r'\d{4}年\d{1,2}月\d{1,2}日', cleaned):
        return True
    # 匹配8位数字的日期，例如 20260101
    if re.match(r'^(19|20)\d{6}$', cleaned):
        return True
    return False

def is_time(val: str) -> bool:
    """粗略判断一个字符串是否包含时间"""
    return bool(re.search(r'\d{2}:\d{2}:\d{2}', val))

def is_number(val: str) -> bool:
    """
    判断字符串是否为数字。
    支持：任意货币符号（$、¥、£、€ 等）及常见币种简写（SGD、USD、HKD等）、千分位逗号、会计括号负数、尾部负号、百分号。
    通过字数和中英文本启发式过滤，防范地址、时间、页码等与数字相关但非数值的列被误判为数值。
    """
    s = val.strip()
    if not s:
        return False
        
    # 排除包含多于1个中文字符的串（防止像 "朝阳区建国路88号" 这样的地址被剥离成 88 误判为数字）
    chinese_chars = re.findall(r'[\u4e00-\u9fa5]', s)
    if len(chinese_chars) > 0:
        # 只放行极少数可能的单字金融单位
        if len(chinese_chars) == 1 and chinese_chars[0] in ('元', '股', '万', '亿', '币'):
            pass
        else:
            return False
            
    # 如果英文字母个数大于 4，则直接判定不是数字（防止 "Block 12", "Page 1 of 5", "Invoice No" 被误判）
    letters = re.findall(r'[A-Za-z]', s)
    if len(letters) > 4:
        return False
        
    # 清洗数字
    cleaned = s.replace("$", "").replace("¥", "").replace("£", "").replace("€", "").replace("￥", "").replace(",", "").strip()
    for currency in ("SGD", "USD", "HKD", "EUR", "CNY", "GBP", "CAD", "AUD", "NZD", "JPY", "KRW", "TWD"):
        cleaned = cleaned.replace(currency, "").replace(currency.lower(), "")
    cleaned = cleaned.strip()
    
    # 括号负数与尾部负号
    if cleaned.startswith("(") and cleaned.endswith(")") and len(cleaned) > 2:
        cleaned = "-" + cleaned[1:-1]
    if cleaned.endswith("-") and len(cleaned) > 1:
        cleaned = "-" + cleaned[:-1]
        
    try:
        float(cleaned)
        return True
    except ValueError:
        return False

def parse_float(val: str) -> float:
    """
    解析数字字符串（支持任意货币符号、千分位逗号、会计负值括号格式、尾部负号）
    """
    if not val:
        return 0.0
    s = val.strip()
    cleaned = s.replace("$", "").replace("¥", "").replace("£", "").replace("€", "").replace("￥", "").replace(",", "").strip()
    for currency in ("SGD", "USD", "HKD", "EUR", "CNY", "GBP", "CAD", "AUD", "NZD", "JPY", "KRW", "TWD", "元", "股", "万", "亿"):
        cleaned = cleaned.replace(currency, "").replace(currency.lower(), "")
    cleaned = cleaned.strip()
    
    if cleaned.startswith("(") and cleaned.endswith(")") and len(cleaned) > 2:
        cleaned = "-" + cleaned[1:-1]
    if cleaned.endswith("-") and len(cleaned) > 1:
        cleaned = "-" + cleaned[:-1]
        
    try:
        return float(cleaned)
    except ValueError:
        return 0.0

def parse_csv_tables(csv_content: str) -> list[list[list[str]]]:
    """
    将 CSV 内容解析为多张表（根据空行分隔）。
    返回: list[list[list[str]]], 即 list of tables, each table is list of rows, each row is list of cells.

    Bug Fix 10: 原先用 csv_content.splitlines() 再传入 csv.reader，
    无法处理内嵌换行符的带引号字段；
    改用 csv.reader(io.StringIO(csv_content)) 正确处理引号内多行字段。
    """
    reader = csv.reader(io.StringIO(csv_content))

    tables: list[list[list[str]]] = []
    current_table: list[list[str]] = []
    for row in reader:
        # 检查是否是空行或全部是空字符串的行
        is_empty = not row or all(c.strip() == "" for c in row)
        if is_empty:
            if current_table:
                tables.append(current_table)
                current_table = []
        else:
            current_table.append([c.strip() for c in row])

    if current_table:
        tables.append(current_table)
    return tables

def classify_trade_type(action: str, asset: str) -> str:
    """
    分类交易行为。
    返回: 'open' (开仓), 'close' (平仓), 'other' (其他)
    注意：排除了未成交、撤单等非成交状态。
    """
    action_lower = action.strip().lower()
    asset_lower = asset.strip().lower()
    
    # 没成交的关键字过滤
    non_execution_kws = ["没成交", "未成交", "已撤销", "撤单", "已撤", "废单", "canceled", "cancelled", "expired", "rejected", "failed", "void"]
    if any(kw in action_lower or kw in asset_lower for kw in non_execution_kws):
        return "other"
        
    # Bug Fix 7: 移除单字 "平"，避免误匹配 "平安"、"太平" 等含"平"字的股票名称。
    # 只保留明确的复合词 "平仓"、"买入平仓"、"卖出平仓"。
    closing_kws = ["买入平仓", "卖出平仓", "平仓", "close", "liquidate", "cover"]
    if any(kw in action_lower or kw in asset_lower for kw in closing_kws):
        return "close"
        
    # 特例：卖空开仓
    short_open_kws = ["卖空开仓", "sell to open", "short open", "开空"]
    if any(kw in action_lower or kw in asset_lower for kw in short_open_kws):
        return "open"
        
    if "sell" in action_lower or "卖出" in action_lower or "卖" in action_lower:
        return "close"
        
    # 开仓/买入/IPO/配售等建仓操作
    opening_kws = ["买入开仓", "buy to open", "开仓", "open", "ipo", "新股", "认购", "allotment", "buy", "买入", "买"]
    if any(kw in action_lower or kw in asset_lower for kw in opening_kws):
        return "open"
        
    return "other"

def extract_closing_trades(
    tables: list[list[list[str]]],
    start_date: datetime | None = None,
    end_date: datetime | None = None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    """
    提取平仓成交数据与开仓成交数据。
    返回: (总混合交易列表, 仅开仓交易列表, 仅平仓交易列表, 所有的双语列名顺序列表)
    """
    all_raw_trades = []
    
    # 列匹配关键字
    date_kws = ["date", "time", "日期", "时间"]
    asset_kws = ["desc", "symbol", "asset", "name", "security", "details", "comment", "名称", "证券", "描述", "资产", "说明", "备注", "代码"]
    qty_kws = ["qty", "quantity", "数量", "成交股数", "股数", "单位"]
    price_kws = ["price", "price/share", "单价", "价格", "成交价格", "成交均价"]
    amount_kws = ["amount", "net amount", "金额", "总金额", "结算金额", "成交金额", "发生金额"]
    action_kws = ["type", "action", "side", "activity", "direction", "类别", "类型", "操作", "买卖", "业务类型"]
    
    def find_key(headers: list[str], kws: list[str]) -> str | None:
        for h in headers:
            if any(kw in h.lower() for kw in kws):
                return h
        return None
        
    # 逐张表格处理
    for table in tables:
        if len(table) < 2:
            continue
            
        rows = table
        
        # 1. 检测表头行
        header_row_idx = -1
        table_headers = list(rows[0])
        for idx, r in enumerate(rows):
            r_lower = [c.lower() for c in r]
            has_dir = any(any(kw in c for kw in ["direction", "action", "type", "买卖", "方向"]) for c in r_lower)
            has_sym = any(any(kw in c for kw in ["symbol", "code", "代码"]) for c in r_lower)
            has_qty = any(any(kw in c for kw in ["qty", "quantity", "数量", "股数"]) for c in r_lower)
            if has_dir or (has_sym and has_qty):
                table_headers = list(r)
                header_row_idx = idx
                break
                
        # 2. 找到成交记录行的索引（跳过小计、总计等非明细行）
        # Bug Perf: 改用 set 存储，成员检测由 O(n) 降至 O(1)
        trade_rows_indices: set[int] = set()
        for idx in range(header_row_idx + 1, len(rows)):
            r = rows[idx]
            r_str = " ".join(r).lower()
            if "subtotal" in r_str or "total" in r_str or "direction" in r_str or "number of" in r_str:
                continue
            for cell in r:
                if classify_trade_type(cell, "") in ["open", "close"]:
                    trade_rows_indices.add(idx)
                    break
                    
        if not trade_rows_indices:
            continue
            
        # 找到列字段映射
        date_col = find_key(table_headers, date_kws)
        asset_col = find_key(table_headers, asset_kws)
        qty_col = find_key(table_headers, qty_kws)
        price_col = find_key(table_headers, price_kws)
        amount_col = find_key(table_headers, amount_kws)
        action_col = find_key(table_headers, action_kws)
        
        # 3. 双层/邻行合并与提取
        i = header_row_idx + 1
        while i < len(rows):
            if i not in trade_rows_indices:
                i += 1
                continue
                
            row = rows[i]
            
            # 找到交易动作单元格
            action = ""
            for cell in row:
                if classify_trade_type(cell, "") in ["open", "close"]:
                    action = cell
                    break
                    
            # 寻找可以合并的上下裂开行
            candidate_rows = []
            if i > header_row_idx + 1 and (i - 1) not in trade_rows_indices:
                candidate_rows.append(rows[i - 1])
            if i < len(rows) - 1 and (i + 1) not in trade_rows_indices:
                candidate_rows.append(rows[i + 1])
                
            best_match = None
            for cand in candidate_rows:
                cand_str = " ".join(cand).lower()
                if "subtotal" in cand_str or "total" in cand_str or "direction" in cand_str or "number of" in cand_str:
                    continue
                has_t = any(is_time(cell) for cell in cand)
                has_ticker = any(re.match(r'^[A-Z]{2,6}$', cell) for cell in cand)
                if has_t or has_ticker:
                    best_match = cand
                    break
                    
            merged = list(row)
            if best_match:
                for col_idx in range(min(len(row), len(best_match))):
                    if not merged[col_idx] and best_match[col_idx]:
                        merged[col_idx] = best_match[col_idx]
                    elif merged[col_idx] and best_match[col_idx]:
                        if is_date(merged[col_idx]) and is_time(best_match[col_idx]):
                            merged[col_idx] = merged[col_idx] + " " + best_match[col_idx]
                        elif is_time(merged[col_idx]) and is_date(best_match[col_idx]):
                            merged[col_idx] = best_match[col_idx] + " " + merged[col_idx]
                        else:
                            val_main = merged[col_idx]
                            val_cand = best_match[col_idx]
                            is_main_ticker = re.match(r'^[A-Z]{2,6}$', val_main) and val_main not in ["US", "USD", "SGD", "HKD", "CNH", "JPY"]
                            is_cand_ticker = re.match(r'^[A-Z]{2,6}$', val_cand) and val_cand not in ["US", "USD", "SGD", "HKD", "CNH", "JPY"]
                            if is_cand_ticker and not is_main_ticker:
                                merged[col_idx] = val_cand
                            elif not is_main_ticker and not is_cand_ticker:
                                merged[col_idx] = val_main + " " + val_cand
                                
            # 提取日期
            trade_date = ""
            for cell in merged:
                if is_date(cell) or (cell.split() and is_date(cell.split()[0])):
                    trade_date = cell
                    break
            if not trade_date:
                for cell in merged:
                    if is_time(cell):
                        trade_date = cell
                        break
                        
            # 提取标的代码
            trade_symbol = ""
            symbol_candidates = []
            for cell in merged:
                if not cell:
                    continue
                if re.match(r'^[A-Z]{2,6}$', cell) and cell not in ["US", "USD", "SGD", "HKD", "CNH", "JPY", "BUY", "SELL", "P.2", "P.3", "P.4", "P.5", "P.6", "P.7", "P.8", "P.9", "P.10"]:
                    symbol_candidates.append(cell)
                    
            if symbol_candidates:
                trade_symbol = symbol_candidates[0]
            else:
                for cell in merged:
                    if not cell:
                        continue
                    m = re.search(r'\b([A-Z]{2,6})\b', cell)
                    if m:
                        ticker = m.group(1)
                        if ticker not in ["US", "USD", "SGD", "HKD", "CNH", "JPY", "BUY", "SELL", "AGENCY", "IPO"]:
                            trade_symbol = ticker
                            break
                            
            # 标的代码兜底
            if not trade_symbol and asset_col:
                asset_idx = table_headers.index(asset_col)
                if asset_idx < len(merged):
                    trade_symbol = merged[asset_idx].strip()
                    
            if trade_symbol.lower() in ["symbol", "ticker", "currency", "exchange"]:
                i += 1
                continue
                
            # 过滤非股票交易的标的（例如现金汇总行 "Sell Amount", "Sell Fee" 等）
            trade_symbol_clean = trade_symbol.strip()
            invalid_symbol_kws = ["amount", "fee", "fees", "total", "subtotal", "cash", "changes", "interest", "dividend", "tax", "balance", "starting", "ending", "exchange", "client", "account", "net asset"]
            if any(kw in trade_symbol_clean.lower() for kw in invalid_symbol_kws):
                i += 1
                continue
                
            # 提取成交数量、价格和金额
            qty_col_idx = table_headers.index(qty_col) if qty_col in table_headers else -1
            price_col_idx = table_headers.index(price_col) if price_col in table_headers else -1
            amount_col_idx = table_headers.index(amount_col) if amount_col in table_headers else -1
            
            direct_qty = merged[qty_col_idx] if qty_col_idx != -1 and qty_col_idx < len(merged) else ""
            direct_price = merged[price_col_idx] if price_col_idx != -1 and price_col_idx < len(merged) else ""
            direct_amount = merged[amount_col_idx] if amount_col_idx != -1 and amount_col_idx < len(merged) else ""
            
            trade_qty = ""
            trade_price = ""
            trade_amount = ""
            
            if direct_qty and direct_price and is_number(direct_qty) and is_number(direct_price):
                trade_qty = direct_qty
                trade_price = direct_price
                trade_amount = direct_amount if direct_amount else f"{parse_float(direct_qty) * parse_float(direct_price)}"
            else:
                # 鲁棒性数学逻辑匹配
                nums = []
                for cell in merged:
                    if not cell:
                        continue
                    if is_number(cell) and not is_date(cell) and not is_time(cell):
                        val = parse_float(cell)
                        nums.append((val, cell))
                        
                nums_filtered = []
                for val, cell in nums:
                    if val > 1000000 and val.is_integer():
                        continue
                    nums_filtered.append((val, cell))
                    
                if len(nums_filtered) >= 3:
                    val0, cell0 = nums_filtered[0]
                    val1, cell1 = nums_filtered[1]
                    val2, cell2 = nums_filtered[2]
                    
                    # Bug Fix 6: 防止 val2==0 时产生 ZeroDivisionError
                    if abs(val0 * val1 - val2) < 0.1 or (val2 != 0 and abs(val0 * val1 - val2) / val2 < 0.01):
                        trade_amount = cell2
                        if val0.is_integer() and not val1.is_integer():
                            trade_qty = cell0
                            trade_price = cell1
                        else:
                            trade_qty = cell1
                            trade_price = cell0
                    else:
                        trade_price = cell0
                        trade_qty = cell1
                        trade_amount = cell2
                elif len(nums_filtered) == 2:
                    val0, cell0 = nums_filtered[0]
                    val1, cell1 = nums_filtered[1]
                    if val0.is_integer():
                        trade_qty = cell0
                        trade_price = cell1
                    else:
                        trade_price = cell0
                        trade_amount = cell1
                        
            # 如果数学匹配没有提取到，则使用直接提取的数据兜底
            if not trade_qty and direct_qty:
                trade_qty = direct_qty
            if not trade_price and direct_price:
                trade_price = direct_price
            if not trade_amount and direct_amount:
                trade_amount = direct_amount
                
            # 过滤：由于必须是真正的交易，我们需要成交数量与单价都是有效数字
            if not trade_qty or not trade_price or not is_number(trade_qty) or not is_number(trade_price):
                if best_match and i < len(rows) - 1 and best_match == rows[i + 1]:
                    i += 1
                i += 1
                continue
                
            # 记录交易记录
            if trade_symbol and action:
                raw_row = {}
                for col_idx, h in enumerate(table_headers):
                    if col_idx < len(merged):
                        raw_row[h] = merged[col_idx]
                    else:
                        raw_row[h] = ""
                        
                # 覆写提取到的正确值到关键字段中
                if qty_col:
                    raw_row[qty_col] = trade_qty
                if price_col:
                    raw_row[price_col] = trade_price
                if amount_col:
                    raw_row[amount_col] = trade_amount
                if asset_col:
                    raw_row[asset_col] = trade_symbol
                if date_col:
                    raw_row[date_col] = trade_date
                    
                trade_class = "close" if classify_trade_type(action, "") == "close" else "open"
                
                all_raw_trades.append({
                    "raw_row": raw_row,
                    "headers": table_headers,
                    "orig_date": trade_date,
                    "orig_asset": trade_symbol,
                    "trade_class": trade_class,
                    "trade_qty": trade_qty,
                    "trade_price": trade_price,
                    "trade_amount": trade_amount
                })
                
            # 若合并了下一行，则将外层循环索引推前一行
            if best_match and i < len(rows) - 1 and best_match == rows[i + 1]:
                i += 1
            i += 1
            
    # 4. 根据开平属性进行分流，并筛选指定时间段内的平仓数据
    # 开仓交易由于是在平仓之前发生，不受平仓指定时间段过滤的直接限制（由 generate_closing_report 在全局匹配平仓的标的后进行过滤）
    target_closing_items = []
    target_opening_items = []
    
    for item in all_raw_trades:
        if item["trade_class"] == "close":
            row_date = parse_date(item["orig_date"])
            if row_date:
                if start_date and row_date < start_date:
                    continue
                if end_date and row_date > end_date:
                    continue
            else:
                if start_date or end_date:
                    continue
            target_closing_items.append(item)
        elif item["trade_class"] == "open":
            target_opening_items.append(item)
            
    # 5. 整理并记录所有遇到的列名的双语表示，同时维持原始列顺序
    seen_bilingual_headers = []
    for item in (target_opening_items + target_closing_items):
        for h in item["headers"]:
            b_h = to_bilingual_header(h)
            if b_h not in seen_bilingual_headers:
                seen_bilingual_headers.append(b_h)
                
    # 确保 "Date (日期)" 必定在列表中
    if not any("date" in h.lower() or "日期" in h for h in seen_bilingual_headers):
        seen_bilingual_headers.insert(0, "Date (日期)")

    trade_type_col = "Trade Type (开平属性)"
    date_idx = -1
    for i, h in enumerate(seen_bilingual_headers):
        if "date" in h.lower() or "日期" in h:
            date_idx = i
            break
            
    if date_idx != -1:
        if trade_type_col not in seen_bilingual_headers:
            seen_bilingual_headers.insert(date_idx + 1, trade_type_col)
    else:
        if trade_type_col not in seen_bilingual_headers:
            seen_bilingual_headers.insert(0, trade_type_col)
        
    # 6. 分流转换出总表、仅开仓表、仅平仓表
    bilingual_open_only = []
    bilingual_close_only = []
    
    def to_bilingual_row(item):
        bilingual_row = {}
        for k, v in item["raw_row"].items():
            bilingual_row[to_bilingual_header(k)] = v
        b_type = "Open (开仓)" if item["trade_class"] == "open" else "Close (平仓)"
        bilingual_row[trade_type_col] = b_type
        
        # 确保 Date (日期) 列一定存在并且有值
        date_header = "Date (日期)"
        existing_date_key = None
        for key in bilingual_row:
            if "date" in key.lower() or "日期" in key:
                existing_date_key = key
                break
        if existing_date_key:
            if not bilingual_row[existing_date_key] and item["orig_date"]:
                bilingual_row[existing_date_key] = item["orig_date"]
        else:
            bilingual_row[date_header] = item["orig_date"]
            
        # 写入私有元数据用于全局过滤与排序
        bilingual_row["_orig_asset"] = item["orig_asset"]
        bilingual_row["_orig_date"] = item["orig_date"]
        bilingual_row["_trade_class"] = item["trade_class"]
        return bilingual_row

    for item in target_opening_items:
        bilingual_open_only.append(to_bilingual_row(item))
    for item in target_closing_items:
        bilingual_close_only.append(to_bilingual_row(item))
        
    bilingual_combined = bilingual_open_only + bilingual_close_only
    
    return bilingual_combined, bilingual_open_only, bilingual_close_only, seen_bilingual_headers

def generate_closing_report(
    combined_trades: list[dict[str, Any]],
    open_trades: list[dict[str, Any]],
    close_trades: list[dict[str, Any]],
    headers: list[str],
    output_dir: Path,
    start_date_str: str = "",
    end_date_str: str = ""
) -> tuple[Path, Path]:
    """生成平仓成交整理报告 (Excel 含有 3 张 Sheet + MD 审计报告)"""
    output_dir.mkdir(parents=True, exist_ok=True)
    
    excel_path = output_dir / "closing_transactions.xlsx"
    report_path = output_dir / "report.md"
    
    # 1. 跨文件/全局过滤开仓记录（只保留与被平仓的标的匹配 of 开仓记录）
    target_assets = {t.get("_orig_asset") for t in close_trades if t.get("_orig_asset")}
    filtered_open_trades = [t for t in open_trades if t.get("_orig_asset") in target_assets]
    
    # 2. 重新拼接总表
    filtered_combined_trades = filtered_open_trades + close_trades
    
    # 3. 对总表进行重新排序 (按标的名称、开平属性【开仓在前】、交易日期)
    def get_sort_key(t):
        asset = t.get("_orig_asset", "")
        is_open = t.get("_trade_class") == "open"
        date_str = t.get("_orig_date", "")
        date_val = parse_date(date_str) or datetime.min
        return (asset, 0 if is_open else 1, date_val)
        
    filtered_combined_trades.sort(key=get_sort_key)
    
    # 4. 原地修改传入的 List 对象，使 app.py 以及后续引用能够拿到过滤和排序后的正确列表
    open_trades.clear()
    open_trades.extend(filtered_open_trades)
    
    combined_trades.clear()
    combined_trades.extend(filtered_combined_trades)
    
    # 5. 采用 pandas.ExcelWriter 写入 3 张工作表
    with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
        df_all = pd.DataFrame(combined_trades)
        df_open = pd.DataFrame(open_trades)
        df_close = pd.DataFrame(close_trades)
        
        def save_sheet(df, name):
            if not df.empty:
                present_headers = [h for h in headers if h in df.columns]
                # 重新按 1-N 添加“序号”列，确保独立标序号
                df.insert(0, "序号", range(1, len(df) + 1))
                final_cols = ["序号"] + present_headers
                if "来自文件" in df.columns and "来自文件" not in final_cols:
                    final_cols.append("来自文件")
                df_to_save = df[final_cols]
                df_to_save.to_excel(writer, sheet_name=name, index=False)
                return df_to_save
            else:
                empty_cols = ["序号"] + headers
                if "来自文件" not in empty_cols:
                    empty_cols.append("来自文件")
                empty_df = pd.DataFrame(columns=empty_cols)
                empty_df.to_excel(writer, sheet_name=name, index=False)
                return empty_df
                
        df_all_formatted = save_sheet(df_all, "总表 (含开仓与平仓)")
        save_sheet(df_open, "只有开仓")
        save_sheet(df_close, "只有平仓")
        
    # 生成 Markdown 审计报告
    total = len(combined_trades)
    total_open = len(open_trades)
    total_close = len(close_trades)
    
    lines = [
        "# 平仓成交标的提取与整理报告 (CSV 版)",
        f"\n**整理时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "\n## 1. 整理参数与摘要",
        f"- **源数据格式**: CSV (.csv)",
        f"- **设定筛选时间段**: {start_date_str or '未限定'} 至 {end_date_str or '未限定'}",
        f"- **总匹配交易记录**: {total} 笔",
        f"  - **开仓记录 (IPO/买入/开空等)**: {total_open} 笔",
        f"  - **平仓记录 (卖出/平仓/买平等)**: {total_close} 笔",
        "\n## 2. 平仓成交与对应开仓明细总表 (已按标的分组对齐)"
    ]
    
    if combined_trades:
        # 获取要输出的列名
        final_cols = []
        if not df_all.empty:
            present_headers = [h for h in headers if h in df_all.columns]
            final_cols = ["序号"] + present_headers
            if "来自文件" in df_all.columns and "来自文件" not in final_cols:
                final_cols.append("来自文件")
                
        if final_cols:
            header_line = "| " + " | ".join(final_cols) + " |"
            sep_line = "| " + " | ".join([":---" for _ in final_cols]) + " |"
            lines.extend([header_line, sep_line])
            for idx, row in df_all_formatted.iterrows():
                row_vals = []
                for col in final_cols:
                    val = str(row.get(col, ""))
                    val_clean = val.replace("|", "I")
                    row_vals.append(val_clean)
                lines.append("| " + " | ".join(row_vals) + " |")
    else:
        lines.append("\n⚠️ **未在指定时间段或上传的文件中检索到符合特征 of 平仓/开仓成交记录。**")
        
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
        
    return excel_path, report_path
