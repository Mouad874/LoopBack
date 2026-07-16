import streamlit as st
from openai import OpenAI
import base64
import os
from dotenv import load_dotenv

# --- CONFIGURATION ---
load_dotenv()
API_KEY = os.getenv("DASHSCOPE_API_KEY")

if not API_KEY:
    st.error("❌ API Key missing! Check .env file.")
    st.stop()

client = OpenAI(
    api_key=API_KEY,
    base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
)

st.title("📸 Screenshot Analyzer (Isolated)")
st.caption("Upload any screenshot for AI analysis. Errors here won't affect your main chat!")

# --- SAFE IMAGE ENCODER ---
def safe_encode_image(file_obj):
    """Returns (base64_string, mime_type) or (None, error_msg)"""
    try:
        content = file_obj.read()
        if len(content) > 5 * 1024 * 1024:  # 5MB limit
            return None, "Image too large (max 5MB)"
        
        b64 = base64.b64encode(content).decode('utf-8')
        mime = "image/png" if file_obj.type == "image/png" else "image/jpeg"
        return b64, mime
    except Exception as e:
        return None, f"Encoding failed: {str(e)}"

# --- ANALYSIS PROMPT TEMPLATES ---
PROMPTS = {
    "general": "Analyze this screenshot in detail. Describe what you see, identify UI elements, text, and potential issues.",
    "debug": "This is a screenshot of an error or bug. Identify the exact error message, explain what caused it, and provide step-by-step fix instructions.",
    "ui_ux": "Review this UI screenshot. Evaluate layout, readability, color contrast, and accessibility. Suggest specific improvements.",
    "code_review": "This screenshot contains code. Transcribe it accurately, then review for bugs, security issues, and optimization opportunities."
}

# --- SIDEBAR CONTROLS ---
st.sidebar.header("️ Analysis Settings")
analysis_type = st.sidebar.selectbox(
    "Analysis Type",
    list(PROMPTS.keys()),
    format_func=lambda x: x.replace("_", " ").title()
)

custom_prompt = st.sidebar.text_area(
    "Custom Instructions (Optional)",
    placeholder="Add specific questions about this screenshot...",
    height=100
)

# --- MAIN UPLOAD AREA ---
uploaded_file = st.file_uploader(
    "Drop your screenshot here",
    type=["png", "jpg", "jpeg"],
    help="Max 5MB • PNG/JPG only"
)

if uploaded_file:
    # Preview immediately
    st.image(uploaded_file, caption=f"📎 {uploaded_file.name}", width=400)
    
    # Encode with safety checks
    b64_img, mime_type = safe_encode_image(uploaded_file)
    
    if b64_img is None:
        st.error(f"❌ {mime_type}")
    else:
        # Build analysis prompt
        system_prompt = PROMPTS[analysis_type]
        user_text = custom_prompt.strip() if custom_prompt.strip() else "Please analyze this screenshot."
        
        full_prompt = f"{system_prompt}\n\nUser request: {user_text}"
        
        # Prepare API payload
        messages = [
            {"role": "system", "content": "You are an expert screenshot analyst. Be precise, structured, and actionable."},
            {"role": "user", "content": [
                {"type": "text", "text": full_prompt},
                {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{b64_img}"}}
            ]}
        ]
        
        # Run analysis with clear loading state
        with st.spinner(" Analyzing screenshot..."):
            try:
                response = client.chat.completions.create(
                    model="qwen-vl-max",
                    messages=messages,
                    temperature=0.3  # Lower temp = more precise analysis
                )
                
                result = response.choices[0].message.content
                
                # Display results in clean sections
                st.success("✅ Analysis Complete!")
                st.divider()
                st.markdown(result)
                
                # Copy button for easy sharing
                st.code(result, language="markdown")
                
            except Exception as e:
                error_msg = str(e)
                st.error(f"❌ Analysis Failed")
                
                # Smart error guidance
                if "400" in error_msg and "image_url" in error_msg.lower():
                    st.warning("""
                    ⚠️ **Image Format Issue Detected**
                    - Try converting to PNG first
                    - Ensure file isn't corrupted
                    - Check if file size < 5MB
                    """)
                elif "429" in error_msg:
                    st.warning("⏳ Rate limited. Wait 30 seconds and retry.")
                elif "401" in error_msg:
                    st.error("🔑 Invalid API key. Check your .env file.")
                else:
                    st.code(error_msg, language="json")
                    
                # Provide manual fallback
                st.info(" **Fallback**: Describe what's in the screenshot below, and I'll help troubleshoot based on your description.")
