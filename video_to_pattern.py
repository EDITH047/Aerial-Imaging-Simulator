import cv2
import numpy as np
from scipy.optimize import linear_sum_assignment
import json
import os

class VideoToPatternConverter:
    def __init__(self, target_resolution=(128, 128), max_drones=4000, intensity_threshold=40):
        self.target_width, self.target_height = target_resolution
        self.max_drones = max_drones
        self.intensity_threshold = intensity_threshold
    
    def process_video(self, video_path):
        print(f"Starting processing for video: {video_path}")
        # PHASE A: Metadata Extraction
        metadata = self._extract_metadata(video_path)
        if not metadata:
            return None
        
        print(f"Metadata extracted: {metadata}")
        
        # PHASE B: Frame Extraction
        cap = cv2.VideoCapture(video_path)
        
        frames_pattern_data = []
        frame_idx = 0
        
        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break
                
            # PHASE C: Preprocessing
            processed_frame = self._preprocess_frame(frame)
            
            # PHASE D & E: Pattern Extraction & 3D Mapping
            points_3d = self._extract_3d_coordinates(processed_frame)
            
            # PHASE F: Drone Position Assignment
            assigned_drones = self._assign_drones(points_3d)
            
            timestamp = frame_idx / metadata['fps']
            
            # PHASE G: Frame Pattern Structure
            frame_data = {
                "frame_no": frame_idx,
                "timestamp": round(timestamp, 3),
                "drones": assigned_drones
            }
            
            print(f"Frame {frame_idx}: Found {len(assigned_drones)} drones.")
            frames_pattern_data.append(frame_data)
            frame_idx += 1
            
        cap.release()
        print(f"Extracted {len(frames_pattern_data)} raw frames.")
        
        # PHASE H: Pattern Smoothing
        smoothed_data = self._smooth_pattern(frames_pattern_data)
        
        return smoothed_data, metadata
        
    def _extract_metadata(self, video_path):
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            print("Error: Could not open video file.")
            return None
            
        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = total_frames / fps if fps > 0 else 0
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        
        metadata = {
            "fps": fps,
            "duration_seconds": duration,
            "total_frames": total_frames,
            "resolution": (width, height)
        }
        cap.release()
        return metadata

    def _preprocess_frame(self, frame):
        # Resize to manageable resolution
        resized = cv2.resize(frame, (self.target_width, self.target_height))
        # Convert to grayscale
        gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
        # Apply thresholding
        _, binary = cv2.threshold(gray, self.intensity_threshold, 255, cv2.THRESH_BINARY)
        # Remove noise using morphological opening ONLY if we have a lot of pixels
        # (This prevents thin letters/lines from being erased in low-res modes)
        kernel = np.ones((3,3), np.uint8)
        if np.sum(binary > 0) > 1000:
            cleaned = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)
        else:
            cleaned = binary # Keep the raw thresholded image for sparse scenes (text)
        
        # Return cleaned binary, original gray for depth mapping, and resized original for color
        return {"binary": cleaned, "gray": gray, "color": resized}

    def _extract_3d_coordinates(self, processed_frame):
        binary = processed_frame["binary"]
        gray = processed_frame["gray"]
        color_frame = processed_frame["color"]
        
        points = []
        # Find active pixels
        y_coords, x_coords = np.where(binary > 0)
        
        for y, x in zip(y_coords, x_coords):
            # Normalize X and Y to range [-10, 10] or similar relative drone space
            # For simplicity let's use 0 to 100 space, where Y is flipped (0 is bottom)
            sim_x = float(x)
            sim_y = float(self.target_height - y) 
            
            # Depth Assignment (Option 2: Brightness-Based Depth)
            # Brighter pixel -> Higher Z
            intensity = gray[y, x]
            # Normalizing Z to a small range (5 units) so shapes stay flat & readable
            sim_z = (intensity / 255.0) * 5.0
            
            # Extract color from original resized frame (OpenCV uses BGR)
            b, g, r = color_frame[y, x]
            color_hex = f"#{int(r):02x}{int(g):02x}{int(b):02x}"
            
            points.append({'x': sim_x, 'y': sim_y, 'z': sim_z, 'light': color_hex, 'intensity': intensity})
            
        return points

    def _assign_drones(self, points):
        if not points:
            return []
            
        # Density Reduction: Uniform spatial grid sampling instead of brightest-first
        # so ALL parts of the shape/text are represented, not just one cluster
        if len(points) > self.max_drones:
            # Calculate grid step to uniformly subsample points across full X/Y extent
            step = int(np.ceil(np.sqrt(len(points) / self.max_drones)))
            # Sort by (y, x) to create a grid-like order then pick every `step`-th
            points.sort(key=lambda p: (round(p['y'] / step), round(p['x'] / step)))
            points = points[::step][:self.max_drones]
            
        # Format for structure
        drones = []
        for p in points:
            drones.append({
                "x": round(p['x'], 2),
                "y": round(p['y'], 2),
                "z": round(p['z'], 2),
                "light": p['light']
            })
            
        return drones

    def _smooth_pattern(self, frames_data):
        print("Applying pattern smoothing...")
        if not frames_data:
            return frames_data
            
        from scipy.spatial import cKDTree
        
        # We need to explicitly assign Drone IDs (D1, D2...) across frames
        # and minimize the Euclidean distance they travel between frames.
        
        # Initialize first frame drones with sequential IDs
        for i, drone in enumerate(frames_data[0]['drones']):
            drone['id'] = f"D{i+1}"
            
        # Iterate through consecutive pairs of frames
        for i in range(1, len(frames_data)):
            prev_drones = frames_data[i-1]['drones']
            curr_drones = frames_data[i]['drones']
            
            if not prev_drones or not curr_drones:
                # If a frame has no drones, assign random virtual IDs or skip smoothing
                for j, drone in enumerate(curr_drones):
                    drone['id'] = f"D{j+1}"
                continue
                
            # Build KDTree for previous drones to quickly find nearest
            prev_coords = np.array([[pd['x'], pd['y'], pd['z']] for pd in prev_drones])
            tree = cKDTree(prev_coords)
            
            assigned_prev_indices = set()
            
            for c, cd in enumerate(curr_drones):
                # Query nearest neighbors
                k_val = min(50, len(prev_drones))
                dists, indices = tree.query([cd['x'], cd['y'], cd['z']], k=k_val)
                
                # If k=1, query returns scalar, otherwise array. Force array
                if np.isscalar(indices):
                    indices = [indices]
                
                for r in indices:
                    if r not in assigned_prev_indices:
                        cd['id'] = prev_drones[r].get('id', "D_temp")
                        assigned_prev_indices.add(r)
                        # NO position blending — keep exact pixel coordinates
                        # so letters stay crisp and undistorted
                        break
                        
            # For any newly appeared points, assign new IDs
            existing_ids = {d.get('id') for d in curr_drones if 'id' in d}
            # Remove None if present
            existing_ids.discard(None)
            
            # Find the highest existing ID number
            max_id_num = 0
            for eid in existing_ids:
                if eid.startswith('D') and eid[1:].isdigit():
                    max_id_num = max(max_id_num, int(eid[1:]))
                    
            next_new_id_num = max_id_num + 1
            
            for c in range(len(curr_drones)):
                if 'id' not in curr_drones[c]:
                    # Try to use a free ID, or create a new one
                    curr_drones[c]['id'] = f"D{next_new_id_num}"
                    next_new_id_num += 1
                    
        return frames_data

