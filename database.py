import firebase_admin
from firebase_admin import credentials, firestore
import json

class FirestoreManager:
    def __init__(self, cred_path: str):
        cred = credentials.Certificate(cred_path)
        firebase_admin.initialize_app(cred)
        self.db = firestore.client()
        print("Firebase initialized.")

    def dump_all_data(self):
        data = {}
        for col in self.db.collections():
            data[col.id] = [doc.to_dict() for doc in col.stream()]
        return data

    def add_user(self, name: str, report: str):
        self.db.collection("users").add({"name": name, "study_report": report})
    