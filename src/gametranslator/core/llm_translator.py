"""
LLM-based translation service for GameTranslator.
"""
import logging
import requests
from .translation_service import TranslationService
from src.gametranslator.config.settings import settings

log = logging.getLogger(__name__)

class LLMTranslator(TranslationService):
    """
    Translator implementation using a generic LLM API (OpenAI compatible).
    """
    def __init__(self):
        """Initialize LLM Translator with settings."""
        self.api_key = settings.get("llm", "api_key", "")
        base_url_setting = settings.get("llm", "base_url", "https://api.openai.com/v1")
        self.base_url = str(base_url_setting) if base_url_setting is not None else ""
        self.model = settings.get("llm", "model", "gpt-4o")
        self.timeout = 45  # seconds, LLMs can be slower
        self.max_retries = 2

    def _build_prompt(self, text, source_lang, target_lang, rag_context=None):
        """Builds a precise prompt for the LLM, optionally including RAG context."""
        
        context_prompt = ""
        if rag_context:
            log.info(f"RAG context received: {rag_context}")
            
            rag_documents = []
            if isinstance(rag_context, list):
                rag_documents = rag_context
            elif isinstance(rag_context, dict) and 'documents' in rag_context:
                rag_documents = rag_context['documents']

            # Process the structured RAG results
            processed_docs = []
            for result in rag_documents:
                if isinstance(result, dict) and 'original_text' in result and 'metadata' in result:
                    metadata = result.get('metadata', {})
                    translation = metadata.get('translation')
                    if translation:
                        processed_docs.append(f"{result['original_text']} -> {translation}")

            if processed_docs:
                log.info(f"Found {len(processed_docs)} processed documents for prompt: {processed_docs}")
                context_prompt = (
                    "When translating, you MUST prioritize using the following vocabulary (original->translation). "
                    "These are key terms from the game and should be translated as provided:\n"
                    "--- Vocabulary Start ---\n"
                )
                for doc in processed_docs:
                    context_prompt += f"- {doc}\n"
                context_prompt += "--- Vocabulary End ---\n\n"
            else:
                log.warning("RAG context was provided, but no documents were found after processing.")
        else:
            log.info("No RAG context provided for this translation.")

        return (
            f"You are a professional translation engine for games. "
            f"Translate the following text from '{source_lang}' to '{target_lang}'. "
            f"{context_prompt}"
            f"Your response must be ONLY the translated text. Do not add any extra information, explanations, or apologies.\n\n"
            f"Text to translate:\n{text}"
        )

    def translate(self, text, source_lang=None, target_lang=None, rag_context=None):
        """
        Translate text using the configured LLM API.
        
        Args:
            text (str): The text to translate.
            source_lang (str, optional): The source language. Defaults to None.
            target_lang (str, optional): The target language. Defaults to None.
            rag_context (dict, optional): Context from RAG for more accurate translation.
        """
        if not text.strip():
            return ""

        if not all([self.api_key, self.base_url, self.model]):
            return "[LLM配置不完整]"

        if not source_lang or source_lang == "auto":
            source_lang = "the source language" # Let the model infer
        if not target_lang:
            target_lang = settings.get("translation", "target_language", "zh-CN")

        prompt = self._build_prompt(text, source_lang, target_lang, rag_context)
        log.debug(f"LLM Prompt: {prompt}")
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.7,
            "stream": False,
        }
        
        endpoint = self.base_url.strip('/') + "/chat/completions"

        for attempt in range(self.max_retries):
            try:
                log.info(f"Sending request to LLM API: {endpoint} with model {self.model}")
                response = requests.post(
                    endpoint,
                    json=payload,
                    headers=headers,
                    timeout=self.timeout
                )
                response.raise_for_status()
                data = response.json()

                if data and 'choices' in data and data['choices']:
                    content = data['choices'][0].get('message', {}).get('content', '')
                    if content:
                        log.info("LLM translation successful.")
                        return content.strip()
                
                log.error(f"LLM response format error: {data}")
                return "[LLM响应格式错误]"

            except requests.exceptions.Timeout:
                log.warning(f"LLM translation timeout, retrying... (attempt {attempt + 1})")
                if attempt >= self.max_retries - 1:
                    return "[LLM连接超时]"
            except requests.exceptions.HTTPError as e:
                log.error(f"LLM HTTP error: {e.response.status_code} - {e.response.text}")
                if e.response.status_code == 401:
                    return "[LLM API密钥无效]"
                elif e.response.status_code == 429:
                    return "[LLM API调用频率超限]"
                return f"[LLM HTTP错误 {e.response.status_code}]"
            except Exception as e:
                log.error(f"An unexpected error occurred during LLM translation: {e}", exc_info=True)
                if attempt >= self.max_retries - 1:
                    return f"[LLM未知错误: {e}]"
        
        return "[LLM翻译失败]"