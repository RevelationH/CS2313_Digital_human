import json
import firebase_admin
from firebase_admin import credentials, firestore
from google.api_core.datetime_helpers import DatetimeWithNanoseconds

# 1. 初始化（只需运行一次）
cred = credentials.Certificate(
    r'./quizsite-fb97c-firebase-adminsdk-fbsvc-76a794e54f.json'
)
firebase_admin.initialize_app(cred)
db = firestore.client()

# --------------------------------------------------
# 2. 工具函数：把 Firestore 特殊对象转成 JSON 可序列化
# --------------------------------------------------
def firestore_to_json(obj):
    if obj is None:
        return None  # 明确保留 None，不要变成 []
    if isinstance(obj, DatetimeWithNanoseconds):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: firestore_to_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [firestore_to_json(item) for item in obj]
    return obj

# --------------------------------------------------
# 3. 抓取全部数据并转换
# --------------------------------------------------

def dump_collection(ref, base):
    col_name = ref.id
    docs = ref.stream()

    if col_name not in base:
        base[col_name] = []

    for doc in docs:
        doc_data = {"id": doc.id, **firestore_to_json(doc.to_dict())}

        # 用专门的 key 放子集合，避免覆盖字段
        sub_collections = {}
        for subcol in doc.reference.collections():
            subcol_name = subcol.id
            subcol_data = []
            for subdoc in subcol.stream():
                subcol_data.append(
                    {"id": subdoc.id, **firestore_to_json(subdoc.to_dict())}
                )
            sub_collections[subcol_name] = subcol_data

        if sub_collections:                    # 有子集合才写
            doc_data["sub_collections"] = sub_collections

        base[col_name].append(doc_data)

# 根集合
all_data = {}
for root_col in db.collections():
    dump_collection(root_col, all_data)

# --------------------------------------------------
# 4. 打印到控制台
# --------------------------------------------------
print(json.dumps(all_data, ensure_ascii=False, indent=2))

# --------------------------------------------------
# 5. 保存为 JSON 文件
# --------------------------------------------------
with open('firestore_dump.json', 'w', encoding='utf-8') as f:
    json.dump(all_data, f, ensure_ascii=False, indent=2)

print('已保存为 firestore_dump.json')