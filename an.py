import os
from anthropic import Anthropic

client = Anthropic(
    api_key="sk-cwpbh4s1lcm4vc61wzkeq2k2n1mkq6yu99u97e1q839ernhp",
    base_url="https://api.xiaomimimo.com/anthropic"
)

message = client.messages.create(
    model="mimo-v2.6-pro",
    max_tokens=1024,
    system="You are MiMo, an AI assistant developed by Xiaomi. Today is date: Tuesday, December 16, 2025. Your knowledge cutoff date is December 2024.",
    messages=[
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": "please introduce yourself"
                }
            ]
        }
    ],
    top_p=0.95,
    stream=False,
    temperature=1.0,
    stop_sequences=None
)

print(message.content)