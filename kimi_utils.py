# kimi_utils.py
import os
import re
import openai
import json


KIMI_API_KEY = os.getenv("KIMI_API_KEY", "sk-7REwDBd0NekJccYmaDIJQ6xa7zgd3ftB1FZKdFqTPCox4YrW")  
KIMI_API_BASE = os.getenv("KIMI_API_BASE", "https://api.moonshot.cn/v1")
KIMI_MODEL = os.getenv("KIMI_MODEL", "moonshot-v1-8k")  # 可改 "moonshot-v1-32k" / "moonshot-v1-128k"


def kimi_chat(prompt: str) -> str:
    try:
        client = openai.OpenAI(api_key=KIMI_API_KEY, base_url=KIMI_API_BASE)
        resp = client.chat.completions.create(
            model=KIMI_MODEL,
            messages=[
                {"role": "system", "content": "You are an experienced instructor."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.2,
        )
        ai_raw = resp.choices[0].message.content
        print(f"Kimi raw output: {ai_raw}")  # raw response
        return ai_raw
    except Exception as e:
        print(f"Error with Kimi API: {e}")
        return ""




def build_kp_prompt(raw_text: str) -> str:
    """
    Request Kimi to provide knowledge points and concise descriptions only in plain text format.
    The output should not include JSON or any special characters, just the plain text knowledge points.
    """
    example_input = (
        "Course excerpt:\n"
        "Linear regression models a linear relationship between features and target. "
        "Common loss is least squares. Parameters can be solved by normal equation "
        "or optimized via gradient descent. Feature scaling accelerates convergence."
    )
    example_output = """
    Knowledge Points:
    1. Linear Regression: A method to model relationships between features and target variables using a linear equation.
    """
    rules = (
        "- 2–10 core knowledge points.\n"
        "- Must be exactly 2-10\n"
        "- Each knowledge point should have a concise, summarized description.\n"
        "- Descriptions should be short and focus on key aspects of the knowledge point.\n"
        "- Output should be plain text, each knowledge point on a new line, without any JSON or code block formatting."
        "- Must be less than 10 core knowledge points, must comprehensively cover the topic's foundation.\n"
    )
    return (
        "Extract knowledge points from the following text. Provide a short, concise description for each knowledge point.\n"
        f"{rules}\n\n"
        "Few-shot example (input → expected output in plain text format):\n"
        f"{example_input}\n"
        f"{example_output}\n\n"
        "Now process this text (truncate if too long):\n"
        f"{raw_text[:12000]}"
    )


def build_question_prompt(kp_name: str, kp_description: str) -> str:
    """
    Request Kimi to generate multiple-choice questions related to the given knowledge point.
    The output should only include multiple-choice questions with clear options and answers.
    """
    # 示例输入和输出，用于指导 Kimi 生成问题
    example_input = (
        "Knowledge Point: C++ Arrays\n"
        "Description: This knowledge point covers topics related to declaring and using arrays in C++.\n"
        "The question should cover array declaration, initialization, and accessing array elements."
    )
    example_output = """
       Question: What is the correct way to declare a 2D array in C++?
       A. `int array[3][4] = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12};`
       B. `int array[][] = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12};`
       C. `int array[3][4] = {{1, 2, 3, 4}, {5, 6, 7, 8}, {9, 10, 11, 12}};`
       D. `int array[3][4] = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12};`
       Answer: C
       Explanation: C uses the correct nested braces for initializing a 2D array. Options A and D attempt a flat initialization that does not conform to C++ 2D array rules, while option B is invalid because it omits the array dimensions.

       Question: How do you access the element at the second row and third column of a 2D array in C++?
       A. `array[1][2]`
       B. `array[2][3]`
       C. `array[2][2]`
       D. `array[3][2]`
       Answer: A
       Explanation: C++ arrays are zero-indexed. The second row has index 1 and the third column has index 2, so the correct access is array[1][2].
    """
    rules = (
        "- Generate **multiple-choice questions** only.\n"
        "- Each question must have four options: A, B, C, D.\n"
        "- Each question should include the correct answer clearly marked.\n"
        "- After the answer, provide a short `Explanation:` (1–6 sentences) explaining why the answer is correct.\n"
        "- Ensure that all questions are directly related to the provided knowledge point.\n"
        "- Do not include any additional commentary beyond Question/Options/Answer/Explanation."
    )
    
    return (
        "Generate multiple-choice questions related to the following knowledge point:\n"
        f"Knowledge Point: {kp_name}\n"
        f"Description: {kp_description}\n\n"
        f"{rules}\n\n"
        "Example:\n"
        f"{example_input}\n"
        f"{example_output}\n\n"
        "Now, generate multiple-choice questions (with Question, Options, Answer, and Explanation) "
        f"based on the provided knowledge point and description:\n"
        f"{kp_description}"
    )





def parse_kps_from_ai(ai_text: str):
    """
    Parse Kimi's plain text output into knowledge points and concise descriptions.
    The input is plain text, not JSON.
    """
    print(f"Parsing AI Output: {ai_text}")  # raw output
    if not ai_text.strip():
        print("Kimi returned empty output.")  # Log the empty response
        return []

    try:
        # Clean up the text and split into individual knowledge points
        ai_text = ai_text.strip()  # Remove leading/trailing whitespace
       # ai_text = ai_text.replace("\n", " ")  # Remove newlines to make sure we handle all text correctly

        # Split the text into knowledge points based on the pattern "1. Knowledge Point: Description"
        kps = []
        lines = ai_text.split("\n")
        for line in lines:
            print(f"Line: {line}")  # Debugging the individual lines
            if line.strip():  # Skip empty lines
                parts = line.split(":")
                print(f"Parts: {parts}")  # Debugging the split parts

                if len(parts) == 2:
                    name = parts[0].strip()
                    description = parts[1].strip()
                    kps.append({"name": name, "description": description})

        print(f"Parsed Knowledge Points: {kps}")  # Debugging step to check if data is correctly parsed
        return kps
    except Exception as e:
        print(f"Error parsing Kimi output: {e}")
        return []




def kimi_personal_analysis(prompt: str) -> str:

    client = openai.OpenAI(
        api_key=KIMI_API_KEY,
        base_url=KIMI_API_BASE
    )
    response = client.chat.completions.create(
        model="kimi-k2-0711-preview",
        messages=[
            {"role": "system", "content": "You are a personalized learning coach."},
            {"role": "user", "content": prompt}
        ]
    )
    return response.choices[0].message.content



def extract_questions_from_ai(ai_text: str):
    """
    Parse the AI-generated text into a list of questions.
    Each question includes:
      - Question (with options)
      - Answer
      - Explanation
    """
    result = []
    lines = ai_text.splitlines()

    question = None
    options = []
    answer = None
    explanation = None

    for line in lines:
        line = line.strip()
        if line.startswith("Question:"):
            if question and options and answer and explanation:
                # Combine question and options
                question_with_options = f"{question}\nOptions:\n" + "\n".join(options)
                result.append({
                    "question": question_with_options,
                    "answer": answer,
                    "explanation": explanation
                })

            question = line.replace("Question:", "").strip()
            options = []
            answer = None
            explanation = None

        elif line.startswith(("A.", "B.", "C.", "D.")):
            options.append(line.strip())

        elif line.startswith("Answer:"):
            answer = line.replace("Answer:", "").strip()

        elif line.startswith("Explanation:"):
            explanation = line.replace("Explanation:", "").strip()

    # Append the last question
    if question and options and answer and explanation:
        question_with_options = f"{question}\nOptions:\n" + "\n".join(options)
        result.append({
            "question": question_with_options,
            "answer": answer,
            "explanation": explanation
        })

    return result

import re

def extract_questions_from_ai_robust(ai_text: str):

    if not ai_text:
        return []

    lines = [ln.rstrip() for ln in ai_text.splitlines()]
    # 分块：按知识点切
    blocks = []
    current_kp = None
    buf = []

    def flush():
        if current_kp and buf:
            blocks.append((current_kp, "\n".join(buf)))

    for ln in lines:
        kp_match = None
        if ln.strip().startswith("Knowledge Point:"):
            kp_match = ln.split("Knowledge Point:", 1)[1].strip()
        elif ln.strip().startswith("[KP]"):
            kp_match = ln.split("]", 1)[1].strip()
        if kp_match:
            flush()
            current_kp = kp_match
            buf = []
        else:
            buf.append(ln)
    flush()

    results = []

    # 两种解析器：标准MCQ块 + 紧凑行
    def parse_block_mcq(text):
        out = []
        q = None; options = []; ans = None; expl = None
        for raw in text.splitlines():
            ln = raw.strip()
            if ln.startswith("Question:"):
                # 结束上一题
                if q and ans:
                    q_with_opt = q
                    if options:
                        q_with_opt += "\nOptions:\n" + "\n".join(options)
                    out.append({"question": q_with_opt, "answer": ans, "explanation": expl or ""})
                # 开启新题
                q = ln.replace("Question:", "", 1).strip()
                options = []; ans = None; expl = None
            elif re.match(r"^[ABCD]\.\s", ln):
                options.append(ln)
            elif ln.startswith("Answer:"):
                ans = ln.replace("Answer:", "", 1).strip()
            elif ln.startswith("Explanation:"):
                expl = ln.replace("Explanation:", "", 1).strip()
        # 收尾
        if q and ans:
            q_with_opt = q
            if options:
                q_with_opt += "\nOptions:\n" + "\n".join(options)
            out.append({"question": q_with_opt, "answer": ans, "explanation": expl or ""})
        return out

    def parse_block_compact(text):
        """
        匹配 `1) <question> Answer: X` 以及可选的 `Explanation: ...`（同行或下一行）
        """
        out = []
        # 先合并多余空行，便于相邻行 Explanation 归属
        merged = []
        for ln in text.splitlines():
            if ln.strip() != "":
                merged.append(ln.strip())
        i = 0
        while i < len(merged):
            ln = merged[i]
            m = re.match(r"^\d+\)\s*(.+?)\s*Answer:\s*([ABCD]|[^\s].*)$", ln, flags=re.IGNORECASE)
            if m:
                qtext = m.group(1).strip()
                ans = m.group(2).strip()
                expl = ""
                # 同行 Explanation
                m_inline = re.search(r"Explanation:\s*(.+)$", ln, flags=re.IGNORECASE)
                if m_inline:
                    expl = m_inline.group(1).strip()
                else:
                    # 下一行如果是 Explanation:
                    if i + 1 < len(merged) and merged[i+1].lower().startswith("explanation:"):
                        expl = merged[i+1].split(":", 1)[1].strip()
                        i += 1
                out.append({"question": qtext, "answer": ans, "explanation": expl})
            i += 1
        return out

    # 对每个块套两种解析器，合并去重
    for kp_name, block_txt in blocks:
        items = []
        items.extend(parse_block_mcq(block_txt))
        items.extend(parse_block_compact(block_txt))
        for it in items:
            it["knowledge_point"] = kp_name
            results.append(it)

    # 若压根没有识别到 Knowledge Point 块，尝试整体作为一个匿名块解析
    if not results:
        anon_items = []
        anon_items.extend(parse_block_mcq(ai_text))
        anon_items.extend(parse_block_compact(ai_text))
        for it in anon_items:
            it["knowledge_point"] = ""  # 没识别出
            results.append(it)

    return results
