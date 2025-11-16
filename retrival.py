import os
import sys
import re
import textwrap
from typing import List
from dotenv import load_dotenv
from rapidfuzz import fuzz
from openai import OpenAI

from db import fire_db
from user import User
from rag import rag
from quiz_app import QuizApp

from kimi_utils import kimi_personal_analysis, kimi_chat, build_kp_prompt, build_question_prompt, extract_questions_from_ai, parse_kps_from_ai
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, abort
from langchain_deepseek import ChatDeepSeek

DEEPSEEK_CHAT_MODEL = os.getenv("DEEPSEEK_CHAT_MODEL", "deepseek-chat")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "sk-61cf109d660d4ba6a9d80ebf38737f06")

class re_and_exc():
    def __init__(self, user : User, shared_rag=None):

        load_dotenv()
        """
        self.INTENT_KB = {
            "LEARNING_REPORT": {
                "must_any": [
                    "learning report", "study report", "study summary", "study review",
                    "weekly report", "monthly report", "reflection", "progress report",
                    "study log", "learning recap"
                ],
                "verbs": ["output", "generate", "write", "create", "export", "summarize", "compile"],
            }
            
            "LESSON_POINTS": {
                "must_any": [
                    "lesson points", "this lesson", "class points", "key points",
                    "knowledge points", "summary of lesson", "lesson outline", "course outline"
                ],
                "verbs": ["output", "list", "summarize", "extract", "enumerate", "compile"],
            }
            
        }
        """
        

        self.USE_LLM_FALLBACK = True
        self.LLM_FALLBACK_THRESHOLD = 55

        self.client = OpenAI(
            api_key=DEEPSEEK_API_KEY or None,
            base_url=DEEPSEEK_BASE_URL
        )

        self.SYSTEM_PROMPT = (
            "You are a helpful study assistant.\n"
            "If uncertain, say so and give possible directions."
        )

        self.history = []

        self.fdb = fire_db()

        self.answer = [None, None]

        self.user = user

        self.analysis = learning_report(user)

        # 使用共享 RAG 实例（如果提供）或创建新的（向后兼容）
        if shared_rag is not None:
            self.course_rag = shared_rag
        else:
            self.course_rag = rag(DEEPSEEK_API_KEY)

        self.model = "deepseek-chat"

        #self.intent = intent(User)

    def _score_intent(self, text, intent):
        """Return similarity score (0–100)."""
        kb = self.INTENT_KB[intent]
        base = 0
        for kw in kb["must_any"]:
            base = max(base, fuzz.partial_ratio(kw, text))

        verb_bonus = 0
        for v in kb["verbs"]:
            if v in text:
                verb_bonus += 6
                if verb_bonus >= 18:
                    break

        length_penalty = 0
        if len(text) < 4 or len(text) > 120:
            length_penalty = 5

        return max(0, min(100, base + verb_bonus - length_penalty))

    def _llm_intent_fallback(self, user_input):
        """classify intent via LLM into LEARNING_REPORT / QUIZ / NORMAL_CHAT."""
        try:
            prompt = (
                "You are classifying the user's intent for a C++ course assistant.\n"
                "You MUST output exactly one label: LEARNING_REPORT, QUIZ, NORMAL_CHAT.\n\n"
                "- LEARNING_REPORT: ONLY if the user explicitly asks for a study/learning report or overall learning summary "
                "(e.g., 'show me my learning report', 'generate my study summary for this course').\n"
                "- QUIZ: if the user clearly wants to practice, take a quiz, do exercises, or test themselves.\n"
                "- NORMAL_CHAT: for everything else, including asking concepts, explaining code, etc.\n\n"
                f"User input: {user_input}\n"
                "Label:"
            )
            resp = self.client.chat.completions.create(
                model=DEEPSEEK_CHAT_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=5,
            )
            tag = (resp.choices[0].message.content or "").strip().upper()
            if tag in {"LEARNING_REPORT", "QUIZ", "NORMAL_CHAT"}:
                return tag
        except Exception:
            pass
        return "NORMAL_CHAT"

    def route_intent(self, user_input):
        """Route intent using fuzzy scores + optional LLM fallback."""
        s = user_input.strip().lower()

        scores = {
            "LEARNING_REPORT": self._score_intent(s, "LEARNING_REPORT"),
            "LESSON_POINTS": self._score_intent(s, "LESSON_POINTS"),
        }
        best_intent = max(scores, key=scores.get)
        best_score = scores[best_intent]

        THRESH = 70
        if best_score >= THRESH:
            return best_intent

        if self.USE_LLM_FALLBACK and best_score <= self.LLM_FALLBACK_THRESHOLD:
            return self._llm_intent_fallback(user_input)

        return "NORMAL_CHAT"

    def build_messages(self, user_input, history):
        messages = [{"role": "system", "content": self.SYSTEM_PROMPT}]
        for turn in history[-8:]:
            messages.append(turn)
        messages.append({"role": "user", "content": user_input})
        return messages

    def chat_with_model(self, system_prompt):
        try:
            # 确保 messages 是列表格式，而不是字符串
            if isinstance(system_prompt, str):
                # 如果传入的是字符串，转换为正确的消息格式
                messages = [
                    {"role": "system", "content": system_prompt}
                ]
            elif isinstance(system_prompt, list):
                # 如果已经是列表格式，直接使用
                messages = system_prompt
            else:
                # 其他情况转换为字符串
                messages = [
                    {"role": "system", "content": str(system_prompt)}
                ]
        
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=messages,  # 这里应该是列表，不是字符串
                stream=False,
            )
            return resp.choices[0].message.content

        except Exception as e:
            print(f"Error in chat_with_model: {e}")
            return f"Sorry, I encountered an error: {str(e)}"

    def generate_learning_report(self, user_input, history):
        #docs = self.fdb.read_wq(user="1")
        print("成功进入generate_learning_report！")
        report, question = self.analysis.ai_analysis()
        return report
        #print("report:", report)
        #print("question:", question)
        #print(docs)


        return "generate learning report"

    def list_lesson_points(self, user_input, history):
        #docs = self.fdb.read_wq(user="1")
        print("成功进入list_lesson_points！")
        out = self.course_rag.rag_answer(question=user_input)
        return out["answer"]

    def user_answer(self, user_input, intent):
        #intent = self.intent.route_intent(user_input)
        print("intent:", intent)
        if intent == "LEARNING_REPORT":
            answer = self.generate_learning_report(user_input, self.history)
        elif intent == "NORMAL_CHAT":
            answer = self.course_rag.rag_answer(question=user_input)
        elif intent == "QUIZ":
            system_prompt = (
                "You are a virtual digital human who speaks English. Now, a user wants to take a test, and you need to tell them you are ready and ask them to follow the instructions on the webpage."
                "This response should be very brief, simply prompting the user to view the webpage content."
            )
            
            answer = self.chat_with_model(system_prompt)
        else:
            system_prompt = (
                "You are a virtual, English-speaking digital human. You don't understand what the user is saying now."
                "You want the user to say it again."
                "This answer should be very brief."
            )
            # 构建消息列表
            messages = [{"role": "system", "content": system_prompt}]
            answer = self.chat_with_model(messages)

        return answer

