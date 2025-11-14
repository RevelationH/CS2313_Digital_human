from flask import Flask, Blueprint, render_template, request, redirect, url_for, session, flash, jsonify, g
from werkzeug.security import generate_password_hash, check_password_hash
from user import User
import threading
import time
import uuid
import psutil
import os

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
        self._quiz_app_routes_registered = False
        
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
            # 确保Session ID存在
            if 'session_id' not in session:
                session['session_id'] = self._generate_session_id()
            
            session_id = session['session_id']
            
            # 如果用户已登录，确保用户组件可用
            if self.is_authenticated():
                user = self.get_current_user_obj()
                if user:
                    g.user_components = self._get_or_create_session_components(session_id, user)
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
    
    def _get_or_create_session_components(self, session_id, user):
        """获取或创建Session特定的用户组件"""
        from retrival import re_and_exc, intent, avatar_text
        with self._session_components_lock:
            if session_id not in self._session_components:
                components = {
                    'rae': re_and_exc(user),
                    'input_intent': intent(user),
                    'avatar_input': avatar_text(user),
                    'quiz_app': self._shared_quiz_app,
                    'user': user,
                    'last_accessed': time.time()
                }
                self._session_components[session_id] = components
                print(f"✓ Session {session_id[:8]}... for user '{user.username}' initialized")
            
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
            if old_session_id and old_session_id in self._session_components:
                with self._session_components_lock:
                    del self._session_components[old_session_id]
                    print(f"Cleaned up old session components: {old_session_id}")
        
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
        if session_id and session_id in self._session_components:
            # 清理用户组件
            with self._session_components_lock:
                del self._session_components[session_id]
        
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
        
        with self._session_components_lock:
            expired_sessions = []
            for session_id, components in self._session_components.items():
                if current_time - components.get('last_accessed', 0) > max_inactive_time:
                    expired_sessions.append(session_id)
            
            for session_id in expired_sessions:
                user = self._session_components[session_id].get('user')
                username = user.username if user else 'unknown'
                del self._session_components[session_id]
                print(f"  • Session {session_id[:8]}... (user: {username})")
            
            return len(expired_sessions)
    
    def get_all_sessions(self):
        """获取所有活跃会话用于调试"""
        with self._session_components_lock:
            return list(self._session_components.keys())
    
    def _start_session_cleanup_thread(self):
        """启动后台线程定期清理过期会话"""
        def cleanup_worker():
            while True:
                time.sleep(180)  # 每3分钟清理一次（更频繁）
                try:
                    expired_count = self.cleanup_expired_sessions(max_inactive_time=900)  # 15分钟不活动就清理（更激进）
                    if expired_count > 0:
                        print(f"🧹 Cleaned up {expired_count} inactive session(s)")
                except Exception as e:
                    print(f"❌ Error in session cleanup: {e}")
        
        cleanup_thread = threading.Thread(target=cleanup_worker, daemon=True, name="SessionCleanup")
        cleanup_thread.start()
        print("✓ Session cleanup thread started (checks every 3 min, removes after 15 min inactivity)")