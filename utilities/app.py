import streamlit as st
from openai import OpenAI
import json
import os
import base64
from dotenv import load_dotenv

# --- CONFIGURATION ---
load_dotenv()
API_KEY = os.getenv("DASHSCOPE_API_KEY")
MEMORY_FILE = "chat_history.json"

if not API_KEY:
    st.error("❌ API Key missing! Check .env file.")
    st.stop()

client = OpenAI(
    api_key=API_KEY,
    base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
)

st.title("🤖 Qwen Hackathon Builder (Unified)")
st.caption("Text + Images in ONE chat. Errors are isolated — your conversation never breaks!")

# --- MODEL SELECTOR ---
st.sidebar.header("⚙️ Settings")
model_choice = st.sidebar.selectbox(
    "Select Model",
    ["qwen-turbo", "qwen-plus", "qwen-max", "qwen-vl-plus", "qwen-vl-max"],
    index=1  # Default to qwen-plus (balanced)
)
is_vision = "vl" in model_choice

# --- SAFE IMAGE ENCODER ---
def safe_encode_image(file_obj):
    try:
        content = file_obj.read()
        if len(content) > 5 * 1024 * 1024:
            return None, "Image too large (max 5MB)"
        b64 = base64.b64encode(content).decode('utf-8')
        mime = "image/png" if file_obj.type == "image/png" else "image/jpeg"
        return f"data:{mime};base64,{b64}", None
    except Exception as e:
        return None, f"Encoding failed: {str(e)}"

# --- LOAD MEMORY ---
if os.path.exists(MEMORY_FILE):
    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            st.session_state.messages = json.load(f)
    except:
        st.session_state.messages = []
else:
    st.session_state.messages = [
        {"role": "system", "content": "You are a helpful AI assistant for a Hackathon project. You can analyze images when using VL models."}
    ]

# --- SAVE MEMORY (Safe Placeholders) ---
def save_memory():
    safe_msgs = []
    for msg in st.session_state.messages:
        if isinstance(msg["content"], list):
            safe_content = []
            for part in msg["content"]:
                if part["type"] == "image_url":
                    # Save a valid placeholder object instead of empty string
                    safe_content.append({"type": "image_url", "image_url": {"url": ""}})
                else:
                    safe_content.append(part)
            safe_msgs.append({"role": msg["role"], "content": safe_content})
        else:
            safe_msgs.append(msg)
    
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(safe_msgs, f, ensure_ascii=False, indent=2)

# --- SANITIZE MESSAGES FOR API (Remove empty image placeholders) ---
def sanitize_messages_for_api(messages):
    """Filter out messages with empty/invalid image_url before sending to API."""
    sanitized = []
    for msg in messages:
        if isinstance(msg["content"], list):
            # Keep only parts with valid content
            valid_parts = []
            for part in msg["content"]:
                if part["type"] == "image_url":
                    url = part.get("image_url", "")
                    # Normalize: handle both string and dict formats
                    if isinstance(url, dict):
                        url = url.get("url", "")
                    # Only include if URL is non-empty
                    if url and url.startswith("data:"):
                        valid_parts.append(part)
                    # else: skip empty/placeholder image parts
                else:
                    valid_parts.append(part)
            # Only include the message if it still has content after filtering
            if valid_parts:
                sanitized.append({"role": msg["role"], "content": valid_parts})
            # else: skip the whole message (it was image-only with no valid image)
        else:
            sanitized.append(msg)
    return sanitized

# --- DISPLAY HISTORY ---
for msg in st.session_state.messages:
    if msg["role"] == "system": continue
    
    with st.chat_message(msg["role"]):
        if isinstance(msg["content"], list):
            for part in msg["content"]:
                if part["type"] == "text":
                    st.markdown(part.get("text", ""))
                elif part["type"] == "image_url":
                    url = part.get("image_url", "")
                    if isinstance(url, dict): url = url.get("url", "")
                    if url and url.startswith("data:"):
                        st.image(url, width=300)
                    else:
                        st.caption(" [Image from previous session]")
        else:
            st.markdown(msg["content"])

# --- INPUT AREA ---
col1, col2 = st.columns([4, 1])
with col1:
    prompt = st.chat_input("Type..." if not is_vision else "Ask about image or type...")
with col2:
    uploaded_img = st.file_uploader("📷", type=["png","jpg","jpeg"], label_visibility="collapsed", disabled=not is_vision)

if not is_vision and uploaded_img:
    st.warning("⚠️ Switch to a 'VL' model in sidebar to use images!")

# --- PROCESS MESSAGE WITH ERROR ISOLATION ---
if prompt or (uploaded_img and is_vision):
    content = []
    
    # Handle Image
    if uploaded_img and is_vision:
        img_data, error = safe_encode_image(uploaded_img)
        if img_data:
            content.append({
                "type": "image_url",
                "image_url": {"url": img_data}
            })
            with st.chat_message("user"):
                st.image(uploaded_img, width=300)
                if prompt: st.markdown(prompt)
        else:
            # ✅ ERROR ISOLATION: Show error WITHOUT breaking chat
            st.error(f"❌ Image upload failed: {error}")
            st.info(" Try a smaller image or convert to PNG. Your chat continues below!")
            # Don't append broken message to history
    
    # Handle Text
    if prompt:
        content.append({"type": "text", "text": prompt})
    elif uploaded_img and is_vision and not prompt and content:
        content.append({"type": "text", "text": "Analyze this image in the context of our conversation."})
        with st.chat_message("user"):
            st.markdown("*Analyze this image in context.*")
    
    # Fallback for text-only
    if not content and prompt:
        content = prompt
    
    # Only append if we have valid content
    if content:
        st.session_state.messages.append({"role": "user", "content": content})
        
        with st.chat_message("assistant"):
            try:
                api_messages = sanitize_messages_for_api(st.session_state.messages)
                resp = client.chat.completions.create(
                    model=model_choice, 
                    messages=api_messages
                )
                reply = resp.choices[0].message.content
                st.markdown(reply)
                st.session_state.messages.append({"role": "assistant", "content": reply})
                save_memory()
            except Exception as e:
                # ✅ ERROR ISOLATION: Show API error WITHOUT breaking chat
                st.error(f"❌ API Error ({model_choice}): {str(e)[:200]}...")
                st.info("💡 Your message wasn't sent due to an error. Try again or switch models!")
                # Remove failed message so it doesn't block future chats
                st.session_state.messages.pop()

# --- SIDEBAR TOOLS ---
st.sidebar.divider()

# Export Chat
if st.session_state.messages:
    export_text = ""
    for m in st.session_state.messages:
        if m['role'] == 'system': continue
        role_name = "You" if m['role'] == 'user' else "Qwen"
        if isinstance(m['content'], list):
            text_parts = [p['text'] for p in m['content'] if p['type'] == 'text']
            content_str = "\n".join(text_parts) + "\n[Image attached]" if any(p['type']=='image_url' for p in m['content']) else "\n".join(text_parts)
        else:
            content_str = str(m['content'])
        export_text += f"{role_name}: {content_str}\n\n"
    
    st.sidebar.download_button(
        label="💾 Export Chat (.txt)",
        data=export_text,
        file_name="hackathon_chat.txt",
        mime="text/plain"
    )

# Clear History
if st.sidebar.button("🗑️ Clear History"):
    st.session_state.messages = [
        {"role": "system", "content": "You are a helpful AI assistant for a Hackathon project. You can analyze images when using VL models."}
    ]
    if os.path.exists(MEMORY_FILE): os.remove(MEMORY_FILE)
    st.rerun()

