# china-tax 项目开发规范 (AI 指引手册 - v2.0)

## 1. 项目愿景与技术栈
- **项目名称**：中国税务自动化申报/处理系统 (china-tax)
- **核心目标**：通过浏览器界面，实现报税数据的导入、解析（PDF/CSV）、逻辑校验、税额计算、持久化存储及一键导出。
- **运行环境**：PyCharm Gateway (远程/本地开发) + 浏览器端展示。
- **技术选型**：
  - **核心语言**：Python 3.14+ (全面采用 Python 3.14 最新语法特性)
  - **浏览器前端**：NiceGUI (基于 FastAPI + Vue + Tailwind CSS 的全栈 Python 框架，采用事件驱动模型，严禁使用全量重执行的框架)
  - **数据处理**：Pandas (强类型读取，杜绝长数字截断)
  - **数据库**：PostgreSQL (作为最终的历史档案数据保险箱)

## 2. 模块化架构与工具类设计 (必须严格遵守)
项目必须采用高内聚、低耦合的模块化设计。目录结构规范如下：
china-tax/
│
├── gemini.md               # 本规范文件
├── app.py                  # 浏览器主入口程序
│
├── config/                 # 配置模块
│   ├── __init__.py
│   ├── db_config.py        # PostgreSQL 连接配置
│   └── tax_rates.py        # 税率表与计算参数
│
├── core/                   # 核心业务逻辑模块
│   ├── __init__.py
│   ├── calculator.py       # 税额计算核心算法 (个税、企业税等)
│   └── validator.py        # 报税数据合法性校验
│
├── utils/                  # 核心工具类模块 (重点建设)
│   ├── __init__.py
│   ├── csv_excel.py     # CSV/Excel 互转工具（必须指定 dtype=str 确保长数字安全）
│   └── pdf_md.py       # PDF 报税单转 Markdown 工具（用于结构化提取）
│   └── pdf_check.py       # PDF 查重，删除重复下载的结单pdf文件
│
└── data/                   # 本地临时缓存/输入输出目录
    ├── input/
    └── output/

## 3. 核心编写规则 (Agy 必须遵守)
- **长数字安全原则**：在 `utils/csv_excel.py` 中处理 CSV/Excel 互转时，导入 CSV 必须指定 `dtype=str`。企业社会信用代码、银行账号、身份证号等长数字，绝对不允许转为科学计数法，也绝不能丢失前导零。
- **原子化函数**：一个函数只做一件事，行数控制在 50 行以内，逻辑清晰。
- **强类型声明 (Type Hints)**：充分利用 Python 3.14 的类型提示特性，所有函数 must 声明输入和输出类型。
- **异常捕获与前端联动**：无论是 PDF 解析失败、CSV 格式错误还是数据库连接超时，必须使用 `try-except` 捕获，并通过网页前端（如 `st.error`）对用户进行友好提示，严禁后台静默崩溃。
- **先设计后代码**：在调整重大模块（尤其是对接 PostgreSQL 表结构 and PDF 解析逻辑）前，必须先向用户阐述设计思路。
a
## 4. 开发进度 (Progress Tracker)
- [x] **app.py (主入口)**: 已完成 NiceGUI 主控制面板，集成了 **CSV/Excel 互转控制台（支持异步进度更新、本地上传与下拉选择）**。
- [x] **utils/csv_excel.py (第1模块 - 互转工具)**: 已开发完成。支持 `dtype=str` 长数字安全原则，提供“本机/Linux后端”与“浏览器客户端”双存储位置环境选择，在 CSV 同级目录生成 Excel 且具有 `_x` 重名避让机制，支持客户端自动触发浏览器下载。
- [x] **utils/pdf_check.py (第2模块 - 查重去密清理)**: 已完成。封裝了高魯棒性的 PDFDeduplicator 引擎，支持非阻塞的 asyncio.to_thread 異步批處理、多密碼遍歷解密、解密後記憶體流雜湊查重、去密落盤及結構化審計報告返回。
- [x] **utils/pdf_md.py (第3模块 - PDF转Markdown)**: 已开发并完美优化完成。支持自适应 lines/text 双层提取与表格裁剪提取、单元格折行缝合、页码注入，并内置了【三层漏斗防线架构】与双重勾稽完整性对账审计引擎（已支持 status="NEED_VISUAL_REVIEW" 路由状态机及 NiceGUI 状态看板联动）。
- [x] **config/ & core/ 其它模块**: 已完成 PostgreSQL/SQLite 双模连接配置、税额七级超额累进与小微企业分类计算核心算法、社会信用代码与身份证号国标校验、勾稽校验算法，并在 NiceGUI 控制中心实装了 7 大高级交互弹窗与 ZIP 打包归档。

