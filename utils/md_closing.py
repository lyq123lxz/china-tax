"""
utils/md_closing.py
Markdown 平仓交易提取与整理工具
支持指定时间段过滤，分析平仓成交的标的并生成 Excel 报告。
"""

import re
from pathlib import Path
from datetime import datetime
from typing import Any

from .closing_utils import MetadataList, parse_date, generate_closing_report as base_generate_closing_report
from .closing_extractor import extract_closing_trades

def _parse_single_markdown_table_raw_with_metadata(
    lines_with_metadata: list[tuple[str, int]],
    page_num: int,
    fallback_date: str
) -> MetadataList:
    rows = MetadataList()
    rows.page_num = page_num
    
    for line, file_line in lines_with_metadata:
        cells = [c.strip() for c in line.split('|')[1:-1]]
        is_sep = True
        for cell in cells:
            cell_clean = cell.replace(':', '').replace('-', '').strip()
            if cell_clean:
                is_sep = False
                break
        if is_sep and cells:
            continue
            
        row_obj = MetadataList(cells)
        row_obj.page_num = page_num
        row_obj.file_line = file_line
        row_obj.fallback_date = fallback_date
        rows.append(row_obj)
        
    return rows

def parse_markdown_tables(md_content: str) -> list[list[list[str]]]:
    """
    解析 Markdown 中的所有表格。
    每个表格表示为一个包含多行的列表，每一行是一个字符串单元格的列表。
    """
    tables = []
    lines = md_content.splitlines()
    
    in_table = False
    current_table_lines = []
    
    current_page = 1
    last_seen_global_date = ""
    
    for line_idx, line in enumerate(lines):
        stripped = line.strip()
        
        page_match = re.search(r'(?:原始PDF頁碼|原始PDF页码|PAGE\s+START)\s*:\s*[Pp]\.?\s*(\d+)', line, re.IGNORECASE)
        if page_match:
            current_page = int(page_match.group(1))
            
        date_match = re.search(r'\b(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})\b|\b(\d{1,2})[-/.](\d{1,2})[-/.](20\d{2})\b|\b(20\d{2})年(\d{1,2})月(\d{1,2})日\b', line)
        if date_match:
            last_seen_global_date = date_match.group(0)
            
        if stripped.startswith('|') and stripped.endswith('|'):
            in_table = True
            current_table_lines.append((stripped, line_idx + 1))
        else:
            if in_table:
                if len(current_table_lines) >= 3:
                    table_data = _parse_single_markdown_table_raw_with_metadata(
                        current_table_lines, current_page, last_seen_global_date
                    )
                    if table_data:
                        tables.append(table_data)
                current_table_lines = []
                in_table = False
                
    if in_table and len(current_table_lines) >= 3:
        table_data = _parse_single_markdown_table_raw_with_metadata(
            current_table_lines, current_page, last_seen_global_date
        )
        if table_data:
            tables.append(table_data)
            
    return tables

def _parse_single_markdown_table_raw(lines: list[str]) -> list[list[str]]:
    """解析单张 Markdown 表格，返回行与单元格的原始列表，过滤掉分隔线行"""
    rows = []
    for line in lines:
        cells = [c.strip() for c in line.split('|')[1:-1]]
        is_sep = True
        for cell in cells:
            cell_clean = cell.replace(':', '').replace('-', '').strip()
            if cell_clean:
                is_sep = False
                break
        if is_sep and cells:
            continue
        rows.append(cells)
    return rows

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
        excel_filename="closing_transactions_md.xlsx",
        source_format="Markdown (.md)",
        report_title="平仓成交标的提取与整理报告 (Markdown 版)"
    )
