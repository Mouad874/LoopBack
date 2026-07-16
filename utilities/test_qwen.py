import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

# Load API key from environment variable
API_KEY = os.getenv("DASHSCOPE_API_KEY")

client = OpenAI(
    api_key=API_KEY,
    # IMPORTANT: Use the correct URL for your region
    base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
)

try:
    print("Testing Qwen API connection...")
    
    completion = client.chat.completions.create(
        model="qwen-turbo",  # Cheapest model, good for testing
        messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Say hello and confirm this API test worked!"}
        ]
    )
    
    print("\n✅ SUCCESS! Qwen responded:")
    print(completion.choices[0].message.content)
    
except Exception as e:
    print(f"\n❌ ERROR: {e}")
    print("Check your API key and base_url!")
