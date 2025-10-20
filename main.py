from openai import OpenAI
import base64
import os
import glob
from dotenv import load_dotenv

load_dotenv(override=True)

client = OpenAI()
SCREENSHOT_PATH = r"C:\Users\hudi\Pictures\Screenshots\*"

screenshot_files = glob.glob(SCREENSHOT_PATH)

latest_file = max(screenshot_files, key=os.path.getctime)

with open(latest_file, "rb") as f:
    img_base64 = base64.b64encode(f.read()).decode("utf-8")

response = client.responses.create(
    model="gpt-5",
    input=[
        {
            "role": "user",
            "content": [
                {
                    "type": "input_text",
                    "text": "Welche der antwortmöglichkeiten sind richtig (Es können mehrere richtig sein)",
                },
                {
                    "type": "input_image",
                    "image_url": f"data:image/png;base64,{img_base64}"
                }
            ]
        }
    ]
)

print(response.output_text)