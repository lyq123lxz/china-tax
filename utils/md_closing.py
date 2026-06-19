"""
utils/md_closing.py
Markdown 平仓交易提取与整理工具
支持指定时间段过滤，分析平仓成交的标的并生成 Excel 报告。
遵循 md 文件中的原始列字段与顺序，如为英文列名则显示为中英双语。
自动匹配平仓标的与其对应的开仓记录（支持买入开仓、卖空开仓、IPO开仓等）。
生成含有 3 张工作表（总表、只有开仓、只有平仓）的 Excel 账单。
"""

import re
from pathlib import Path
from datetime import datetime
import pandas as pd
from typing import Any

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
        
    # 子字符串模糊匹配，例如 "trade price" -> "trade price (单价)"
    for key, bilingual in BILINGUAL_MAP.items():
        if key in h_lower:
            trans = bilingual.split('(')[1]
            return f"{h_clean} ({trans}"
            
    return h_clean

def parse_date(date_str: str) -> datetime | None:
    """提取并解析各种日期格式"""
    if not date_str:
        return None
    cleaned = re.sub(r'\s+', ' ', date_str.strip())
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%d-%m-%Y", "%Y%m%d", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S"):
        try:
            return datetime.strptime(cleaned, fmt)
        except ValueError:
            continue
    m = re.search(r'(\d{4})[-/](\d{1,2})[-/](\d{1,2})', cleaned)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
    return None

def parse_markdown_tables(md_content: str) -> list[list[dict[str, str]]]:
    """解析 Markdown 中的所有表格"""
    tables = []
    lines = md_content.splitlines()
    
    in_table = False
    current_table_lines = []
    
    for line in lines:
        stripped = line.strip()
        if stripped.startswith('|') and stripped.endswith('|'):
            in_table = True
            current_table_lines.append(stripped)
        else:
            if in_table:
                if len(current_table_lines) >= 3:
                    table_data = _parse_single_markdown_table(current_table_lines)
                    if table_data:
                        tables.append(table_data)
                current_table_lines = []
                in_table = False
                
    if in_table and len(current_table_lines) >= 3:
        table_data = _parse_single_markdown_table(current_table_lines)
        if table_data:
            tables.append(table_data)
            
    return tables

def _parse_single_markdown_table(lines: list[str]) -> list[dict[str, str]]:
    """解析单张 Markdown 表格"""
    headers = [c.strip() for c in lines[0].split('|')[1:-1]]
    if not headers:
        return []
        
    rows = []
    for line in lines[2:]:
        cells = [c.strip() for c in line.split('|')[1:-1]]
        while len(cells) < len(headers):
            cells.append("")
        row_dict = {}
        for idx, header in enumerate(headers):
            row_dict[header] = cells[idx]
        rows.append(row_dict)
    return rows

def classify_trade_type(action: str, asset: str) -> str:
    """
    分类交易行为。
    返回: 'open' (开仓), 'close' (平仓), 'other' (其他)
    """
    action_lower = action.lower()
    asset_lower = asset.lower()
    
    # 平仓/卖出等收回资金操作
    closing_kws = ["买入平仓", "卖出平仓", "平仓", "close", "liquidate", "cover", "平"]
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
    tables: list[list[dict[str, str]]],
    start_date: datetime | None = None,
    end_date: datetime | None = None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    """
    提取指定时间段内的平仓成交数据，以及匹配的开仓数据。
    返回: (总混合交易列表, 仅开仓交易列表, 仅平仓交易列表, 所有的双语列名顺序列表)
    """
    all_raw_rows = []
    
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
        
    # 1. 扫描并分类所有行
    for table in tables:
        if not table:
            continue
        headers = list(table[0].keys())
        
        date_col = find_key(headers, date_kws)
        asset_col = find_key(headers, asset_kws)
        qty_col = find_key(headers, qty_kws)
        price_col = find_key(headers, price_kws)
        amount_col = find_key(headers, amount_kws)
        action_col = find_key(headers, action_kws)
        
        for row in table:
            orig_date = row.get(date_col, "") if date_col else ""
            orig_asset = row.get(asset_col, "") if asset_col else ""
            orig_action = row.get(action_col, "") if action_col else ""
            
            trade_class = classify_trade_type(orig_action, orig_asset)
            
            all_raw_rows.append({
                "raw_row": row,
                "headers": headers,
                "orig_date": orig_date,
                "orig_asset": orig_asset,
                "trade_class": trade_class
            })
            
    # 2. 筛选出指定时间段内符合要求的平仓成交记录
    target_closing_items = []
    for item in all_raw_rows:
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
            
    # 3. 找出这些平仓成交所对应的标的 (证券名称/代码)
    target_assets = {item["orig_asset"] for item in target_closing_items if item["orig_asset"]}
    
    # 4. 提取这些标的在历史记录中的所有对应开仓成交
    target_opening_items = []
    for item in all_raw_rows:
        if item["trade_class"] == "open" and item["orig_asset"] in target_assets:
            target_opening_items.append(item)
            
    # 5. 合并并按照 [标的, 开平属性(开仓在前), 交易日期] 进行排序
    combined_items = target_opening_items + target_closing_items
    
    def get_sort_key(item):
        asset = item["orig_asset"]
        # 开仓(0) 排在 平仓(1) 前面
        type_sort = 0 if item["trade_class"] == "open" else 1
        date_val = parse_date(item["orig_date"]) or datetime.min
        return (asset, type_sort, date_val)
        
    combined_items.sort(key=get_sort_key)
    
    # 6. 整理并记录所有遇到的列名的双语表示，同时维持原始列顺序
    seen_bilingual_headers = []
    for item in combined_items:
        for h in item["headers"]:
            b_h = to_bilingual_header(h)
            if b_h not in seen_bilingual_headers:
                seen_bilingual_headers.append(b_h)
                
    # 在日期列后面增加双语的 “Trade Type (开平属性)”
    trade_type_col = "Trade Type (开平属性)"
    if "Date (日期)" in seen_bilingual_headers:
        idx = seen_bilingual_headers.index("Date (日期)")
        seen_bilingual_headers.insert(idx + 1, trade_type_col)
    else:
        seen_bilingual_headers.insert(0, trade_type_col)
        
    # 7. 分流转换出总表、仅开仓表、仅平仓表
    bilingual_combined = []
    bilingual_open_only = []
    bilingual_close_only = []
    
    for item in combined_items:
        bilingual_row = {}
        for k, v in item["raw_row"].items():
            bilingual_row[to_bilingual_header(k)] = v
            
        b_type = "Open (开仓)" if item["trade_class"] == "open" else "Close (平仓)"
        bilingual_row[trade_type_col] = b_type
        
        bilingual_combined.append(bilingual_row)
        if item["trade_class"] == "open":
            bilingual_open_only.append(bilingual_row)
        else:
            bilingual_close_only.append(bilingual_row)
            
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
    
    # 采用 pandas.ExcelWriter 写入 3 张工作表
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
        "# 平仓成交标的提取与整理报告",
        f"\n**整理时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "\n## 1. 整理参数与摘要",
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
        lines.append("\n⚠️ **未在指定时间段或上传的文件中检索到符合特征的平仓/开仓成交记录。**")
        
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
        
    return excel_path, report_path
