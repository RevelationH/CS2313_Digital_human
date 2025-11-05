from flask.views import MethodView
from datetime import datetime, timezone
import re
from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, jsonify, abort
)
from markupsafe import Markup, escape
import firebase_admin
from firebase_admin import credentials, firestore

app = Flask(__name__)
app.config['SECRET_KEY'] = 'demo123'
cred = credentials.Certificate(r'quizsite-fb97c-firebase-adminsdk-fbsvc-76a794e54f.json')
firebase_admin.initialize_app(cred)
db = firestore.client()


def safe_id(text: str, max_len: int = 150) -> str:
    text = _INVALID_CHARS.sub('_', (text or '').strip())
    return text[:max_len] or 'untitled'

class AnswerRecord:
    def __init__(self, user_id, question_id, user_answer, is_correct, timestamp, knowledge_point, ai_question=None, ai_answer=None):
        self.user_id = user_id
        self.question_id = question_id
        self.user_answer = user_answer
        self.is_correct = is_correct
        self.timestamp = timestamp
        self.knowledge_point = knowledge_point
        self.ai_question = ai_question
        self.ai_answer = ai_answer

    def save(self):
        db.collection('answer_records').document().set({
            'user_id': self.user_id,
            'question_id': self.question_id,
            'user_answer': self.user_answer,
            'is_correct': self.is_correct,
            'timestamp': self.timestamp,
            'knowledge_point': self.knowledge_point,
            'ai_question': self.ai_question,
            'ai_answer': self.ai_answer
        })

class PracticeView(MethodView):
    """
    ：提交后在页面内显示“正确/错误 + 正确答案 + 解析”，
    同时把作答写入 answer_records；错误写入错题本。
    """

    # ---------- 小工具 ----------
    @staticmethod
    def _canon(s: str) -> str:
        return (s or "").strip().casefold()

    @staticmethod
    def _pick_mcq(s: str):
        m = re.search(r"\b([ABCD])\b", (s or ""), flags=re.IGNORECASE)
        return m.group(1).upper() if m else None

    @staticmethod
    def _require_login():
        if not session.get('user_id'):
            session['user_id'] = "2"  # 设置您想要的用户ID
            session['username'] = "2"
        return None  # 返回None表示不需要重定向

    @staticmethod
    def _get_kp_or_redirect(list_id: str, kp_name: str):
        kp = KnowledgePoint.get_by_name(list_id, kp_name)
        if not kp:
            flash("Knowledge point not found!")
            return None, redirect(url_for('dashboard'))
        return kp, None

    # ---------- GET ----------
    def get(self, list_id: str, kp_name: str):
        need = self._require_login()
        if need:
            return need

        kp, redir = self._get_kp_or_redirect(list_id, kp_name)
        if redir:
            return redir

        questions = kp.questions or []
        return render_template(
            'practice.html',
            questions=questions,
            kp_name=kp_name,
            list_id=list_id,
            results_map=None,
            summary=None
        )

    # ---------- POST ----------
    def post(self, list_id: str, kp_name: str):
        need = self._require_login()
        if need:
            return need

        kp, redir = self._get_kp_or_redirect(list_id, kp_name)
        if redir:
            return redir

        user = User.get_by_username(session['user_id'])
        if not user:
            flash("User not found!")
            return redirect(url_for('login'))

        questions = kp.questions or []
        now_ts = datetime.now(timezone.utc)
        answered = 0
        correct = 0
        results_map = {}  # key = question_text

        for q in questions:
            q_text = q.get("question") or ""
            if not q_text:
                continue

            form_key = f"user_answer_{q_text}"
            user_ans_raw = (request.form.get(form_key) or "").strip()
            std_ans_raw  = (q.get("answer") or "").strip()
            explanation  = (q.get("explanation") or "").strip()

            # 判分：文本等价或 A-D 选项等价
            is_correct = False
            if self._canon(user_ans_raw) and self._canon(std_ans_raw):
                if self._canon(user_ans_raw) == self._canon(std_ans_raw):
                    is_correct = True
                else:
                    ua = self._pick_mcq(user_ans_raw)
                    sa = self._pick_mcq(std_ans_raw)
                    if ua and sa and ua == sa:
                        is_correct = True

            if user_ans_raw:
                answered += 1

                # 记录到 answer_records
                AnswerRecord(
                    user_id=user.username,
                    question_id=str(q.get("id") or ""),
                    user_answer=user_ans_raw,
                    is_correct=is_correct,
                    timestamp=now_ts,
                    knowledge_point=kp_name,
                    ai_question=q_text,     # 用该字段在明细里展示题干
                    ai_answer=std_ans_raw   # 标准答案
                ).save()

                # 错题写入错题本
                if not is_correct:
                    wrong_answer_data = {
                        "list_id": list_id,
                        "question": q_text,
                        "std_answer": std_ans_raw,
                        "user_answer": user_ans_raw,
                        "timestamp": now_ts,
                    }
                    wrong_questions_ref = db.collection('users').document(user.username).collection('wrong_questions')
                    kp_ref = wrong_questions_ref.document(kp_name)
                    if not kp_ref.get().exists:
                        kp_ref.set({'id': kp_name, 'list_id': list_id}, merge=True)
                    kp_ref.collection('questions').add(wrong_answer_data)

                if is_correct:
                    correct += 1

            # 页面反馈
            results_map[q_text] = {
                "user_answer": user_ans_raw,
                "std_answer": std_ans_raw,
                "is_correct": is_correct if user_ans_raw else False,
                "explanation": explanation
            }

        summary = {
            "answered": answered,
            "correct": correct,
            "incorrect": max(answered - correct, 0)
        }

        return render_template(
            'practice.html',
            questions=questions,
            kp_name=kp_name,
            list_id=list_id,
            results_map=results_map,
            summary=summary
        )

