from flask import Flask, Blueprint, render_template, request, redirect, url_for, session, flash, jsonify, g
from werkzeug.security import generate_password_hash, check_password_hash
from user import User
import threading
import time
import uuid
import psutil
import os

class SessionComponentProxy(dict):
    """Lazy session component holder to avoid eager heavy instantiation."""
    __slots__ = ("_manager", "_user", "_username", "_component_cache", "_components_acquired")

    def __init__(self, manager, user):
        super().__init__(
            quiz_app=manager._shared_quiz_app,
            user=user,
            username=user.username,
            last_accessed=time.time(),
        )
        self._manager = manager
        self._user = user
        self._username = user.username
        self._component_cache = None
        self._components_acquired = False

    def _ensure_components(self):
        if not self._components_acquired:
            pool = self._manager._get_or_create_user_component_pool(self._user)
            self._manager._acquire_user_components(self._username)
            self._manager._enforce_user_cache_limit()
            self._component_cache = pool
            self._components_acquired = True
        return self._component_cache

    def __getitem__(self, key):
        if key in ("rae", "input_intent", "avatar_input"):
            components = self._ensure_components()
            return components.get(key)
        return super().__getitem__(key)

    def release(self):
        if self._components_acquired:
            self._manager._release_user_components(self._username)
            self._component_cache = None
            self._components_acquired = False


