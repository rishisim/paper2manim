from dotenv import load_dotenv
load_dotenv()
from google import genai
from google.genai import types
from agents.coder import _build_config, MODEL_NAME

client = genai.Client()
chat = client.chats.create(model=MODEL_NAME, config=_build_config())
print(f"Testing {MODEL_NAME} with tools...")
try:
    response = chat.send_message("Draw a red square. Look up the docs for Square first.")
    print("Response text:", repr(response.text))
except Exception as e:
    print(f"Exception: {e}")
