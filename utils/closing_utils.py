import re
import warnings
from pathlib import Path
from datetime import datetime
import pandas as pd
from typing import Any

# 忽略 openpyxl 样式相关的 UserWarning，防止缺少默认样式引起日志输出或在严格警告模式下报错
warnings.filterwarnings("ignore", category=UserWarning, module="openpyxl")

class MetadataList(list):
    pass

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
    cleaned = date_str.replace("年", "-").replace("月", "-").replace("日", "").strip()
    cleaned = re.sub(r'\s+', ' ', cleaned)
    if re.search(r'\d{1,4}\.\d{1,2}\.\d{1,4}', cleaned):
        cleaned = re.sub(r'(\d{1,4})\.(\d{1,2})\.(\d{1,4})', r'\1-\2-\3', cleaned, count=1)
    
    for fmt in (
        "%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%m-%d-%Y", "%Y%m%d",
        "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M",
        "%d/%m/%Y %H:%M:%S", "%m/%d/%Y %H:%M:%S"
    ):
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

def is_date(val: str) -> bool:
    """粗略判断一个字符串是否包含日期"""
    cleaned = val.strip()
    if re.search(r'\d{4}[-/.]\d{1,2}[-/.]\d{1,2}', cleaned):
        return True
    if re.search(r'\d{1,2}[-/.]\d{1,2}[-/.]\d{4}', cleaned):
        return True
    if re.search(r'\d{4}年\d{1,2}月\d{1,2}日', cleaned):
        return True
    if re.match(r'^(19|20)\d{6}$', cleaned):
        return True
    return False

def is_time(val: str) -> bool:
    """粗略判断一个字符串是否包含时间（支持 HH:MM 和 HH:MM:SS）"""
    return bool(re.search(r'\d{1,2}:\d{2}(?::\d{2})?', val))

def is_number(val: str) -> bool:
    """判断字符串是否为数字。支持过滤 HTML 标签与多行拆分处理。"""
    s = val.strip()
    if not s:
        return False

    # 清洗 HTML 标签如 <br> 或 <br/> 并处理多行拼接情况
    s = re.sub(r'<[^>]+>', ' ', s).strip()
    if " " in s:
        parts = s.split()
        for p in parts:
            if is_number(p):
                return True
        return False
        
    chinese_chars = re.findall(r'[\u4e00-\u9fa5]', s)
    if len(chinese_chars) > 0:
        if len(chinese_chars) == 1 and chinese_chars[0] in ('元', '股', '万', '亿', '币'):
            pass
        else:
            return False
            
    letters = re.findall(r'[A-Za-z]', s)
    if len(letters) > 4:
        return False
        
    if re.match(r'^[Pp](?:g|age)?[.\s]?\d+', s):
        return False
        
    # 彻底清理掉货币符号及逗号再校验
    cleaned = re.sub(r'[\$\u00a5\u00a3\u20ac\uffe5\u20a9]', '', s)
    cleaned = re.compile(r'^[A-Z]{2,4}\$?\s*', re.I).sub('', cleaned)
    cleaned = re.compile(r'\s*[A-Z]{2,4}$', re.I).sub('', cleaned)
    cleaned = cleaned.replace(",", "").replace("%", "").strip()
    
    # 检查括号形式的负数 (123.45)
    if cleaned.startswith("(") and cleaned.endswith(")"):
        cleaned = cleaned[1:-1].strip()
        
    if cleaned.endswith("-"):
        cleaned = cleaned[:-1].strip()
        
    if not cleaned:
        return False
        
    # 看是否能转换为浮点数
    try:
        float(cleaned)
        return True
    except ValueError:
        return False

def parse_float(val: str) -> float:
    """将包含各种财务格式的字符串解析为浮点数，支持 HTML 标签与多行拆分处理，失败则返回 0.0"""
    s = val.strip()
    if not s:
        return 0.0

    # 清洗 HTML 标签如 <br> 或 <br/> 并处理多行拼接情况
    s = re.sub(r'<[^>]+>', ' ', s).strip()
    if " " in s:
        parts = s.split()
        for p in parts:
            res = parse_float(p)
            if res != 0.0:
                return res
        if parts:
            return parse_float(parts[0])
        return 0.0
        
    is_negative = False
    if s.startswith("(") and s.endswith(")"):
        is_negative = True
        s = s[1:-1].strip()
    elif s.endswith("-"):
        is_negative = True
        s = s[:-1].strip()
    elif s.startswith("-"):
        is_negative = True
        s = s[1:].strip()
        
    cleaned = re.sub(r'[\$\u00a5\u00a3\u20ac\uffe5\u20a9]', '', s)
    cleaned = re.compile(r'^[A-Z]{2,4}\$?\s*', re.I).sub('', cleaned)
    cleaned = re.compile(r'\s*[A-Z]{2,4}$', re.I).sub('', cleaned)
    cleaned = cleaned.replace(",", "").replace("%", "").strip()
    
    if not cleaned:
        return 0.0
        
    try:
        val_float = float(cleaned)
        if is_negative:
            val_float = -val_float
        return val_float
    except ValueError:
        return 0.0

