# china-tax 项目开发规范 (AI 指引手册 - v3.0)

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
项目必须采用高内聚、低耦合的模块化设计，每个 Py 文件均控制在 500 行以内。目录结构规范如下：
```markdown
china-tax/
│
├── gemini.md               # 本规范文件
├── app.py                  # 浏览器主入口程序 (轻量化，< 200行)
│
├── config/                 # 配置模块
│   ├── __init__.py
│   ├── db_config.py        # PostgreSQL 连接配置
│   ├── paths.py            # 多券商/银行数据目录隔离及活动路径配置
│   └── tax_rates.py        # 税率表与计算参数
│
├── core/                   # 核心业务逻辑模块
│   ├── __init__.py
│   ├── calculator.py       # 税额计算核心算法 (个税、企业税等)
│   └── validator.py        # 报税数据合法性校验
│
├── utils/                  # 核心工具类模块
│   ├── __init__.py
│   ├── sys_utils.py        # 系统底层工具 (端口清理、数据清理、ZIP归档等)
│   ├── report_generator.py # 转换与对账的结构化 Markdown 审计报告生成器
│   ├── csv_excel.py        # CSV/Excel 无损互转（必须指定 dtype=str 确保长数字安全）
│   ├── excel_csv.py        # Excel/CSV 无损互转及多Sheet拆分器
│   ├── md_csv.py           # 结构化 Markdown 转换为标准 CSV
│   ├── pdf_check.py        # PDF 查重，删除重复下载的结单pdf文件
│   ├── pdf_md.py           # PDF 解析主入口 (基于 IBM Docling + Pandas 重构版)
│   ├── csv_closing.py      # CSV 格式平仓数据整理提取Facade
│   ├── md_closing.py       # Markdown 格式平仓数据整理提取Facade
│   ├── closing_utils.py    # 平仓处理通用函数与 Excel 汇总表生成
│   └── closing_extractor.py # 开平仓配对匹配与流分类核心引擎
│
├── ui/                     # 会话隔离 UI 组件包
│   ├── __init__.py
│   ├── app_state.py        # 多标签页会话共享 State
│   ├── sys_logs.py         # 系统操作日志与运行状态弹窗
│   ├── csv_excel.py        # CSV-to-Excel 互转控制弹窗
│   ├── excel_csv.py        # Excel-to-CSV 拆分控制弹窗
│   ├── pdf_dedup.py        # PDF 查重去密控制弹窗
│   ├── pdf_md.py           # PDF 结单结构化提取弹窗界面
│   ├── pdf_md_converters.py # 调度 PDF-to-MD 与 MD-to-CSV 异步转换处理器
│   ├── closing_dialogs.py  # 平仓交易整理控制弹窗 (CSV/Markdown 双版)
│   ├── db_dialogs.py       # PostgreSQL 连接测试、归档查询与配置参数面板
│   └── tax_dialogs.py      # 税额计算、深度合法性审计与一键生成申报表面板
│
└── data/                   # 本地隔离缓存/输入输出目录
```

## 3. 核心编写规则 (AI 与开发人员必须遵守)
- **长数字安全原则**：在 `utils/csv_excel.py` 等转换模块中处理 CSV/Excel 互转时，导入 CSV 必须指定 `dtype=str`。企业社会信用代码、银行账号、身份证号等长数字，绝对不允许转为科学计数法，也绝不能丢失前导零。
- **500行硬上限规则**：为保证项目结构的高可读性，**每个 Python 代码文件必须控制在 500 行以内**。如文件接近 500 行，必须按照SRP（单一职责原则）或下文所述的绑定模式拆分成多个物理文件。
- **NiceGUI 会话安全隔离规范**：为了防范 NiceGUI 全局状态引起的多用户/多标签页数据污染，弹窗、进度状态、局部表单变量等交互变量，**禁止以全局变量形式存放在 app.py 或外部文件中**。必须将各个交互面板声明为独立的类（Class），并在 `main_page()` 中根据会话动态实例化，局部参数全部存储于 Session 专属的 `AppState` 中。
- **Bound Function 动态绑定拆分模式**：若大类的某成员函数内部逻辑过长需要物理拆分，但方法高度耦合类的成员状态时，为了不破坏原本的类调用约定，应将该方法剥离到单独的模块中定义（其第一个参数为 `self`），然后在类声明中引用绑定（如 `ClassName.method = method`）将其动态挂载。这是一种高内聚的拆分模式，不产生冗余的参数转发，完美实现长逻辑的文件切分。
- **原子化函数**：一个函数只做一件事，行数控制在 50 行以内，逻辑清晰。
- **强类型声明 (Type Hints)**：充分利用 Python 的类型提示特性，所有函数 must 声明输入和输出类型。
- **异常捕获与前端联动**：无论是 PDF 解析失败、CSV 格式错误还是数据库连接超时，必须使用 `try-except` 捕获，并通过网页前端弹窗对用户进行友好提示，严禁后台静默崩溃。
- **先设计后代码**：在调整重大模块（尤其是对接 PostgreSQL 表结构 and PDF 解析逻辑）前，必须先向用户阐述设计思路。

## 4. 开发进度 (Progress Tracker)
- [x] **app.py (主入口)**: 已完成 NiceGUI 主控制面板，完全拆分轻量化（< 200行）。
- [x] **utils/csv_excel.py (第1模块 - 互转工具)**: 已开发完成。支持 `dtype=str` 长数字安全原则，提供双存储位置环境选择，在 CSV 同级目录生成 Excel 且具有 `_x` 重名避让机制。
- [x] **utils/pdf_check.py (第2模块 - 查重去密清理)**: 已完成。封裝了高魯棒性的 PDFDeduplicator 引擎，支持非阻塞的 asyncio.to_thread 異步批處理、多密碼遍歷解密、解密後記憶體流雜湊查重、去密落盤及結構化審計報告返回。
- [x] **utils/pdf_md.py (第3模块 - PDF转Markdown)**: 重构完成。基于 IBM Docling + Pandas 黄金架构重写，支持子表提取、数字纠错、重复表头剔除、汇总行前置拦截、向上折行缝合及向下顺延填充。
- [x] **utils/md_closing.py & csv_closing.py**: 重构完成。抽取公用的 `closing_extractor.py` 和 `closing_utils.py`，去除雷同代码。
- [x] **ui/ 会话隔离组件包**: 交互组件重构完成。把 12 大功能项弹窗分离为独立的类，在会话中进行隔离，完全避免标签页交互串数据的问题。
