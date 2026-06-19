"""
utils/md_closing.py
Markdown 平仓交易提取与整理工具
支持指定时间段过滤，分析平仓成交的标的并生成 Excel 报告。
"""

import re
from pathlib import Path
from datetime import datetime
import pandas as pd
from typing import Any

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
) -> list[dict[str, Any]]:
    """提取指定时间段内的平仓成交数据"""
    closing_rows = []
    
    # 列匹配关键字
    date_kws = ["date", "time", "日期", "时间"]
    asset_kws = ["desc", "symbol", "asset", "name", "security", "details", "comment", "名称", "证券", "描述", "资产", "说明", "备注", "代码"]
    qty_kws = ["qty", "quantity", "数量", "成交股数", "股数", "单位"]
    price_kws = ["price", "price/share", "单价", "价格", "成交价格", "成交均价"]
    amount_kws = ["amount", "net amount", "金额", "总金额", "结算金额", "成交金额", "发生金额"]
    action_kws = ["type", "action", "side", "activity", "direction", "类别", "类型", "操作", "买卖", "业务类型"]
    page_kws = ["原始pdf頁碼", "页码", "page"]
    
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
        
        date_col = find_key(headers, date_kws)
        asset_col = find_key(headers, asset_kws)
        qty_col = find_key(headers, qty_kws)
        price_col = find_key(headers, price_kws)
        amount_col = find_key(headers, amount_kws)
        action_col = find_key(headers, action_kws)
        page_col = find_key(headers, page_kws)
        
        for row in table:
            # 1. 过滤日期
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
                    
            # 2. 判断是否为平仓成交
            is_closing = False
            
            # Heuristic 1: 操作列包含平仓或卖出关键字
            if action_col and any(kw in row[action_col].lower() for kw in close_kws):
                is_closing = True
            # Heuristic 2: 标的描述中含有平仓关键字
            elif asset_col and any(kw in row[asset_col].lower() for kw in close_kws):
                is_closing = True
            # Heuristic 3: 数量为负数（一般代表卖出/平仓）
            elif qty_col:
                val_str = row[qty_col].strip()
                if val_str.startswith("-") or val_str.startswith("("):
                    is_closing = True
            
            if is_closing:
                closing_rows.append({
                    "日期": row.get(date_col, "") if date_col else "",
                    "标的/证券名称": row.get(asset_col, "") if asset_col else "",
                    "类型/方向": row.get(action_col, "") if action_col else "",
                    "成交数量": row.get(qty_col, "") if qty_col else "",
                    "成交均价": row.get(price_col, "") if price_col else "",
                    "成交金额": row.get(amount_col, "") if amount_col else "",
                    "原始PDF页码": row.get(page_col, "") if page_col else ""
                })
                
    return closing_rows

def generate_closing_report(
    closing_trades: list[dict[str, Any]],
    output_dir: Path,
    start_date_str: str = "",
    end_date_str: str = ""
) -> tuple[Path, Path]:
    """生成平仓成交整理报告 (Excel + MD 审计报告)"""
    output_dir.mkdir(parents=True, exist_ok=True)
    
    excel_path = output_dir / "closing_transactions.xlsx"
    report_path = output_dir / "report.md"
    
    df = pd.DataFrame(closing_trades)
    
    # 强类型保存 Excel，保证数字格式不丢失，添加索引序号
    if not df.empty:
        df.insert(0, "序号", range(1, len(df) + 1))
        # 强制将成交数量和均价转换为 string 格式避免长数字和精度被截断，也可适当保留小数
        df.to_excel(excel_path, index=False)
    else:
        # 空数据创建空表结构
        empty_df = pd.DataFrame(columns=["序号", "日期", "标的/证券名称", "类型/方向", "成交数量", "成交均价", "成交金额", "原始PDF页码"])
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
    
    if closing_trades:
        lines.extend([
            "| 序号 | 交易日期 | 标的/证券名称 | 类型/方向 | 成交数量 | 成交价格 | 发生金额 | 页码 |",
            "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |"
        ])
        for idx, row in enumerate(closing_trades, start=1):
            lines.append(
                f"| {idx} | {row.get('日期', '')} | {row.get('标的/证券名称', '')} | {row.get('类型/方向', '')} | {row.get('成交数量', '')} | {row.get('成交均价', '')} | {row.get('成交金额', '')} | {row.get('原始PDF页码', '')} |"
            )
    else:
        lines.append("\n⚠️ **未在指定时间段或上传的文件中检索到符合特征的平仓成交记录。**")
        
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
        
    return excel_path, report_path
