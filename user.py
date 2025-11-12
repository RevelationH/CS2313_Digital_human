from db import fire_db
from firebase_admin import credentials, firestore

class User:
    def __init__(self, username, password, is_admin=False):
        self.username = username
        self.password = password
        self.is_admin = is_admin
        self.fdb = fire_db()

    def save(self):
        self.fdb.collection('users').document(self.username).set({
            'username': self.username,
            'password': self.password,
            'is_admin': self.is_admin
        })

    @classmethod
    def get_by_username(cls, username):
        """类方法：通过用户名获取用户"""
        # 创建临时实例来访问fdb
        temp_user = cls(username, "")  # 密码设为空字符串
        doc = temp_user.fdb.read_doc('users', username)
        if doc.exists:
            data = doc.to_dict()
            return cls(data['username'], data['password'], data.get('is_admin', False))
        return None

    def add_wrong_answer(self, question, std_answer, user_answer, timestamp, keypoint):
        wrong_answer_data = {
            "question": question,
            "std_answer": std_answer,
            "user_answer": user_answer,
            "timestamp": timestamp
        }

        self.fdb.collection('users').document(self.username) \
            .collection('wrong_questions') \
            .document(keypoint) \
            .collection('questions') \
            .add(wrong_answer_data)