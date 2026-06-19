"""
utils/md_closing.py
Markdown 平仓交易提取与整理工具
支持指定时间段过滤，分析平仓成交的标的并生成 Excel 报告。
遵循 md 文件中的原始列字段与顺序，如为英文列名则显示为中英双语。
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

def extract_closing_trades(
    tables: list[list[dict[str, str]]],
    start_date: datetime | None = None,
    end_date: datetime | None = None
) -> tuple[list[dict[str, Any]], list[str]]:
    """
    提取指定时间段内的平仓成交数据。
    返回: (过滤后的双语键值对行列表, 遇到的所有双语列名顺序列表)
    """
    closing_rows = []
    seen_bilingual_headers = []
    
    # 列匹配关键字
    date_kws = ["date", "time", "日期", "时间"]
    asset_kws = ["desc", "symbol", "asset", "name", "security", "details", "comment", "名称", "证券", "描述", "资产", "说明", "备注", "代码"]
    qty_kws = ["qty", "quantity", "数量", "成交股数", "股数", "单位"]
    price_kws = ["price", "price/share", "单价", "价格", "成交价格", "成交均价"]
    amount_kws = ["amount", "net amount", "金额", "总金额", "结算金额", "成交金额", "发生金额"]
    action_kws = ["type", "action", "side", "activity", "direction", "类别", "类型", "操作", "买卖", "业务类型"]
    
    # 平仓/卖出特征关键字
    close_kws = ["平仓", "close", "liquidate", "sell", "卖出", "cover", "平"]
    
    def find_key(headers: list[str], kws: list[str]) -> str | None:
        for h in headers:
            if any(kw in h.lower() for kw in kws):
                return h
        return None
        
    for table in tables:
        if not table:
            continue
        headers = list(table[0].keys())
        
        # 1. 动态分析当前表的列名
        date_col = find_key(headers, date_kws)
        asset_col = find_key(headers, asset_kws)
        qty_col = find_key(headers, qty_kws)
        price_col = find_key(headers, price_kws)
        amount_col = find_key(headers, amount_kws)
        action_col = find_key(headers, action_kws)
        
        # 2. 将当前表的列转换为双语并记录其顺序
        for h in headers:
            b_h = to_bilingual_header(h)
            if b_h not in seen_bilingual_headers:
                seen_bilingual_headers.append(b_h)
                
        # 3. 逐行匹配与转换
        for row in table:
            # 过滤日期
            row_date = None
            if date_col:
                row_date = parse_date(row[date_col])
                
            if row_date:
                if start_date and row_date < start_date:
                    continue
                if end_date and row_date > end_date:
                    continue
            else:
                if start_date or end_date:
                    continue
                    
            # 判断是否为平仓成交
            is_closing = False
            
            if action_col and any(kw in row[action_col].lower() for kw in close_kws):
                is_closing = True
            elif asset_col and any(kw in row[asset_col].lower() for kw in close_kws):
                is_closing = True
            elif qty_col:
                val_str = row[qty_col].strip()
                if val_str.startswith("-") or val_str.startswith("("):
                    is_closing = True
            
            if is_closing:
                bilingual_row = {}
                for k, v in row.items():
                    bilingual_row[to_bilingual_header(k)] = v
                closing_rows.append(bilingual_row)
                
    return closing_rows, seen_bilingual_headers

def generate_closing_report(
    closing_trades: list[dict[str, Any]],
    headers: list[str],
    output_dir: Path,
    start_date_str: str = "",
    end_date_str: str = ""
) -> tuple[Path, Path]:
    """生成平仓成交整理报告 (Excel + MD 审计报告)"""
    output_dir.mkdir(parents=True, exist_ok=True)
    
    excel_path = output_dir / "closing_transactions.xlsx"
    report_path = output_dir / "report.md"
    
    df = pd.DataFrame(closing_trades)
    
    final_cols = []
    if not df.empty:
        # 将 headers 过滤并对其保留顺序
        present_headers = [h for h in headers if h in df.columns]
        
        df.insert(0, "序号", range(1, len(df) + 1))
        final_cols = ["序号"] + present_headers
        
        if "来自文件" in df.columns:
            if "来自文件" not in final_cols:
                final_cols.append("来自文件")
                
        df = df[final_cols]
        df.to_excel(excel_path, index=False)
    else:
        empty_cols = ["序号"] + headers
        if "来自文件" not in empty_cols:
            empty_cols.append("来自文件")
        empty_df = pd.DataFrame(columns=empty_cols)
        empty_df.to_excel(excel_path, index=False)
        
    # 生成 Markdown 审计报告
    total = len(closing_trades)
    lines = [
        "# 平仓成交标的提取与整理报告",
        f"\n**整理时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "\n## 1. 整理参数与摘要",
        f"- **设定筛选时间段**: {start_date_str or '未限定'} 至 {end_date_str or '未限定'}",
        f"- **共匹配并整理出平仓交易**: {total} 笔",
        "\n## 2. 平仓成交标的明细清单"
    ]
    
    if closing_trades and final_cols:
        header_line = "| " + " | ".join(final_cols) + " |"
        sep_line = "| " + " | ".join([":---" for _ in final_cols]) + " |"
        lines.extend([header_line, sep_line])
        for idx, row in df.iterrows():
            row_vals = []
            for col in final_cols:
                val = str(row.get(col, ""))
                val_clean = val.replace("|", "I")
                row_vals.append(val_clean)
            lines.append("| " + " | ".join(row_vals) + " |")
    else:
        lines.append("\n⚠️ **未在指定时间段或上传的文件中检索到符合特征的平仓成交记录。**")
        
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
        
    return excel_path, report_path
