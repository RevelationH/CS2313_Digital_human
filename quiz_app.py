import webbrowser
import threading
from flask.views import MethodView
from datetime import datetime, timezone
import re
from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, jsonify, abort
)
from markupsafe import Markup, escape
from db import fire_db
from user import User
import socket
import netifaces
import os


class QuizApp:
    def __init__(self, user_class, host='0.0.0.0', port=5001):
        self.app = Flask(__name__)
        self.app.config['SECRET_KEY'] = 'demo123'

        # 保存主机和端口配置
        self.host = host  # 0.0.0.0 表示监听所有网络接口
        self.port = port

        self.local_ip = self._get_local_ip()
        print(f"Device A IP address: {self.local_ip}")

        # 初始化 Firebase
        self.db = fire_db()

        self.UserClass = user_class
        self._setup_filters()
        self._setup_routes()

        # 存储用户实例
        self.current_user = None
        self.server_thread = None

        self._INVALID_CHARS = re.compile(r'[\/\\#?%]')

        self._add_firewall_rule()
        
        print(f"QuizApp initialized - Accessible at: http://{self.local_ip}:{self.port}")

    def _get_local_ip(self):
        """动态获取设备A的局域网IP地址"""
        try:
            # 方法1: 通过连接外部服务器获取本机IP
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except:
            try:
                # 方法2: 使用netifaces获取所有网络接口的IP
                import netifaces
                interfaces = netifaces.interfaces()
                for interface in interfaces:
                    addrs = netifaces.ifaddresses(interface)
                    if netifaces.AF_INET in addrs:
                        for addr in addrs[netifaces.AF_INET]:
                            ip = addr['addr']
                            # 排除回环地址和链路本地地址
                            if ip != '127.0.0.1' and not ip.startswith('169.254'):
                                return ip
            except:
                # 方法3: 使用socket.gethostbyname
                try:
                    hostname = socket.gethostname()
                    ip = socket.gethostbyname(hostname)
                    if ip != '127.0.0.1':
                        return ip
                except:
                    pass
        
        # 如果所有方法都失败，返回回环地址
        print("Fail to get ip!!!!!!!!!")
        return "127.0.0.1"

    def _add_firewall_rule(self):
        """添加防火墙规则允许外部访问"""
        if os.name == 'nt':  # Windows
            try:
                import subprocess
                rule_name = f"Open TCP Port {self.port} for QuizApp"
                # 检查规则是否已存在
                result = subprocess.run([
                    'netsh', 'advfirewall', 'firewall', 'show', 'rule',
                    f'name={rule_name}'
                ], capture_output=True, text=True)
                
                # 如果规则不存在，则添加
                if "No rules match" in result.stdout:
                    subprocess.run([
                        'netsh', 'advfirewall', 'firewall', 'add', 'rule',
                        f'name={rule_name}',
                        'dir=in',
                        'action=allow',
                        'protocol=TCP',
                        f'localport={self.port}'
                    ], capture_output=True, text=True)
                    print(f"Firewall rule added for port {self.port}")
                else:
                    print(f"Firewall rule for port {self.port} already exists")
            except Exception as e:
                print(f"Warning: Could not add firewall rule: {e}")

    def get_remote_url(self, path="/dashboard"):
        """生成设备B可以访问的URL"""
        # 使用动态获取的设备A的IP地址
        url = f"http://{self.local_ip}:{self.port}{path}"
        print(f"QuizApp URL for device B: {url}")
        return url

    def start_in_background(self):
        """在后台启动服务器并返回远程URL"""
        try:
            # 每次启动时重新获取IP地址，以防IP发生变化
            current_ip = self._get_local_ip()
            if current_ip != self.local_ip:
                print(f"IP address changed from {self.local_ip} to {current_ip}")
                self.local_ip = current_ip
            
            if self.server_thread and self.server_thread.is_alive():
                print("QuizApp server is already running")
                return self.get_remote_url()
            
            # 启动服务器线程
            print("Starting QuizApp server in background thread...")
            self.server_thread = threading.Thread(target=self._start_server_async, daemon=True)
            self.server_thread.start()
            
            # 在新线程中等待服务器启动
            threading.Thread(target=self._wait_for_server, daemon=True).start()
            
            # 返回设备B可以访问的URL
            remote_url = self.get_remote_url()
            print(f"QuizApp will be accessible at: {remote_url}")
            return remote_url
            
        except Exception as e:
            print(f"Error starting QuizApp in background: {e}")
            return self.get_remote_url()

    def _start_server_async(self):
        """异步启动服务器"""
        try:
            print(f"Starting Flask server on {self.host}:{self.port}")
            self.app.run(
                host=self.host, 
                port=self.port, 
                debug=False, 
                use_reloader=False, 
                threaded=True
            )
        except Exception as e:
            print(f"Error in server thread: {e}")

    def _wait_for_server(self):
        """等待服务器启动"""
        import time
        max_wait = 15
        # 使用localhost来测试服务器是否启动
        test_url = f"http://127.0.0.1:{self.port}/"
        
        for i in range(max_wait):
            time.sleep(1)
            try:
                import urllib.request
                urllib.request.urlopen(test_url, timeout=1)
                # 服务器已启动，打印可访问的URL
                remote_url = self.get_remote_url()
                print(f"QuizApp server is ready and accessible at: {remote_url}")
                break
            except Exception as e:
                if i == max_wait - 1:
                    print(f"Warning: QuizApp server might not be fully ready: {e}")
    
    def _setup_filters(self):
        """设置模板过滤器"""
        self.app.add_template_filter(self._mcq_html_filter(), 'mcq_html')
        self.app.add_template_filter(self._extract_mcq_options_filter(), 'extract_mcq_options')

    def _setup_routes(self):
        """设置路由"""
        # 添加练习视图
        self.app.add_url_rule(
            '/practice/<string:list_id>/<string:kp_name>',
            view_func=PracticeView.as_view('practice', quiz_app=self),
            methods=['GET', 'POST']
        )

        # 其他路由
        self.app.route('/dashboard')(self.dashboard)
        self.app.route('/analysis')(self.analysis)
        self.app.route('/wrongbook')(self.wrongbook)
        self.app.route('/delete_account', methods=['GET', 'POST'])(self.delete_account)
        self.app.route('/logout')(self.logout)
        self.app.route('/')(self.index)

    class MCQHtmlFilter:
        _re_options_split = re.compile(r'Options?\s*:\s*', flags=re.IGNORECASE)
        _re_sentence_break = re.compile(r'([.?!])\s+')

        def __call__(self, text: str):
            if not text:
                return ""
            parts = self._re_options_split.split(text, maxsplit=1)
            stem = (parts[0] if parts else text).strip()
            stem = self._re_sentence_break.sub(r'\1\n', stem).replace("\\n", "\n")
            html = "<br>".join(
                escape(line.strip()) for line in stem.splitlines() if line.strip()
            )
            return Markup(html)

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
            tokens = self._re_tokenizer.split(opt_str)
            out = []
            for i in range(1, len(tokens), 2):
                label = (tokens[i] or "").upper()
                content = (tokens[i + 1] or "").strip()
                if content:
                    out.append((label, content))
            return out

    def _mcq_html_filter(self):
        return self.MCQHtmlFilter()

    def _extract_mcq_options_filter(self):
        return self.ExtractMCQOptionsFilter()

    def safe_id(self, text: str, max_len: int = 150) -> str:
        text = self._INVALID_CHARS.sub('_', (text or '').strip())
        return text[:max_len] or 'untitled'

    """
    def run(self, **kwargs):
        self.app.run(**kwargs)
    """

    def dashboard(self):
        if not session.get('user_id'):
            # 创建用户实例
            self.current_user = self.UserClass
            session['user_id'] = "2"
            session['username'] = "2"

        kps = KnowledgePoint.get_all(self.db)
        return render_template('dashboard.html', kps=kps, username=session.get('username'))

    def analysis(self):
        if not session.get('user_id'):
            return redirect(url_for('login'))

        user_id = session['user_id']
        wrong_questions_ref = self.db.collection('users').document(user_id).collection('wrong_questions')
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
                kp_stats[keypoint_name] = {'wrong': wrong_count}
                if wrong_count >= 3:
                    weak_points.append(keypoint_name)

        return render_template('analysis.html', username=session.get('username'),
                               kp_stats=kp_stats, weak_points=weak_points)

    def wrongbook(self):
        if not session.get('user_id'):
            return redirect(url_for('login'))

        user = self.UserClass.get_by_username(session['user_id'])
        if not user:
            flash("User not found!")
            return redirect(url_for('login'))

        wrong_questions_ref = self.db.collection('users').document(user.username).collection('wrong_questions')
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
                    "timestamp": question_data.get('timestamp')
                })

        if not wrong_answers:
            flash("No wrong answers recorded.")

        return render_template('wrongbook.html', wrong_answers=wrong_answers)

    def delete_account(self):
        if not session.get('user_id'):
            return redirect(url_for('login'))

        if request.method == 'POST':
            user_id = session['user_id']
            self._delete_user_wrong_kp_index(user_id)

            for rec in self.db.collection('answer_records').where('user_id', '==', user_id).stream():
                self.db.collection('answer_records').document(rec.id).delete()

            self.db.collection('users').document(user_id).delete()
            session.clear()
            flash("Your account has been deleted and all your data removed.")
            return redirect(url_for('index'))

        return render_template('delete_account.html')

    def logout(self):
        session.clear()
        self.current_user = None
        return redirect(url_for('index'))

    def index(self):
        return redirect(url_for('dashboard'))

    def _delete_user_wrong_kp_index(self, user_id):
        """删除用户的错题索引"""
        wrong_questions_ref = self.db.collection('users').document(user_id).collection('wrong_questions')
        for kp_doc in wrong_questions_ref.stream():
            kp_doc.reference.delete()