class learning_report():
    def __init__(self, user : User):
        self.fdb = fire_db()
        self.user = user
        self.username = str(user.username)
        print("self.username:", self.username)
    
    def ai_analysis(self):
        print("start analysis")
        wrong_questions_ref = self.fdb.read_wq('users', self.username, 'wrong_questions')
        keypoints = list(wrong_questions_ref.stream())
        print(f"[debug] user={self.username} keypoints_count={len(keypoints)}")
        kp_stats = {} 
        weak_points = []  

        for idx, keypoint_doc in enumerate(keypoints):
            keypoint_name = keypoint_doc.id  
            print(f"[debug] keypoint[{idx}]={keypoint_name}")

            questions_ref = keypoint_doc.reference.collection('questions')
            questions = list(questions_ref.stream())
            print(f"[debug]   questions_count={len(questions)}")

            wrong_count = 0

            for q_idx, question_doc in enumerate(questions):
                question_data = question_doc.to_dict()
                print(f"[debug]     question[{q_idx}] data={question_data}")
                user_answer = question_data.get('user_answer', '').strip()
                std_answer = question_data.get('std_answer', '').strip()

                if user_answer != std_answer:
                    wrong_count += 1

            if wrong_count > 0:
                kp_stats[keypoint_name] = {
                    'wrong': wrong_count 
                }


                if wrong_count >= 3:  
                    weak_points.append(keypoint_name)

        user_data = {
            "user_id": self.username,
            "knowledge_points": kp_stats,   
            "weak_points": weak_points
        }

        """
        prompt = (
            "You are a personalized learning coach for C++ programming course. "
            "Based on the following student knowledge point data (in JSON), analyze the student's weak areas, "
            "give concrete suggestions for improvement, and generate 1 to 3 targeted practice questions with answers for each weak knowledge point. Those question should be corresponding to the C++ programming course"
            "Questions should be relevant to the original knowledge points."
            "Please pay attention to the format of the generated answers; different content should be on a separate line."
            "\n\nStudent answer data:\n"
            f"{user_data}\n"
        )
        """

        prompt = (
            "Please enter standard Markdown format that can be correctly processed by marked.min.js, and do not add unnecessary line breaks."
            "You are a personalized learning coach for C++ programming course. Based on the following student knowledge point data (in JSON), analyze the student's weak areas, give concrete suggestions for improvement, and generate 1 to 3 targeted practice questions with answers for each weak knowledge point. Those question should be corresponding to the C++ programming course."
            "Questions should be relevant to the original knowledge points."
            "Please format your response with clear line breaks and sections. Use the following structure exactly: Weak-area Analysis"
            "## Concrete Improvement Suggestions:"
            "1. [Suggestion 1]"
            "2. [Suggestion 2]"
            "3. [Suggestion 3]"
    
            "## Targeted Practice Questions"
            "Knowledge Point: [Knowledge Point Name]"
            "Question 1: [Question text]"
            "Answer: [Answer]"
            "Question 2: [Question text]"
            "Answer: [Answer]"
            "Question 3: [Question text]"
            "Answer: [Answer]"
    
            "Student answer data:"
            f"{user_data}"
        )


        analysis_text = kimi_personal_analysis(prompt)
    
        questions_ai = extract_questions_from_ai(analysis_text)

        analysis_text = re.sub(r'([.!?])', r'\1\n', analysis_text)

        # 返回分析结果及推荐题目
        text_questions = []
        for q in questions_ai:
            if isinstance(q, dict):
                text_questions.append(q["question"] + " Answer: " + q["answer"])
            else:
                text_questions.append(str(q))

        return analysis_text, text_questions


