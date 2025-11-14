# scripts/view_user_wrongbook.py
import os
import sys

# 确保可以从项目根目录导入模块
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from db import fire_db

def view_wrongbook(username: str):
    db = fire_db()
    wrong_questions_ref = db.collection('users').document(username).collection('wrong_questions')
    keypoints = wrong_questions_ref.stream()

    print(f"== Wrongbook of user '{username}' ==")
    empty = True

    for kp_doc in keypoints:
        kp_name = kp_doc.id
        questions_ref = kp_doc.reference.collection('questions')
        questions = list(questions_ref.stream())

        if not questions:
            continue

        empty = False
        print(f"\nKnowledge Point: {kp_name} ({len(questions)} records)")

        for q_doc in questions:
            data = q_doc.to_dict() or {}
            print("  - Question :", data.get('question'))
            print("    Std Ans  :", data.get('std_answer'))
            print("    User Ans :", data.get('user_answer'))
            print("    Time     :", data.get('timestamp'))
            print("    List ID  :", data.get('list_id'))
            print()

    if empty:
        print("No wrong questions found.")

if __name__ == "__main__":
    view_wrongbook("dya")