app.add_url_rule(
    '/practice/<string:list_id>/<string:kp_name>',
    view_func=PracticeView.as_view('practice'),
    methods=['GET', 'POST']
)


from markupsafe import Markup, escape

class MCQHtmlFilter:
    _re_options_split = re.compile(r'Options?\s*:\s*', flags=re.IGNORECASE)
    _re_sentence_break = re.compile(r'([.?!])\s+')

    def __call__(self, text: str):
        if not text:
            return ""
        # 切掉 Options: 之后的内容，只保留题干
        parts = self._re_options_split.split(text, maxsplit=1)
        stem = (parts[0] if parts else text).strip()
        # 在句号/问号后加换行，并把转义的 \n 还原为真正的换行
        stem = self._re_sentence_break.sub(r'\1\n', stem).replace("\\n", "\n")
        # 安全转义 + 换行转 <br>
        html = "<br>".join(
            escape(line.strip()) for line in stem.splitlines() if line.strip()
        )
        return Markup(html)

# -------- 从题干中抽取 A/B/C/D 选项为列表 [('A','...'), ...] --------
class ExtractMCQOptionsFilter:
    _re_options_split = re.compile(r'Options?\s*:\s*', flags=re.IGNORECASE)
    _re_tokenizer = re.compile(r'(?:(?<=^)|(?<=\s))([A-D])\.\s*')

    def __call__(self, text: str):
        if not text:
            return []
        parts = self._re_options_split.split(text, maxsplit=1)
        if len(parts) != 2:
            return []
        opt_str = parts[1].strip()
        # tokens: ["", "A", "optA", "B", "optB", ...]
        tokens = self._re_tokenizer.split(opt_str)
        out = []
        for i in range(1, len(tokens), 2):
            label = (tokens[i] or "").upper()
            content = (tokens[i + 1] or "").strip()
            if content:
                out.append((label, content))
        return out

app.add_template_filter(MCQHtmlFilter(), 'mcq_html')
app.add_template_filter(ExtractMCQOptionsFilter(), 'extract_mcq_options')


class KnowledgePoint:
    def __init__(self, list_id, name, description="", questions=None):
        self.list_id = list_id
        self.name = name
        self.description = description
        self.questions = questions if questions else []

    @staticmethod
    def _doc_ref(list_id, name):
        return (db.collection('knowledge_points')
                  .document(list_id)
                  .collection('items')
                  .document(name))

    def save(self):
        doc_ref = self._doc_ref(self.list_id, self.name)
        doc_ref.set({
            'list': self.list_id,
            'name': self.name,
            'description': self.description,
            'questions': self.questions,
        })

    @staticmethod
    def get_all(list_id=None):
        kps = []
        if list_id:
            docs = (db.collection('knowledge_points')
                      .document(list_id)
                      .collection('items')
                      .stream())
        else:
            docs = db.collection_group('items').stream()

        for doc in docs:
            data = doc.to_dict() or {}
            kp = KnowledgePoint(
                data.get('list') or doc.reference.parent.parent.id,
                data.get('name') or doc.id,
                data.get('description', ""),
                data.get('questions', []),
            )
            kps.append(kp)
        return kps

    @staticmethod
    def get_by_name(list_id, kp_name):
        doc_ref = (
            db.collection('knowledge_points')
            .document(safe_id(list_id))
            .collection('items')
            .document(safe_id(kp_name))
        )
        snap = doc_ref.get()
        if snap.exists:
            data = snap.to_dict()
            return KnowledgePoint(
                list_id=data['list'],
                name=data['name'],
                description=data['description'],
                questions=data.get('questions', [])
            )
        return None

