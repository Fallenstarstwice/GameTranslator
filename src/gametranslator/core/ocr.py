"""
OCR module for GameTranslator.
"""

import os
import pytesseract
from PIL import Image
import numpy as np
from typing import Union, List

from src.gametranslator.config.settings import settings


class OCREngine:
    """Handles OCR text recognition."""
    
    def __init__(self):
        """Initialize OCR engine with settings."""
        # First try to use local Tesseract in project directory
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
        local_tesseract_path = os.path.join(project_root, "Tesseract-OCR", "tesseract.exe")
        local_tessdata_path = os.path.join(project_root, "Tesseract-OCR", "tessdata")
        
        if os.path.exists(local_tesseract_path):
            # Use local Tesseract
            pytesseract.pytesseract.tesseract_cmd = local_tesseract_path
            os.environ['TESSDATA_PREFIX'] = local_tessdata_path
            print(f"Using local Tesseract: {local_tesseract_path}")
            print(f"Tessdata path set to: {local_tessdata_path}")
        else:
            # Try to get tesseract path from settings
            tesseract_path = settings.get("ocr", "tesseract_path")
            if tesseract_path and os.path.exists(tesseract_path):
                pytesseract.pytesseract.tesseract_cmd = tesseract_path
                print(f"Using configured Tesseract: {tesseract_path}")
            else:
                # Try default system path
                print("Using system Tesseract (if available)")
        
        # Get OCR language from settings
        self.language = settings.get("ocr", "language", "eng")
    
    def recognize_text(self, image: Union[Image.Image, np.ndarray], max_retries: int = 3) -> str:
        """
        Recognize text from an image with retry mechanism.
        
        Args:
            image (Union[Image.Image, np.ndarray]): The image to recognize text from.
            max_retries (int): Maximum number of retry attempts.
        
        Returns:
            str: The recognized text.
        """
        debug_files: List[str] = []  # Track debug files for cleanup
        for attempt in range(max_retries):
            try:
                # Ensure image is in PIL format
                if hasattr(image, 'shape'):  # numpy array
                    if len(image.shape) == 3:
                        image = Image.fromarray(image)
                    else:
                        image = Image.fromarray(np.uint8(image))
                
                # Save image temporarily for debugging if first attempt fails
                if attempt > 0:
                    debug_path = f"debug_ocr_attempt_{attempt}.png"
                    image.save(debug_path)
                    debug_files.append(debug_path)
                    print(f"Saved debug image: {debug_path}")
                
                # Perform OCR with different configurations based on attempt
                if attempt == 0:
                    # First attempt: normal OCR
                    text = pytesseract.image_to_string(image, lang=self.language)
                elif attempt == 1:
                    # Second attempt: with PSM 6 (single uniform block)
                    config = '--psm 6'
                    text = pytesseract.image_to_string(image, lang=self.language, config=config)
                else:
                    # Third attempt: with PSM 8 (single word) and different preprocessing
                    config = '--psm 8'
                    # Convert to grayscale and enhance contrast
                    if image.mode != 'L':
                        image = image.convert('L')
                    text = pytesseract.image_to_string(image, lang=self.language, config=config)
                
                # Ensure we return a string
                if isinstance(text, str):
                    result = text.strip()
                else:
                    result = str(text).strip()
                
                if result:  # If we got some text, consider it successful
                    print(f"OCR successful on attempt {attempt + 1}: extracted {len(result)} characters")
                    # Clean up debug files if any were created
                    self._cleanup_debug_files(debug_files)
                    return result
                elif attempt == max_retries - 1:
                    print(f"OCR completed but no text found after {max_retries} attempts")
                    # Clean up debug files if any were created
                    self._cleanup_debug_files(debug_files)
                    return "[OCR] 未识别到文本内容"
                else:
                    print(f"OCR attempt {attempt + 1} returned empty, retrying...")
                    continue
                
            except pytesseract.TesseractNotFoundError as e:
                error_msg = f"Tesseract未找到: {e}"
                print(error_msg)
                return f"[OCR错误] Tesseract未正确安装或配置"
                
            except pytesseract.TesseractError as e:
                error_msg = f"Tesseract执行错误 (尝试 {attempt + 1}): {e}"
                print(error_msg)
                if attempt == max_retries - 1:
                    return f"[OCR错误] Tesseract执行失败: {str(e)}"
                else:
                    print(f"Retrying OCR (attempt {attempt + 2})...")
                    continue
                
            except PermissionError as e:
                error_msg = f"权限错误 (尝试 {attempt + 1}): {e}"
                print(error_msg)
                if attempt == max_retries - 1:
                    return f"[OCR错误] 没有权限访问Tesseract，请以管理员身份运行程序"
                else:
                    print(f"Retrying OCR with different approach (attempt {attempt + 2})...")
                    import time
                    time.sleep(0.5)  # Brief delay before retry
                    continue
                
            except FileNotFoundError as e:
                error_msg = f"文件未找到: {e}"
                print(error_msg)
                return f"[OCR错误] Tesseract可执行文件未找到"
                
            except Exception as e:
                error_msg = f"OCR未知错误 (尝试 {attempt + 1}): {e}"
                print(error_msg)
                if attempt == max_retries - 1:
                    return f"[OCR错误] {str(e)}"
                else:
                    print(f"Retrying OCR (attempt {attempt + 2})...")
                    import time
                    time.sleep(0.5)  # Brief delay before retry
                    continue
        
        return "[OCR错误] 所有重试尝试均失败"
    
    def _cleanup_debug_files(self, debug_files: List[str]) -> None:
        """
        Clean up debug files created during OCR process.
        
        Args:
            debug_files (List[str]): List of file paths to clean up.
        """
        for file_path in debug_files:
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
                    print(f"Cleaned up debug file: {file_path}")
            except Exception as e:
                print(f"Warning: Could not clean up debug file {file_path}: {e}")
    
    def set_language(self, language):
        """
        Set the OCR language.
        
        Args:
            language (str): The language code to use for OCR.
        """
        self.language = language
        settings.set("ocr", "language", language)