from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from datetime import datetime
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your_secret_key_here'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///project_management.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# Models
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    register_no = db.Column(db.String(20), unique=True, nullable=True)  # Only for students
    password_hash = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), nullable=False)  # 'manager' or 'student'
    
    teams = db.relationship('TeamMember', back_populates='user', cascade="all, delete-orphan")
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
        
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Team(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    members = db.relationship('TeamMember', back_populates='team', cascade="all, delete-orphan")
    tasks = db.relationship('Task', back_populates='team', cascade="all, delete-orphan")

class TeamMember(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=False)
    
    user = db.relationship('User', back_populates='teams')
    team = db.relationship('Team', back_populates='members')

class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), default='To Start')  # 'To Start', 'In Progress', 'Completed'
    time_spent = db.Column(db.Float, default=0.0)  # Hours spent on the task
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=False)
    team = db.relationship('Team', back_populates='tasks')
    
    def update_status(self, new_status, hours_spent=None):
        self.status = new_status
        if hours_spent is not None:
            self.time_spent += float(hours_spent)
        self.updated_at = datetime.utcnow()

# Decorators for route protection
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to access this page', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def manager_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to access this page', 'warning')
            return redirect(url_for('login'))
        
        user = User.query.get(session['user_id'])
        if user.role != 'manager':
            flash('Access denied. Manager privileges required.', 'danger')
            return redirect(url_for('dashboard'))
        
        return f(*args, **kwargs)
    return decorated_function

@app.context_processor
def inject_year():
    return {'current_year': datetime.now().year}

# Routes
@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return render_template('dashboard.html', current_time=datetime.now())

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        identifier = request.form.get('identifier')  # username or register_no
        password = request.form.get('password')
        
        # Try to find user by username or register_no
        user = User.query.filter((User.username == identifier) | 
                                (User.register_no == identifier)).first()
        
        if user and user.check_password(password):
            session['user_id'] = user.id
            flash(f'Welcome, {user.username}!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid credentials. Please try again.', 'danger')
    
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        role = request.form.get('role')
        register_no = request.form.get('register_no') if role == 'student' else None
        
        # Check if username already exists
        existing_username = User.query.filter_by(username=username).first()
        
        if existing_username:
            flash('Username already exists!', 'danger')
        elif role == 'student' and register_no:
            # Only check register_no for students
            existing_register = User.query.filter_by(register_no=register_no).first()
            if existing_register:
                flash('Register Number already exists!', 'danger')
            else:
                new_user = User(username=username, role=role, register_no=register_no)
                new_user.set_password(password)
                
                db.session.add(new_user)
                db.session.commit()
                
                flash('Registration successful! Please log in.', 'success')
                return redirect(url_for('login'))
        else:
            # For managers or students without register number
            new_user = User(username=username, role=role, register_no=register_no)
            new_user.set_password(password)
            
            db.session.add(new_user)
            db.session.commit()
            
            flash('Registration successful! Please log in.', 'success')
            return redirect(url_for('login'))
    
    return render_template('register.html')

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    flash('You have been logged out successfully.', 'info')
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    user = User.query.get(session['user_id'])
    
    if user.role == 'manager':
        teams = Team.query.all()
        return render_template('manager_dashboard.html', teams=teams, user=user)
    else:  # student
        # Find team of the student
        team_member = TeamMember.query.filter_by(user_id=user.id).first()
        
        if team_member:
            team = team_member.team
            tasks = Task.query.filter_by(team_id=team.id).all()
            
            # Calculate task statistics
            to_start_count = sum(1 for task in tasks if task.status == 'To Start')
            in_progress_count = sum(1 for task in tasks if task.status == 'In Progress')
            completed_count = sum(1 for task in tasks if task.status == 'Completed')
            total_count = len(tasks)
            completion_rate = (completed_count / total_count * 100) if total_count > 0 else 0
            
            return render_template('student_dashboard.html', 
                                  team=team, 
                                  tasks=tasks,
                                  user=user,
                                  to_start_count=to_start_count,
                                  in_progress_count=in_progress_count,
                                  completed_count=completed_count,
                                  completion_rate=completion_rate)
        else:
            flash('You are not assigned to any team yet.', 'warning')
            return render_template('student_dashboard.html', team=None, user=user)

@app.route('/team/<int:team_id>')
@login_required
def team_details(team_id):
    user = User.query.get(session['user_id'])
    team = Team.query.get_or_404(team_id)
    
    # Check if manager or team member
    if user.role == 'manager' or TeamMember.query.filter_by(user_id=user.id, team_id=team_id).first():
        team_members = User.query.join(TeamMember).filter(TeamMember.team_id == team_id).all()
        tasks = Task.query.filter_by(team_id=team_id).all()
        
        # Calculate task statistics
        total_tasks = len(tasks)
        completed_tasks = sum(1 for task in tasks if task.status == 'Completed')
        in_progress_tasks = sum(1 for task in tasks if task.status == 'In Progress')
        to_start_tasks = sum(1 for task in tasks if task.status == 'To Start')
        
        stats = {
            'total': total_tasks,
            'completed': completed_tasks,
            'in_progress': in_progress_tasks,
            'to_start': to_start_tasks,
            'completion_rate': (completed_tasks / total_tasks * 100) if total_tasks > 0 else 0
        }
        
        return render_template('team_details.html', team=team, members=team_members, 
                              tasks=tasks, stats=stats, user=user)
    else:
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard'))

