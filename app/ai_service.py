"""
ai_service.py — Transaction parser using Novita.ai (Llama-3.1-8B-Instruct).

Key design decisions:
- Fully async via httpx (no executor / run_in_executor needed).
- Strips markdown fences before JSON parsing (model sometimes wraps with ```json).
- Validates and normalises every field so the rest of the app always gets a
  clean dict regardless of what the model returns.
- Falls back to a heuristic mock parser when NOVITA_API_KEY is not set.
"""

import json
import logging
import os
import re
from datetime import date, datetime, timezone

import httpx

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────

# Novita uses an OpenAI-compatible endpoint — just swap base URL + key.
AI_API_KEY  = os.getenv("AI_API_KEY", "")
AI_BASE_URL = os.getenv("AI_BASE_URL", "")
AI_MODEL    = os.getenv("AI_MODEL", "")
AI_TIMEOUT      = float(os.getenv("AI_TIMEOUT_SECONDS", "25"))
VALID_TAGS  = {"Personal", "Family", "Work"}
VALID_TYPES = {"income", "expense"}

# ── System prompt (matches your exact schema) ─────────────────────────────────

# SYSTEM_PROMPT = (
#     "You are a parsing assistant that helps to parse scripts into relevant details "
#     "and respond in JSON format. You are not to answer any prompts without the JSON "
#     "formatting in your responses. When a user submits a transaction, your job is to "
#     "parse them into these categories: content(str), currency(str), amount(int64), "
#     "type(str, only between income and expense), date(YYYY-MM-DD), category(str), "
#     "tags(str), notes(str). "
#     "Available categories include (Food & Drinks, Education, Transportation, Health, "
#     "Entertainment, Utilities, Devices, Others). "
#     "Available tags include (Personal, Family, Work). "
#     "If date or note information is missing, return null for those fields. "
#     "Always return just a string for the values of each key. "
#     "THE CONTENT FIELD SHOULD NOT CONTAIN ANY OTHER DETAILS "
#     "(e.g 'new phone for 500USD' is NOT a valid content field, but 'new phone' IS). "
#     "USE THE CONTENT'S CONTEXT to fill in the category and tags field "
#     "(e.g 'breakfast of banh mi' means Food and Drinks category and Personal tag "
#     "while 'november tuition fees' means Education category and Family tag). "
#     "Tag field can not be null. "
#     "Always respond in raw JSON format and do not tamper it with Markdown or other "
#     "formatting methods. "
#     "DO NOT RESPOND LIKE A NORMAL CHAT AI IN ANY CIRCUMSTANCES."
# )

# Danh sách mapping để AI tham chiếu (đã tối ưu hóa cho prompt)
# Type 1: Income, Type 0: Expense
CATEGORY_MAPPING = """
INCOME (type:1):
1: Salary/Lương, 2: Bonus/Thưởng, 3: Allowance/Phụ cấp, 4: Business/Kinh doanh, 
5: Investment/Đầu tư, 6: Passive Income/Thu nhập thụ động, 7: Gift/Quà tặng, 8: Other Income/Thu khác, 35: Other/Khác

EXPENSE (type:0):
9: Food & Drink/Ăn uống, 10: Transport/Đi lại, 11: Phone/Điện thoại, 12: Internet, 
13: Fuel/Xăng dầu, 14: Groceries/Nhu yếu phẩm, 15: Clothing/Trang phục, 16: Beauty/Làm đẹp, 
17: Entertainment/Giải trí, 18: Travel/Du lịch, 19: Family Support/Chu cấp, 20: Events & Gifts/Hiếu hỉ, 
21: Medical/Khám bệnh, 22: Medicine/Thuốc men, 23: Fitness/Tập luyện, 24: Fund/Quỹ, 
25: Repair/Sửa chữa, 26: Accident/Tai nạn, 27: Fine & Fee/Phí phạt, 28: Rent/Tiền nhà, 
29: Electricity/Tiền điện, 30: Water/Tiền nước, 31: Education/Học phí, 32: Insurance/Bảo hiểm, 
33: Installment/Trả góp, 34: Other/Khác
"""

# SYSTEM_PROMPT = f"""
# You are a financial parsing assistant. Parse user text into a RAW JSON object.
# When a user submits a transaction content, your job is to parse them based on the following rules 
# RULES:
# 1. ONLY return a single JSON object format and do not tamper it with Markdown. DO NOT include explanations, introduction, or markdown outside the JSON.
# 2. Fields: content(str), currency(str), amount(int64), type(str: 'income' or 'expense'), 
#    date(YYYY-MM-DD), master_category_id(int), address(str), tags(str), notes(str).
# 3. master_category_id: Must match the CATEGORY MAPPING provided below based on the transaction context.
# 4. Tags: Must be one of (Personal, Family, Work). Use context to decide.
# 5. Content: A short, clean description of what was purchased or done (e.g., 'Ăn trưa phở bò', 'Mua xăng', 'Tiền điện tháng 5'). Keep the meal type (breakfast/lunch/dinner) if mentioned.
# 6. Address: The specific place/store/location name where the transaction happened (e.g., 'Circle K', 'Vinmart', 'Grab'). Leave empty string if no location is mentioned.
# 8. Language/Currency: Use provided context unless user explicitly overrides.

