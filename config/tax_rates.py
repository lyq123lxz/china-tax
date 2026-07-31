"""
config/tax_rates.py
中国税务系统税率与计算参数配置表 (Python 3.14+ 强类型声明)
"""

from typing import Final
from decimal import Decimal

# 个人所得税（综合所得）七级超额累进税率表
# 元组结构: (应纳税所得额上限, 税率, 速算扣除数)
# 应纳税所得额上限为 None 代表无穷大
INDIVIDUAL_TAX_BRACKETS: Final[list[tuple[Decimal | None, Decimal, Decimal]]] = [
    (Decimal("36000"), Decimal("0.03"), Decimal("0")),
    (Decimal("144000"), Decimal("0.10"), Decimal("2520")),
    (Decimal("300000"), Decimal("0.20"), Decimal("16920")),
    (Decimal("420000"), Decimal("0.25"), Decimal("31920")),
    (Decimal("660000"), Decimal("0.30"), Decimal("52920")),
    (Decimal("960000"), Decimal("0.35"), Decimal("85920")),
    (None, Decimal("0.45"), Decimal("181920")),
]

# 个人所得税免征额 (起征点)
INDIVIDUAL_TAX_THRESHOLD: Final[Decimal] = Decimal("60000")  # 年免征额 60000 元 (5000元/月)

# 企业所得税税率配置
CORPORATE_TAX_STANDARD: Final[Decimal] = Decimal("0.25")      # 标准税率 25%
CORPORATE_TAX_HIGH_TECH: Final[Decimal] = Decimal("0.15")     # 高新技术企业 15%
CORPORATE_TAX_SMALL_LIMIT: Final[Decimal] = Decimal("3000000") # 小微企业认定上限 300 万元
CORPORATE_TAX_SMALL_RATE: Final[Decimal] = Decimal("0.05")     # 小微企业实际优惠税率 5%
