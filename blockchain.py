import hashlib
import time
from firebase_admin import firestore

class Block:
    def __init__(self, index, timestamp, data, previous_hash):
        self.index = index
        self.timestamp = timestamp
        self.data = data
        self.previous_hash = previous_hash
        self.hash = self.calculate_hash()

    def calculate_hash(self):
        block_string = f"{self.index}{self.timestamp}{self.data}{self.previous_hash}"
        return hashlib.sha256(block_string.encode()).hexdigest()

class Blockchain:
    def __init__(self, db, poll_id):
        self.db = db
        self.poll_id = poll_id  # Unique identifier for the poll
        self.chain = []
        self.load_chain_from_db()

    def create_genesis_block(self):
        return Block(0, time.time(), "Genesis Block", "0")

    def add_block(self, data):
        previous_block = self.chain[-1]
        new_block = Block(len(self.chain), time.time(), data, previous_block.hash)
        self.chain.append(new_block)
        self.save_block_to_db(new_block)

    def load_chain_from_db(self):
        blocks_ref = self.db.collection(f'polls/{self.poll_id}/blockchain').order_by('index').stream()
        for block_doc in blocks_ref:
            block_data = block_doc.to_dict()
            block = Block(
                block_data['index'],
                block_data['timestamp'],
                block_data['data'],
                block_data['previous_hash']
            )
            self.chain.append(block)

        if not self.chain:
            genesis_block = self.create_genesis_block()
            self.chain.append(genesis_block)
            self.save_block_to_db(genesis_block)

    def save_block_to_db(self, block):
        block_ref = self.db.collection(f'polls/{self.poll_id}/blockchain').document(str(block.index))
        block_ref.set({
            'index': block.index,
            'timestamp': block.timestamp,
            'data': block.data,
            'previous_hash': block.previous_hash,
            'hash': block.hash
        })

    def is_chain_valid(self):
        for i in range(1, len(self.chain)):
            current_block = self.chain[i]
            previous_block = self.chain[i - 1]

            if current_block.hash != current_block.calculate_hash():
                return False
            if current_block.previous_hash != previous_block.hash:
                return False

        return True
