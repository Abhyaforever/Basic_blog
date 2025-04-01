import os
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Length, Email
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
from datetime import datetime
import pytz  # Add this import at the top
load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'a_default_secret_key_for_development')
# Use SQLite for simplicity, can be changed to PostgreSQL later
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///blog.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
migrate = Migrate(app, db)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message_category = 'info'

# --- Models ---

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(128))

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f'<User {self.username}>'

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_name = db.Column(db.String(100), nullable=False)
    content = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, server_default=db.func.now())
    is_reviewed = db.Column(db.Boolean, default=False)
    is_published = db.Column(db.Boolean, default=False) # To track if it became a blog post

    @property
    def ist_timestamp(self):
        """Convert UTC timestamp to IST"""
        ist = pytz.timezone('Asia/Kolkata')
        return self.timestamp.replace(tzinfo=pytz.UTC).astimezone(ist)

    def __repr__(self):
        return f'<Message {self.id} from {self.sender_name}>'

class BlogPost(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    message_id = db.Column(db.Integer, db.ForeignKey('message.id'), nullable=True) # Link back to original message if applicable
    message = db.relationship('Message', backref=db.backref('blog_post', uselist=False))

    @property
    def ist_timestamp(self):
        """Convert UTC timestamp to IST"""
        ist = pytz.timezone('Asia/Kolkata')
        return self.timestamp.replace(tzinfo=pytz.UTC).astimezone(ist)

    def __repr__(self):
        return f'<BlogPost {self.id}: {self.title}>'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- Forms ---

class LoginForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired()])
    password = PasswordField('Password', validators=[DataRequired()])
    submit = SubmitField('Login')

class MessageForm(FlaskForm):
    sender_name = StringField('Your Name', validators=[DataRequired(), Length(min=2, max=100)])
    content = TextAreaField('Message', validators=[DataRequired(), Length(min=10)])
    submit = SubmitField('Send Message')

class BlogPostForm(FlaskForm):
    title = StringField('Title', validators=[DataRequired(), Length(min=3, max=200)])
    content = TextAreaField('Content', validators=[DataRequired()])
    submit = SubmitField('Publish Post')

# --- Routes ---

@app.route('/')
def index():
    posts = BlogPost.query.order_by(BlogPost.timestamp.desc()).all()
    return render_template('index.html', 
                         posts=posts, 
                         now=datetime.now(pytz.timezone('Asia/Kolkata')))

@app.route('/submit_message', methods=['GET', 'POST'])
def submit_message():
    form = MessageForm()
    if form.validate_on_submit():
        message = Message(sender_name=form.sender_name.data, content=form.content.data)
        db.session.add(message)
        db.session.commit()
        flash('Your message has been sent successfully!', 'success')
        return redirect(url_for('index')) # Or a dedicated thank you page
    return render_template('submit_message.html', form=form, now=datetime.now())

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('admin_dashboard'))
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if user and user.check_password(form.password.data):
            login_user(user)
            next_page = request.args.get('next')
            flash('Login successful!', 'success')
            return redirect(next_page) if next_page else redirect(url_for('admin_dashboard'))
        else:
            flash('Login Unsuccessful. Please check username and password', 'danger')
    return render_template('login.html', form=form, now=datetime.now())

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('index'))

@app.route('/admin')
@login_required
def admin_dashboard():
    messages = Message.query.filter_by(is_reviewed=False).order_by(Message.timestamp.asc()).all()
    posts = BlogPost.query.order_by(BlogPost.timestamp.desc()).all()
    
    # Current time in IST
    ist_now = datetime.now(pytz.timezone('Asia/Kolkata'))
    
    return render_template('admin_dashboard.html', 
                         messages=messages,
                         posts=posts,
                         now=ist_now)

# Create a timezone object for IST
ist = pytz.timezone('Asia/Kolkata')

@app.route('/admin/review_message/<int:message_id>', methods=['GET', 'POST'])
@login_required
def review_message(message_id):
    message = Message.query.get_or_404(message_id)
    form = BlogPostForm()

    if request.method == 'POST': # Handle form submission for creating post
        if form.validate_on_submit():
            post = BlogPost(
                title=form.title.data,
                content=form.content.data,
                message_id=message.id,
                timestamp=datetime.utcnow()  # Explicitly set UTC time
            )
            db.session.add(post)
            message.is_reviewed = True
            message.is_published = True
            db.session.commit()
            flash('Blog post created successfully!', 'success')
            return redirect(url_for('admin_dashboard'))
    elif request.method == 'GET': # Pre-populate form for review
        form.title.data = f"From {message.sender_name}" # Suggest a title
        form.content.data = message.content

    # Convert UTC time to IST
    ist_time = message.timestamp.replace(tzinfo=pytz.UTC).astimezone(ist)
    
    # Pass the converted time to template
    return render_template('review_message.html', 
                         form=form, 
                         message=message, 
                         ist_time=ist_time,
                         now=datetime.now(ist))

@app.route('/admin/mark_reviewed/<int:message_id>', methods=['POST'])
@login_required
def mark_reviewed(message_id):
    message = Message.query.get_or_404(message_id)
    message.is_reviewed = True
    db.session.commit()
    flash('Message marked as reviewed.', 'info')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/edit_post/<int:post_id>', methods=['GET', 'POST'])
@login_required
def edit_post(post_id):
    post = BlogPost.query.get_or_404(post_id)
    form = BlogPostForm(obj=post) # Pre-populate form with post data

    if form.validate_on_submit():
        post.title = form.title.data
        post.content = form.content.data
        db.session.commit()
        flash('Blog post updated successfully!', 'success')
        return redirect(url_for('admin_dashboard'))

    return render_template('edit_post.html', form=form, post=post, now=datetime.now())

@app.route('/admin/delete_post/<int:post_id>', methods=['POST'])
@login_required
def delete_post(post_id):
    post = BlogPost.query.get_or_404(post_id)
    # Optionally mark related message as not published if needed
    if post.message:
        post.message.is_published = False
    db.session.delete(post)
    db.session.commit()
    flash('Blog post deleted successfully!', 'success')
    return redirect(url_for('admin_dashboard'))

# --- CLI Commands ---
@app.cli.command('create-user')
def create_user():
    """Creates the initial admin user."""
    username = input('Enter admin username: ')
    password = input('Enter admin password: ')
    existing_user = User.query.filter_by(username=username).first()
    if existing_user:
        print(f'User {username} already exists.')
        return
    user = User(username=username)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    print(f'Admin user {username} created successfully.')


if __name__ == '__main__':
    # Create tables if they don't exist (useful for initial setup with SQLite)
    with app.app_context():
        db.create_all()
    app.run(debug=True) # Turn off debug in production
