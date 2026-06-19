"""
utils/excel_csv.py
Excel → CSV 无损批量转换工具 (模块 1 扩展)

设计规范 (Python 3.14 + NiceGUI 异步架构)：
  1. 全面使用 pathlib.Path，附带完整强类型声明（Type Hints）。
  2. 无损长数字读取：pd.read_excel(..., dtype=str, keep_default_na=False, engine='openpyxl')
     确保发票号、纳税人识别号等不丢失前导零、不变成科学计数法；空单元格为 "" 而非 NaN。
  3. 多 Sheet 智能拆分：
     - 单 Sheet  → 输出 原文件名.csv
     - 多 Sheet  → 输出 原文件名_工作表名.csv（各表独立文件）
  4. Excel 友好的 CSV 输出：encoding='utf-8-sig', index=False
  5. 非阻塞异步：全部阻塞 I/O 封装在 asyncio.to_thread() 内执行。
  6. 实时进度回调：每完成一个 Sheet 或文件即触发，签名：
       (current: int, total: int, file_name: str, success: bool, message: str)
  7. 异常防御：单表转换失败独立捕获，记录错误但不中断整个批量队列。
  8. 资源安全：pd.ExcelFile 使用 context manager 确保文件句柄在任何情况下关闭。
"""

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Any
import warnings

# 忽略 openpyxl 样式相关的 UserWarning，防止缺少默认样式引起日志输出或在严格警告模式下报错
warnings.filterwarnings("ignore", category=UserWarning, module="openpyxl")

import pandas as pd


# 进度回调函数类型别名
ProgressCallback = Callable[[int, int, str, bool, str], None]


