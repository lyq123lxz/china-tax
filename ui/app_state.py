# ui/app_state.py
class AppState:
    def __init__(self) -> None:
        self.bank_name: str = ""
        self.csv_excel = None
        self.excel_csv = None
        self.pdf_dedup = None
        self.pdf_md = None
        self.closing_md = None
        self.closing_csv = None
        self.db_tools = None
        self.sys_logs = None