@app.route('/dashboard')
def dashboard():
    if not session.get('user_id'):
        session['user_id'] = "2"  # 设置您想要的用户ID
        session['username'] = "2"
    return render_template('dashboard.html', kps=KnowledgePoint.get_all(), username=session.get('username'))



class User:
    def __init__(self, username, password, is_admin=False):
        self.username = username
        self.password = password
        self.is_admin = is_admin

    def save(self):
        db.collection('users').document(self.username).set({
            'username': self.username,
            'password': self.password,
            'is_admin': self.is_admin
        })

    @staticmethod
    def get_by_username(username):
        doc = db.collection('users').document(username).get()
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

        db.collection('users').document(self.username) \
            .collection('wrong_questions') \
            .document(keypoint) \
            .collection('questions') \
            .add(wrong_answer_data)


@app.route('/analysis')
def analysis():
    if not session.get('user_id'):
        return redirect(url_for('login'))

    user_id = session['user_id']

    wrong_questions_ref = db.collection('users').document(user_id).collection('wrong_questions')

    # 获取用户所有的关键知识点文档（kp_name）
    keypoints = wrong_questions_ref.stream()
    kp_stats = {}  # 存储每个知识点的错题统计数据
    weak_points = []  # 用于存储掌握不好的知识点（错题较多）

    for keypoint_doc in keypoints:
        keypoint_name = keypoint_doc.id  # 获取知识点名称

        # 获取当前知识点下的所有问题
        questions_ref = keypoint_doc.reference.collection('questions')
        questions = questions_ref.stream()

        wrong_count = 0  # 记录错题数量

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

            if wrong_count >= 3:  # 假设超过3道错题，认为该知识点为弱项
                weak_points.append(keypoint_name)

    return render_template('analysis.html', username=session.get('username'), kp_stats=kp_stats,
                           weak_points=weak_points)


@app.route('/wrongbook')
def wrongbook():
    if not session.get('user_id'):
        return redirect(url_for('login'))

    user = User.get_by_username(session['user_id'])
    if not user:
        flash("User not found!")
        return redirect(url_for('login'))

    wrong_questions_ref = db.collection('users').document(user.username).collection('wrong_questions')

    keypoints = wrong_questions_ref.stream()
    wrong_answers = []

    for keypoint_doc in keypoints:
        keypoint_name = keypoint_doc.id
        questions_ref = keypoint_doc.reference.collection('questions')
        questions = questions_ref.stream()

        for question_doc in questions:
            question_data = question_doc.to_dict()
            wrong_answers.append({
                "question": question_data.get('question'),
                "std_answer": question_data.get('std_answer'),
                "user_answer": question_data.get('user_answer'),
                "timestamp": question_data.get('timestamp')  # 这里可以增删信息
            })

    if not wrong_answers:
        flash("No wrong answers recorded.")

    return render_template('wrongbook.html', wrong_answers=wrong_answers)

@app.route('/delete_account', methods=['GET', 'POST'])
def delete_account():
    if not session.get('user_id'):
        return redirect(url_for('login'))

    if request.method == 'POST':
        user_id = session['user_id']


        _delete_user_wrong_kp_index(user_id)

        for rec in db.collection('answer_records').where('user_id', '==', user_id).stream():
            db.collection('answer_records').document(rec.id).delete()

        db.collection('users').document(user_id).delete()

        session.clear()
        flash("Your account has been deleted and all your data removed.")
        return redirect(url_for('index'))

    return render_template('delete_account.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

@app.route('/')
def index():
    return redirect(url_for('dashboard'))

_INVALID_CHARS = re.compile(r'[\/\\#?%]')


if __name__ == '__main__':
    app.run(debug=True)