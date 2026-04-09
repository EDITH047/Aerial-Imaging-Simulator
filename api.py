from fastapi import FastAPI, HTTPException, Query, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pymongo import MongoClient
import os
import shutil
import tempfile
from typing import Optional

from video_to_pattern import VideoToPatternConverter
from mongo_storage import DroneMongoStorage

app = FastAPI(title="Aerial Imageing Simulator API")

# Allow CORS for frontend testing
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Connect to MongoDB
try:
    client = MongoClient("mongodb://localhost:27017/", serverSelectionTimeoutMS=2000)
    db = client["drone_display_3d"]
    shows_collection = db["shows"]
    frames_collection = db["frames"]
except Exception as e:
    print(f"Failed to connect to MongoDB: {e}")

# Storage Engine (Singleton)
mongo_storage = DroneMongoStorage("mongodb://localhost:27017/")

# Mount Static Files (Frontend)
if not os.path.exists("static"):
    os.makedirs("static")
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.post("/upload")
def upload_video(file: UploadFile = File(...)):
    """Upload a video, convert to drone pattern, and save to MongoDB"""
    
    if not file.filename.endswith(('.mp4', '.avi', '.mov')):
         raise HTTPException(status_code=400, detail="Invalid file type. Only mp4, avi, mov are allowed.")
         
    # Save the uploaded file to a temporary location
    try:
        temp_dir = tempfile.mkdtemp()
        temp_path = os.path.join(temp_dir, file.filename)
        
        with open(temp_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        print(f"File uploaded successfully to {temp_path}")
        
        # Kick off processing using the converter
        converter = VideoToPatternConverter(target_resolution=(128, 128), max_drones=6000)
        result = converter.process_video(temp_path)
        
        if not result:
             raise HTTPException(status_code=500, detail="Failure during video processing.")
             
        # Process result tuple
        frames_data, metadata = result
        
        # Configure Show Metadata
        show_docs = {
             "title": f"Uploaded: {file.filename}",
             "fps": metadata["fps"],
             "total_frames": metadata["total_frames"],
             "resolution": metadata["resolution"],
             "max_drones": 6000
        }
        
        # Save to DB
        show_id = mongo_storage.insert_pattern(show_docs, frames_data)

        # Also save to a JSON file so you can see exactly what the frontend reads!
        import json
        combined_data = {
             "show_info": show_docs,
             "frames": frames_data
        }
        
        # We will name the file after the original video name (e.g., video_name_exported.json)
        safe_filename = "".join([c for c in file.filename if c.isalnum() or c in (' ', '.', '_')]).rstrip()
        base_name = os.path.splitext(safe_filename)[0]
        export_filename = f"{base_name}_exported.json"
        
        with open(export_filename, "w") as f:
             json.dump(combined_data, f, indent=2)
             
        return {"show_id": show_id, "message": f"Video successfully converted, saved to DB, and exported to {export_filename}"}
        
    except Exception as e:
         print(f"Upload Error: {e}")
         raise HTTPException(status_code=500, detail=str(e))
    finally:
         # Clean up temp files
         if 'temp_path' in locals() and os.path.exists(temp_path):
             os.remove(temp_path)
         if 'temp_dir' in locals() and os.path.exists(temp_dir):
             os.rmdir(temp_dir)


@app.get("/shows")
async def get_shows():
    """Retrieve all available shows/patterns"""
    shows = list(shows_collection.find({}, {"_id": 1, "title": 1, "fps": 1, "total_frames": 1}))
    return shows

@app.get("/shows/{show_id}")
async def get_show_metadata(show_id: str):
    """Retrieve metadata for a specific show"""
    show = shows_collection.find_one({"_id": show_id})
    if not show:
        raise HTTPException(status_code=404, detail="Show not found")
    return show

@app.get("/shows/{show_id}/frames")
async def get_show_frames(show_id: str, batch: Optional[int] = Query(None, description="Number of frames to return"), offset: Optional[int] = Query(0, description="Starting frame number")):
    """Retrieve frames for a show. Can be paginated/streamed."""
    query = {"show_id": show_id}
    
    if batch is not None:
        cursor = frames_collection.find(query, {"_id": 0}).sort("frame_no", 1).skip(offset).limit(batch)
    else:
        cursor = frames_collection.find(query, {"_id": 0}).sort("frame_no", 1)
        
    frames = list(cursor)
    if not frames and offset == 0:
        raise HTTPException(status_code=404, detail="Frames not found for this show")
        
    return {"frames": frames}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api:app", host="0.0.0.0", port=8000, reload=True)
