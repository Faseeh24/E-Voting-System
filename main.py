from flask import Flask, request, jsonify, redirect, url_for, session
from flask_cors import CORS
import firebase_admin
from firebase_admin import credentials, firestore
from werkzeug.security import generate_password_hash, check_password_hash
from blockchain import Blockchain  # Import the Blockchain class
import time
from Crypto.Cipher import AES
import base64
import json
from Crypto.Util.Padding import pad, unpad

# Load stored key and IV
with open("./KEYS/AES_KEY.json", "r") as f:
    config = json.load(f)
    key = base64.b64decode(config["key"])
    iv = base64.b64decode(config["iv"])

def encrypt_AES(plaintext: str) -> str:
    cipher = AES.new(key, AES.MODE_CBC, iv)
    ct_bytes = cipher.encrypt(pad(plaintext.encode(), AES.block_size))
    return base64.b64encode(ct_bytes).decode()

def decrypt_AES(ciphertext_b64: str) -> str:
    ct = base64.b64decode(ciphertext_b64)
    cipher = AES.new(key, AES.MODE_CBC, iv)
    pt = unpad(cipher.decrypt(ct), AES.block_size)
    return pt.decode()


# Initialize Flask app
app = Flask(__name__)
app.secret_key = 'your_secret_key'  # Replace with a secure secret key
CORS(app, origins=["http://localhost:5173"], supports_credentials=True)

# Initialize Firestore DB
cred = credentials.Certificate("./KEYS/Google Cloud FireStore API.json")
firebase_admin.initialize_app(cred)
db = firestore.client()
users_collection = db.collection('users')


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

@app.route("/getusers", methods=['GET'])
def get_users():
    try:
        users = users_collection.stream()
        user_list = []

        for user in users:
            user_list.append(user.to_dict())

        return jsonify(user_list), 200

    except Exception as e:
        print("Error fetching users:", e)
        return jsonify({"error": "Failed to fetch users"}), 500


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

    email = encrypt_AES(email)
    # Check if user already exists
    if users_collection.document(email).get().exists:
        return jsonify({"error": "User already exists"}), 400

    # Hash the password before storing
    hashed_password = generate_password_hash(password)

    # Save user data to Firestore
    users_collection.document(email).set({
        "email": email,
        "password": hashed_password,
        "username": encrypt_AES(username),
        "name": encrypt_AES(name)
    })

    return jsonify({"message": "Signup successful"}), 201


@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    email = data.get('email')
    password = data.get('password')

    if not email or not password:
        return jsonify({"error": "Email and password are required"}), 400

    email = encrypt_AES(email)

    # Verify user credentials
    user_doc = users_collection.document(email).get()
    if not user_doc.exists or not check_password_hash(user_doc.to_dict().get('password'), password):
        return jsonify({"error": "Invalid email or password"}), 401

    # Retrieve the full user object
    user_data = user_doc.to_dict()
    user_data['email'] = decrypt_AES(user_data['email'])
    user_data['username'] = decrypt_AES(user_data['username'])
    user_data['name'] = decrypt_AES(user_data['name'])

    # Set session for logged-in user
    session['user'] = decrypt_AES(email)

    return jsonify({"message": "Login successful", "user": user_data}), 200

@app.route('/update-user', methods=['POST'])
def update_user():
    data = request.get_json()
    email = data.get('email')
    name = data.get('name')
    password = data.get('password')

    if not email or not name or not password:
        return jsonify({"error": "Email, name, and password are required"}), 400

    user_ref = users_collection.document(encrypt_AES(email))
    user_doc = user_ref.get()

    if not user_doc.exists:
        return jsonify({"error": "User not found"}), 404

    # Hash the new password
    hashed_password = generate_password_hash(password)

    # Update the user document
    user_ref.update({
        "name": encrypt_AES(name),
        "password": hashed_password
    })

    return jsonify({"message": "User info updated successfully"}), 200


