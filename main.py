from flask import Flask, request, jsonify, redirect, url_for, session
from flask_cors import CORS
import firebase_admin
from firebase_admin import credentials, firestore
from werkzeug.security import generate_password_hash, check_password_hash
from blockchain import Blockchain  # Import the Blockchain class
import time

# Initialize Flask app
app = Flask(__name__)
app.secret_key = 'your_secret_key'  # Replace with a secure secret key
CORS(app, origins=["http://localhost:5173"], supports_credentials=True)

# Initialize Firestore DB
cred = credentials.Certificate("./KEYS/Google Cloud FireStore API.json")
firebase_admin.initialize_app(cred)
db = firestore.client()
users_collection = db.collection('users')



@app.route('/signup', methods=['POST'])
def signup():
    data = request.get_json()
    email = data.get('email')
    password = data.get('password')
    username = data.get('username')
    name = data.get('name')  # Full name

    # Basic validation
    if not email or not password or not username or not name:
        return jsonify({"error": "Email, password, username, and name are required"}), 400

    # Check if user already exists
    if users_collection.document(email).get().exists:
        return jsonify({"error": "User already exists"}), 400

    # Hash the password before storing
    hashed_password = generate_password_hash(password)

    # Save user data to Firestore
    users_collection.document(email).set({
        "email": email,
        "password": hashed_password,
        "username": username,
        "name": name
    })

    return jsonify({"message": "Signup successful"}), 201

@app.route('/delete_all_users', methods=['GET'])
def delete_all_users():
    try:
        users = users_collection.stream()
        deleted = 0

        for user in users:
            users_collection.document(user.id).delete()
            deleted += 1

        return jsonify({"message": f"Deleted {deleted} users"}), 200

    except Exception as e:
        print("Error deleting users:", e)
        return jsonify({"error": "Failed to delete users"}), 500


@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    email = data.get('email')
    password = data.get('password')

    if not email or not password:
        return jsonify({"error": "Email and password are required"}), 400

    # Verify user credentials
    user_doc = users_collection.document(email).get()
    if not user_doc.exists or not check_password_hash(user_doc.to_dict().get('password'), password):
        return jsonify({"error": "Invalid email or password"}), 401

    # Retrieve the full user object
    user_data = user_doc.to_dict()
    print(user_data)

    # Set session for logged-in user
    session['user'] = email

    return jsonify({"message": "Login successful", "user": user_data}), 200


@app.route('/home', methods=['GET'])
def home():
    if 'user' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    return jsonify({"message": "Welcome to the home page", "user": session['user']}), 200

@app.route('/add_poll', methods=['POST'])
def add_poll():
    if 'user' not in session:
        return jsonify({"error": "Unauthorized"}), 401

    poll_name = request.json.get('poll_name')
    closing_date = request.json.get('closing_date')
    candidates = request.json.get('candidates')

    if not poll_name or not closing_date or not candidates:
        return jsonify({"error": "All fields are required"}), 400

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

    return jsonify({"message": "Poll created successfully"}), 201

@app.route('/cast_vote', methods=['POST'])
def cast_vote():
    if 'user' not in session:
        return jsonify({"error": "Unauthorized"}), 401

    poll_name = request.json.get('poll_name')
    candidate = request.json.get('candidate')

    if not poll_name or not candidate:
        return jsonify({"error": "Poll name and candidate are required"}), 400

    # Fetch the poll document by name
    poll_ref = db.collection('polls').where('poll_name', '==', poll_name).stream()
    poll_doc = next(poll_ref, None)  # Get the first matching document
    if not poll_doc:
        return jsonify({"error": "Poll not found"}), 404

    poll_id = poll_doc.id

    # Check if the user has already voted in this poll
    votes_ref = db.collection(f'polls/{poll_id}/votes').document(session['user'])
    if votes_ref.get().exists:
        return jsonify({"error": "You have already voted in this poll"}), 400

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

    return jsonify({"message": "Vote cast successfully"}), 200

@app.route('/view_votes', methods=['GET'])
def view_votes():
    if 'user' not in session:
        return jsonify({"error": "Unauthorized"}), 401

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

    return jsonify({"ongoing_polls": ongoing_polls, "past_polls": past_polls}), 200

@app.route("/view_poll_details/<poll_id>", methods=['GET'])
def view_poll_details(poll_id):
    if 'user' not in session:
        return jsonify({"error": "Unauthorized"}), 401

    # Fetch the poll document by ID
    poll_ref = db.collection('polls').document(poll_id)
    poll_doc = poll_ref.get()
    if not poll_doc.exists:
        return jsonify({"error": "Poll not found"}), 404

    poll_data = poll_doc.to_dict()

    # Extract vote counts
    vote_counts = poll_data.get('votes', {})
    vote_counts = {candidate.replace("_", " "): count for candidate, count in vote_counts.items()}

    return jsonify({"poll_name": poll_data['poll_name'], "vote_counts": vote_counts}), 200

@app.route('/logout', methods=['POST'])
def logout():
    session.pop('user', None)
    return jsonify({"message": "Logged out successfully"}), 200

if __name__ == '__main__':
    app.run(debug=False , port=5000)