def classify_trade_type(action: str, asset: str) -> str:
    """分类交易行为：open, close, other"""
    action_lower = action.strip().lower()
    asset_lower = asset.strip().lower()
    
    non_execution_kws = ["没成交", "未成交", "已撤销", "撤单", "已撤", "废单", "canceled", "cancelled", "expired", "rejected", "failed", "void"]
    if any(kw in action_lower or kw in asset_lower for kw in non_execution_kws):
        return "other"
        
    closing_kws = ["买入平仓", "卖出平仓", "平仓", "close", "liquidate", "cover", "sold", "redemption", "redeem"]
    if any(kw in action_lower or kw in asset_lower for kw in closing_kws):
        return "close"
        
    short_open_kws = ["卖空开仓", "sell to open", "short open", "开空"]
    if any(kw in action_lower or kw in asset_lower for kw in short_open_kws):
        return "open"
        
    if "sell" in action_lower or "sold" in action_lower or "卖出" in action_lower or "卖" in action_lower:
        return "close"
        
    opening_kws = ["买入开仓", "buy to open", "开仓", "open", "ipo", "新股", "认购", "allotment", "buy", "bought", "purchase", "pur", "买入", "买"]
    if any(kw in action_lower or kw in asset_lower for kw in opening_kws):
        return "open"
        
    return "other"

def generate_closing_report(
    combined_trades: list[dict[str, Any]],
    open_trades: list[dict[str, Any]],
    close_trades: list[dict[str, Any]],
    headers: list[str],
    output_dir: Path,
    start_date_str: str = "",
    end_date_str: str = "",
    excel_filename: str = "closing_transactions.xlsx",
    source_format: str = "Markdown (.md)",
    report_title: str = "平仓成交标的提取与整理报告"
) -> tuple[Path, Path]:
    """生成平仓成交整理报告 (Excel 含有 3 张 Sheet + MD 审计报告)"""
    output_dir.mkdir(parents=True, exist_ok=True)
    
    excel_path = output_dir / excel_filename
    report_path = output_dir / "report.md"
    
    # 1. 跨文件/全局过滤开仓记录（只保留与被平仓的标的匹配 of 开仓记录）
    target_assets = {t.get("_orig_asset") for t in close_trades if t.get("_orig_asset")}
    filtered_open_trades = [t for t in open_trades if t.get("_orig_asset") in target_assets]
    
    # 2. 重新拼接总表
    filtered_combined_trades = filtered_open_trades + close_trades
    
    # 3. 对总表进行重新排序
    def get_sort_key(t):
        date_str = t.get("_orig_date", "")
        date_val = parse_date(date_str) or datetime.min
        file_name = t.get("来自文件", "")
        asset = t.get("_orig_asset", "")
        is_open = t.get("_trade_class") == "open"
        return (date_val, file_name, asset, 0 if is_open else 1)
        
    filtered_combined_trades.sort(key=get_sort_key)
    filtered_open_trades.sort(key=lambda t: (parse_date(t.get("_orig_date", "")) or datetime.min, t.get("来自文件", "")))
    close_trades.sort(key=lambda t: (parse_date(t.get("_orig_date", "")) or datetime.min, t.get("来自文件", "")))
    
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
        f"# {report_title}",
        f"\n**整理时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "\n## 1. 整理参数与摘要",
        f"- **源数据格式**: {source_format}",
        f"- **设定筛选时间段**: {start_date_str or '未限定'} 至 {end_date_str or '未限定'}",
        f"- **总匹配交易记录**: {total} 笔",
        f"  - **开仓记录 (IPO/买入/开空等)**: {total_open} 笔",
        f"  - **平仓记录 (卖出/平仓/买平等)**: {total_close} 笔",
        "\n## 2. 平仓成交与对应开仓明细总表 (已按标的分组对齐)"
    ]
    
    if combined_trades:
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
