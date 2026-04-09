import os
import glob
from pymongo import MongoClient

def clear_database():
    print("Connecting to MongoDB...")
    try:
        client = MongoClient("mongodb://localhost:27017/", serverSelectionTimeoutMS=2000)
        db = client["drone_display_3d"]
        
        # Drop collections
        print("Dropping 'shows' collection...")
        db.shows.drop()
        
        print("Dropping 'frames' collection...")
        db.frames.drop()
        
        print("Database cleared successfully!")
        
        # Delete exported JSON files
        print("Cleaning up exported JSON files...")
        exported_files = glob.glob("*_exported.json")
        for f in exported_files:
            try:
                os.remove(f)
                print(f"Deleted {f}")
            except Exception as e:
                print(f"Could not delete {f}: {e}")
                
    except Exception as e:
        print(f"Error clearing database: {e}")

if __name__ == "__main__":
    clear_database()
