"""
Defines the base class for all translation services.
"""

class TranslationService:
    """Base class for translation services."""
    
    def translate(self, text: str, source_lang: str = None, target_lang: str = None) -> str:
        """
        Translate text from source language to target language.
        
        Args:
            text (str): Text to translate.
            source_lang (str, optional): Source language code.
            target_lang (str, optional): Target language code.
            
        Returns:
            str: Translated text.
        """
        raise NotImplementedError("Subclasses must implement translate()")