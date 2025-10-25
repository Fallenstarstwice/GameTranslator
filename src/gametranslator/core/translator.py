"""
Translation module for GameTranslator.
"""

import requests
import json
from src.gametranslator.config.settings import settings
from .llm_translator import LLMTranslator
from .translation_service import TranslationService


class MicrosoftTranslator(TranslationService):
    """Microsoft Translator API implementation."""
    
    def __init__(self):
        """Initialize Microsoft Translator with settings."""
        self.api_key = settings.get("translation", "api_key", "")
        self.region = settings.get("translation", "region", "global")
        self.endpoint = "https://api.cognitive.microsofttranslator.com/translate"
        self.timeout = 10  # seconds
        self.max_retries = 3
        
    def translate(self, text, source_lang=None, target_lang=None):
        """
        Translate text using Microsoft Translator API.
        
        Args:
            text (str): Text to translate.
            source_lang (str, optional): Source language code.
            target_lang (str, optional): Target language code.
            
        Returns:
            str: Translated text.
        """
        if not text.strip():
            return ""
            
        if not source_lang:
            source_lang = settings.get("translation", "source_language", "auto")
        
        if not target_lang:
            target_lang = settings.get("translation", "target_language", "zh-CN")
            
        # If no API key, return original text
        if not self.api_key:
            return f"[需要API密钥] {text}"
            
        # Retry logic
        for attempt in range(self.max_retries):
            try:
                params = {
                    'api-version': '3.0',
                    'to': target_lang
                }
                
                # Add source language if not auto-detect
                if source_lang and source_lang != "auto":
                    params['from'] = source_lang
                
                headers = {
                    'Ocp-Apim-Subscription-Key': str(self.api_key),
                    'Ocp-Apim-Subscription-Region': str(self.region),
                    'Content-type': 'application/json'
                }
                
                body = [{
                    'text': text
                }]
                
                response = requests.post(
                    self.endpoint, 
                    params=params,
                    headers=headers,
                    json=body,
                    timeout=self.timeout
                )
                
                response.raise_for_status()
                result = response.json()
                
                if result and len(result) > 0 and 'translations' in result[0]:
                    translated_text = result[0]['translations'][0]['text']
                    
                    # Also get detected language if available
                    if 'detectedLanguage' in result[0]:
                        detected_lang = result[0]['detectedLanguage']['language']
                        print(f"Detected language: {detected_lang}")
                    
                    return translated_text
                else:
                    return f"[响应格式错误] {text}"
                    
            except requests.exceptions.Timeout:
                if attempt < self.max_retries - 1:
                    print(f"Translation timeout, retrying... (attempt {attempt + 1})")
                    continue
                return f"[连接超时] {text}"
                
            except requests.exceptions.ConnectionError:
                if attempt < self.max_retries - 1:
                    print(f"Connection error, retrying... (attempt {attempt + 1})")
                    continue
                return f"[网络连接错误] {text}"
                
            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 401:
                    return f"[API密钥无效] {text}"
                elif e.response.status_code == 403:
                    return f"[API访问被拒绝] {text}"
                elif e.response.status_code == 429:
                    return f"[API调用频率超限] {text}"
                else:
                    return f"[HTTP错误 {e.response.status_code}] {text}"
                    
            except json.JSONDecodeError:
                return f"[响应解析错误] {text}"
                
            except Exception as e:
                if attempt < self.max_retries - 1:
                    print(f"Translation error, retrying... (attempt {attempt + 1}): {e}")
                    continue
                print(f"Translation error: {e}")
                return f"[翻译错误] {text}"
        
        return f"[翻译失败] {text}"


class MockTranslator(TranslationService):
    """Mock translator for testing without API keys."""
    
    def translate(self, text, source_lang=None, target_lang=None):
        """
        Mock translation for testing.
        
        Args:
            text (str): Text to translate.
            source_lang (str, optional): Source language code.
            target_lang (str, optional): Target language code.
            
        Returns:
            str: Translated text with mock prefix.
        """
        if not text.strip():
            return ""
            
        return f"[MOCK TRANSLATION] {text}"


def get_translator():
    """
    Factory function to get the appropriate translator based on settings.
    
    Returns:
        TranslationService: A translator instance.
    """
    service = settings.get("translation", "service", "microsoft")
    
    if service == "microsoft":
        translator = MicrosoftTranslator()
        # If no API key, fall back to mock translator
        if not translator.api_key:
            return MockTranslator()
        return translator
    elif service == "llm":
        return LLMTranslator()
    else:
        # Default to mock translator for testing
        return MockTranslator()