# PHASE I: Final Pattern Output via script execution
if __name__ == "__main__":
    # Test wrapper
    generator = VideoToPatternConverter(target_resolution=(50, 50), max_drones=50)
    
    # Let's generate a dummy black/white video for testing if none exists
    test_vid = "test_pattern.mp4"
    if not os.path.exists(test_vid):
        print(f"Creating dummy test video {test_vid}...")
        out = cv2.VideoWriter(test_vid, cv2.VideoWriter_fourcc(*'mp4v'), 10.0, (200, 200))
        for i in range(30):
            frame = np.zeros((200, 200, 3), dtype=np.uint8)
            # Draw moving circle
            cv2.circle(frame, (50 + i*5, 100), 20, (255, 255, 255), -1)
            out.write(frame)
        out.release()
        
    result_data, meta_info = generator.process_video(test_vid)
    
    if result_data:
        out_file = "output_pattern.json"
        with open(out_file, 'w') as f:
            json.dump(result_data, f, indent=2)
        print(f"Successfully processed {len(result_data)} frames.")
        print(f"Pattern stored in {out_file}")
        
        # Display sample from first frame
        print("Sample drone data from frame 0:")
        if result_data[0]['drones']:
            print(json.dumps(result_data[0]['drones'][:2], indent=2))
        else:
            print("No drones active in frame 0.")
