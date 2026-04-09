import cv2
import numpy as np
import os
from video_to_pattern import VideoToPatternConverter

def diagnose_processing(video_path):
    if not os.path.exists(video_path):
        print(f"Error: Video file {video_path} not found.")
        return

    converter = VideoToPatternConverter(target_resolution=(50, 50), max_drones=6000, intensity_threshold=80)
    
    # Extract metadata
    metadata = converter._extract_metadata(video_path)
    print(f"Metadata: {metadata}")
    
    cap = cv2.VideoCapture(video_path)
    frame_count = 0
    total_drones_found = 0
    
    while cap.isOpened() and frame_count < 10: # Check first 10 frames
        ret, frame = cap.read()
        if not ret:
            break
            
        processed = converter._preprocess_frame(frame)
        binary = processed["binary"]
        points = converter._extract_3d_coordinates(processed)
        
        active_pixels = np.sum(binary > 0)
        print(f"Frame {frame_count}: Active pixels after threshold/opening: {active_pixels}, Points extracted: {len(points)}")
        
        total_drones_found += len(points)
        frame_count += 1
        
    cap.release()
    
    if total_drones_found == 0:
        print("DIAGNOSIS: No drones were extracted. Threshold might be too high or letters too thin for MORPH_OPEN.")
    else:
        print(f"DIAGNOSIS: Found {total_drones_found} drone points in first {frame_count} frames.")

if __name__ == "__main__":
    # Look for the last uploaded file in MongoDB or just common names
    # For now, let's ask the user if they can provide the filename or check the temp dir if it wasn't cleaned up (but api.py cleans up)
    # However, I can check if there are any mp4 files in the current dir that might be the test video
    files = [f for f in os.listdir('.') if f.endswith('.mp4')]
    if files:
        print(f"Checking {files[0]}...")
        diagnose_processing(files[0])
    else:
        print("No mp4 files found to diagnose.")
