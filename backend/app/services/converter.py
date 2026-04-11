import os
import subprocess
import tempfile
from pathlib import Path

from loguru import logger
from markitdown import MarkItDown

_md = MarkItDown()

PLAINTEXT_EXTENSIONS = {
    '.txt', '.md', '.csv', '.json', '.xml', '.yaml', '.yml',
    '.html', '.htm', '.log', '.ini', '.cfg', '.toml',
}

OFFICE_MODERN_EXTENSIONS = {
    '.docx', '.pptx',
}

OFFICE_LEGACY_EXTENSIONS = {
    '.doc', '.ppt',
}


def _convert_with_pypandoc(file_path: str, output_path: str, to_format: str) -> bool:
    """尝试使用 pypandoc 转换文件"""
    try:
        import pypandoc
        pypandoc.convert_file(file_path, to_format, outputfile=output_path)
        return os.path.exists(output_path) and os.path.getsize(output_path) > 0
    except Exception as e:
        logger.warning(f"pypandoc 转换失败: {e}")
        return False


def _convert_with_libreoffice(file_path: str, output_dir: str, output_ext: str) -> str | None:
    """尝试使用 LibreOffice 命令行转换文件"""
    libreoffice_paths = [
        'libreoffice',
        'soffice',
        r'C:\Program Files\LibreOffice\program\soffice.exe',
        r'C:\Program Files (x86)\LibreOffice\program\soffice.exe',
    ]
    
    executable = None
    for path in libreoffice_paths:
        try:
            result = subprocess.run(
                [path, '--version'],
                capture_output=True,
                timeout=5
            )
            if result.returncode == 0:
                executable = path
                break
        except Exception:
            continue
    
    if not executable:
        logger.warning("LibreOffice 未找到")
        return None
    
    try:
        result = subprocess.run(
            [
                executable,
                '--headless',
                '--convert-to', output_ext,
                '--outdir', output_dir,
                file_path
            ],
            capture_output=True,
            timeout=60
        )
        
        if result.returncode == 0:
            base_name = Path(file_path).stem
            converted_path = os.path.join(output_dir, base_name + output_ext)
            if os.path.exists(converted_path):
                return converted_path
        
        logger.warning(f"LibreOffice 转换失败: {result.stderr.decode('utf-8', errors='replace')}")
        return None
    except Exception as e:
        logger.warning(f"LibreOffice 转换异常: {e}")
        return None


def convert_legacy_office_to_modern(file_path: str, original_filename: str) -> str | None:
    """
    将遗留的 .doc/.ppt 文件转换为 .docx/.pptx
    
    策略:
    1. 优先尝试 LibreOffice (如果已安装)
    2. 其次尝试 pypandoc (需要 pandoc 后端)
    3. 都失败则返回 None
    """
    ext = os.path.splitext(original_filename)[1].lower()
    
    if ext == '.doc':
        output_ext = '.docx'
    elif ext == '.ppt':
        output_ext = '.pptx'
    else:
        return None
    
    with tempfile.TemporaryDirectory() as tmpdir:
        # 策略 1: LibreOffice
        converted = _convert_with_libreoffice(file_path, tmpdir, output_ext.lstrip('.'))
        if converted:
            logger.info(f"使用 LibreOffice 成功转换 {original_filename}")
            return converted
        
        # 策略 2: pypandoc
        output_path = os.path.join(tmpdir, Path(original_filename).stem + output_ext)
        if _convert_with_pypandoc(file_path, output_path, 'docx' if output_ext == '.docx' else 'pptx'):
            logger.info(f"使用 pypandoc 成功转换 {original_filename}")
            return output_path
        
        logger.error(f"无法转换遗留 Office 文件: {original_filename}")
        return None


def convert_to_markdown(file_path: str, original_filename: str) -> str:
    ext = os.path.splitext(original_filename)[1].lower()

    # 纯文本文件直接读取
    if ext in PLAINTEXT_EXTENSIONS:
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            return f.read()

    # 遗留 Office 文件需要先转换
    if ext in OFFICE_LEGACY_EXTENSIONS:
        modern_path = convert_legacy_office_to_modern(file_path, original_filename)
        if modern_path:
            result = _md.convert(modern_path)
            return result.text_content or ''
        else:
            raise ValueError(
                f"无法转换 {original_filename}。请安装 LibreOffice 或 Pandoc 以支持 .{ext.lstrip('.')} 文件。"
            )

    # 现代格式直接使用 markitdown
    result = _md.convert(file_path)
    return result.text_content or ''
