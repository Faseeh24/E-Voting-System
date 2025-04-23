from flask import Flask, request, render_template, redirect, url_for, session
import firebase_admin
from firebase_admin import credentials, firestore
from werkzeug.security import generate_password_hash, check_password_hash
from blockchain import Blockchain  # Import the Blockchain class
import time

# Initialize Flask app
app = Flask(__name__)
app.secret_key = 'your_secret_key'  # Replace with a secure secret key

# Initialize Firestore DB
cred = credentials.Certificate("E:/University/IS Lab/Semester Project/KEYS/Google Cloud FireStore API.json")
firebase_admin.initialize_app(cred)
db = firestore.client()
users_collection = db.collection('users')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')

        if not email or not password:
            return render_template('signup.html', error="Email and password are required")

        # Check if user already exists
        if users_collection.document(email).get().exists:
            return render_template('signup.html', error="User already exists")

        # Hash the password before storing
        hashed_password = generate_password_hash(password)
        users_collection.document(email).set({"password": hashed_password})
        return redirect(url_for('login'))

    return render_template('signup.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')

        if not email or not password:
            return render_template('login.html', error="Email and password are required")

        # Verify user credentials
        user_doc = users_collection.document(email).get()
        if not user_doc.exists or not check_password_hash(user_doc.to_dict().get('password'), password):
            return render_template('login.html', error="Invalid email or password")

        # Set session for logged-in user
        session['user'] = email
        return redirect(url_for('home'))

    return render_template('login.html')

@app.route('/home')
def home():
    if 'user' not in session:
        return redirect(url_for('login'))
    return render_template('home.html', user=session['user'])

@app.route('/add_poll', methods=['GET', 'POST'])
def add_poll():
    if 'user' not in session:
        return redirect(url_for('login'))
    if request.method == 'POST':
        poll_name = request.form.get('poll_name')
        closing_date = request.form.get('closing_date')
        candidates = request.form.getlist('candidates')

        if not poll_name or not closing_date or not candidates:
            return render_template('add_poll.html', error="All fields are required")

        # Save poll data to Firestore with auto-generated document ID
        poll_ref = db.collection('polls').document()
        poll_ref.set({
            "poll_name": poll_name,
            'created_by': session['user'],
            'closing_date': closing_date,
            'candidates': candidates,
            'votes': {candidate.replace(" ", "_"): 0 for candidate in candidates},
            'created_at': firestore.SERVER_TIMESTAMP
        })

        return redirect(url_for('home'))

    return render_template('add_poll.html')

@app.route('/cast_vote', methods=['GET', 'POST'])
def cast_vote():
    if 'user' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
        poll_name = request.form.get('poll_name')
        candidate = request.form.get('candidate')

        if not poll_name or not candidate:
            return render_template('cast_vote.html', error="Please select a poll and a candidate")

        # Fetch the poll document by name
        poll_ref = db.collection('polls').where('poll_name', '==', poll_name).stream()
        poll_doc = next(poll_ref, None)  # Get the first matching document
        if not poll_doc:
            return render_template('cast_vote.html', error="Poll not found")

        poll_id = poll_doc.id

        # Check if the user has already voted in this poll
        votes_ref = db.collection(f'polls/{poll_id}/votes').document(session['user'])
        if votes_ref.get().exists:
            return render_template('cast_vote.html', error="You have already voted in this poll")

        # Add the vote to the blockchain
        blockchain = Blockchain(db, poll_id)
        blockchain.add_block({
            'voter': session['user'],
            'candidate': candidate
        })

        # Increment the vote count for the selected candidate in the poll document
        poll_doc_ref = db.collection('polls').document(poll_id)
        poll_doc_ref.update({f'votes.{candidate.replace(" ", "_")}': firestore.Increment(1)})

        # Mark the user as having voted in this poll
        votes_ref.set({'voted': True})

        return redirect(url_for('home'))

    # Fetch only ongoing polls
    today = time.strftime('%Y-%m-%d')
    polls_ref = db.collection('polls').where('closing_date', '>=', today).stream()
    ongoing_polls = []
    for poll in polls_ref:
        poll_data = poll.to_dict()
        # Check if the user has already voted in this poll
        vote_ref = db.collection(f'polls/{poll.id}/votes').document(session['user'])
        if not vote_ref.get().exists:
            ongoing_polls.append({
                'name': poll_data['poll_name'],
                'candidates': poll_data['candidates']
            })
    return render_template('cast_vote.html', polls=ongoing_polls)

@app.route('/view_votes')
def view_votes():
    if 'user' not in session:
        return redirect(url_for('login'))

    # Fetch all polls
    today = time.strftime('%Y-%m-%d')
    polls_ref = db.collection('polls').stream()
    ongoing_polls = []
    past_polls = []

    for poll in polls_ref:
        poll_data = poll.to_dict()
        poll_id = poll.id

        # Categorize polls into ongoing and past
        if poll_data['closing_date'] >= today:
            ongoing_polls.append({
                'name': poll_data['poll_name'],
                'closing_date': poll_data['closing_date'],
                'created_by': poll_data['created_by'],
                'id': poll_id
            })
        else:
            past_polls.append({
                'name': poll_data['poll_name'],
                'closing_date': poll_data['closing_date'],
                'created_by': poll_data['created_by'],
                'id': poll_id
            })

    return render_template('view_votes.html', ongoing_polls=ongoing_polls, past_polls=past_polls)

@app.route("/view_poll_details/<poll_id>")
def view_poll_details(poll_id):
    if 'user' not in session:
        return redirect(url_for('login'))

    # Fetch the poll document by ID
    poll_ref = db.collection('polls').document(poll_id)
    poll_doc = poll_ref.get()
    if not poll_doc.exists:
        return render_template('poll_details.html', error="Poll not found")

    poll_data = poll_doc.to_dict()

    # Extract vote counts
    vote_counts = poll_data.get('votes', {})
    vote_counts = {candidate.replace("_", " "): count for candidate, count in vote_counts.items()}

    return render_template('poll_details.html', poll_name=poll_data['poll_name'], vote_counts=vote_counts)

@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True)
