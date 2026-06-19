"""
core/calculator.py
税额智能计算核心逻辑模块 (Python 3.14+ 强类型，Decimal 高精度财务计算)
"""

from decimal import Decimal, ROUND_HALF_UP
from typing import Any
from config.tax_rates import (
    INDIVIDUAL_TAX_BRACKETS,
    INDIVIDUAL_TAX_THRESHOLD,
    CORPORATE_TAX_STANDARD,
    CORPORATE_TAX_HIGH_TECH,
    CORPORATE_TAX_SMALL_LIMIT,
    CORPORATE_TAX_SMALL_RATE,
)

def calculate_individual_tax(income_str: str, deductions_str: str) -> dict[str, Any]:
    """
    计算个人所得税（综合所得年纳税额）
    
    :param income_str: 年总收入金额 (元)
    :param deductions_str: 专项扣除、专项附加扣除等扣除总额 (元)
    :return: 包含各项计算细节的字典
    """
    income = Decimal(income_str)
    deductions = Decimal(deductions_str)
    
    # 应纳税所得额 = 收入 - 扣除 - 起征点
    taxable_income = income - deductions - INDIVIDUAL_TAX_THRESHOLD
    if taxable_income <= 0:
        return {
            "taxable_income": "0.00",
            "tax_rate": "0.00",
            "quick_deduction": "0.00",
            "tax_payable": "0.00"
        }
        
    # 匹配超额累进税率区间
    matched_rate = Decimal("0.00")
    matched_deduction = Decimal("0.00")
    
    for limit, rate, quick_deduc in INDIVIDUAL_TAX_BRACKETS:
        if limit is None or taxable_income <= limit:
            matched_rate = rate
            matched_deduction = quick_deduc
            break
            
    # 应纳税额 = 应纳税所得额 * 税率 - 速算扣除数
    tax_payable = (taxable_income * matched_rate - matched_deduction).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if tax_payable < 0:
        tax_payable = Decimal("0.00")
        
    return {
        "taxable_income": f"{taxable_income:.2f}",
        "tax_rate": f"{matched_rate * 100:.0f}%",
        "quick_deduction": f"{matched_deduction:.2f}",
        "tax_payable": f"{tax_payable:.2f}"
    }

def calculate_corporate_tax(profit_str: str, is_high_tech: bool) -> dict[str, Any]:
    """
    计算企业所得税
    
    :param profit_str: 年纳税调整后所得 (利润) (元)
    :param is_high_tech: 是否为国家需要扶持的高新技术企业
    :return: 包含各项计算细节的字典
    """
    profit = Decimal(profit_str)
    if profit <= 0:
        return {
            "taxable_income": "0.00",
            "tax_rate": "0.00",
            "tax_payable": "0.00",
            "company_type": "无应纳税所得"
        }
        
    # 智能识别企业优惠档次
    if profit <= CORPORATE_TAX_SMALL_LIMIT:
        # 小微企业优惠政策：实际税负减按 5% 征收
        matched_rate = CORPORATE_TAX_SMALL_RATE
        company_type = "符合条件的小型微利企业"
    elif is_high_tech:
        # 高新技术企业：减按 15% 税率征收
        matched_rate = CORPORATE_TAX_HIGH_TECH
        company_type = "国家重点扶持的高新技术企业"
    else:
        # 标准企业：25% 税率
        matched_rate = CORPORATE_TAX_STANDARD
        company_type = "标准普通税率企业"
        
    tax_payable = (profit * matched_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    
    return {
        "taxable_income": f"{profit:.2f}",
        "tax_rate": f"{matched_rate * 100:.0f}%",
        "tax_payable": f"{tax_payable:.2f}",
        "company_type": company_type
    }