class ExcelToCsvConverter:
    """
    Excel → CSV 无损批量转换器。

    支持单文件与批量模式，自动检测多 Sheet，对每个工作表独立拆分为
    独立的 CSV 文件。全程使用 asyncio.to_thread() 防止卡死 NiceGUI
    主事件循环。
    """

    def __init__(self, input_dir: Path | str, output_dir: Path | str) -> None:
        """
        初始化转换器。

        :param input_dir:  Excel 输入目录（pathlib.Path 或字符串路径均可）。
        :param output_dir: CSV 输出目录。
        """
        self.input_dir: Path = Path(input_dir).resolve()
        self.output_dir: Path = Path(output_dir).resolve()

    # ------------------------------------------------------------------
    # 内部同步方法（阻塞，仅在线程池内执行）
    # ------------------------------------------------------------------

    def _convert_single_file_sync(
        self,
        excel_path: Path,
        out_dir: Path,
        progress_callback: ProgressCallback | None,
        file_idx: int,
        total_files: int,
    ) -> list[Path]:
        """
        同步执行单个 Excel 文件的转换（含多 Sheet 拆分）。

        :param excel_path:        待转换的 Excel 文件路径。
        :param out_dir:           输出 CSV 的目标目录。
        :param progress_callback: 进度回调。
        :param file_idx:          当前文件在批量队列中的序号（1-based）。
        :param total_files:       批量队列中的文件总数。
        :returns: 成功写出的 CSV 路径列表（一个 Excel 可能产生多个 CSV）。
        """
        out_dir.mkdir(parents=True, exist_ok=True)
        output_paths: list[Path] = []

        # Bug Fix 4: 使用 context manager (with ef:) 确保 pd.ExcelFile 在所有情况下关闭，
        # 防止文件描述符泄漏。同时将已打开的对象传入 pd.read_excel，
        # 避免对每张 Sheet 重复打开/关闭文件。
        try:
            ef = pd.ExcelFile(excel_path, engine="openpyxl")
        except Exception as err:
            msg = f"无法打开 Excel 文件 {excel_path.name}：{err}"
            if progress_callback:
                progress_callback(file_idx, total_files, excel_path.name, False, msg)
            return output_paths

        with ef:  # pd.ExcelFile.__exit__ 负责关闭底层文件句柄
            sheet_names: list[str] = ef.sheet_names
            single_sheet: bool = len(sheet_names) == 1

            for sheet_name in sheet_names:
                # 确定输出文件名
                if single_sheet:
                    csv_filename: str = f"{excel_path.stem}.csv"
                else:
                    # 清理工作表名中可能影响文件系统的特殊字符
                    safe_sheet: str = (
                        sheet_name.replace("/", "-")
                        .replace("\\", "-")
                        .replace(":", "-")
                        .replace("*", "")
                        .replace("?", "")
                        .replace('"', "")
                        .replace("<", "")
                        .replace(">", "")
                        .replace("|", "-")
                        .strip()
                    )
                    csv_filename = f"{excel_path.stem}_{safe_sheet}.csv"

                csv_path: Path = out_dir / csv_filename

                # 若文件已存在则追加 _x 后缀防止覆盖
                while csv_path.exists():
                    csv_path = csv_path.parent / f"{csv_path.stem}_x.csv"

                try:
                    # 核心读取：
                    #   传入已打开的 ExcelFile 对象 ef（Bug Fix 4 — 避免重复打开文件）
                    #   dtype=str             — 所有列强制字符串，防止长数字变科学计数法
                    #   keep_default_na=False — Bug Fix 5: 空单元格 → "" 而非 NaN，
                    #                           防止写入 CSV 时出现字面量 "nan"
                    df: pd.DataFrame = pd.read_excel(
                        ef,
                        sheet_name=sheet_name,
                        dtype=str,
                        keep_default_na=False,
                    )

                    # 写出 CSV：utf-8-sig 防止 Excel 打开中文乱码，index=False 不写行号
                    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
                    output_paths.append(csv_path)

                    if single_sheet:
                        msg = f"转换成功: {excel_path.name} → {csv_filename}"
                    else:
                        msg = (
                            f"Sheet 转换成功: {excel_path.name}"
                            f"[{sheet_name}] → {csv_filename}"
                        )
                    if progress_callback:
                        progress_callback(file_idx, total_files, excel_path.name, True, msg)

                except Exception as sheet_err:
                    # 单表转换失败：独立捕获，记录错误，继续处理下一张表
                    err_msg = (
                        f"Sheet 转换失败: {excel_path.name}[{sheet_name}]"
                        f" → 原因: {sheet_err}"
                    )
                    if progress_callback:
                        progress_callback(file_idx, total_files, excel_path.name, False, err_msg)

        return output_paths

    # ------------------------------------------------------------------
    # 公开异步方法
    # ------------------------------------------------------------------

    async def convert_file(
        self,
        excel_path: Path,
        out_dir: Path | None = None,
        progress_callback: ProgressCallback | None = None,
        file_idx: int = 1,
        total_files: int = 1,
    ) -> list[Path]:
        """
        异步转换单个 Excel 文件（含多 Sheet 拆分）。

        将阻塞的 Pandas/openpyxl I/O 操作投递至后台线程池执行，
        防止卡死 NiceGUI 主事件循环。

        :param excel_path:        待转换的 Excel 文件路径。
        :param out_dir:           CSV 输出目录（不传则使用 self.output_dir）。
        :param progress_callback: 进度回调函数。
        :param file_idx:          当前文件序号（用于进度显示）。
        :param total_files:       总文件数（用于进度显示）。
        :returns: 成功写出的 CSV 路径列表。
        """
        resolved: Path = Path(excel_path).resolve()
        target_dir: Path = Path(out_dir).resolve() if out_dir else self.output_dir

        # 获取当前正在运行的事件循环（即主线程的事件循环）
        loop = asyncio.get_running_loop()

        # 定义一个线程安全的包装器，确保 progress_callback 在主事件循环中调度执行
        def safe_progress_callback(curr: int, tot: int, fname: str, succ: bool, msg: str) -> None:
            if progress_callback:
                loop.call_soon_threadsafe(progress_callback, curr, tot, fname, succ, msg)

        return await asyncio.to_thread(
            self._convert_single_file_sync,
            resolved,
            target_dir,
            safe_progress_callback if progress_callback else None,
            file_idx,
            total_files,
        )

    async def convert_all(
        self,
        progress_callback: ProgressCallback | None = None,
        out_dir: Path | None = None,
    ) -> list[Path]:
        """
        异步批量转换 input_dir 下所有 Excel 文件（.xlsx / .xls / .xlsm / .xlsb）。

        每处理完一个 Sheet 或文件，立即触发 progress_callback 通知前端
        更新进度条与状态文本。单表转换失败不中断整个批量任务。

        :param progress_callback: 进度回调函数，签名：
            (current: int, total: int, file_name: str, success: bool, message: str)
        :param out_dir: 指定 CSV 输出目录（不传则使用 self.output_dir）。
        :returns: 所有成功生成的 CSV 路径列表。
        """
        target_dir: Path = Path(out_dir).resolve() if out_dir else self.output_dir

        # 枚举所有 Excel 文件
        excel_suffixes: set[str] = {".xlsx", ".xls", ".xlsm", ".xlsb"}
        files: list[Path] = [
            f
            for f in self.input_dir.iterdir()
            if f.is_file() and f.suffix.lower() in excel_suffixes
        ]
        total: int = len(files)

        if total == 0:
            if progress_callback:
                progress_callback(0, 0, "", True, "未在输入目录中找到任何 Excel 文件。")
            return []

        all_outputs: list[Path] = []

        for idx, file_path in enumerate(files, start=1):
            # 每个文件投递到线程池，单文件失败不影响后续文件
            outputs: list[Path] = await self.convert_file(
                excel_path=file_path,
                out_dir=target_dir,
                progress_callback=progress_callback,
                file_idx=idx,
                total_files=total,
            )
            all_outputs.extend(outputs)

        return all_outputs