class intent():
    def __init__(self, user : User):
        self.INTENT_KB = {
            "LEARNING_REPORT": {
                "must_any": [
                    "learning report", "study report", "study summary", "study review",
                    "weekly learning report", "learning recap"
                ],
                "verbs": ["output", "generate", "write", "create", "export", "summarize", "compile"],  
            },
            "QUIZ": {
                "must_any": [
                    "quiz", "exercise", "practice"
                ],
                "verbs": ["take", "do"],  
            },
        }
        
        self.USE_LLM_FALLBACK = True
        self.LLM_FALLBACK_THRESHOLD = 55
    
    def _score_intent(self, text, intent):
        """Return similarity score (0–100)."""
        kb = self.INTENT_KB[intent]
        base = 0
        for kw in kb["must_any"]:
            base = max(base, fuzz.partial_ratio(kw, text))

        verb_bonus = 0
        for v in kb["verbs"]:
            if v in text:
                verb_bonus += 6
                if verb_bonus >= 18:
                    break

        length_penalty = 0
        if len(text) < 4 or len(text) > 120:
            length_penalty = 5

        return max(0, min(100, base + verb_bonus - length_penalty))

    def _llm_intent_fallback(self, user_input):
        """classify intent via LLM into LEARNING_REPORT / LESSON_POINTS / NORMAL_CHAT."""
        try:
            prompt = (
                "You are classifying the user's intent for a C++ course assistant.\n"
                "You MUST output exactly one label: LEARNING_REPORT, QUIZ, NORMAL_CHAT.\n\n"
                "- LEARNING_REPORT: ONLY if the user explicitly asks for a study/learning report or overall learning summary "
                "(e.g., 'show me my learning report', 'generate my study summary for this course').\n"
                "- QUIZ: if the user clearly wants to practice, take a quiz, do exercises, or test themselves.\n"
                "- NORMAL_CHAT: for everything else, including asking concepts, explaining code, etc.\n\n"
                f"User input: {user_input}\n"
                "Label:"
            )
            resp = self.client.chat.completions.create(
                model=DEEPSEEK_CHAT_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=5,
            )
            tag = (resp.choices[0].message.content or "").strip().upper()
            if tag in {"LEARNING_REPORT", "QUIZ", "NORMAL_CHAT"}:
                return tag
        except Exception:
            pass
        return "NORMAL_CHAT"

    def route_intent(self, user_input):
        """Route intent using fuzzy scores + optional LLM fallback."""
        s = user_input.strip().lower()

        scores = {
            "LEARNING_REPORT": self._score_intent(s, "LEARNING_REPORT"),
            "QUIZ": self._score_intent(s, "QUIZ")
        }
        best_intent = max(scores, key=scores.get)
        best_score = scores[best_intent]

        THRESH = 75
        if best_score >= THRESH:
            return best_intent

        if self.USE_LLM_FALLBACK and best_score <= self.LLM_FALLBACK_THRESHOLD:
            return self._llm_intent_fallback(user_input)

        return "NORMAL_CHAT"

