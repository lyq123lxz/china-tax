import asyncio
import hashlib
import io
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any
from pypdf import PdfReader, PdfWriter

class PDFDeduplicator:
    """PDF 查重與去密編制引擎。

    負責處理 PDF 檔案的讀取、解密、雜湊計算、去密落盤及重複件篩選。
    """

    def __init__(self, output_dir: Path) -> None:
        """初始化 PDF 查重引擎。

        Args:
            output_dir: 存放唯一且去密後的 PDF 檔案的輸出目錄。
        """
        self.output_dir: Path = output_dir

    def _process_single_file(
        self,
        file_path: Path,
        passwords: list[str],
        seen_hashes: dict[str, str]
    ) -> dict[str, Any]:
        """同步處理單個 PDF 檔案的解密、雜湊計算與查重。 (在後台線程中運行)

        Args:
            file_path: 待處理的 PDF 檔案路徑。
            passwords: 密碼候選列表。
            seen_hashes: 已處理過的雜湊值字典 {sha256: 首次出現的檔名}。

        Returns:
            結構化審計報告字典。
        """
        file_name = file_path.name
        
        # 檢查檔案是否存在
        if not file_path.is_file():
            return {
                "file_name": file_name,
                "file_size_kb": 0.0,
                "encryption_status": "Failed (解密失敗)",
                "sha256": None,
                "status": "Error",
                "action": "Ignored (已忽略)",
                "duplicate_of": None
            }

        file_size_kb = round(file_path.stat().st_size / 1024, 2)
        
        # 預設值
        encryption_status = "No Password (無密碼)"
        sha256_val = None
        status = "Error"
        action = "Ignored (已忽略)"
        duplicate_of = None
        mem_file = None

        try:
            reader = PdfReader(file_path)
            
            # 情況 A：已加密
            if reader.is_encrypted:
                encryption_status = "Failed (解密失敗)"  # 預設為失敗，成功解密後覆蓋
                decrypted = False
                
                # 篩選並去重用戶傳入的密碼，最多嘗試 3 個
                user_pwds = []
                for pwd in (passwords or []):
                    if pwd not in user_pwds:
                        user_pwds.append(pwd)
                user_pwds = user_pwds[:3]
                
                # 優先嘗試空密碼，再嘗試用戶密碼
                to_try = [""] + user_pwds
                unique_to_try = []
                for p in to_try:
                    if p not in unique_to_try:
                        unique_to_try.append(p)
                
                for pwd in unique_to_try:
                    try:
                        # decrypt 回傳 0 表示失敗，1 或 2 表示成功
                        if reader.decrypt(pwd) > 0:
                            decrypted = True
                            encryption_status = "Decrypted (解密成功)"
                            break
                    except Exception:
                        continue
                
                if not decrypted:
                    return {
                        "file_name": file_name,
                        "file_size_kb": file_size_kb,
                        "encryption_status": "Failed (解密失敗)",
                        "sha256": None,
                        "status": "Error",
                        "action": "Ignored (已忽略)",
                        "duplicate_of": None
                    }
                
                # 解密成功，複製所有頁面至 PdfWriter 以去除密碼限制
                writer = PdfWriter()
                for page in reader.pages:
                    writer.add_page(page)
                
                mem_file = io.BytesIO()
                writer.write(mem_file)
                mem_file.seek(0)
                
                # 對解密後的記憶體流計算 SHA-256
                sha256_hash = hashlib.sha256()
                while chunk := mem_file.read(8192):
                    sha256_hash.update(chunk)
                sha256_val = sha256_hash.hexdigest()
                mem_file.seek(0)
                
            # 情況 B：未加密
            else:
                sha256_hash = hashlib.sha256()
                with open(file_path, "rb") as f:
                    while chunk := f.read(8192):
                        sha256_hash.update(chunk)
                sha256_val = sha256_hash.hexdigest()
            
            # 雜湊值判定與查重
            if sha256_val in seen_hashes:
                status = "Duplicate"
                action = "Skipped (已跳過)"
                duplicate_of = seen_hashes[sha256_val]
            else:
                seen_hashes[sha256_val] = file_name
                status = "Unique"
                
                # 建立輸出目錄
                self.output_dir.mkdir(parents=True, exist_ok=True)
                dest_path = self.output_dir / file_name
                
                if reader.is_encrypted and mem_file is not None:
                    # 將去密後的記憶體流寫入硬碟
                    with open(dest_path, "wb") as out_f:
                        out_f.write(mem_file.getvalue())
                    action = "Kept (已保留並去密)"
                else:
                    # 未加密檔案，直接複製原檔案
                    shutil.copy2(file_path, dest_path)
                    action = "Kept (已保留)"
                    
        except Exception:
            # 應對損壞或格式不支援的 PDF 檔案
            return {
                "file_name": file_name,
                "file_size_kb": file_size_kb,
                "encryption_status": "Failed (解密失敗)" if encryption_status == "Decrypted (解密成功)" else encryption_status,
                "sha256": None,
                "status": "Error",
                "action": "Ignored (已忽略)",
                "duplicate_of": None
            }
        finally:
            if mem_file is not None:
                mem_file.close()

        return {
            "file_name": file_name,
            "file_size_kb": file_size_kb,
            "encryption_status": encryption_status,
            "sha256": sha256_val,
            "status": status,
            "action": action,
            "duplicate_of": duplicate_of
        }

    async def process_deduplication(
        self,
        file_paths: list[Path],
        passwords: list[str] | None = None,
        progress_callback: Callable[[float, str], None] | None = None
    ) -> list[dict[str, Any]]:
        """異步批處理 PDF 查重與去密編制。

        內部使用 asyncio.to_thread 將耗時的 PDF 處理委派給後台線程，避免阻塞 NiceGUI 主事件循環。

        Args:
            file_paths: 待處理的 PDF 檔案路徑列表。
            passwords: 用於解密的候選密碼列表。
            progress_callback: 即時進度回報回調函數，格式為 progress_callback(progress_ratio, status_message)。

        Returns:
            結構化審計報告列表，格式符合 ui.table。
        """
        if not file_paths:
            if progress_callback:
                progress_callback(1.0, "無待處理檔案")
            return []

        total_files = len(file_paths)
        results: list[dict[str, Any]] = []
        seen_hashes: dict[str, str] = {}  # 用於記錄 {SHA-256 -> 首次出現的文件名}
        passwords_list = passwords or []

        for index, path in enumerate(file_paths):
            current_progress = index / total_files
            msg = f"正在處理 ({index + 1}/{total_files}): {path.name}"
            if progress_callback:
                progress_callback(current_progress, msg)

            # 將耗時的讀寫與解密任務丟到後台線程
            result = await asyncio.to_thread(
                self._process_single_file,
                path,
                passwords_list,
                seen_hashes
            )
            results.append(result)

        if progress_callback:
            progress_callback(1.0, f"處理完成，共處理 {total_files} 個檔案")

        return results
