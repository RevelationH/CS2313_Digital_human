from flask import Flask, Blueprint, render_template, request, redirect, url_for, session, flash, jsonify, g
from werkzeug.security import generate_password_hash, check_password_hash
from user import User
import threading
import time
import uuid

class AuthSystem:
    def __init__(self, user_class, secret_key='demo123'):
        self.user_class = user_class
        self.secret_key = secret_key
        self.bp = Blueprint('auth', __name__)
        
        # Session ID 到用户组件的映射
        self._session_components_lock = threading.RLock()
        self._session_components = {}  # session_id -> components
        
        self._setup_routes()
        self._setup_middleware()
    
    def _setup_routes(self):
        """设置认证相关的路由"""
        self.bp.route('/login', methods=['GET', 'POST'])(self.login)
        self.bp.route('/register', methods=['GET', 'POST'])(self.register)
        self.bp.route('/logout')(self.logout)
        self.bp.route('/auth/current_user')(self.get_current_user)
    
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
    
    def _get_or_create_session_components(self, session_id, user):
        """获取或创建Session特定的用户组件"""
        with self._session_components_lock:
            if session_id not in self._session_components:
                from retrival import re_and_exc, intent, avatar_text
                from quiz_app import QuizApp
                
                components = {
                    'rae': re_and_exc(user),
                    'input_intent': intent(user),
                    'avatar_input': avatar_text(user),
                    'quiz_app': QuizApp(user, host='0.0.0.0', port=50012),
                    'user': user,
                    'last_accessed': time.time()
                }
                self._session_components[session_id] = components
                print(f"Created components for session: {session_id}, user: {user.username}")
            
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
    
    def cleanup_expired_sessions(self, max_inactive_time=3600):
        """清理过期的Session"""
        current_time = time.time()
        
        with self._session_components_lock:
            expired_sessions = []
            for session_id, components in self._session_components.items():
                if current_time - components.get('last_accessed', 0) > max_inactive_time:
                    expired_sessions.append(session_id)
            
            for session_id in expired_sessions:
                del self._session_components[session_id]
                print(f"Cleaned up expired session: {session_id}")
    
    def get_all_sessions(self):
        """获取所有活跃会话用于调试"""
        with self._session_components_lock:
            return list(self._session_components.keys())