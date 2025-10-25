import logging
from typing import Optional
from PySide6.QtCore import QThread, Signal
from PIL.Image import Image

log = logging.getLogger(__name__)

class TranslationWorker(QThread):
    """
    Performs OCR and translation in a background thread to avoid blocking the UI.
    """
    # Signal emitted on successful translation.
    # Provides: original_text (str), translated_text (str)
    translation_successful = Signal(str, str)
    
    # Signal emitted on failure.
    # Provides: error_message (str)
    translation_failed = Signal(str)

    def __init__(self, translator, target_lang: str, *, ocr_engine=None, screenshot: Optional[Image] = None, text_to_translate: Optional[str] = None, vocabulary_db=None, rag_vocabulary_name: Optional[str] = None, parent=None):
        """
        Initializes the worker.
        
        Args:
            translator: The translator instance.
            target_lang: The target language for translation.
            ocr_engine: (Optional) The OCR engine instance. Required if using screenshot.
            screenshot: (Optional) The PIL.Image screenshot to perform OCR on.
            text_to_translate: (Optional) The text to translate directly.
            vocabulary_db: (Optional) The vocabulary DB instance for RAG.
            rag_vocabulary_name: (Optional) The name of the vocabulary to use for RAG.
        """
        super().__init__(parent)
        self.translator = translator
        self.target_lang = target_lang
        self.ocr_engine = ocr_engine
        self.screenshot = screenshot
        self.text_to_translate = text_to_translate
        self.vocabulary_db = vocabulary_db
        self.rag_vocabulary_name = rag_vocabulary_name

    def run(self):
        """
        The main logic of the worker thread. This will be executed when the thread starts.
        """
        try:
            original_text = ""
            if self.screenshot is not None and self.ocr_engine is not None:
                # Path 1: OCR from screenshot, then translate
                log.info("Worker thread: Starting OCR.")
                original_text = self.ocr_engine.recognize_text(self.screenshot)
                if not original_text or not original_text.strip():
                    log.warning("Worker thread: OCR did not find any text.")
                    self.translation_failed.emit("OCR未能识别到任何文本")
                    return
            elif self.text_to_translate is not None:
                # Path 2: Translate pre-existing text
                original_text = self.text_to_translate
            else:
                # No valid task provided
                self.translation_failed.emit("没有提供翻译任务")
                return

            # --- RAG Context Injection ---
            rag_context = None
            if self.vocabulary_db and self.rag_vocabulary_name:
                try:
                    log.info(f"Querying RAG vocabulary '{self.rag_vocabulary_name}' for context.")
                    # Ensure embedding provider is configured for the DB instance
                    from src.gametranslator.config.settings import settings
                    api_key = settings.get("embedding", "api_key")
                    base_url = settings.get("embedding", "base_url")
                    model = settings.get("embedding", "model")
                    if all([api_key, base_url, model]):
                        self.vocabulary_db.configure_embedding_provider(api_key, base_url, model)
                        rag_context = self.vocabulary_db.query(self.rag_vocabulary_name, original_text, n_results=5)
                    else:
                        log.warning("Embedding provider not fully configured. Skipping RAG query.")
                except Exception as e:
                    log.error(f"Error during RAG query: {e}", exc_info=True)
            
            log.info(f"Worker thread: Starting translation for text length {len(original_text)}.")
            
            from inspect import signature
            kwargs = {"target_lang": self.target_lang}
            try:
                if rag_context is not None:
                    sig = signature(self.translator.translate)
                    if "rag_context" in sig.parameters:
                        kwargs["rag_context"] = rag_context
            except Exception:
                pass
            translated_text = self.translator.translate(original_text, **kwargs)

            log.info("Worker thread: Translation successful.")

            # Emit success signal with both original and translated text
            self.translation_successful.emit(original_text, translated_text)

        except Exception as e:
            log.error(f"An error occurred in the translation worker thread: {e}", exc_info=True)
            self.translation_failed.emit(f"翻译时发生错误: {str(e)}")