@app.route('/get_polls', methods=['GET'])
def get_polls():
    try:
        polls_ref = db.collection('polls')
        polls = polls_ref.stream()

        poll_list = []
        for poll in polls:
            poll_data = poll.to_dict()
            poll_data['id'] = poll.id  # Include document ID
            poll_list.append(poll_data)

        return jsonify({"polls": poll_list}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/add_poll', methods=['POST'])
def add_poll():

    poll_name = request.json.get('poll_name')
    closing_date = request.json.get('closing_date')
    candidates = request.json.get('candidates')
    creator = request.json.get('creator')

    if not poll_name or not closing_date or not candidates:
        return jsonify({"error": "All fields are required"}), 400

    # Save poll data to Firestore with auto-generated document ID
    poll_ref = db.collection('polls').document()
    poll_ref.set({
        "poll_name": poll_name,
        'created_by': creator,
        'closing_date': closing_date,
        'candidates': candidates,
        'votes': {candidate.replace(" ", "_"): 0 for candidate in candidates},
        'created_at': firestore.SERVER_TIMESTAMP
    })

    return jsonify({"message": "Poll created successfully"}), 201

@app.route('/get_user_polls', methods=['GET'])
def get_user_polls():
    user_email = request.args.get('user')
    if not user_email:
        return jsonify({"error": "User not provided"}), 400

    polls_ref = db.collection('polls').where('created_by', '==', user_email)
    polls = polls_ref.stream()
    
    poll_list = []
    for poll in polls:
        data = poll.to_dict()
        data['id'] = poll.id
        poll_list.append(data)

    return jsonify({"polls": poll_list}), 200

@app.route("/past_polls", methods=["GET"])
def get_past_polls():
    today_timestamp = time.time()
    polls_ref = db.collection("polls")
    all_polls = polls_ref.stream()

    past_polls = []
    for poll_doc in all_polls:
        poll_data = poll_doc.to_dict()
        try:
            closing_date_str = poll_data.get("closing_date", "")
            closing_struct = time.strptime(closing_date_str, "%Y-%m-%d")
            closing_timestamp = time.mktime(closing_struct)

            # If poll has ended
            if closing_timestamp < today_timestamp:
                poll_data["id"] = poll_doc.id
                past_polls.append(poll_data)
        except Exception as e:
            continue  # skip invalid or malformed dates

    return jsonify({"past_polls": past_polls})


@app.route("/ongoing_polls", methods=["GET"])
def get_ongoing_polls():
    today_timestamp = time.time()
    polls_ref = db.collection("polls")
    all_polls = polls_ref.stream()

    ongoing_polls = []
    for poll_doc in all_polls:
        poll_data = poll_doc.to_dict()
        try:
            # Convert closing_date (e.g., "2025-05-17") to timestamp
            closing_date_str = poll_data.get("closing_date", "")
            closing_struct = time.strptime(closing_date_str, "%Y-%m-%d")
            closing_timestamp = time.mktime(closing_struct)

            if closing_timestamp >= today_timestamp:
                poll_data["id"] = poll_doc.id
                ongoing_polls.append(poll_data)
        except Exception as e:
            continue  # skip invalid entries

    return jsonify({"ongoing_polls": ongoing_polls})


@app.route('/cast_vote', methods=['POST'])
def cast_vote():
    if 'user' not in session:
        return jsonify({"error": "Unauthorized"}), 401

    poll_name = request.json.get('poll_name')
    candidate = request.json.get('candidate')
    userEmail = request.json.get('userEmail')

    if not poll_name or not candidate:
        return jsonify({"error": "Poll name and candidate are required"}), 400

    # Fetch the poll document by name
    poll_ref = db.collection('polls').where('poll_name', '==', poll_name).stream()
    poll_doc = next(poll_ref, None)  # Get the first matching document
    if not poll_doc:
        return jsonify({"error": "Poll not found"}), 404

    poll_id = poll_doc.id

    # Check if the user has already voted in this poll
    votes_ref = db.collection(f'polls/{poll_id}/votes').document(userEmail)
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
    votes_ref.set({'voted': True,
                   'candidate': candidate})

    return jsonify({"message": "Vote cast successfully"}), 200

@app.route('/user_vote_status', methods=['GET'])
def user_vote_status():
    # Get user_email from query parameters
    user_email = request.args.get('userEmail')

    if not user_email:
        return jsonify({"error": "User email is required"}), 400
    
    # Fetch the polls collection
    polls_ref = db.collection('polls')
    all_polls = polls_ref.stream()

    # This will hold the user's voting status for each poll, with poll_id as the key
    user_votes = {}

    for poll_doc in all_polls:
        poll_data = poll_doc.to_dict()
        poll_id = poll_doc.id

        # Check if the user has voted in this poll
        votes_ref = db.collection(f'polls/{poll_id}/votes').document(user_email)
        vote_doc = votes_ref.get()

        if vote_doc.exists:
            # The user has voted, retrieve the candidate they voted for
            user_vote = vote_doc.to_dict().get('candidate')
            user_votes[poll_id] = {
                "poll_name": poll_data['poll_name'],
                "voted": True,
                "candidate": user_vote
            }
        else:
            # The user has not voted in this poll
            user_votes[poll_id] = {
                "poll_name": poll_data['poll_name'],
                "voted": False,
                "candidate": None
            }

    return jsonify({"user_votes": user_votes}), 200


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