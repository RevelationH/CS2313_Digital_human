from openai import OpenAI

class moonshot_agent():
    def __init__(self):
        self.client = OpenAI(
            api_key="sk-7REwDBd0NekJccYmaDIJQ6xa7zgd3ftB1FZKdFqTPCox4YrW",  # 在这里将 MOONSHOT_API_KEY 替换为你从 Kimi 开放平台申请的 API Key
            base_url="https://api.moonshot.cn/v1",
        )

    def answer(self, question):
        completion = self.client.chat.completions.create(
            model="moonshot-v1-8k",
            messages=[
                {"role": "user",
                "content": question}
            ],
            temperature=0.3,
        )

        return completion.choices[0].message.content
