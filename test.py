import os
import sys
import textwrap
from typing import List
from dotenv import load_dotenv
from rapidfuzz import fuzz
from openai import OpenAI

from db import fire_db
from user import User

DEEPSEEK_CHAT_MODEL = os.getenv("DEEPSEEK_CHAT_MODEL", "deepseek-chat")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "sk-61cf109d660d4ba6a9d80ebf38737f06")

db = fire_db()
print("start")
wrong_questions_ref = db.read_wq('users', "1", 'wrong_questions')
keypoints = wrong_questions_ref.stream()

# 遍历流中的每个知识点文档
for keypoint_doc in keypoints:
    keypoint_name = keypoint_doc.id  # 获取知识点名称
    print(f"Knowledge Point: {keypoint_name}")

    # 获取当前知识点下的错题集合
    questions_ref = keypoint_doc.reference.collection('questions')
    questions = questions_ref.stream()

    # 遍历当前知识点下的每个错题文档
    for question_doc in questions:
        question_data = question_doc.to_dict()  # 将文档数据转换为字典
        print(f"  Question ID: {question_doc.id}")
        print(f"    User Answer: {question_data.get('user_answer', '')}")
        print(f"    Standard Answer: {question_data.get('std_answer', '')}")
        print(f"    Other Data: {question_data}")
#print("done")
