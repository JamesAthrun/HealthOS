import base64
import json

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.config import Settings

PROMPT_VERSION = "meal-photo-v1"


class RecognizedFoodItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    quantity: float = Field(gt=0, le=100000)
    unit: str = Field(min_length=1, max_length=20)
    kcal: float = Field(ge=0, le=10000)
    protein_g: float = Field(default=0, ge=0, le=1000)
    carbs_g: float = Field(default=0, ge=0, le=1000)
    fat_g: float = Field(default=0, ge=0, le=1000)
    confidence: float = Field(ge=0, le=1)


class MealRecognition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    meal_type: str = Field(pattern="^(breakfast|lunch|dinner|snack)$")
    food_items: list[RecognizedFoodItem] = Field(min_length=1, max_length=20)
    overall_confidence: float = Field(ge=0, le=1)
    warnings: list[str] = Field(default_factory=list, max_length=10)


class AIProviderError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


SYSTEM_PROMPT = """你是 HealthOS 的餐食照片结构化识别器。只根据照片中可见内容估算，不能虚构看不见的配料。
返回一个 JSON 对象，且只能包含 meal_type、food_items、overall_confidence、warnings。
food_items 每项必须包含 name、quantity、unit、kcal、protein_g、carbs_g、fat_g、confidence。
数值是待用户确认的粗略估算。份量或菜品不确定时降低 confidence，并把简短中文说明放入 warnings。
不要输出医疗建议，不要输出 Markdown。"""


def recognize_meal(image_bytes: bytes, settings: Settings) -> MealRecognition:
    if not settings.deepseek_api_key:
        raise AIProviderError("AI_NOT_CONFIGURED")

    image_url = f"data:image/jpeg;base64,{base64.b64encode(image_bytes).decode('ascii')}"
    payload = {
        "model": settings.deepseek_model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "识别这张餐食照片并返回 JSON。"},
                    {
                        "type": "image_url",
                        "image_url": {"url": image_url, "detail": "high"},
                    },
                ],
            },
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.1,
        "max_tokens": 1500,
    }
    last_code = "AI_INVALID_RESPONSE"
    for _attempt in range(2):
        try:
            with httpx.Client(timeout=settings.deepseek_timeout_seconds) as client:
                response = client.post(
                    f"{settings.deepseek_base_url.rstrip('/')}/chat/completions",
                    headers={"Authorization": f"Bearer {settings.deepseek_api_key}"},
                    json=payload,
                )
                response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            return MealRecognition.model_validate(json.loads(content))
        except httpx.TimeoutException:
            last_code = "AI_TIMEOUT"
        except httpx.HTTPStatusError as exc:
            last_code = f"AI_HTTP_{exc.response.status_code}"
            if exc.response.status_code in {400, 401, 403}:
                break
        except (KeyError, TypeError, json.JSONDecodeError, ValidationError):
            last_code = "AI_INVALID_RESPONSE"
    raise AIProviderError(last_code)
