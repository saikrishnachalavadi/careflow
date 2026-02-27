import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

from langchain_google_genai import ChatGoogleGenerativeAI

# Initialize Gemini (LangSmith will auto-trace if env vars are set)
llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    google_api_key=os.getenv("GOOGLE_API_KEY")
)

print("Testing Gemini + LangSmith connection...\n")

# Test 1: Simple response
response = llm.invoke("Say 'CareFlow is ready!' in a friendly way")
print("✅ Gemini Response:")
print(response.content)

# Test 2: Medical context (to simulate CareFlow)
print("\n" + "="*50 + "\n")
medical_response = llm.invoke(
    "You are a medical triage assistant. A user says: 'I have a mild headache since morning.' "
    "Respond in 2 sentences max. Do not diagnose, just acknowledge and suggest next step."
)
print("✅ Medical Triage Test:")
print(medical_response.content)

print("\n" + "="*50)
print("🎯 Check LangSmith dashboard: https://smith.langchain.com")
print("   Project: careflow")