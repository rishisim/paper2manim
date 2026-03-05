import os
from dotenv import load_dotenv
load_dotenv()

from google import genai
from google.genai import types

def get_time() -> str:
    """Returns the current time."""
    return "The time is 12:00 PM."

client = genai.Client()
config = types.GenerateContentConfig(
    tools=[get_time],
    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    temperature=0.0
)
chat = client.chats.create(model="gemini-3.1-pro-preview", config=config)
response = chat.send_message("What time is it in your timezone? Use the get_time tool. Also, give me a python script to print the time.")

print("First response parts:")
if response.candidates:
    for p in response.candidates[0].content.parts:
        print(" ", p)

if response.function_calls:
    tool_responses = []
    for fc in response.function_calls:
        print(f"Executing {fc.name}...")
        res = "The time is 1:00 PM via manual tool"
        tool_responses.append(
            types.Part.from_function_response(name=fc.name, response={"result": res})
        )
    print("Sending tool response...")
    response2 = chat.send_message(tool_responses)
    print("Final text:", response2.text)
else:
    print("No function calls. Text:", response.text)
