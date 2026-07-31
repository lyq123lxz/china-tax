"""
core/validator.py
报税合法性与长数字校验模块 (Python 3.14+ 强类型，高标准国标校验)
"""

import re
from typing import Any

# 统一社会信用代码字符集与权重映射
CREDIT_CODE_CHARS = "0123456789ABCDEFGHJKLMNPQRTUWXY"
CREDIT_CODE_WEIGHTS = [1, 3, 9, 27, 19, 26, 16, 17, 20, 29, 25, 13, 8, 24, 10, 30, 28]

# 身份证校验权重
ID_CARD_WEIGHTS = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
ID_CARD_CHECKS = "10X98765432"

def validate_social_credit_code(code: str) -> bool:
    """
    按照 GB 32100-2015 校验统一社会信用代码是否合规。
    """
    code = code.upper().strip()
    if not re.match(r"^[0-9A-HJ-NPQRTUWXY]{18}$", code):
        return False
        
    try:
        total = 0
        for i in range(17):
            val = CREDIT_CODE_CHARS.index(code[i])
            total += val * CREDIT_CODE_WEIGHTS[i]
            
        remainder = total % 31
        check_index = (31 - remainder) % 31
        check_char = CREDIT_CODE_CHARS[check_index]
        return code[17] == check_char
    except Exception:
        return False

def validate_id_card(id_num: str) -> bool:
    """
    根据 GB 11643-1999 标准校验 18 位身份证号。
    """
    id_num = id_num.upper().strip()
    if not re.match(r"^[1-9]\d{5}(18|19|20)\d{2}(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])\d{3}[\dXx]$", id_num):
        return False
        
    try:
        total = sum(int(id_num[i]) * ID_CARD_WEIGHTS[i] for i in range(17))
        remainder = total % 11
        return id_num[17] == ID_CARD_CHECKS[remainder]
    except Exception:
        return False

def validate_taxpayer_id(tax_id: str) -> dict[str, Any]:
    """
    智能检测并校验纳税人识别号（身份证或统一社会信用代码）。
    """
    tax_id = tax_id.strip()
    if len(tax_id) == 18:
        if validate_social_credit_code(tax_id):
            return {"valid": True, "type": "统一社会信用代码 (企业)"}
        elif validate_id_card(tax_id):
            return {"valid": True, "type": "身份证号 (个人)"}
            
    return {"valid": False, "type": "未知/不合规识别号"}

def clean_numeric_string(val_str: str) -> str:
    """
    清洗数字字符串，支持任意货币符号、千分位逗号、会计括号负数、尾部负号、以及常见币种后缀。
    """
    s = val_str.strip()
    cleaned = s.replace("$", "").replace("¥", "").replace("£", "").replace("€", "").replace("￥", "").replace(",", "").strip()
    for currency in ("SGD", "USD", "HKD", "EUR", "CNY", "GBP", "CAD", "AUD", "NZD", "JPY", "KRW", "TWD", "元", "股", "万", "亿"):
        cleaned = cleaned.replace(currency, "").replace(currency.lower(), "")
    cleaned = cleaned.strip()
    
    if cleaned.startswith("(") and cleaned.endswith(")") and len(cleaned) > 2:
        inner = cleaned[1:-1].strip()
        if inner.startswith("-") or inner.startswith("+"):
            inner = inner[1:]
        cleaned = "-" + inner
    elif cleaned.endswith("-") and len(cleaned) > 1:
        cleaned = "-" + cleaned[:-1]
    return cleaned

def validate_declaration_data(
    taxpayer_name: str,
    taxpayer_id: str,
    income_str: str,
    deductions_str: str
) -> dict[str, Any]:
    """
    全面校验税前申报单条记录的完整性与逻辑合法性。
    """
    errors = []
    
    # 1. 检查企业/纳税人名称
    if not taxpayer_name.strip():
        errors.append("纳税人名称不能为空")
        
    # 2. 检查识别号
    id_check = validate_taxpayer_id(taxpayer_id)
    if not id_check["valid"]:
        errors.append(f"识别号 '{taxpayer_id}' 格式错误或未通过国标校验和校验")
        
    # 3. 检查数值
    cleaned_income = clean_numeric_string(income_str)
    cleaned_deductions = clean_numeric_string(deductions_str)
    
    try:
        income = float(cleaned_income)
        if income < 0:
            errors.append("总收入金额不能为负数")
    except ValueError:
        errors.append("总收入金额必须为合法数值")
        
    try:
        deductions = float(cleaned_deductions)
        if deductions < 0:
            errors.append("扣除金额不能为负数")
    except ValueError:
        errors.append("扣除金额必须为合法数值")
        
    return {
        "is_valid": len(errors) == 0,
        "type": id_check["type"],
        "errors": errors
    }
