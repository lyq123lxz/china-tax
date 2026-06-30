"""
utils/csv_closing.py
CSV 平仓交易提取与整理工具
"""

import csv
import io
from pathlib import Path
from datetime import datetime
from typing import Any

from .closing_utils import MetadataList, parse_date, is_date, generate_closing_report as base_generate_closing_report
from .closing_extractor import extract_closing_trades

def parse_csv_tables(csv_content: str) -> list[list[list[str]]]:
    """
    将 CSV 内容解析为多张表（根据空行分隔）。
    返回: list[list[list[str]]], 即 list of tables, each table is list of rows, each row is list of cells.
    """
    reader = csv.reader(io.StringIO(csv_content))

    tables: list[list[list[str]]] = []
    current_table = MetadataList()
    current_table.page_num = 1  # default page
    
    file_line = 0
    last_seen_global_date = ""
    
    for row in reader:
        file_line += 1
        is_empty = not row or all(c.strip() == "" for c in row)
        if is_empty:
            if current_table:
                for r in current_table:
                    r.fallback_date = last_seen_global_date
                tables.append(current_table)
                current_table = MetadataList()
                current_table.page_num = 1
        else:
            row_cells = [c.strip() for c in row]
            
            for cell in row_cells:
                if is_date(cell):
                    last_seen_global_date = cell
                    break
            
            row_obj = MetadataList(row_cells)
            row_obj.page_num = 1
            row_obj.file_line = file_line
            current_table.append(row_obj)

    if current_table:
        for r in current_table:
            r.fallback_date = last_seen_global_date
        tables.append(current_table)
    return tables

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
    return base_generate_closing_report(
        combined_trades=combined_trades,
        open_trades=open_trades,
        close_trades=close_trades,
        headers=headers,
        output_dir=output_dir,
        start_date_str=start_date_str,
        end_date_str=end_date_str,
        excel_filename="closing_transactions_csv.xlsx",
        source_format="CSV (.csv)",
        report_title="平仓成交标的提取与整理报告 (CSV 版)"
    )
