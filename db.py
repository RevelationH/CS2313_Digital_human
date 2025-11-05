import json
import firebase_admin
from firebase_admin import credentials, firestore
from google.api_core.datetime_helpers import DatetimeWithNanoseconds

if not firebase_admin._apps:
    cred = credentials.Certificate(
        r'./quizsite-fb97c-firebase-adminsdk-fbsvc-76a794e54f.json'
    )
if not firebase_admin._apps:
    firebase_admin.initialize_app(cred)

print("database activate!!!!")


class fire_db():
    def __init__(self):
        self.db = firestore.client()
    
    # 添加缺失的方法以兼容原始代码
    def collection(self, collection_name):
        """直接访问集合"""
        return self.db.collection(collection_name)
    
    def collection_group(self, collection_name):
        """访问集合组"""
        return self.db.collection_group(collection_name)
    
    def document(self, collection_name, doc_name):
        """访问文档"""
        return self.db.collection(collection_name).document(doc_name)

    # 保留原有方法
    def read_wq(self, collection_1, username, collection_2):
        wq_doc = self.db.collection(collection_1).document(username).collection(collection_2)
        return wq_doc
    
    def read_doc(self, collection, username):
        doc = self.db.collection(collection).document(username).get()
        return doc
    