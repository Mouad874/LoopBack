import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

# Load API key from environment variable
API_KEY = os.getenv("DASHSCOPE_API_KEY")

client = OpenAI(
    api_key=API_KEY,
    base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
)

print("💬 Welcome to Qwen Chat! Type 'quit' or 'exit' to stop.\n")

messages = [
    {"role": "system", "content": "You are a helpful assistant for a Hackathon project."}
]

while True:
    user_input = input("You: ")
    
    if user_input.lower() in ["quit", "exit"]:
        print("Goodbye!")
        break
        
    messages.append({"role": "user", "content": user_input})
    
    try:
        response = client.chat.completions.create(
            model="qwen-turbo",
            messages=messages
        )
        
        reply = response.choices[0].message.content
        print(f"Qwen: {reply}\n")
        
        messages.append({"role": "assistant", "content": reply})
        
    except Exception as e:
        print(f"❌ Error: {e}")
        break
