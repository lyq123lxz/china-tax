"""
utils/md_csv.py
Markdown 表格转 CSV 转换工具。
支持提取 Markdown 文件中的所有表格，并转换为带 BOM 的 CSV 格式（防止 Excel 中文乱码）。
"""

import re
import csv
from pathlib import Path
from typing import Any

def clean_value(val: str) -> str:
    """清洗单元格值：去除首尾空格，并清洗千分位逗号"""
    stripped = val.strip()
    if "," not in stripped:
        return stripped
        
    # 如果英文字符数多于 4，直接跳过以保留英文股票名称
    letters = re.findall(r'[A-Za-z]', stripped)
    if len(letters) > 4:
        return stripped
        
    # 如果包含非金融单位的中文字符，跳过千分位清洗（避免地址等文本被误处理）
    if any(c not in ('元', '股', '万', '亿', '币') for c in re.findall(r'[\u4e00-\u9fa5]', stripped)):
        return stripped
    # 千分位模式：1-3位数字开头，后跟一组或多组 ",xxx"
    thousand_sep_pattern = r'\d{1,3}(,\d{3})+'
    if re.search(thousand_sep_pattern, stripped):
        def remove_sep(m: re.Match) -> str:
            return m.group(0).replace(",", "")
        return re.sub(thousand_sep_pattern, remove_sep, stripped)
    return stripped

def parse_markdown_tables_from_file(md_path: Path) -> list[list[list[str]]]:
    """
    从 Markdown 文件中解析出所有表格。
    每个表格表示为 row_list，其中每行是一个 cell_list 的字符串。
    """
    # 严格使用 utf-8-sig 读取
    content = md_path.read_text(encoding="utf-8-sig", errors="ignore")
    lines = content.splitlines()
    
    tables = []
    current_table_lines = []
    in_table = False
    
    for line in lines:
        stripped = line.strip()
        if stripped.startswith('|') and stripped.endswith('|'):
            in_table = True
            current_table_lines.append(stripped)
        else:
            if in_table:
                if len(current_table_lines) >= 3:
                    table_data = _parse_table_lines(current_table_lines)
                    if table_data:
                        tables.append(table_data)
                current_table_lines = []
                in_table = False
                
    if in_table and len(current_table_lines) >= 3:
        table_data = _parse_table_lines(current_table_lines)
        if table_data:
            tables.append(table_data)
            
    return tables

def _parse_table_lines(lines: list[str]) -> list[list[str]]:
    """解析单张表格的行，过滤掉分隔行"""
    parsed_rows = []
    for line in lines:
        cells = [clean_value(c) for c in line.split('|')[1:-1]]
        # 检查是否是分割线行如 |---|:---|
        is_sep = True
        for cell in cells:
            cell_clean = cell.replace(':', '').replace('-', '').strip()
            if cell_clean:
                is_sep = False
                break
        if is_sep and cells:
            continue
        parsed_rows.append(cells)
    return parsed_rows

def convert_md_to_csv(md_path: Path, csv_path: Path) -> list[dict[str, Any]]:
    """
    将单个 Markdown 文件中的所有表格转换为一个 CSV 文件。
    如果包含多个表格，用空行分隔。
    使用 utf-8-sig 编码写出以确保 Excel 打开不乱码。
    返回审计日志列表。
    """
    alerts = []
    file_name = md_path.name
    
    try:
        tables = parse_markdown_tables_from_file(md_path)
        if not tables:
            alerts.append({
                "file": file_name,
                "type": "MD转CSV",
                "status": "warning",
                "message": "未在 Markdown 文件中检测到任何有效表格结构。"
            })
            csv_path.parent.mkdir(parents=True, exist_ok=True)
            with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
                pass
            return alerts
            
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            for idx, table in enumerate(tables):
                if idx > 0:
                    writer.writerow([])
                for row in table:
                    writer.writerow(row)
                    
        alerts.append({
            "file": file_name,
            "type": "MD转CSV",
            "status": "success",
            "message": f"成功转换 {len(tables)} 张表格到 CSV 文件 {csv_path.name}。"
        })
    except Exception as err:
        alerts.append({
            "file": file_name,
            "type": "MD转CSV",
            "status": "error",
            "message": f"转换 CSV 失败。原因: {str(err)}"
        })
        
    return alerts
