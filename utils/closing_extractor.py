import re
from datetime import datetime
from typing import Any
from .closing_utils import (
    to_bilingual_header, parse_date, is_date, is_time, is_number, parse_float, classify_trade_type
)

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
        last_seen_date = ""
        
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
            
            # 如果依然没有提取到日期，使用前序行日期或全局备份日期
            if not trade_date:
                trade_date = last_seen_date or getattr(row, "fallback_date", "")
            
            if trade_date and is_date(trade_date):
                last_seen_date = trade_date
                        
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
                
            # 过滤非股票交易的标的
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
                    "trade_amount": trade_amount,
                    "page_num": getattr(row, "page_num", 1),
                    "file_line": getattr(row, "file_line", 0),
                    "table_row_num": i + 1
                })
                
            # 若合并了下一行，则将外层循环索引推前一行
            if best_match and i < len(rows) - 1 and best_match == rows[i + 1]:
                i += 1
            i += 1
            
    # 4. 根据开平属性进行分流，并筛选指定时间段内的平仓数据
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

    page_col = "Page (对应页码)"
    row_col = "Row (对应行号)"
    type_idx = -1
    for idx_h, h in enumerate(seen_bilingual_headers):
        if "开平属性" in h or "trade type" in h.lower():
            type_idx = idx_h
            break
    if type_idx != -1:
        if row_col not in seen_bilingual_headers:
            seen_bilingual_headers.insert(type_idx + 1, row_col)
        if page_col not in seen_bilingual_headers:
            seen_bilingual_headers.insert(type_idx + 1, page_col)
    else:
        if row_col not in seen_bilingual_headers:
            seen_bilingual_headers.insert(0, row_col)
        if page_col not in seen_bilingual_headers:
            seen_bilingual_headers.insert(0, page_col)
        
    # 6. 分流转换出总表、仅开仓表、仅平仓表
    bilingual_open_only = []
    bilingual_close_only = []
    
    def to_bilingual_row(item):
        bilingual_row = {}
        for k, v in item["raw_row"].items():
            bilingual_row[to_bilingual_header(k)] = v
        b_type = "Open (开仓)" if item["trade_class"] == "open" else "Close (平仓)"
        bilingual_row[trade_type_col] = b_type
        
        page_col = "Page (对应页码)"
        row_col = "Row (对应行号)"
        bilingual_row[page_col] = item.get("page_num", 1)
        row_num = item.get("table_row_num", 0)
        file_line = item.get("file_line", 0)
        if file_line > 0:
            bilingual_row[row_col] = f"第 {row_num} 行 (文件第 {file_line} 行)"
        else:
            bilingual_row[row_col] = f"第 {row_num} 行"
            
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