class AnswerRecord:
    def __init__(self, quiz_app, user_id, question_id, user_answer, is_correct, timestamp, knowledge_point, ai_question=None, ai_answer=None):
        self.quiz_app = quiz_app
        self.user_id = user_id
        self.question_id = question_id
        self.user_answer = user_answer
        self.is_correct = is_correct
        self.timestamp = timestamp
        self.knowledge_point = knowledge_point
        self.ai_question = ai_question
        self.ai_answer = ai_answer

    def save(self):
        self.quiz_app.db.collection('answer_records').document().set({
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
    def __init__(self, quiz_app):
        self.quiz_app = quiz_app

    def _canon(self, s: str) -> str:
        return (s or "").strip().casefold()

    def _pick_mcq(self, s: str):
        m = re.search(r"\b([ABCD])\b", (s or ""), flags=re.IGNORECASE)
        return m.group(1).upper() if m else None

    def _require_login(self):
        if not self.quiz_app.current_user and not session.get('user_id'):
            # 创建默认用户
            self.quiz_app.current_user = self.quiz_app.UserClass(username="2", password="demo")
            session['user_id'] = "2"
            session['username'] = "2"
        return None

    def _get_kp_or_redirect(self, list_id: str, kp_name: str):
        kp = KnowledgePoint.get_by_name(self.quiz_app.db, list_id, kp_name)
        if not kp:
            flash("Knowledge point not found!")
            return None, redirect(url_for('dashboard'))
        return kp, None

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

    def post(self, list_id: str, kp_name: str):
        need = self._require_login()
        if need:
            return need

        kp, redir = self._get_kp_or_redirect(list_id, kp_name)
        if redir:
            return redir

        user = self.quiz_app.UserClass.get_by_username(session['user_id'])
        if not user:
            flash("User not found!")
            return redirect(url_for('login'))

        questions = kp.questions or []
        now_ts = datetime.now(timezone.utc)
        answered = 0
        correct = 0
        results_map = {}

        for q in questions:
            q_text = q.get("question") or ""
            if not q_text:
                continue

            form_key = f"user_answer_{q_text}"
            user_ans_raw = (request.form.get(form_key) or "").strip()
            std_ans_raw = (q.get("answer") or "").strip()
            explanation = (q.get("explanation") or "").strip()

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
                    self.quiz_app,
                    user_id=user.username,
                    question_id=str(q.get("id") or ""),
                    user_answer=user_ans_raw,
                    is_correct=is_correct,
                    timestamp=now_ts,
                    knowledge_point=kp_name,
                    ai_question=q_text,
                    ai_answer=std_ans_raw
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
                    wrong_questions_ref = self.quiz_app.db.collection('users').document(user.username).collection('wrong_questions')
                    kp_ref = wrong_questions_ref.document(kp_name)
                    if not kp_ref.get().exists:
                        kp_ref.set({'id': kp_name, 'list_id': list_id}, merge=True)
                    kp_ref.collection('questions').add(wrong_answer_data)

                if is_correct:
                    correct += 1

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

class KnowledgePoint:
    def __init__(self, db, list_id, name, description="", questions=None):
        self.db = db
        self.list_id = list_id
        self.name = name
        self.description = description
        self.questions = questions if questions else []

    @staticmethod
    def _doc_ref(db, list_id, name):
        return (db.collection('knowledge_points')
                  .document(list_id)
                  .collection('items')
                  .document(name))

    def save(self):
        doc_ref = self._doc_ref(self.db, self.list_id, self.name)
        doc_ref.set({
            'list': self.list_id,
            'name': self.name,
            'description': self.description,
            'questions': self.questions,
        })

    @staticmethod
    def get_all(db, list_id=None):
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
                db,
                data.get('list') or doc.reference.parent.parent.id,
                data.get('name') or doc.id,
                data.get('description', ""),
                data.get('questions', []),
            )
            kps.append(kp)
        return kps

    @staticmethod
    def get_by_name(db, list_id, kp_name):
        doc_ref = (
            db.collection('knowledge_points')
            .document(list_id)
            .collection('items')
            .document(kp_name)
        )
        snap = doc_ref.get()
        if snap.exists:
            data = snap.to_dict()
            return KnowledgePoint(
                db,
                list_id=data['list'],
                name=data['name'],
                description=data['description'],
                questions=data.get('questions', [])
            )
        return None


