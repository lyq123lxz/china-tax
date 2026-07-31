import time
from nicegui import ui
from ui.app_state import AppState

system_logs_list: list[str] = []

def log_action(action: str) -> None:
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    entry = f"[{timestamp}] {action}"
    system_logs_list.append(entry)
    print(entry)

class SystemLogsDialog:
    def __init__(self, state: AppState) -> None:
        self.state = state
        self.dialog = None
        self.log_board = None
        self.system_logs_container = None
        self.build()
        
    def build(self) -> None:
        with ui.dialog() as self.dialog:
            with ui.card().classes("w-[650px] p-6 gap-4 bg-white rounded-xl shadow-2xl"):
                with ui.row().classes("w-full justify-between items-center"):
                    with ui.row().classes("items-center gap-2"):
                        ui.icon("receipt_long", size="1.8rem").classes("text-indigo-600")
                        ui.label("系统审计与运行监控监控日志").classes("text-lg font-bold text-slate-800")
                    ui.button(icon="close", on_click=self.dialog.close).props("flat round dense").classes("text-slate-400")
                
                ui.separator()
                
                with ui.card().classes("w-full h-80 p-4 bg-slate-900 text-slate-100 rounded-xl overflow-y-auto") as self.log_board:
                    self.system_logs_container = ui.column().classes("w-full gap-1 mt-1")
                    
                with ui.row().classes("w-full justify-end mt-2"):
                    ui.button("刷新", on_click=self.refresh_logs).classes("bg-indigo-50 hover:bg-indigo-100 text-indigo-600 py-2 px-4 rounded-lg text-sm font-semibold")
                    ui.button("关闭", on_click=self.dialog.close).props("flat").classes("text-slate-500 text-sm")

    def open(self) -> None:
        self.refresh_logs()
        self.dialog.open()

    def refresh_logs(self) -> None:
        if self.system_logs_container:
            self.system_logs_container.clear()
            for log_entry in system_logs_list:
                with self.system_logs_container:
                    ui.label(log_entry).classes("text-xs font-mono text-emerald-400")
            if self.log_board:
                ui.run_javascript(f"document.getElementById('{self.log_board.id}').scrollTop = document.getElementById('{self.log_board.id}').scrollHeight")
