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

    def get_by_username(self, username):
        #doc = self.fdb_client.collection('users').document(username).get()
        doc = self.fdb.read_doc('users', username)
        if doc.exists:
            data = doc.to_dict()
            return User(data['username'], data['password'], data.get('is_admin', False))
        return None

    def add_wrong_answer(self, question, std_answer, user_answer, timestamp, keypoint):
        wrong_answer_data = {
            "question": question,
            "std_answer": std_answer,
            "user_answer": user_answer,
            "timestamp": timestamp
        }

        self.db.collection('users').document(self.username) \
            .collection('wrong_questions') \
            .document(keypoint) \
            .collection('questions') \
            .add(wrong_answer_data)

