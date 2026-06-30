import time
from pathlib import Path
from typing import Any

def generate_audit_report(results: list[dict[str, Any]], output_dir: Path) -> Path:
    """生成 PDF 查重去密編制審計報告到指定目錄。"""
    report_path = output_dir / "report.md"
    
    total = len(results)
    unique = sum(1 for r in results if r["status"] == "Unique")
    duplicates = sum(1 for r in results if r["status"] == "Duplicate")
    errors = sum(1 for r in results if r["status"] == "Error")
    saved_kb = sum(r["file_size_kb"] for r in results if r["status"] == "Duplicate")
    
    decrypted_success = sum(1 for r in results if r["encryption_status"] == "Decrypted (解密成功)")
    decrypted_failed = sum(1 for r in results if r["encryption_status"] == "Failed (解密失敗)")
    no_password_needed = sum(1 for r in results if r["encryption_status"] == "No Password (無密碼)")
    
    lines = [
        "# PDF 查重與去密編制審計報告",
        f"\n**產生時間**: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "\n## 1. 執行摘要",
        f"- **總處理檔案數**: {total} 個",
        f"- **解密成功件數**: {decrypted_success} 個",
        f"- **解密失敗件數**: {decrypted_failed} 個 (密碼錯誤或檔案損壞)",
        f"- **無需解密件數**: {no_password_needed} 個 (未加密檔)",
        f"- **唯一保留件數**: {unique} 個 (包含去密成功件)",
        f"- **重複跳過件數**: {duplicates} 個",
        f"- **錯誤/忽略件數**: {errors} 個",
        f"- **節省磁碟空間**: {saved_kb:.2f} KB",
        "\n## 2. 審計明細清單",
        "| 檔案名稱 | 大小 (KB) | 加密狀態 | SHA-256 | 查重狀態 | 處理動作 | 母本引用 |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |"
    ]
    for r in results:
        sha = r["sha256"][:12] + "..." if r["sha256"] else "None"
        dup_of = r["duplicate_of"] if r["duplicate_of"] else "None"
        lines.append(
            f"| {r['file_name']} | {r['file_size_kb']} | {r['encryption_status']} | `{sha}` | {r['status']} | {r['action']} | {dup_of} |"
        )
    
    output_dir.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return report_path

def generate_pdf_conversion_report(all_alerts: list[dict[str, Any]], output_dir: Path) -> Path:
    """生成 PDF 轉 Markdown 解析與對賬勾稽審計報告。"""
    report_path = output_dir / "report.md"
    
    total_alerts = len(all_alerts)
    errors = sum(1 for a in all_alerts if a.get("status") == "error")
    warnings = sum(1 for a in all_alerts if a.get("status") == "warning")
    reviews = sum(1 for a in all_alerts if a.get("status") == "NEED_VISUAL_REVIEW")
    successes = sum(1 for a in all_alerts if a.get("status") == "success")
    
    # 篩選出需要人工審核的警告/異常
    manual_reviews = [a for a in all_alerts if a.get("status") in ("warning", "NEED_VISUAL_REVIEW", "error")]
    
    lines = [
        "# PDF 轉 Markdown 解析與對賬勾稽審计報告",
        f"\n**產生時間**: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "\n## 1. 執行摘要",
        f"- **總審計警示數**: {total_alerts} 處",
        f"- **勾稽成功件數**: {successes} 處",
        f"- **人工視覺覆核 (NEED_VISUAL_REVIEW)**: {reviews} 處",
        f"- **對賬警告件數**: {warnings} 處",
        f"- **解析錯誤件數**: {errors} 處",
        "\n## 2. 需要人工審核的勾稽與警示清單"
    ]
    
    if manual_reviews:
        lines.extend([
            "| 檔案名稱 | 頁碼 | 警示類型 | 警示狀態 | 警示訊息 |",
            "| :--- | :--- | :--- | :--- | :--- |"
        ])
        for a in manual_reviews:
            lines.append(
                f"| {a.get('file', 'Unknown')} | {a.get('page', 0)} | {a.get('type', 'None')} | {a.get('status', 'info')} | {a.get('message', '').replace('|', 'I')} |"
            )
    else:
        lines.append("\n🟢 **恭喜，未發現需要人工審核的勾稽異常或警告項目。**")
        
    lines.extend([
        "\n## 3. 全量審計明细清單",
        "| 檔案名稱 | 頁碼 | 警示類型 | 警示狀態 | 警示訊息 |",
        "| :--- | :--- | :--- | :--- | :--- |"
    ])
    for a in all_alerts:
        lines.append(
            f"| {a.get('file', 'Unknown')} | {a.get('page', 0)} | {a.get('type', 'None')} | {a.get('status', 'info')} | {a.get('message', '').replace('|', 'I')} |"
        )
        
    output_dir.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return report_path

def generate_md_csv_conversion_report(all_alerts: list[dict[str, Any]], output_dir: Path) -> Path:
    """生成 Markdown 转 CSV 转换审计报告。"""
    report_path = output_dir / "report.md"
    
    total_alerts = len(all_alerts)
    errors = sum(1 for a in all_alerts if a.get("status") == "error")
    warnings = sum(1 for a in all_alerts if a.get("status") == "warning")
    successes = sum(1 for a in all_alerts if a.get("status") == "success")
    
    lines = [
        "# Markdown 轉 CSV 數據矩陣轉換報告",
        f"\n**產生時間**: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "\n## 1. 執行摘要",
        f"- **總轉換警示數**: {total_alerts} 處",
        f"- **成功轉換件數**: {successes} 處",
        f"- **轉換警告件數**: {warnings} 處",
        f"- **轉換錯誤件數**: {errors} 处",
        "\n## 2. 全量轉換狀態明細清單",
        "| 檔案名稱 | 轉換類型 | 轉換狀態 | 轉換訊息 |",
        "| :--- | :--- | :--- | :--- |"
    ]
    for a in all_alerts:
        lines.append(
            f"| {a.get('file', 'Unknown')} | {a.get('type', 'None')} | {a.get('status', 'info')} | {a.get('message', '').replace('|', 'I')} |"
        )
        
    output_dir.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return report_path

def generate_csv_excel_report(all_logs: list[dict[str, Any]], output_dir: Path, direction: str = "未知方向") -> Path:
    """生成 CSV/Excel 互转审计与转换报告。"""
    report_path = output_dir / "report.md"
    
    total = len(all_logs)
    successes = sum(1 for a in all_logs if a.get("status") == "success")
    errors = sum(1 for a in all_logs if a.get("status") == "failed")
    
    lines = [
        "# CSV 与 Excel 转换对账审计报告",
        f"\n- **转换方向**: {direction}",
        f"- **报告产生时间**: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "\n## 1. 运行摘要",
        f"- **总处理文件数**: {total} 个",
        f"- **转换成功数**: {successes} 个",
        f"- **转换失败数**: {errors} 个",
        "\n## 2. 转换明细清单",
        "| 序号 | 原始文件名 | 转换状态 | 提示信息 |",
        "| :--- | :--- | :--- | :--- |"
    ]
    for idx, a in enumerate(all_logs, start=1):
        lines.append(
            f"| {idx} | {a.get('file', 'Unknown')} | {a.get('status', 'info')} | {a.get('message', '').replace('|', 'I')} |"
        )
        
    output_dir.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return report_path
