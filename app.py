from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime
import os
from dotenv import load_dotenv
import yookassa
from yookassa import Configuration, Payment

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-key')
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///site.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# Yookassa config
Configuration.account_id = os.getenv('YOOKASSA_SHOP_ID')
Configuration.secret_key = os.getenv('YOOKASSA_SECRET_KEY')

# Models
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(150), nullable=False)
    balance = db.Column(db.Float, default=0.0)
    listings = db.relationship('Listing', backref='seller', lazy=True)

class Listing(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)
    price = db.Column(db.Float, nullable=False)
    game = db.Column(db.String(100), nullable=False)
    image = db.Column(db.String(200))
    seller_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    status = db.Column(db.String(50), default='active')  # active, sold, pending
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Routes
@app.route('/')
def index():
    listings = Listing.query.filter_by(status='active').order_by(Listing.created_at.desc()).all()
    return render_template('index.html', listings=listings)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = generate_password_hash(request.form['password'], method='pbkdf2:sha256')
        if User.query.filter_by(username=username).first():
            flash('Username already exists')
            return redirect(url_for('register'))
        user = User(username=username, email=email, password=password)
        db.session.add(user)
        db.session.commit()
        flash('Registered successfully!')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form['username']).first()
        if user and check_password_hash(user.password, request.form['password']):
            login_user(user)
            return redirect(url_for('index'))
        flash('Invalid credentials')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/add_listing', methods=['GET', 'POST'])
@login_required
def add_listing():
    if request.method == 'POST':
        title = request.form['title']
        description = request.form['description']
        price = float(request.form['price'])
        game = request.form['game']
        image = request.files.get('image')
        filename = None
        if image:
            filename = secure_filename(image.filename)
            image.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        listing = Listing(title=title, description=description, price=price, game=game, image=filename, seller_id=current_user.id)
        db.session.add(listing)
        db.session.commit()
        flash('Listing added!')
        return redirect(url_for('index'))
    return render_template('add_listing.html')

@app.route('/buy/<int:listing_id>', methods=['POST'])
@login_required
def buy(listing_id):
    listing = Listing.query.get_or_404(listing_id)
    if listing.seller_id == current_user.id:
        flash('Cannot buy your own listing')
        return redirect(url_for('index'))
    
    # Create Yookassa payment
    idempotence_key = str(datetime.utcnow().timestamp())
    payment = Payment.create({
        "amount": {
            "value": f"{listing.price:.2f}",
            "currency": "RUB"
        },
        "confirmation": {
            "type": "redirect",
            "return_url": url_for('confirm_payment', _external=True)
        },
        "capture": True,
        "description": f"Purchase: {listing.title}",
        "metadata": {"listing_id": listing_id}
    }, idempotence_key)
    
    # Simple escrow: mark as pending
    listing.status = 'pending'
    db.session.commit()
    
    return redirect(payment.confirmation.confirmation_url)

@app.route('/confirm_payment')
def confirm_payment():
    # Handle Yookassa callback (simplified - in real use webhook)
    flash('Payment processed! Check your email for delivery.')
    return redirect(url_for('index'))

@app.route('/profile')
@login_required
def profile():
    user_listings = Listing.query.filter_by(seller_id=current_user.id).all()
    return render_template('profile.html', listings=user_listings)

if __name__ == '__main__':
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    with app.app_context():
        db.create_all()
    app.run(debug=True)
