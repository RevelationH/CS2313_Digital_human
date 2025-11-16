import webbrowser
import threading
from flask.views import MethodView
from datetime import datetime, timezone
import math
import time
import re
from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, jsonify, abort, has_request_context
)
from markupsafe import Markup, escape
from db import fire_db
from user import User
import socket
import netifaces
import os


class QuizApp:
    # 类级别的标志，追踪路由是否已在外部app中注册
    _routes_registered = {}
    _template_context_registered = {}
    
    def __init__(self, user_class, external_app=None, host='0.0.0.0', port=5000, skip_setup=False):
        # 如果传入了外部 Flask app，就使用它；否则创建新的
        if external_app is not None:
            self.app = external_app
            self.is_external_app = True
        else:
            self.app = Flask(__name__)
            self.app.config['SECRET_KEY'] = 'demo123'
            self.is_external_app = False
        
        # 配置以支持反向代理和公网访问
        # 使 url_for 始终生成相对路径，不依赖请求头中的 Host
        if not self.is_external_app:
            self.app.config['PREFERRED_URL_SCHEME'] = 'http'
            self.app.config['APPLICATION_ROOT'] = '/'
        
        # 保存主机和端口配置
        self.host = host  # 0.0.0.0 表示监听所有网络接口
        self.port = port

        # 延迟初始化：只在需要时扫描网络（节省启动时间和资源）
        self._local_ip_cache = None
        if not skip_setup:
            self.local_ip = self._get_local_ip()
            print(f"Device A IP address: {self.local_ip}")
        
        # 初始化 Firebase
        self.db = fire_db()

        self.UserClass = user_class
        
        # 如果 skip_setup=True，跳过路由和过滤器设置（路由已预先注册）
        if not skip_setup:
            self._setup_filters()
            self._setup_routes()
            self._setup_template_context()
        else:
            print(f"QuizApp initialized in data-only mode (routes already registered)")
            # 即使跳过设置，也需要注册模板上下文处理器
            if self.is_external_app:
                self._setup_template_context()

        # 存储用户实例
        self.current_user = None
        self.server_thread = None

        self._INVALID_CHARS = re.compile(r'[\/\\#?%]')

        # 只有在不是外部app时才添加防火墙规则
        if not self.is_external_app:
            self._add_firewall_rule()
        
        if not skip_setup:
            print(f"QuizApp initialized - Routes registered for port {self.port}")

    def _is_port_in_use(self, port):
        """检查端口是否已被占用"""
        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(('127.0.0.1', port))
                return False
            except socket.error:
                return True


    @property
    def local_ip(self):
        """延迟获取 local_ip，使用缓存避免重复扫描"""
        if self._local_ip_cache is None:
            self._local_ip_cache = self._get_local_ip()
        return self._local_ip_cache
    
    @local_ip.setter
    def local_ip(self, value):
        """允许设置 local_ip"""
        self._local_ip_cache = value
    
    def _get_local_ip(self):
        """动态获取设备A的局域网IP地址"""
        try:
            # 方法1: 使用socket连接获取出站IP（这个可能返回错误的144.214.0.16）
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            outbound_ip = s.getsockname()[0]
            s.close()
            print(f"Outbound IP: {outbound_ip}")
        except:
            outbound_ip = None
    
        try:
            # 方法2: 获取所有网络接口的IP，优先选择正确的网段
            import netifaces
            interfaces = netifaces.interfaces()
            all_ips = []
        
            for interface in interfaces:
                addrs = netifaces.ifaddresses(interface)
                if netifaces.AF_INET in addrs:
                    for addr in addrs[netifaces.AF_INET]:
                        ip = addr['addr']
                        if ip != '127.0.0.1' and not ip.startswith('169.254'):
                            all_ips.append((interface, ip))
        
            print(f"All network IPs: {all_ips}")
        
            # 优先选择172.28.x.x网段的IP
            for interface, ip in all_ips:
                if ip.startswith('172.28.'):
                    print(f"Selected preferred IP {ip} from interface {interface}")
                    return ip
        
            # 如果没有172.28网段，选择第一个非出站IP
            for interface, ip in all_ips:
                if ip != outbound_ip:
                    print(f"Selected alternative IP {ip} from interface {interface}")
                    return ip
        
            # 最后选择出站IP
            if outbound_ip:
                print(f"Using outbound IP: {outbound_ip}")
                return outbound_ip
            
        except Exception as e:
            print(f"Error getting network interfaces: {e}")
    
        return "127.0.0.1"

    def _add_firewall_rule(self):
        """添加防火墙规则允许外部访问"""
        if os.name == 'nt':  # Windows
            try:
                import subprocess
                rule_name = f"Open TCP Port {self.port} for QuizApp"
            
                # 使用更安全的方式执行命令，忽略输出编码
                try:
                    # 检查规则是否已存在
                    result = subprocess.run([
                        'netsh', 'advfirewall', 'firewall', 'show', 'rule',
                        f'name={rule_name}'
                    ], capture_output=True, text=True, encoding='utf-8', errors='ignore')
                
                    # 如果规则不存在，则添加
                    if "No rules match" in result.stdout:
                        subprocess.run([
                            'netsh', 'advfirewall', 'firewall', 'add', 'rule',
                            f'name={rule_name}',
                            'dir=in',
                            'action=allow',
                            'protocol=TCP',
                            f'localport={self.port}'
                        ], capture_output=True, text=True, encoding='utf-8', errors='ignore')
                        print(f"Firewall rule added for port {self.port}")
                    else:
                        print(f"Firewall rule for port {self.port} already exists")
                except UnicodeDecodeError:
                    # 如果仍然有编码问题，使用二进制模式
                    subprocess.run([
                        'netsh', 'advfirewall', 'firewall', 'add', 'rule',
                        f'name={rule_name}',
                        'dir=in',
                        'action=allow',
                        'protocol=TCP',
                        f'localport={self.port}'
                    ], capture_output=True)
                    print(f"Firewall rule added for port {self.port} (binary mode)")
                
            except Exception as e:
                print(f"Warning: Could not add firewall rule: {e}")


    def _build_url_from_request_host(self, request_host, path="/dashboard"):
        """根据 request_host 构建 URL"""
        if request_host:
            try:
                from flask import has_request_context, request as flask_request
                
                # 分离主机名和端口
                if request_host.startswith('['):
                    # IPv6 地址
                    hostname = request_host.rsplit(']:', 1)[0] + ']'
                elif ':' in request_host and request_host.count(':') == 1:
                    # IPv4 地址带端口
                    hostname = request_host.rsplit(':', 1)[0]
                else:
                    # 纯主机名或纯 IPv4（无端口）
                    hostname = request_host
                
                # 判断协议：如果在请求上下文中，使用请求的协议；否则默认 http
                scheme = 'http'
                if has_request_context():
                    scheme = flask_request.scheme  # 'http' 或 'https'
                
                # 判断是否是域名（包含字母）还是 IP 地址（纯数字和点）
                is_domain = any(c.isalpha() for c in hostname.replace('[', '').replace(']', ''))
                
                if is_domain:
                    # 域名访问（通过 nginx），不添加端口号
                    url = f"{scheme}://{hostname}{path}"
                    print(f"QuizApp URL (domain via nginx): {url}")
                else:
                    # IP 地址访问，需要添加端口号
                    url = f"{scheme}://{hostname}:{self.port}{path}"
                    print(f"QuizApp URL (direct IP): {url}")
                
                return url
            except Exception as e:
                print(f"Error parsing request host: {e}, falling back to local IP")
        
        # 回退到本地 IP
        url = f"http://{self.local_ip}:{self.port}{path}"
        print(f"QuizApp URL (using local IP): {url}")
        return url
    
    def get_remote_url(self, path="/dashboard", use_request_host=True):
        """生成设备B可以访问的URL"""
        if use_request_host and has_request_context():
            try:
                # 在 Flask 请求上下文中，获取用户访问的主机名
                host_with_port = request.host
                
                # 使用 _build_url_from_request_host 方法来构建 URL
                return self._build_url_from_request_host(host_with_port, path)
            except Exception as e:
                print(f"Error getting request host: {e}, falling back to local IP")
                url = f"http://{self.local_ip}:{self.port}{path}"
                print(f"QuizApp URL (fallback to local IP): {url}")
                return url
        else:
            url = f"http://{self.local_ip}:{self.port}{path}"
            print(f"QuizApp URL (using local IP): {url}")
            return url

    def start_in_background(self, request_host=None):
        """返回 Quiz 页面的 URL（不启动独立服务器，因为路由已注册到主应用）"""
        # 保存 request_host 供后续使用
        self._request_host = request_host
        
        # 如果使用外部app，直接返回URL（路由已经注册到主应用）
        if self.is_external_app:
            remote_url = self._build_url_from_request_host(request_host)
            print(f"✓ QuizApp routes ready at: {remote_url}")
            return remote_url
        
        # 以下是独立模式的逻辑（保留向后兼容）
        try:
            # 每次启动时重新获取IP地址，以防IP发生变化
            current_ip = self._get_local_ip()
            if current_ip != self.local_ip:
                print(f"IP address changed from {self.local_ip} to {current_ip}")
                self.local_ip = current_ip
        
            # 检查端口是否已被占用
            if self._is_port_in_use(self.port):
                print(f"Port {self.port} is already in use, trying to use existing server")
                return self._build_url_from_request_host(request_host)
        
            if self.server_thread and self.server_thread.is_alive():
                print("QuizApp server is already running")
                return self._build_url_from_request_host(request_host)
        
            # 启动服务器线程
            print("Starting QuizApp server in background thread...")
            self.server_thread = threading.Thread(target=self._start_server_async, daemon=True)
            self.server_thread.start()
        
            # 在新线程中等待服务器启动
            success = self._wait_for_server()
        
            if success:
                remote_url = self._build_url_from_request_host(request_host)
                print(f"✓ QuizApp is ready at: {remote_url}")
                return remote_url
            else:
                print(f"✗ QuizApp server failed to start, but you can try: {self._build_url_from_request_host(request_host)}")
                return self._build_url_from_request_host(request_host)
            
        except Exception as e:
            print(f"Error starting QuizApp in background: {e}")
            return self._build_url_from_request_host(request_host)

    def _start_server_async(self):
        """异步启动服务器"""
        try:
            print(f"Starting Flask server on {self.host}:{self.port}")
            # 禁用重载器，避免重复启动
            self.app.run(
                host=self.host, 
                port=self.port, 
                debug=False, 
                use_reloader=False, 
                threaded=True
            )
        except OSError as e:
            if "Address already in use" in str(e):
                print(f"Port {self.port} is already in use by another process")
            else:
                print(f"Error starting QuizApp server: {e}")
        except Exception as e:
            print(f"Unexpected error in server thread: {e}")

    def _wait_for_server(self):
        """等待服务器启动"""
        import time
        max_wait = 20  
        test_url = f"http://127.0.0.1:{self.port}/dashboard"
    
        for i in range(max_wait):
            time.sleep(1)
            try:
                import urllib.request
                response = urllib.request.urlopen(test_url, timeout=2)
                if response.getcode() == 200:
                    # 服务器已启动，打印可访问的URL
                    request_host = getattr(self, '_request_host', None)
                    remote_url = self._build_url_from_request_host(request_host)
                    print(f"✓ QuizApp server is ready and accessible at: {remote_url}")
                    return True
            except Exception as e:
                if i == max_wait - 1:
                    print(f"✗ QuizApp server failed to start: {e}")
                    print(f"  Please check if port {self.port} is available")
                    return False
                elif i % 5 == 0: 
                    print(f"  Waiting for QuizApp server... ({i+1}/{max_wait} seconds)")
    
        return False
    
    def _setup_template_context(self):
        """设置模板上下文处理器，提供自定义的 url_for"""
        app_id = id(self.app)
        
        # 检查是否已经注册过（避免重复注册）
        if self.is_external_app and app_id in QuizApp._template_context_registered:
            print("Template context processor already registered, skipping...")
            return
        
        # 需要在闭包外保存 self 的引用
        quiz_app_instance = self
        
        @self.app.context_processor
        def quiz_url_for_context():
            """为模板提供一个能正确处理 QuizApp 路由的 url_for 函数"""
            from flask import g
            
            def quiz_url_for(endpoint, **values):
                from flask import url_for as flask_url_for
                
                # 尝试从请求上下文获取当前用户的 quiz_app
                current_quiz_app = quiz_app_instance
                if hasattr(g, 'user_components') and 'quiz_app' in g.user_components:
                    current_quiz_app = g.user_components['quiz_app']
                
                if current_quiz_app.is_external_app:
                    # 在外部app模式下，映射 endpoint 名称
                    endpoint_map = {
                        'dashboard': 'quiz_dashboard',
                        'analysis': 'quiz_analysis',
                        'wrongbook': 'quiz_wrongbook',
                        'delete_account': 'quiz_delete_account',
                        'practice': 'practice',  # practice 保持不变
                    }
                    mapped_endpoint = endpoint_map.get(endpoint, endpoint)
                    try:
                        return flask_url_for(mapped_endpoint, **values)
                    except:
                        # 如果失败，尝试直接返回路径
                        return current_quiz_app.get_url_for(endpoint, **values)
                else:
                    # 独立模式，正常使用
                    return flask_url_for(endpoint, **values)
            
            # 返回字典，将 url_for 注入模板上下文
            return dict(url_for=quiz_url_for)
        
        # 标记已注册
        if self.is_external_app:
            QuizApp._template_context_registered[app_id] = True
            print("Template context processor registered successfully")
    
    def _setup_filters(self):
        """设置模板过滤器"""
        # 如果使用外部app且过滤器已存在，跳过添加
        if self.is_external_app:
            # 检查过滤器是否已经存在
            if 'mcq_html' not in self.app.jinja_env.filters:
                try:
                    self.app.add_template_filter(self._mcq_html_filter(), 'mcq_html')
                except AssertionError:
                    # 应用已经启动，手动添加到 jinja_env
                    self.app.jinja_env.filters['mcq_html'] = self._mcq_html_filter()
            
            if 'extract_mcq_options' not in self.app.jinja_env.filters:
                try:
                    self.app.add_template_filter(self._extract_mcq_options_filter(), 'extract_mcq_options')
                except AssertionError:
                    # 应用已经启动，手动添加到 jinja_env
                    self.app.jinja_env.filters['extract_mcq_options'] = self._extract_mcq_options_filter()
        else:
            # 独立模式，正常添加
            self.app.add_template_filter(self._mcq_html_filter(), 'mcq_html')
            self.app.add_template_filter(self._extract_mcq_options_filter(), 'extract_mcq_options')

    def _setup_routes(self):
        """设置路由"""
        # 如果使用外部app，检查路由是否已注册
        app_id = id(self.app)
        if self.is_external_app and app_id in QuizApp._routes_registered:
            print("QuizApp routes already registered, skipping...")
            return
        
        # 对于外部app，使用包装函数从请求上下文获取正确的 quiz_app 实例
        if self.is_external_app:
            # 添加练习视图
            self.app.add_url_rule(
                '/practice/<string:list_id>/<string:kp_name>',
                view_func=PracticeView.as_view('practice', quiz_app=self),
                methods=['GET', 'POST']
            )
            
            # 只注册 QuizApp 特有的路由，避免与主应用冲突
            # 使用唯一的 endpoint 名称
            self.app.add_url_rule('/dashboard', 'quiz_dashboard', 
                                  self._wrap_route_handler(self.dashboard), 
                                  methods=['GET'])
            self.app.add_url_rule('/analysis', 'quiz_analysis', 
                                  self._wrap_route_handler(self.analysis), 
                                  methods=['GET'])
            self.app.add_url_rule('/wrongbook', 'quiz_wrongbook', 
                                  self._wrap_route_handler(self.wrongbook), 
                                  methods=['GET'])
            self.app.add_url_rule('/delete_account', 'quiz_delete_account', 
                                  self._wrap_route_handler(self.delete_account), 
                                  methods=['GET', 'POST'])
            # 不注册 /logout 和 /，避免与主应用冲突
        else:
            # 独立模式，正常注册所有路由
            self.app.add_url_rule(
                '/practice/<string:list_id>/<string:kp_name>',
                view_func=PracticeView.as_view('practice', quiz_app=self),
                methods=['GET', 'POST']
            )
            self.app.route('/dashboard')(self.dashboard)
            self.app.route('/analysis')(self.analysis)
            self.app.route('/wrongbook')(self.wrongbook)
            self.app.route('/delete_account', methods=['GET', 'POST'])(self.delete_account)
            self.app.route('/logout')(self.logout)
            self.app.route('/')(self.index)
            self.app.route('/server_error')(self.server_error)
        
        # 标记路由已注册
        if self.is_external_app:
            QuizApp._routes_registered[app_id] = True
            print("QuizApp routes registered successfully")
    
    def get_cached_knowledge_point(self, list_id, kp_name, include_questions=True):
        """Load knowledge point directly (no long-lived cache to minimize memory)."""
        return KnowledgePoint.get_by_name(self.db, list_id, kp_name, include_questions=include_questions)
    
    def _wrap_route_handler(self, handler):
        """包装路由处理函数，从请求上下文获取正确的 quiz_app 实例"""
        def wrapped_handler(*args, **kwargs):
            from flask import g
            # 尝试从 g 对象获取当前用户的 quiz_app
            if hasattr(g, 'user_components') and 'quiz_app' in g.user_components:
                quiz_app = g.user_components['quiz_app']
                # 使用正确的实例调用方法
                return getattr(quiz_app, handler.__name__)(*args, **kwargs)
            else:
                # 回退到当前实例
                return handler(*args, **kwargs)
        wrapped_handler.__name__ = handler.__name__
        return wrapped_handler

    def server_error(self):
        """服务器错误页面"""
        return """
        <html>
            <head><title>QuizApp Server Error</title></head>
            <body>
                <h1>QuizApp Server Error</h1>
                <p>The QuizApp server failed to start properly.</p>
                <p>Please check:</p>
                <ul>
                    <li>Port 50012 is not already in use</li>
                    <li>Firewall allows access to port 50012</li>
                    <li>Try refreshing the page</li>
                </ul>
                <p><a href="/dashboard">Try accessing dashboard again</a></p>
            </body>
        </html>
        """

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
    
    def get_url_for(self, endpoint, **kwargs):
        """获取路由URL，处理外部app模式下的endpoint名称差异"""
        if self.is_external_app:
            # 在外部app模式下，使用带前缀的endpoint名称或直接返回路径
            endpoint_map = {
                'dashboard': '/dashboard',
                'analysis': '/analysis',
                'wrongbook': '/wrongbook',
                'delete_account': '/delete_account',
                'login': '/auth/login',
                'index': '/auth/login',  # 重定向到登录页
            }
            path = endpoint_map.get(endpoint)
            if path:
                return path
            # 如果没有映射，尝试使用 quiz_ 前缀
            try:
                from flask import url_for
                return url_for(f'quiz_{endpoint}', **kwargs)
            except:
                return f'/{endpoint}'
        else:
            # 独立模式，正常使用 url_for
            from flask import url_for
            return url_for(endpoint, **kwargs)

    def dashboard(self):
        if not session.get('user_id'):
            # 创建用户实例
            self.current_user = self.UserClass
            session['user_id'] = "2"
            session['username'] = "2"

        kps = KnowledgePoint.get_all_summary(self.db)
        return render_template('dashboard.html', kps=kps, username=session.get('username'))

    def analysis(self):
        if not session.get('user_id'):
            return redirect(self.get_url_for('login'))

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
            return redirect(self.get_url_for('login'))

        user_id = session['user_id']

        wrong_questions_ref = self.db.collection('users').document(user_id).collection('wrong_questions')
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
            return redirect(self.get_url_for('login'))

        if request.method == 'POST':
            user_id = session['user_id']
            self._delete_user_wrong_kp_index(user_id)

            for rec in self.db.collection('answer_records').where('user_id', '==', user_id).stream():
                self.db.collection('answer_records').document(rec.id).delete()

            self.db.collection('users').document(user_id).delete()
            session.clear()
            flash("Your account has been deleted and all your data removed.")
            return redirect(self.get_url_for('index'))

        return render_template('delete_account.html')

    def logout(self):
        session.clear()
        self.current_user = None
        return redirect(self.get_url_for('index'))

    def index(self):
        return redirect(self.get_url_for('dashboard'))

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
    PAGE_SIZE = 5

    def __init__(self, quiz_app):
        self.quiz_app = quiz_app
    
    def _get_quiz_app(self):
        """获取正确的 quiz_app 实例（优先从请求上下文）"""
        from flask import g
        if hasattr(g, 'user_components') and 'quiz_app' in g.user_components:
            return g.user_components['quiz_app']
        return self.quiz_app

    def _canon(self, s: str) -> str:
        return (s or "").strip().casefold()

    def _pick_mcq(self, s: str):
        m = re.search(r"\b([ABCD])\b", (s or ""), flags=re.IGNORECASE)
        return m.group(1).upper() if m else None

    def _require_login(self):
        quiz_app = self._get_quiz_app()
        if not quiz_app.current_user and not session.get('user_id'):
            # 创建默认用户
            quiz_app.current_user = quiz_app.UserClass(username="2", password="demo")
            session['user_id'] = "2"
            session['username'] = "2"
        return None

    def _get_kp_or_redirect(self, list_id: str, kp_name: str, include_questions=True):
        quiz_app = self._get_quiz_app()
        kp = quiz_app.get_cached_knowledge_point(list_id, kp_name, include_questions=include_questions)
        if not kp:
            flash("Knowledge point not found!")
            return kp, redirect(quiz_app.get_url_for('dashboard'))
        return kp, None

    def _get_page_from_request(self):
        source = request.args if request.method == 'GET' else request.form
        try:
            page = int(source.get('page', 1))
            return max(1, page)
        except (TypeError, ValueError):
            return 1

    def _paginate_questions(self, questions, page):
        total = len(questions)
        page_size = self.PAGE_SIZE
        total_pages = max(1, math.ceil(total / page_size)) if total else 1
        page = max(1, min(page, total_pages))
        start = (page - 1) * page_size
        end = start + page_size
        subset = questions[start:end]
        return {
            "questions": subset,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
            "total_questions": total,
            "start_index": start
        }

    def get(self, list_id: str, kp_name: str):
        need = self._require_login()
        if need:
            return need

        kp, redir = self._get_kp_or_redirect(list_id, kp_name)
        if redir:
            return redir

        questions = kp.questions or kp.get_questions()
        pagination = self._paginate_questions(questions, self._get_page_from_request())
        page_questions = pagination["questions"]
        if not page_questions:
            flash("No questions available for this knowledge point.")
        return render_template(
            'practice.html',
            questions=page_questions,
            kp_name=kp_name,
            list_id=list_id,
            results_map=None,
            summary=None,
            pagination=pagination,
            start_index=pagination["start_index"]
        )

    def post(self, list_id: str, kp_name: str):
        need = self._require_login()
        if need:
            return need

        kp, redir = self._get_kp_or_redirect(list_id, kp_name)
        if redir:
            return redir

        quiz_app = self._get_quiz_app()
        if not session.get('user_id'):
            flash("User not found!")
            return redirect(quiz_app.get_url_for('login'))

        user_id = session['user_id']

        questions = kp.questions or kp.get_questions()
        pagination = self._paginate_questions(questions, self._get_page_from_request())
        page_questions = pagination["questions"]
        start_index = pagination["start_index"]

        if not page_questions:
            flash("No questions available on this page.")
            return render_template(
                'practice.html',
                questions=[],
                kp_name=kp_name,
                list_id=list_id,
                results_map=None,
                summary=None,
                pagination=pagination,
                start_index=start_index
            )

        now_ts = datetime.now(timezone.utc)
        answered = 0
        correct = 0
        results_map = {}

        for idx, q in enumerate(page_questions):
            q_text = q.get("question") or ""
            if not q_text:
                continue

            global_idx = start_index + idx
            form_key = f"user_answer_{global_idx}"
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
                    quiz_app,
                    user_id=user_id,
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
                    wrong_questions_ref = quiz_app.db.collection('users').document(user_id).collection('wrong_questions')
                    kp_ref = wrong_questions_ref.document(kp_name)
                    if not kp_ref.get().exists:
                        kp_ref.set({'id': kp_name, 'list_id': list_id}, merge=True)
                    kp_ref.collection('questions').add(wrong_answer_data)

                if is_correct:
                    correct += 1

            results_map[str(global_idx)] = {
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
            questions=page_questions,
            kp_name=kp_name,
            list_id=list_id,
            results_map=results_map,
            summary=summary,
            pagination=pagination,
            start_index=start_index
        )


