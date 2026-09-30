import os, json, re
from urllib.parse import quote_plus
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()
MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

LINKS = {
    "amazon": "https://www.amazon.in/s?k=", "flipkart": "https://www.flipkart.com/search?q=",
    "ikea": "https://www.ikea.com/in/en/search/?q=", "swiggy": "https://www.swiggy.com/search?query=",
    "zomato": "https://www.zomato.com/search?q=", "oyo": "https://www.oyorooms.com/search/?location=",
}
PLATFORMS = {
    "home": "Amazon, IKEA, Flipkart",
    "party": "Swiggy, Zomato, OYO, Amazon (for decor)",
    "jewelry": "Amazon, Flipkart",
}
GOALS = {
    "home": "Recommend furniture/lights/fans/decor for each room and quantity requested.",
    "party": "Split the budget across catering, decoration and entertainment/venue for the event type and guest count.",
    "jewelry": "Recommend jewelry matching the occasion and style. If an outfit image is given, match its colours.",
}

def fallback(kind, data):
    b = float(data.get("budget", 0) or 0)
    return [{"name": f"Budget {kind} pick {i+1}", "category": c, "platform": "Amazon",
             "price": round(b * p), "reason": "Default suggestion (AI unavailable)."}
            for i, (c, p) in enumerate([("Essential", .4), ("Comfort", .3), ("Extra", .2)])]

def recommend(kind, data, image=None):
    prompt = (f"You are a budget assistant for Indian shoppers. {GOALS[kind]}\n"
              f"User inputs: {json.dumps(data)}\nAll prices in INR. Total of all item prices MUST NOT exceed the budget.\n"
              f"Use only these platforms: {PLATFORMS[kind]}.\n"
              'Return ONLY JSON: {"items":[{"name":"","category":"","platform":"","price":0,"reason":""}]}')
    contents = [prompt]
    if image:
        contents.append(types.Part.from_bytes(data=image[0], mime_type=image[1]))
    try:
        r = client.models.generate_content(model=MODEL, contents=contents,
            config=types.GenerateContentConfig(response_mime_type="application/json"))
        items = json.loads(re.sub(r"```json|```", "", r.text).strip())["items"]
        assert items
    except Exception as e:
        print("Gemini error:", e)
        items = fallback(kind, data)
    for i in items:
        p = str(i.get("platform", "")).split(",")[0].strip().split(" ")[0].lower()
        i["link"] = LINKS[p] + quote_plus(str(i.get("name", ""))) if p in LINKS else "#"
    return items