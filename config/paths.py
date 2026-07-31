import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent.resolve()

# Default directory variables
INPUT_DIR = BASE_DIR / "data" / "unselected" / "input"
OUTPUT_DIR = BASE_DIR / "data" / "unselected" / "output"

INPUT_PDF_DIR = INPUT_DIR / "pdf"
INPUT_CSV_DIR = INPUT_DIR / "csv"
INPUT_EXCEL_DIR = INPUT_DIR / "excel"
INPUT_MD_DIR = INPUT_DIR / "md"

OUTPUT_PDF_DIR = OUTPUT_DIR / "pdf"
OUTPUT_PDF_DECRYPT_DIR = OUTPUT_DIR / "pdf-Decrypt"
OUTPUT_CSV_DIR = OUTPUT_DIR / "csv"
OUTPUT_EXCEL_DIR = OUTPUT_DIR / "excel"
OUTPUT_MD_DIR = OUTPUT_DIR / "md"

def update_active_paths(bank_name: str) -> None:
    """根据银行/券商名称动态更新全局的输入与输出目录变量，并确保这些目录存在"""
    global INPUT_DIR, OUTPUT_DIR
    global INPUT_PDF_DIR, INPUT_CSV_DIR, INPUT_EXCEL_DIR, INPUT_MD_DIR
    global OUTPUT_PDF_DIR, OUTPUT_PDF_DECRYPT_DIR, OUTPUT_CSV_DIR, OUTPUT_EXCEL_DIR, OUTPUT_MD_DIR
    
    clean_name = "".join(c for c in bank_name if c.isalnum() or c in ("-", "_", " ")).strip()
    if not clean_name:
        raise ValueError("金融機構名稱不得為空")
        
    INPUT_DIR = BASE_DIR / "data" / clean_name / "input"
    OUTPUT_DIR = BASE_DIR / "data" / clean_name / "output"
        
    INPUT_PDF_DIR = INPUT_DIR / "pdf"
    INPUT_CSV_DIR = INPUT_DIR / "csv"
    INPUT_EXCEL_DIR = INPUT_DIR / "excel"
    INPUT_MD_DIR = INPUT_DIR / "md"
    
    OUTPUT_PDF_DIR = OUTPUT_DIR / "pdf"
    OUTPUT_PDF_DECRYPT_DIR = OUTPUT_DIR / "pdf-Decrypt"
    OUTPUT_CSV_DIR = OUTPUT_DIR / "csv"
    OUTPUT_EXCEL_DIR = OUTPUT_DIR / "excel"
    OUTPUT_MD_DIR = OUTPUT_DIR / "md"
