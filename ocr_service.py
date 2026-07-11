import base64
import httpx
import os
import re
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage

load_dotenv()

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

def get_openrouter_client():
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise ValueError(
            "کلید OPENROUTER_API_KEY تنظیم نشده است. "
            "لطفاً آن را در فایل .env قرار دهید."
        )

    return ChatOpenAI(
        model="gpt-4o",
        temperature=0.2,
        api_key=api_key,
        base_url="https://openrouter.ai/api/v1",
        max_tokens=1000,  # فقط یک کد ۱۰ رقمی نیاز داریم، پیش‌ فرض لنگ‌چین (۱۶۳۸۴) باعث خطای اعتبار ناکافی می‌شد
    )

def encode_image_to_base64(image_path: str) -> str:
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')

def get_image_mime_type(image_path: str) -> str:
    extension = image_path.lower().split('.')[-1]
    mime_types = {
        'jpg': 'image/jpeg',
        'jpeg': 'image/jpeg',
        'png': 'image/png',
        'gif': 'image/gif',
        'webp': 'image/webp'
    }
    return mime_types.get(extension, 'image/jpeg')

OCR_SYSTEM_PROMPT = """شما یک سیستم OCR متخصص هستید که اطلاعات کارت ملی ایرانی را استخراج می‌کنید.
فقط کد ملی ۱۰ رقمی را استخراج کنید.
پاسخ را فقط به صورت یک عدد ۱۰ رقمی بدهید، بدون هیچ توضیح یا متن اضافه.
اگر کد ملی پیدا نشد یا تصویر کارت ملی نبود، فقط کلمه "NOT_FOUND" را برگردانید.
کد ملی را به صورت عدد و فقط به صورت انگلیسی برگردان. یعنی اعداد
۱۲۷۰۷۶۵۱۰۸
نباشد. یعنی به صورت
1270765108
باشد.

در ادامه چند نمونه از تصویر کارت ملی و پاسخ صحیح متناظر با آن را می‌بینید. دقیقاً با همین سبک و فرمت پاسخ بده."""

FEW_SHOT_EXAMPLES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "few_shot_examples")

SUPPORTED_IMAGE_EXTENSIONS = ["jpg", "jpeg", "png", "gif", "webp"]

FEW_SHOT_EXAMPLES = [
    {"file_base_name": "sample_01", "national_code": "1234567890"},
    {"file_base_name": "sample_02", "national_code": "NOT_FOUND"},
    {"file_base_name": "sample_03", "national_code": "NOT_FOUND"},
    {"file_base_name": "sample_04", "national_code": "4006791196"},
    {"file_base_name": "sample_05", "national_code": "7162171074"},
    {"file_base_name": "sample_06", "national_code": "NOT_FOUND"},
]

def resolve_example_image_path(file_base_name: str):
    """
    برای یک نام پایه (مثلاً "sample_01")، به ترتیب پسوندهای SUPPORTED_IMAGE_EXTENSIONS
    را امتحان می‌کند و اولین فایلی که واقعاً در پوشه‌ی FEW_SHOT_EXAMPLES_DIR وجود دارد
    را برمی‌گرداند. اگر هیچ‌کدام پیدا نشد، None برمی‌گردد.
    """
    for extension in SUPPORTED_IMAGE_EXTENSIONS:
        candidate_path = os.path.join(FEW_SHOT_EXAMPLES_DIR, f"{file_base_name}.{extension}")
        if os.path.exists(candidate_path):
            return candidate_path
    return None

_few_shot_messages_cache = None

def get_few_shot_messages() -> list:
    
    global _few_shot_messages_cache

    if _few_shot_messages_cache is not None:
        return _few_shot_messages_cache

    messages = []

    for example in FEW_SHOT_EXAMPLES:
        file_base_name = example["file_base_name"]
        expected_code = example["national_code"]

        image_path = resolve_example_image_path(file_base_name)

        if image_path is None:
            supported = " / ".join(SUPPORTED_IMAGE_EXTENSIONS)
            print(
                f"⚠️ هشدار: هیچ فایلی برای نمونه‌ی few-shot با نام «{file_base_name}» "
                f"با فرمت‌های ({supported}) در پوشه‌ی {FEW_SHOT_EXAMPLES_DIR} پیدا نشد و نادیده گرفته شد."
            )
            continue

        try:
            example_base64 = encode_image_to_base64(image_path)
            example_mime = get_image_mime_type(image_path)
        except Exception as e:
            print(f"⚠️ هشدار: خطا در خواندن تصویر نمونه‌ی few-shot ({image_path}): {e}")
            continue

        messages.append(HumanMessage(content=[
            {
                "type": "text",
                "text": "لطفاً کد ملی را از این تصویر کارت ملی استخراج کنید. فقط عدد ۱۰ رقمی کد ملی را برگردانید."
            },
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:{example_mime};base64,{example_base64}"
                }
            }
        ]))
        messages.append(AIMessage(content=expected_code))

    _few_shot_messages_cache = messages
    return _few_shot_messages_cache


