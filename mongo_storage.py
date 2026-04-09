import json
import pymongo
from pymongo import MongoClient, InsertOne
import datetime
import uuid

class DroneMongoStorage:
    def __init__(self, connection_string="mongodb://localhost:27017/"):
        self.client = MongoClient(connection_string)
        # Phase 1: Create Database
        self.db = self.client["drone_display_3d"]
        
        # Define Collections
        self.shows_collection = self.db["shows"]
        self.frames_collection = self.db["frames"]
        
        self._ensure_indexes()

    def _ensure_indexes(self):
        # Phase 2: Create Indexes (CRITICAL)
        # ascending index on show_id and frame_no
        self.frames_collection.create_index(
            [("show_id", pymongo.ASCENDING), ("frame_no", pymongo.ASCENDING)],
            unique=True
        )
        print("Indexes ensured on 'frames' collection: (show_id, frame_no)")

    def insert_pattern(self, show_metadata, frames_data):
        print(f"Starting import for show: {show_metadata.get('title', 'Unknown')}")
        
        # Generate a unique SHOW_ID if not already present
        show_id = show_metadata.get("_id")
        if not show_id:
            show_id = f"SHOW_{uuid.uuid4().hex[:8].upper()}"
            show_metadata["_id"] = show_id
            
        show_metadata["created_at"] = datetime.datetime.utcnow().isoformat()
        
        # Insert metadata into 'shows'
        self.shows_collection.insert_one(show_metadata)
        print(f"Show metadata inserted successfully. ID: {show_id}")
        
        # Prepare frames for bulk insertion
        bulk_operations = []
        for frame in frames_data:
            frame_doc = {
                "show_id": show_id,
                "frame_no": frame["frame_no"],
                "timestamp": frame["timestamp"],
                "drones": frame["drones"]
            }
            bulk_operations.append(InsertOne(frame_doc))
            
        # Bulk Insert Frame Documents
        if bulk_operations:
            result = self.frames_collection.bulk_write(bulk_operations, ordered=True)
            print(f"Bulk inserted {result.inserted_count} frames into MongoDB.")
            
        return show_id

    def get_all_frames_sequential(self, show_id):
        # Phase 3: Sequential Frame Query
        # To simulate playback, fetch all frames sorted by frame_no
        print(f"Retrieving all frames for {show_id} sequentially...")
        cursor = self.frames_collection.find({"show_id": show_id}).sort("frame_no", pymongo.ASCENDING)
        frames = list(cursor)
        return frames

    def stream_frames(self, show_id, batch_size=10):
        # Phase 3: Real-Time Frame Streaming
        # Yield frames in batches to improve memory efficiency
        print(f"Streaming frames for {show_id} in batches of {batch_size}...")
        
        skip = 0
        while True:
            # Query the next batch
            cursor = self.frames_collection.find(
                {"show_id": show_id}
            ).sort("frame_no", pymongo.ASCENDING).skip(skip).limit(batch_size)
            
            batch = list(cursor)
            if not batch:
                break
                
            yield batch
            skip += batch_size

    def validate_insertion(self, show_id):
        # Phase 4: Validation
        metadata = self.shows_collection.find_one({"_id": show_id})
        if not metadata:
            print(f"Validation Error: Metadata for {show_id} not found.")
            return False
            
        expected_frames = metadata.get("total_frames", 0)
        actual_frames = self.frames_collection.count_documents({"show_id": show_id})
        
        print(f"Validation for {show_id}:")
        print(f"✔ Metadata exists (Title: {metadata.get('title')})")
        
        if actual_frames == expected_frames:
             print(f"✔ Correct frame count: {actual_frames}")
        else:
             print(f"❌ Frame count mismatch! Expected {expected_frames}, got {actual_frames}")
             
        # Check an arbitrary frame to verify structure
        sample_frame = self.frames_collection.find_one({"show_id": show_id, "frame_no": 0})
        if sample_frame and "drones" in sample_frame and "timestamp" in sample_frame:
             print(f"✔ Correct frame structure in sample (frame_no 0)")
             if sample_frame["drones"] and "id" in sample_frame["drones"][0]:
                  print("✔ Drone IDs correctly stored inside frames.")
        
        return actual_frames == expected_frames

if __name__ == "__main__":
    import sys
    try:
        # Connect to MongoDB
        mongo_storage = DroneMongoStorage("mongodb://localhost:27017/")
        
        # Test connection by pinging
        mongo_storage.client.admin.command('ping')
        print("Successfully connected to MongoDB.")
        
        # Load the generated JSON Pattern
        try:
            with open("output_pattern.json", "r") as f:
                frames_data = json.load(f)
        except FileNotFoundError:
            print("output_pattern.json not found! Run video_to_pattern.py first.")
            sys.exit(1)
            
        print(f"Loaded {len(frames_data)} frames from JSON file.")
        
        # Create mockup metadata
        mock_show = {
            "title": "Test Pattern - Local",
            "fps": 10.0,
            "total_frames": len(frames_data),
            "resolution": [100, 100],
            "max_drones": 50
        }
        
        # FULL STEP 4 FLOW
        print("\n--- Testing Full Flow ---")
        show_id = mongo_storage.insert_pattern(mock_show, frames_data)
        
        # Validate Insertion
        print("\n--- Running Validation ---")
        mongo_storage.validate_insertion(show_id)
        
        print("\n--- Testing Retrieval Engine ---")
        # Test Sequential Retrieval
        retrieved_frames = mongo_storage.get_all_frames_sequential(show_id)
        if retrieved_frames:
            print(f"Successfully retrieved {len(retrieved_frames)} frames.")
            print(f"First retrieved frame drone count: {len(retrieved_frames[0]['drones'])}")
            
        # Test Streaming Retrieval
        print("\n--- Testing Streaming ---")
        batches = list(mongo_storage.stream_frames(show_id, batch_size=10))
        print(f"Streamed {len(batches)} batches of frames.")
        if batches:
             print(f"First batch size: {len(batches[0])}")

        print("\nFinished successfully. Ready for 3D Simulation Rendering.")
        
    except pymongo.errors.ServerSelectionTimeoutError:
        print("\n[!] Error: Could not connect to MongoDB server at mongodb://localhost:27017/")
        print("Please ensure your local MongoDB daemon is running, or update the connection string.")
        sys.exit(1)
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
