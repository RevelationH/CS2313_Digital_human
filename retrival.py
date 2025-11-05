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

DEEPSEEK_CHAT_MODEL = os.getenv("DEEPSEEK_CHAT_MODEL", "deepseek-chat")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "sk-61cf109d660d4ba6a9d80ebf38737f06")

class re_and_exc():
    def __init__(self, user : User):

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

        self.course_rag = rag(DEEPSEEK_API_KEY)

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
        """classify intent via LLM into LEARNING_REPORT / LESSON_POINTS / NORMAL_CHAT."""
        try:
            prompt = (
                "Classify the user query into exactly one of: LEARNING_REPORT, LESSON_POINTS, NORMAL_CHAT.\n"
                "- LESSON_POINTS only if the user BOTH refers to a specific lesson scope (e.g., 'this lesson', 'Unit 3', 'today's class') "
                "AND explicitly asks for a list/outline of points.\n"
                "- LEARNING_REPORT if asking for a learning/study report/summary.\n"
                "- Otherwise NORMAL_CHAT. Output only the label.\n\n"
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
            if tag in {"LEARNING_REPORT", "LESSON_POINTS", "NORMAL_CHAT"}:
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

        THRESH = 68
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

    def chat_with_model(self, user_input, history):
        messages = self.build_messages(user_input, history)
        resp = self.client.chat.completions.create(
            model=DEEPSEEK_CHAT_MODEL,
            messages=messages,
            temperature=0.3,
        )
        return resp.choices[0].message.content

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

        """
        try:
            if intent == "LEARNING_REPORT":
                answer = self.generate_learning_report(user_input, self.history)
            elif intent == "LESSON_POINTS":
                answer = self.list_lesson_points(user_input, self.history)

            elif intent == "NORMAL_CHAT":
                answer = self.chat_with_model(user_input, self.history)
                #print("\nAssistant:", textwrap.fill(answer, width=80))
                self.history.append({"role": "user", "content": user_input})
                self.history.append({"role": "assistant", "content": answer})
            
            else:
                answer = "I may not understand what you said, could you please say it again?"

        except Exception as e:
            answer = "Sorry, there seems to be some problem with my system, please contact the developer!"
        """
        if intent == "LEARNING_REPORT":
            answer = self.generate_learning_report(user_input, self.history)
        elif intent == "NORMAL_CHAT":
            """
            answer = self.chat_with_model(user_input, self.history)
            #print("\nAssistant:", textwrap.fill(answer, width=80))
            self.history.append({"role": "user", "content": user_input})
            self.history.append({"role": "assistant", "content": answer})
            """
            answer = self.course_rag.rag_answer(question=user_input)
        else:
            answer = "I may not understand what you said, could you please say it again?"

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
        keypoints = wrong_questions_ref.stream()  
        kp_stats = {} 
        weak_points = []  

        for keypoint_doc in keypoints:
            keypoint_name = keypoint_doc.id  

            questions_ref = keypoint_doc.reference.collection('questions')
            questions = questions_ref.stream()

            wrong_count = 0

            for question_doc in questions:
                question_data = question_doc.to_dict()
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
            "You are a personalized learning coach. "
            "Based on the following student knowledge point data (in JSON), analyze the student's weak areas, "
            "give concrete suggestions for improvement, and generate 3 targeted practice questions with answers for each weak knowledge point. "
            "Questions should be relevant to the original knowledge points."
            "Please pay attention to the format of the generated answers; different content should be on a separate line."
            "\n\nStudent answer data:\n"
            f"{user_data}\n"
        )
        """

        prompt = (
            "You are a personalized learning coach. "
            "Based on the following student knowledge point data (in JSON), analyze the student's weak areas, "
            "give concrete suggestions for improvement, and generate 3 targeted practice questions with answers for each weak knowledge point. "
            "Questions should be relevant to the original knowledge points.\n\n"
    
            "Please format your response with clear line breaks and sections. Use the following structure exactly:\n\n"
    
            "Weak-area Analysis\n"
            "[Your analysis here - use multiple lines if needed]\n\n"
    
            "Concrete Improvement Suggestions\n"
            "1. [Suggestion 1]\n"
            "2. [Suggestion 2]\n"
            "3. [Suggestion 3]\n\n"
    
            "Targeted Practice Questions\n"
            "Knowledge Point: [Knowledge Point Name]\n"
            "Question 1: [Question text]\n"
            "Answer: [Answer]\n\n"
            "Question 2: [Question text]\n"
            "Answer: [Answer]\n\n"
            "Question 3: [Question text]\n"
            "Answer: [Answer]\n\n"
    
            "Student answer data:\n"
            f"{user_data}\n"
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
                    "weekly report", "monthly report", "reflection", "progress report",
                    "study log", "learning recap"
                ],
                "verbs": ["output", "generate", "write", "create", "export", "summarize", "compile"],  
            },
            "QUIZ": {
                "must_any": [
                    "quiz"
                ],
                "verbs": ["output", "generate", "write", "create", "export", "summarize", "compile"],  
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
                "Classify the user query into exactly one of: LEARNING_REPORT, NORMAL_CHAT.\n"
                "- LESSON_POINTS only if the user BOTH refers to a specific lesson scope (e.g., 'this lesson', 'Unit 3', 'today's class') "
                "AND explicitly asks for a list/outline of points.\n"
                "- Otherwise NORMAL_CHAT. Output only the label.\n\n"
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

        THRESH = 68
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

        self.SYSTEM_PROMPT = (
            "You are a helpful study assistant.\n"
            "If uncertain, say so and give possible directions."
        )

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
        answer = "OK, I am generating a learning report"

        return answer


    