def extract_national_code_with_langchain(image_path: str) -> tuple:
    
    try:
        llm = get_openrouter_client()
        
        base64_image = encode_image_to_base64(image_path)
        mime_type = get_image_mime_type(image_path)
        
        final_user_message = HumanMessage(content=[
            {
                "type": "text",
                "text": "لطفاً کد ملی را از این تصویر کارت ملی استخراج کنید. فقط عدد ۱۰ رقمی کد ملی را برگردانید."
            },
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:{mime_type};base64,{base64_image}"
                }
            }
        ])
        
        messages = [
            SystemMessage(content=OCR_SYSTEM_PROMPT),
            *get_few_shot_messages(),
            final_user_message,
        ]
        
        response = llm.invoke(messages)
        result = response.content.strip()
        
        numbers = re.findall(r'\d+', result)
        for num in numbers:
            if len(num) == 10:
                return num, None
        
        if "NOT_FOUND" in result:
            return None, "کد ملی در تصویر یافت نشد"
        
        return None, "کد ملی معتبر در تصویر یافت نشد"
        
    except Exception as e:
        return None, f"خطا در پردازش تصویر: {str(e)}"

def extract_national_code_with_httpx(image_path: str, api_key: str, model: str = "openai/gpt-4o") -> tuple:
    if not api_key:
        return None, "کلید API وارد نشده است"
    
    try:
        base64_image = encode_image_to_base64(image_path)
        mime_type = get_image_mime_type(image_path)
        
        headers = {
            "Authorization": f"Bearer {api_key}",
            "HTTP-Referer": "http://localhost:7860",
            "X-Title": "Tax Calculator App",
            "Content-Type": "application/json"
        }
        
        few_shot_payload_messages = []
        for lc_message in get_few_shot_messages():
            role = "user" if isinstance(lc_message, HumanMessage) else "assistant"
            few_shot_payload_messages.append({
                "role": role,
                "content": lc_message.content
            })
        
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": OCR_SYSTEM_PROMPT
                },
                *few_shot_payload_messages,
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "لطفاً کد ملی را از این تصویر کارت ملی استخراج کنید. فقط عدد ۱۰ رقمی کد ملی را برگردانید."
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime_type};base64,{base64_image}"
                            }
                        }
                    ]
                }
            ],
            "max_tokens": 50
        }
        
        with httpx.Client(timeout=60.0) as client:
            response = client.post(
                f"{OPENROUTER_BASE_URL}/chat/completions",
                headers=headers,
                json=payload
            )
            response.raise_for_status()
            
        result_json = response.json()
        result = result_json["choices"][0]["message"]["content"].strip()
        
        numbers = re.findall(r'\d+', result)
        for num in numbers:
            if len(num) == 10:
                return num, None
        
        if "NOT_FOUND" in result:
            return None, "کد ملی در تصویر یافت نشد"
        
        return None, "کد ملی معتبر در تصویر یافت نشد"
        
    except httpx.HTTPStatusError as e:
        return None, f"خطای HTTP: {e.response.status_code} - {e.response.text}"
    except Exception as e:
        return None, f"خطا در پردازش تصویر: {str(e)}"

def extract_national_code_from_image(image_path: str) -> tuple:
    return extract_national_code_with_langchain(image_path)

def validate_national_code(national_code: str) -> bool:
    if not national_code or len(national_code) != 10:
        return False
    
    if not national_code.isdigit():
        return False
    
    if national_code == national_code[0] * 10:
        return False
    
    try:
        check = int(national_code[9])
        total = sum(int(national_code[i]) * (10 - i) for i in range(9))
        remainder = total % 11
        
        if remainder < 2:
            return check == remainder
        else:
            return check == (11 - remainder)
    except:
        return False

AVAILABLE_MODELS = [
    ("openai/gpt-4o", "GPT-4o (OpenAI)"),
    ("openai/gpt-4o-mini", "GPT-4o Mini (OpenAI)"),
    ("openai/gpt-4-turbo", "GPT-4 Turbo (OpenAI)"),
    ("anthropic/claude-3.5-sonnet", "Claude 3.5 Sonnet (Anthropic)"),
    ("anthropic/claude-3-opus", "Claude 3 Opus (Anthropic)"),
    ("google/gemini-pro-vision", "Gemini Pro Vision (Google)"),
    ("google/gemini-pro-1.5", "Gemini 1.5 Pro (Google)"),
    ("meta-llama/llama-3.2-90b-vision-instruct", "Llama 3.2 90B Vision (Meta)"),
]

def get_model_choices():
    return [model[0] for model in AVAILABLE_MODELS]

def get_model_labels():
    return {model[0]: model[1] for model in AVAILABLE_MODELS}