class KnowledgePoint:
    def __init__(self, db, list_id, name, description="", questions=None, question_count=None):
        self.db = db
        self.list_id = list_id
        self.name = name
        self.description = description
        self.questions = list(questions) if questions else []
        if question_count is not None:
            self.question_count = question_count
        else:
            self.question_count = len(self.questions)

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
            'question_count': len(self.questions),
        })

    @staticmethod
    def get_all(db, list_id=None, include_questions=False):
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
            questions_data = data.get('questions')
            question_count = data.get('question_count')
            if question_count is None:
                question_count = len(questions_data) if questions_data else 0
            questions = list(questions_data) if (include_questions and questions_data) else []
            kp = KnowledgePoint(
                db,
                data.get('list') or doc.reference.parent.parent.id,
                data.get('name') or doc.id,
                data.get('description', ""),
                questions,
                question_count=question_count,
            )
            kps.append(kp)
        return kps
    
    @staticmethod
    def get_all_summary(db, list_id=None):
        return KnowledgePoint.get_all(db, list_id=list_id, include_questions=False)

    @staticmethod
    def get_by_name(db, list_id, kp_name, include_questions=True):
        doc_ref = (
            db.collection('knowledge_points')
            .document(list_id)
            .collection('items')
            .document(kp_name)
        )
        snap = doc_ref.get()
        if snap.exists:
            data = snap.to_dict()
            questions = data.get('questions', []) if include_questions else []
            question_count = data.get('question_count')
            if question_count is None:
                question_count = len(data.get('questions', [])) if include_questions else 0
            return KnowledgePoint(
                db,
                list_id=data['list'],
                name=data['name'],
                description=data['description'],
                questions=questions,
                question_count=question_count
            )
        return None
    
    def get_questions(self):
        if self.questions:
            return self.questions
        if not self.db:
            return []
        doc = self._doc_ref(self.db, self.list_id, self.name).get()
        data = doc.to_dict() or {}
        self.questions = data.get('questions', []) or []
        self.question_count = len(self.questions)
        return self.questions