class avatar_text():
    def __init__(self, user : User):
        self.client = OpenAI(
            api_key=DEEPSEEK_API_KEY or None,
            base_url=DEEPSEEK_BASE_URL
        )

        self.llm = self.get_llm(model="deepseek-chat")

    def get_llm(self, model: str = "deepseek-chat", temperature: float = 0.2) -> ChatDeepSeek:
        # 需要 DEEPSEEK_API_KEY
        # deepseek-chat 为 V3.1 的非思考模式, 响应更快
        # deepseek-reasoner 为思考模式, 更长上下文与推理能力, 但不支持工具调用
        # 参考官方文档与 LangChain 集成说明
        return ChatDeepSeek(model=model, temperature=temperature)


    def chat_with_model(self, user_input, history):
        messages = self.build_messages(user_input, history)
        resp = self.client.chat.completions.create(
            model=DEEPSEEK_CHAT_MODEL,
            messages=messages,
            temperature=0.3,
        )
        return resp.choices[0].message.content
    
    def user_answer(self, user_input, intent):
        #intent = self.intent.route_intent(user_input)
        if intent == "NORMAL_CHAT" or "QUIZ":
            system_prompt = (
                "You are a virtual, English-speaking digital human. Now, a user has entered some text, and you need to translate that text into everyday, conversational English, but try not to change the content provided by the user."

                "This means you need to remove or transform redundant characters in the text."

                "For example, changing the % to 'percent,' etc., so that the digital human can express itself better when outputting speech."
            )

            user_prompt = (
                f"Question:\n{user_input}\n\n"
            )

            messages = [("system", system_prompt), ("human", user_prompt)]

            resp = self.llm.invoke(messages)
        
        if intent == "LEARNING_REPORT":
            system_prompt = (
                "You are a virtual, English-speaking digital human. Now, you need to tell the user that you have generated a learning report for him and ask him to browse it."
                "The reply should be very brief, just prompting the user to view the study report."
            )

            resp = self.llm.invoke(system_prompt)

        return resp.content


    




