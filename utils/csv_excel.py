"""
utils/csv_excel.py
中国税务系统数据安全无损互转工具 (CSV <-> Excel)
全面支持 Python 3.14+ 现代语法，强类型声明，支持 NiceGUI 异步进度回调。
"""

import asyncio
from collections.abc import Callable
from pathlib import Path
import warnings

# 忽略 openpyxl 样式相关的 UserWarning，防止缺少默认样式引起日志输出或在严格警告模式下报错
warnings.filterwarnings("ignore", category=UserWarning, module="openpyxl")

import pandas as pd


class BatchConverter:
    """批量无损互转工具类 (CSV <-> Excel)"""

    def __init__(self, input_dir: Path | str, output_dir: Path | str) -> None:
        """
        初始化转换器。
        
        :param input_dir: 输入文件目录。
        :param output_dir: 输出文件目录。
        """
        self.input_dir: Path = Path(input_dir).resolve()
        self.output_dir: Path = Path(output_dir).resolve()

    def _convert_csv_to_excel_sync(self, csv_path: Path, excel_path: Path) -> None:
        """
        同步执行 CSV 到 Excel 的转换 (阻塞操作)
        """
        encodings: list[str] = ["utf-8-sig", "gb18030", "utf-8"]
        df: pd.DataFrame | None = None
        last_error: Exception | None = None

        # 健壮的编码识别读取 CSV
        for encoding in encodings:
            try:
                # 强类型读取，指定 dtype=str 确保长数字安全（杜绝科学计数法与丢失前导零）
                df = pd.read_csv(csv_path, dtype=str, encoding=encoding)
                break
            except Exception as err:
                last_error = err
                continue

        if df is None:
            raise ValueError(f"无法使用支持的编码格式 ({', '.join(encodings)}) 读取 CSV 文件。原因: {last_error}")

        # 确保输出目录存在
        excel_path.parent.mkdir(parents=True, exist_ok=True)

        # 写入 Excel（显式指定 openpyxl 引擎，兼容所有 pandas 版本）
        with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
            df.to_excel(writer, index=False)

    def _convert_excel_to_csv_sync(self, excel_path: Path, csv_path: Path) -> None:
        """
        同步执行 Excel 到 CSV 的转换 (阻塞操作)
        """
        # 强类型读取 Excel：
        #   engine='openpyxl'       — 避免 xlrd>=2 不支持 .xlsx 的崩溃
        #   dtype=str               — 长数字（发票号/纳税人识别号）无损保留
        #   keep_default_na=False   — 空单元格读为空字符串而非 NaN
        df: pd.DataFrame = pd.read_excel(
            excel_path,
            dtype=str,
            engine="openpyxl",
            keep_default_na=False,
        )

        # 确保输出目录存在
        csv_path.parent.mkdir(parents=True, exist_ok=True)

        # 写入 CSV (utf-8-sig 编码防止 Excel 打开中文乱码)
        df.to_csv(csv_path, index=False, encoding="utf-8-sig")

    async def convert_file(self, file_path: Path, mode: str = "csv_to_excel") -> Path:
        """
        异步封装的单文件转换方法。
        将阻塞的 Pandas 读写操作投递至后台线程池执行，防 NiceGUI 界面卡顿。
        在同目录中生成同名文件，若遇同名文件则在名称后增加 _x 后缀。
        """
        resolved_file = Path(file_path).resolve()
        # Bug Fix: 输出路径必须指向 self.output_dir，而非输入文件所在目录
        self.output_dir.mkdir(parents=True, exist_ok=True)
        if mode == "csv_to_excel":
            output_path = self.output_dir / f"{resolved_file.stem}.xlsx"
            while output_path.exists():
                output_path = output_path.parent / f"{output_path.stem}_x.xlsx"
            # 使用 asyncio.to_thread 运行阻塞型 I/O 操作
            await asyncio.to_thread(self._convert_csv_to_excel_sync, resolved_file, output_path)
            return output_path
        elif mode == "excel_to_csv":
            output_path = self.output_dir / f"{resolved_file.stem}.csv"
            while output_path.exists():
                output_path = output_path.parent / f"{output_path.stem}_x.csv"
            await asyncio.to_thread(self._convert_excel_to_csv_sync, resolved_file, output_path)
            return output_path
        else:
            raise ValueError(f"不支持的转换模式: {mode}")

    async def convert_all(
        self,
        mode: str = "csv_to_excel",
        progress_callback: Callable[[int, int, str, bool, str], None] | None = None
    ) -> list[Path]:
        """
        异步批量转换指定目录下所有的文件。
        
        :param mode: 转换模式，'csv_to_excel' 或 'excel_to_csv'
        :param progress_callback: 进度回调函数，签名为 (当前进度, 总文件数, 当前文件名, 是否成功, 提示消息)
        """
        if mode == "csv_to_excel":
            files = [f for f in self.input_dir.iterdir() if f.is_file() and f.suffix.lower() == ".csv"]
        else:
            files = [f for f in self.input_dir.iterdir() if f.is_file() and f.suffix.lower() in (".xlsx", ".xls")]
        total_files = len(files)
        converted_paths: list[Path] = []

        if total_files == 0:
            if progress_callback:
                progress_callback(0, 0, "", True, "未在输入目录中找到待处理的文件。")
            return converted_paths

        for idx, file_path in enumerate(files, start=1):
            file_name = file_path.name
            try:
                # 异步转换单文件，互不干扰
                out_path = await self.convert_file(file_path, mode=mode)
                converted_paths.append(out_path)
                if progress_callback:
                    progress_callback(idx, total_files, file_name, True, f"转换成功: {file_name}")
            except Exception as err:
                if progress_callback:
                    progress_callback(idx, total_files, file_name, False, f"转换失败: {file_name}。原因: {str(err)}")
        return converted_paths