# CATEGORY MAPPING:
# {CATEGORY_MAPPING}
# """

SYSTEM_PROMPT = f"""
You are a financial transaction parser. Extract structured data from user input.

OUTPUT: A single raw JSON object. No markdown, no explanation, no extra text.

FIELD DEFINITIONS:
- content: The ACTION + ITEM only. Remove location, price, and filler words. (e.g. input "Ăn trưa mỳ Ramen ở Go Thăng Long 115k" → content = "Ăn trưa mỳ Ramen")
- amount: Numeric value only. Convert 'k'=×1000, 'triệu'/'tr'=×1,000,000.
- currency: From context, default to user's currency setting.
- type: 'income' or 'expense'.
- date: YYYY-MM-DD. Use today if not specified.
- master_category_id: Integer from CATEGORY MAPPING below.
- address: The PLACE or STORE NAME only. Typically follows keywords 'ở', 'tại', 'at', 'by', 'trên'. Empty string "" if no location mentioned.
- tags: One of: Personal, Family, Work.
- notes: Any extra detail not captured above. Empty string "" if none.

CATEGORY MAPPING:
{CATEGORY_MAPPING}
"""

# ── Public API ────────────────────────────────────────────────────────────────

async def parse_transaction(user_text: str, user_currency: str = "VND", language_code: str = "vi") -> dict:
    """
    Parse a natural-language transaction description into a structured dict.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    today_str = date.today().isoformat()


    if not AI_API_KEY:
        logger.warning("NOVITA_API_KEY not set — using heuristic mock parser")
        return _mock_parse(user_text, user_currency, now_iso)

    # prompt = (
    #     f"Today's date: {date.today().isoformat()}\n"
    #     f"User currency: {user_currency}\n"
    #     f"Language code: {language_code}\n"
    #     f"Transaction: {user_text}"
    # )
    # Tạo prompt chi tiết cho AI
    # Cung cấp ngữ cảnh ngôn ngữ giúp AI hiểu các từ lóng hoặc tên riêng địa phương tốt hơn
    prompt = (
        f"CONTEXT:\n"
        f"- Today's date: {today_str}\n"
        f"- Target Currency: {user_currency}\n"
        f"- Target Language: {language_code}\n\n"
        f"USER INPUT:\n"
        f"'{user_text}'"
    )

    try:
        raw = await _call_llm(prompt)
        # Hàm _parse_and_validate cần được giữ lại để xử lý chuỗi JSON từ AI
        return _parse_and_validate(raw, user_currency, now_iso)
    except Exception as e:
        logger.error(f"Failed to parse transaction: {e}")
        raise ValueError(f"Failed to parse transaction: {e}") from e


# ── LLM call ─────────────────────────────────────────────────────────────────

async def _call_llm(prompt: str) -> str:
    """
    POST to the Novita OpenAI-compatible endpoint.
    Fully async — no run_in_executor needed.
    """
    headers = {
        "Authorization": f"Bearer {AI_API_KEY}",
        "Content-Type": "application/json",
    }
    # logger.debug(f"Sending request to LLM with headers: {headers}")
    payload = {
        "model": AI_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": prompt},
        ],
        "temperature": 0.0, # Giảm xuống 0.0 để kết quả trích xuất ổn định nhất
        "max_tokens": 500,
    }

    async with httpx.AsyncClient(timeout=AI_TIMEOUT) as client:
        resp = await client.post(
            f"{AI_BASE_URL}/chat/completions",
            headers=headers,
            json=payload,
        )

    # Surface HTTP errors as plain exceptions so the caller can wrap them.
    resp.raise_for_status()

    logger.debug(f"Received response from LLM: {resp.text}")  # Log the raw response for debugging
    result = resp.json()
    content = result["choices"][0]["message"]["content"].strip()
    
    # Xử lý trường hợp AI trả về markdown code block
    if content.startswith("```"):
        content = content.split("```")[1]
        if content.startswith("json"):
            content = content[4:]
    
    logger.debug(f"Extracted content after stripping markdown: {content}")  # Log the cleaned content for debugging
    
    return content.strip()


# ── JSON extraction & validation ──────────────────────────────────────────────

def _strip_markdown(text: str) -> str:
    """
    Remove ```json ... ``` or ``` ... ``` fences that the model may add
    despite being told not to.
    """
    # Remove opening fence (```json or ```)
    text = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.IGNORECASE)
    # Remove closing fence
    text = re.sub(r"\s*```$", "", text.strip())
    return text.strip()


def _parse_and_validate(raw: str, default_currency: str, now_iso: str) -> dict:
    clean = _strip_markdown(raw)

    try:
        data = json.loads(clean)
    except json.JSONDecodeError as exc:
        logger.error("JSON parse failed. Raw text: %r", raw)
        raise ValueError(f"Model returned non-JSON output: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object, got {type(data).__name__}")

    # ── Normalise each field ─────────────────────────────────────────────────

    # content
    content = str(data.get("content") or "").strip() or "Transaction"

    # currency
    currency = str(data.get("currency") or default_currency).upper().strip()

    # amount — accept int, float, or numeric string
    raw_amount = data.get("amount", 0)
    try:
        amount = int(str(raw_amount).replace(",", "").replace(".", "").strip() or 0)
    except (ValueError, TypeError):
        amount = 0

    # type
    txn_type = str(data.get("type") or "expense").lower().strip()
    if txn_type not in VALID_TYPES:
        txn_type = "expense"

    # date — keep as YYYY-MM-DD string or null
    raw_date = data.get("date")
    parsed_date: str | None = None
    if raw_date and str(raw_date).lower() not in ("null", "none", ""):
        try:
            parsed_date = str(datetime.strptime(str(raw_date), "%Y-%m-%d").date())
        except ValueError:
            parsed_date = None

    # category
    master_category_id = data.get("master_category_id")
    # try:
    #     category_id = int(master_category_id)
    #     if txn_type == "income" and not (1 <= category_id <= 8):
    #         category_id = 35  # Default to "Other" for income
    #     elif txn_type == "expense" and not (9 <= category_id <= 34):
    #         category_id = 34  # Default to "Other" for expense
    # except (ValueError, TypeError):
    #     category_id = 35 if txn_type == "income" else 34  # Default to "Other"

    # tags — must not be null
    tags = str(data.get("tags") or "Personal").strip()
    if tags not in VALID_TAGS:
        tags = "Personal"

    # notes — nullable
    notes_raw = data.get("notes")
    notes: str | None = None
    if notes_raw and str(notes_raw).lower() not in ("null", "none", ""):
        notes = str(notes_raw).strip()

    # address — best effort to extract from content if not provided
    address = str(data.get("address") or "").strip()
    if not address:
        # Heuristic: look for keywords like 'ở', 'tại', 'at', 'by', 'trên' followed by a place name
        m = re.search(r"(?:ở|tại|at|by|trên)\s+([^\d,]+)", content, flags=re.IGNORECASE)
        if m:
            address = m.group(1).strip()
            # Remove the address part from content to keep it clean
            content = re.sub(r"(?:ở|tại|at|by|trên)\s+[^\d,]+", "", content, flags=re.IGNORECASE).strip()
    
    # Build date_time for FinA compatibility (ISO8601)
    if parsed_date:
        date_time = f"{parsed_date}T00:00:00Z"
    else:
        date_time = now_iso

    return {
        # Schema from your system prompt
        "content":  content,
        "currency": currency,
        "amount":   amount,
        "type":     txn_type,
        "date":     parsed_date,
        "master_category_id": master_category_id,
        "tags":     tags,
        "notes":    notes,
        # Extra fields kept for FinA backend compatibility
        "address":   address,      # best approximation without address field
        "wallet":    "cash",
        "date_time": date_time,
    }


# ── Heuristic mock (dev / no API key) ────────────────────────────────────────

def _mock_parse(text: str, currency: str, now_iso: str) -> dict:
    """Deterministic fallback used when NOVITA_API_KEY is absent."""
    amount = 0
    m = re.search(r"(\d[\d,.]*)([kK])?", text)
    if m:
        raw = m.group(1).replace(",", "").replace(".", "")
        try:
            amount = int(raw)
            if m.group(2):          # "k" / "K" suffix
                amount *= 1000
        except ValueError:
            amount = 0

    text_lower = text.lower()
    is_income = any(w in text_lower for w in
                    ["lương", "nhận", "thu nhập", "salary", "income", "received"])

    if any(w in text_lower for w in ["cafe", "coffee", "trà", "bún", "phở", "cơm", "ăn", "breakfast", "lunch", "dinner"]):
        category, tags = "Food & Drinks", "Personal"
    elif any(w in text_lower for w in ["grab", "taxi", "xe", "bus", "xăng", "transport"]):
        category, tags = "Transportation", "Personal"
    elif any(w in text_lower for w in ["học", "tuition", "school", "course", "study"]):
        category, tags = "Education", "Family"
    elif any(w in text_lower for w in ["thuốc", "bệnh", "doctor", "hospital", "health"]):
        category, tags = "Health", "Personal"
    elif any(w in text_lower for w in ["phone", "laptop", "device", "máy"]):
        category, tags = "Devices", "Personal"
    elif is_income:
        category, tags = "Others", "Work"
    else:
        category, tags = "Others", "Personal"

    words = text.split()
    content = " ".join(words[:3]) if len(words) >= 3 else text

    return {
        "content":   content,
        "currency":  currency,
        "amount":    amount,
        "type":      "income" if is_income else "expense",
        "date":      None,
        "category":  category,
        "tags":      tags,
        "notes":     None,
        "address":   content,
        "wallet":    "cash",
        "date_time": now_iso,
    }