@app.route('/create_team', methods=['GET', 'POST'])
@manager_required
def create_team():
    if request.method == 'POST':
        team_name = request.form.get('team_name')
        
        new_team = Team(name=team_name)
        db.session.add(new_team)
        db.session.commit()
        
        flash(f'Team "{team_name}" created successfully!', 'success')
        return redirect(url_for('dashboard'))
    
    return render_template('create_team.html')

@app.route('/add_member/<int:team_id>', methods=['GET', 'POST'])
@manager_required
def add_member(team_id):
    team = Team.query.get_or_404(team_id)
    
    if request.method == 'POST':
        register_no = request.form.get('register_no')
        student = User.query.filter_by(register_no=register_no, role='student').first()
        
        if not student:
            flash('Student not found with the given register number.', 'danger')
        else:
            # Check if student is already in a team
            existing_member = TeamMember.query.filter_by(user_id=student.id).first()
            if existing_member:
                flash(f'Student is already a member of team "{existing_member.team.name}"', 'warning')
            else:
                # Check if team already has 4 members
                member_count = TeamMember.query.filter_by(team_id=team_id).count()
                if member_count >= 4:
                    flash('Team is already at maximum capacity (4 members).', 'warning')
                else:
                    new_member = TeamMember(user_id=student.id, team_id=team_id)
                    db.session.add(new_member)
                    db.session.commit()
                    flash(f'Added {student.username} to the team!', 'success')
        
        return redirect(url_for('team_details', team_id=team_id))
    
    return render_template('add_member.html', team=team)

@app.route('/remove_member/<int:team_id>/<int:user_id>')
@manager_required
def remove_member(team_id, user_id):
    member = TeamMember.query.filter_by(team_id=team_id, user_id=user_id).first_or_404()
    
    db.session.delete(member)
    db.session.commit()
    
    flash('Team member removed successfully.', 'success')
    return redirect(url_for('team_details', team_id=team_id))

@app.route('/create_task/<int:team_id>', methods=['GET', 'POST'])
@manager_required
def create_task(team_id):
    team = Team.query.get_or_404(team_id)
    
    if request.method == 'POST':
        title = request.form.get('title')
        description = request.form.get('description')
        
        new_task = Task(
            title=title,
            description=description,
            team_id=team_id
        )
        
        db.session.add(new_task)
        db.session.commit()
        
        flash('Task created successfully!', 'success')
        return redirect(url_for('team_details', team_id=team_id))
    
    return render_template('create_task.html', team=team)

@app.route('/update_task/<int:task_id>', methods=['GET', 'POST'])
@login_required
def update_task(task_id):
    task = Task.query.get_or_404(task_id)
    user = User.query.get(session['user_id'])
    
    # Check if user is manager or a member of the task's team
    is_team_member = TeamMember.query.filter_by(user_id=user.id, team_id=task.team_id).first()
    
    if user.role != 'manager' and not is_team_member:
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        new_status = request.form.get('status')
        time_spent = request.form.get('time_spent', 0)
        
        # Update task
        task.update_status(new_status, time_spent)
        
        # If manager is updating, also update other fields
        if user.role == 'manager':
            task.title = request.form.get('title')
            task.description = request.form.get('description')
        
        db.session.commit()
        flash('Task updated successfully!', 'success')
        
        # Redirect back to appropriate page
        if user.role == 'manager':
            return redirect(url_for('team_details', team_id=task.team_id))
        else:
            return redirect(url_for('dashboard'))
    
    return render_template('update_task.html', task=task, user=user)

@app.route('/delete_task/<int:task_id>')
@manager_required
def delete_task(task_id):
    task = Task.query.get_or_404(task_id)
    team_id = task.team_id
    
    db.session.delete(task)
    db.session.commit()
    
    flash('Task deleted successfully.', 'success')
    return redirect(url_for('team_details', team_id=team_id))

# # Initialize database
# @app.before_first_request
# def create_tables():
#     db.create_all()
    
#     # Create a default manager if none exists
#     if not User.query.filter_by(role='manager').first():
#         default_manager = User(username='admin', role='manager')
#         default_manager.set_password('admin')
#         db.session.add(default_manager)
#         db.session.commit()

if __name__ == '__main__':
    # Create the database directory if it doesn't exist
    if not os.path.exists('instance'):
        os.makedirs('instance')
    
    # Initialize the database and create default user
    with app.app_context():
        db.create_all()
        
        # Create a default manager if none exists
        if not User.query.filter_by(role='manager').first():
            default_manager = User(username='admin', role='manager')
            default_manager.set_password('admin')
            db.session.add(default_manager)
            db.session.commit()
    
    # Run the app
    app.run(debug=True)