class AuthSystem:
    def __init__(self, user_class, flask_app=None, secret_key='demo123'):
        self.user_class = user_class
        self.secret_key = secret_key
        self.bp = Blueprint('auth', __name__)
        self.flask_app = flask_app
        
        # Session ID 到用户组件的映射
        self._session_components_lock = threading.RLock()
        self._session_components = {}  # session_id -> components
        
        # 全局共享的 QuizApp 实例（路由仅需注册一次）
        self._shared_quiz_app = None
        # 用户级组件缓存（避免重复创建占用内存的对象）
        self._user_component_cache = {}
        self._user_component_refcount = {}
        self._user_component_cache_lock = threading.RLock()
        self._user_component_cache_limit = 50  # 增加到50，避免频繁创建和销毁
        self._quiz_app_routes_registered = False
        
        # 全局共享的重型组件（所有用户共享，大幅减少内存占用）
        self._shared_rag = None
        self._shared_rag_lock = threading.Lock()
        
        self._setup_routes()
        self._setup_middleware()
        
        # 如果提供了 flask_app，在应用启动前注册 QuizApp 路由
        if flask_app:
            self._register_quiz_routes(flask_app)
        
        # 启动会话清理线程
        self._start_session_cleanup_thread()
    
    def _setup_routes(self):
        """设置认证相关的路由"""
        self.bp.route('/login', methods=['GET', 'POST'])(self.login)
        self.bp.route('/register', methods=['GET', 'POST'])(self.register)
        self.bp.route('/logout')(self.logout)
        self.bp.route('/auth/current_user')(self.get_current_user)
        self.bp.route('/auth/system_status')(self.get_system_status)
    
    def _setup_middleware(self):
        """设置中间件，在每个请求前准备用户组件"""
        @self.bp.before_app_request
        def before_request():
            from flask import request as flask_request
            
            # 确保Session ID存在
            if 'session_id' not in session:
                session['session_id'] = self._generate_session_id()
            
            session_id = session['session_id']
            
            # 如果用户已登录，准备基本信息
            if self.is_authenticated():
                user = self.get_current_user_obj()
                if user:
                    # 只为需要对话功能的路由创建组件，避免在 dashboard 等页面浪费内存
                    # dashboard、practice、analysis 等页面不需要 AI 组件
                    path = flask_request.path
                    needs_ai_components = not any([
                        path.startswith('/dashboard'),
                        path.startswith('/practice'),
                        path.startswith('/analysis'),
                        path.startswith('/wrongbook'),
                        path.startswith('/delete_account'),
                        path.startswith('/static'),
                        path.startswith('/auth/'),
                        path.endswith('.html'),
                        path.endswith('.css'),
                        path.endswith('.js'),
                        path.endswith('.ico')
                    ])
                    
                    if needs_ai_components:
                        # 只在需要时才创建组件（延迟加载）
                        g.user_components = self._get_or_create_session_components(session_id, user)
                    else:
                        # 对于不需要 AI 的路由，只提供基本信息
                        g.user_components = {
                            'quiz_app': self._shared_quiz_app,
                            'user': user,
                            'username': user.username,
                            'last_accessed': time.time()
                        }
                    
                    g.current_user = user
    
    def _generate_session_id(self):
        """生成唯一的Session ID"""
        return str(uuid.uuid4())
    
    def _register_quiz_routes(self, flask_app):
        """在应用启动前注册 QuizApp 路由并创建共享组件（只注册一次）"""
        if self._quiz_app_routes_registered:
            return
        
        from quiz_app import QuizApp
        
        # 创建共享的组件实例（所有用户共享，大幅节省内存）
        # 使用一个虚拟用户来初始化
        dummy_user = self.user_class("_dummy_", "_dummy_", False)
        
        self._shared_quiz_app = QuizApp(dummy_user, external_app=flask_app, host='0.0.0.0', port=5000)
        
        self._quiz_app_routes_registered = True
        print("✓ Shared components created successfully")
        print(f"  - QuizApp: {id(self._shared_quiz_app)}")
        print(f"  - QuizApp: {id(self._shared_quiz_app)}")
    
    def _get_shared_rag(self):
        """获取全局共享的 RAG 实例（所有用户共享，大幅减少内存占用）"""
        if self._shared_rag is None:
            with self._shared_rag_lock:
                if self._shared_rag is None:  # Double-check locking
                    from rag import rag
                    import os
                    DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "sk-61cf109d660d4ba6a9d80ebf38737f06")
                    print("🔄 Initializing shared RAG instance (this may take a moment)...")
                    self._shared_rag = rag(DEEPSEEK_API_KEY)
                    print("✓ Shared RAG instance initialized successfully")
        return self._shared_rag
    
    def _get_or_create_user_component_pool(self, user):
        """按用户名缓存和复用重型组件，减少内存占用"""
        from retrival import re_and_exc, intent, avatar_text
        username = user.username
        with self._user_component_cache_lock:
            cached = self._user_component_cache.get(username)
            if not cached:
                # 使用共享 RAG 实例
                shared_rag = self._get_shared_rag()
                
                cached = {
                    'rae': re_and_exc(user, shared_rag=shared_rag),  # 传入共享 RAG
                    'input_intent': intent(user),
                    'avatar_input': avatar_text(user),
                    'last_accessed': time.time()
                }
                self._user_component_cache[username] = cached
                self._user_component_refcount[username] = 0
                print(f"✓ Created components for user '{username}' (using shared RAG)")
            else:
                cached['last_accessed'] = time.time()
                # 确保缓存的组件使用最新的 user 引用
                rae = cached.get('rae')
                if rae:
                    setattr(rae, 'user', user)
                    analysis = getattr(rae, 'analysis', None)
                    if analysis:
                        setattr(analysis, 'user', user)
                        setattr(analysis, 'username', str(user.username))
        return cached

    def _acquire_user_components(self, username):
        with self._user_component_cache_lock:
            self._user_component_refcount[username] = self._user_component_refcount.get(username, 0) + 1

    def _release_user_components(self, username):
        with self._user_component_cache_lock:
            if username in self._user_component_refcount:
                self._user_component_refcount[username] -= 1
                if self._user_component_refcount[username] <= 0:
                    self._user_component_refcount.pop(username, None)
                    self._user_component_cache.pop(username, None)
    
    def _release_session_components(self, session_id):
        """释放会话占用的资源引用"""
        with self._session_components_lock:
            components = self._session_components.pop(session_id, None)
        if not components:
            return
        if isinstance(components, SessionComponentProxy):
            components.release()

    
    def _enforce_user_cache_limit(self):
        """限制用户组件缓存大小，避免内存无限增长"""
        limit = self._user_component_cache_limit
        if limit is None or limit <= 0:
            return
        with self._user_component_cache_lock:
            if len(self._user_component_cache) <= limit:
                return
            # 按 last_accessed 排序，淘汰最旧且无人引用的缓存
            candidates = sorted(
                self._user_component_cache.items(),
                key=lambda kv: kv[1].get('last_accessed', 0)
            )
            for username, _ in candidates:
                if len(self._user_component_cache) <= limit:
                    break
                if self._user_component_refcount.get(username, 0) > 0:
                    continue
                self._user_component_cache.pop(username, None)
                self._user_component_refcount.pop(username, None)
                print(f"🗑️ Evicted cached components for '{username}' due to cache limit")
    def _get_or_create_session_components(self, session_id, user):
        """获取或创建Session特定的用户组件"""
        with self._session_components_lock:
            if session_id not in self._session_components:
                components = SessionComponentProxy(self, user)
                self._session_components[session_id] = components
                print(f"✓ Session {session_id[:8]}... for user '{user.username}' initialized (lazy components)")
            
            # 更新最后访问时间
            self._session_components[session_id]['last_accessed'] = time.time()
            
            return self._session_components[session_id]
    
    def get_user_components_by_session(self, session_id):
        """根据session_id获取用户组件"""
        with self._session_components_lock:
            components = self._session_components.get(session_id)
            if components:
                components['last_accessed'] = time.time()
            return components
    
    def get_user_components(self):
        """从请求上下文中获取当前用户的组件"""
        if hasattr(g, 'user_components'):
            return g.user_components
        return None
    
    def is_authenticated(self):
        """检查用户是否已认证"""
        return 'user_id' in session
    
    def get_current_user_obj(self):
        """获取当前用户对象"""
        if 'user_id' in session:
            return self.user_class.get_by_username(session['user_id'])
        return None
    
    """
    def login(self):
        #登录处理
        if request.method == 'POST':
            username = request.form['username'].strip()
            password = request.form['password']
            
            # 与 Firebase 数据库交互验证用户
            user = self.user_class.get_by_username(username)
            
            if not user or not check_password_hash(user.password, password):
                flash('Incorrect username or password.')
                return redirect(url_for('auth.login'))
            
            # 设置会话，保存用户信息
            session['user_id'] = user.username
            session['username'] = user.username
            session['is_admin'] = user.is_admin
            
            # 预初始化用户组件
            session_id = session['session_id']
            self._get_or_create_session_components(session_id, user)
            
            # 登录成功后重定向到主应用界面
            return redirect('/chatapi.html')
        
        return render_template('login.html')
    
    
    def login(self):
        #登录处理
        if request.method == 'POST':
            username = request.form['username'].strip()
            password = request.form['password']
        
            # 与 Firebase 数据库交互验证用户
            user = self.user_class.get_by_username(username)
        
            if not user or not check_password_hash(user.password, password):
                flash('Incorrect username or password.')
                return redirect(url_for('auth.login'))
        
            # 设置会话，保存用户信息
            session['user_id'] = user.username
            session['username'] = user.username
            session['is_admin'] = user.is_admin
        
            # 预初始化用户组件
            session_id = session['session_id']
            self._get_or_create_session_components(session_id, user)
        
            # 重定向到主应用界面，并传递会话ID
            response = redirect('/chatapi.html')
            # 设置一个明确的session_id cookie供前端使用
            response.set_cookie('app_session_id', session_id)
            return response
    
        return render_template('login.html')
        """

    def login(self):
        #登录处理"""
        if request.method == 'POST':
            username = request.form['username'].strip()
            password = request.form['password']
    
            # 与 Firebase 数据库交互验证用户
            user = self.user_class.get_by_username(username)
    
            if not user or not check_password_hash(user.password, password):
                flash('Incorrect username or password.')
                return redirect(url_for('auth.login'))
    
            # 在设置新会话前，先彻底清理旧会话
            old_session_id = session.get('session_id')
            if old_session_id:
                self._release_session_components(old_session_id)
        
            # 重新生成会话ID，确保全新会话
            session.clear()  # 彻底清除所有会话数据
            session['session_id'] = self._generate_session_id()
    
            # 设置会话，保存用户信息
            session['user_id'] = user.username
            session['username'] = user.username
            session['is_admin'] = user.is_admin
    
            # 强制创建新的用户组件
            session_id = session['session_id']
            self._get_or_create_session_components(session_id, user)
    
            print(f"User {username} logged in with new session: {session_id}")
            print(f"Current session data: {dict(session)}")
    
            # 重定向到主应用界面
            response = redirect('/chatapi.html')
            # 设置一个明确的session_id cookie供前端使用
            response.set_cookie('app_session_id', session_id)
        
            return response

        return render_template('login.html')

    def register(self):
        """注册处理"""
        if request.method == 'POST':
            username = request.form['username'].strip()
            password = request.form['password']
            
            # 检查用户是否已存在
            if self.user_class.get_by_username(username):
                flash('Username already exists!')
                return redirect(url_for('auth.register'))
            
            # 创建新用户并保存到 Firebase
            user = self.user_class(username, generate_password_hash(password), False)
            user.save()
            
            flash('Registration successful! Please log in.')
            return redirect(url_for('auth.login'))
        
        return render_template('register.html')
    
    def logout(self):
        """登出处理"""
        session_id = session.get('session_id')
        if session_id:
            self._release_session_components(session_id)
        
        session.clear()
        return redirect(url_for('auth.login'))
    
    def get_current_user(self):
        """获取当前用户信息（API接口）"""
        if 'user_id' in session:
            return jsonify({
                'user_id': session['user_id'],
                'username': session['username'],
                'is_admin': session.get('is_admin', False)
            })
        else:
            return jsonify({'error': 'Not logged in'}), 401
    
    def get_system_status(self):
        """获取系统状态（内存、活跃会话等）"""
        try:
            process = psutil.Process(os.getpid())
            memory_info = process.memory_info()
            memory_percent = process.memory_percent()
            
            # 系统总内存
            system_memory = psutil.virtual_memory()
            
            with self._session_components_lock:
                active_sessions = len(self._session_components)
                sessions_info = []
                for sid, comp in self._session_components.items():
                    user = comp.get('user')
                    sessions_info.append({
                        'session_id': sid[:8] + '...',
                        'username': user.username if user else 'unknown',
                        'last_accessed': time.strftime('%H:%M:%S', time.localtime(comp.get('last_accessed', 0)))
                    })
            
            status = {
                'memory': {
                    'process_mb': round(memory_info.rss / 1024 / 1024, 2),
                    'process_percent': round(memory_percent, 2),
                    'system_total_gb': round(system_memory.total / 1024 / 1024 / 1024, 2),
                    'system_used_percent': system_memory.percent
                },
                'sessions': {
                    'active_count': active_sessions,
                    'details': sessions_info
                },
                'shared_components': {
                    'quiz_app_id': id(self._shared_quiz_app) if self._shared_quiz_app else None
                }
            }
            
            return jsonify(status)
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    
    def cleanup_expired_sessions(self, max_inactive_time=3600):
        """清理过期的Session，返回清理数量"""
        current_time = time.time()
        
        expired_sessions = []
        with self._session_components_lock:
            for session_id, components in list(self._session_components.items()):
                if current_time - components.get('last_accessed', 0) > max_inactive_time:
                    expired_sessions.append(session_id)
        
        for session_id in expired_sessions:
            self._release_session_components(session_id)
            print(f"  • Session {session_id[:8]}... released (inactive)")
        
        return len(expired_sessions)
    
    def get_all_sessions(self):
        """获取所有活跃会话用于调试"""
        with self._session_components_lock:
            return list(self._session_components.keys())
    
    def _start_session_cleanup_thread(self):
        """启动后台线程定期清理过期会话"""
        def cleanup_worker():
            while True:
                time.sleep(120)  # 每2分钟清理一次
                try:
                    # 清理10分钟不活动的会话
                    expired_count = self.cleanup_expired_sessions(max_inactive_time=600)
                    if expired_count > 0:
                        print(f"🧹 Cleaned up {expired_count} inactive session(s)")
                    
                    # 打印内存使用情况
                    import psutil
                    process = psutil.Process()
                    memory_mb = process.memory_info().rss / 1024 / 1024
                    print(f"📊 Memory usage: {memory_mb:.1f} MB, Active sessions: {len(self._session_components)}, Cached users: {len(self._user_component_cache)}")
                except Exception as e:
                    print(f"❌ Error in session cleanup: {e}")
        
        cleanup_thread = threading.Thread(target=cleanup_worker, daemon=True, name="SessionCleanup")
        cleanup_thread.start()
        print("✓ Session cleanup thread started (checks every 2 min, removes after 10 min inactivity)")