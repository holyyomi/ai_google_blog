import json
import logging
from blogspot_automation.config import Settings
from blogspot_automation.utils.network import post_json_with_retry

logger = logging.getLogger(__name__)

class OpenAIImageClient:
    def __init__(self, settings: Settings) -> None:
        self.api_key = settings.openai_api_key
        self.model = settings.openai_image_model or "dall-e-3"
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY is not set.")

    def generate_image(self, prompt: str) -> dict[str, object]:
        payload = {
            "model": self.model,
            "prompt": prompt,
            "n": 1,
            "size": "1024x1024",
            "response_format": "url"
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        response_str = post_json_with_retry(
            url="https://api.openai.com/v1/images/generations",
            headers=headers,
            payload=payload,
            operation_name="openai_image_generation",
            logger=logger,
            connect_timeout=20,
            read_timeout=180,
        )
        return json.loads(response_str)
