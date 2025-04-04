import time
import os
import tempfile
import zipfile
import platform
import subprocess
from moviepy.editor import (AudioFileClip, CompositeVideoClip, CompositeAudioClip, ImageClip,
                            TextClip, VideoFileClip, concatenate_videoclips)
from moviepy.video.fx.all import crop # Ensure crop is imported
from moviepy.audio.fx.audio_loop import audio_loop
from moviepy.audio.fx.audio_normalize import audio_normalize
import requests
import numpy as np
from ultralytics import YOLO # Import YOLO
import cv2 # Import OpenCV

# --- YOLO Model Loading ---
# Load the YOLOv8 model (e.g., yolov8n.pt for nano version).
# This will download the model weights the first time it's run.
try:
    yolo_model = YOLO('yolov8n.pt')
    print("YOLOv8 model loaded successfully.")
except Exception as e:
    print(f"Error loading YOLOv8 model: {e}. Intelligent cropping will be disabled.")
    yolo_model = None
# --- End YOLO Model Loading ---

def download_file(url, filename):
    # Simple download function
    with open(filename, 'wb') as f:
        headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        response = requests.get(url, headers=headers, stream=True) # Use stream=True for potentially large files
        response.raise_for_status() # Raise an exception for bad status codes
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)

def search_program(program_name):
    # Finds the path of an executable
    try:
        search_cmd = "where" if platform.system() == "Windows" else "which"
        return subprocess.check_output([search_cmd, program_name]).decode().strip()
    except subprocess.CalledProcessError:
        return None

def get_program_path(program_name):
    # Gets the program path, potentially useful for setting env vars
    program_path = search_program(program_name)
    return program_path

# --- YOLO Cropping Function ---
def yolo_reframe_clip(clip, target_aspect=9/16, target_height=1920):
    """
    Applies YOLO detection to find the largest object and crops/resizes
    the clip to keep it centered in a 9:16 frame.
    Uses clip.fl for frame-by-frame processing.
    """
    if yolo_model is None: # Fallback if YOLO failed to load
        print("YOLO model not available, using simple resize.")
        # Resize based on height, Compositing will center it
        return clip.resize(height=target_height)

    # Store the bounding box of the largest object found across frames for stability
    largest_object_bbox = None
    target_width = int(target_height * target_aspect)

    def process_frame(get_frame, t):
        # This inner function is passed to clip.fl
        frame = get_frame(t)
        h, w, _ = frame.shape
        current_aspect = w / h

        # Default crop is center if no object detected or if already portrait
        x1, y1, x2, y2 = 0, 0, w, h
        final_frame = None

        # Only process if not already target aspect ratio (within tolerance)
        if abs(current_aspect - target_aspect) > 0.01:
            results = yolo_model(frame, verbose=False) # Perform detection
            nonlocal largest_object_bbox # Allow modification of outer scope variable

            current_largest_bbox_in_frame = None
            if results and results[0].boxes:
                boxes = results[0].boxes.xyxy.cpu().numpy()
                areas = (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])
                if len(areas) > 0:
                    largest_object_index = np.argmax(areas)
                    current_largest_bbox_in_frame = boxes[largest_object_index]
                    # Update the overall largest bbox if the current one is bigger
                    if largest_object_bbox is None or areas[largest_object_index] > ((largest_object_bbox[2] - largest_object_bbox[0]) * (largest_object_bbox[3] - largest_object_bbox[1])):
                         largest_object_bbox = current_largest_bbox_in_frame

            # Use the largest bbox found *so far* for stability, fallback to current frame's largest
            bbox_to_use = largest_object_bbox if largest_object_bbox is not None else current_largest_bbox_in_frame

            if bbox_to_use is not None:
                obj_x1, obj_y1, obj_x2, obj_y2 = bbox_to_use
                obj_center_x = (obj_x1 + obj_x2) / 2
                obj_center_y = (obj_y1 + obj_y2) / 2

                # Calculate desired crop dimensions based on target aspect with padding
                padding_factor = 1.2 # Zoom out slightly (increase crop window size)
                if current_aspect > target_aspect: # Landscape video
                    # Calculate minimum width needed for 9:16
                    min_w = h * target_aspect
                    # Add padding, but don't exceed original width
                    new_w = min(w, min_w * padding_factor)
                    new_h = h
                    # Center the padded window around the object
                    x1 = max(0, obj_center_x - new_w / 2)
                    x2 = min(w, x1 + new_w)
                    # Recalculate x1 if x2 hit the boundary
                    x1 = max(0, x2 - new_w)
                    y1, y2 = 0, h
                else: # Portrait video (narrower than target)
                    # Calculate minimum height needed
                    min_h = w / target_aspect
                    # Add padding, but don't exceed original height
                    new_h = min(h, min_h * padding_factor)
                    new_w = w
                    # Center the padded window around the object
                    y1 = max(0, obj_center_y - new_h / 2)
                    y2 = min(h, y1 + new_h)
                    # Recalculate y1 if y2 hit the boundary
                    y1 = max(0, y2 - new_h)
                    x1, x2 = 0, w

                x1, y1, x2, y2 = map(int, [x1, y1, x2, y2])
                # Ensure crop dimensions are valid
                if y1 < y2 and x1 < x2:
                    cropped_frame = frame[y1:y2, x1:x2]
                    # Resize the cropped frame to the target size
                    final_frame = cv2.resize(cropped_frame, (target_width, target_height), interpolation=cv2.INTER_AREA)

        # If intelligent cropping didn't produce a frame (e.g., no object, already portrait, error)
        if final_frame is None:
             if current_aspect > target_aspect: # Landscape center crop fallback
                 new_w = int(h * target_aspect)
                 x_center = w // 2
                 x1 = max(0, x_center - new_w // 2)
                 cropped_frame = frame[:, x1:x1+new_w]
                 final_frame = cv2.resize(cropped_frame, (target_width, target_height), interpolation=cv2.INTER_AREA)
             else: # Portrait or square - resize height and let compositing center it
                 interpolation = cv2.INTER_AREA if h > target_height else cv2.INTER_LINEAR
                 final_frame = cv2.resize(frame, (int(target_height * current_aspect), target_height), interpolation=interpolation)

        # Final check to ensure output frame matches target size exactly, padding if necessary
        fh, fw, _ = final_frame.shape
        if fh != target_height or fw != target_width:
             background = np.zeros((target_height, target_width, 3), dtype=np.uint8)
             paste_x = (target_width - fw) // 2
             paste_y = (target_height - fh) // 2
             # Ensure pasting coordinates are valid
             if paste_y >= 0 and paste_y+fh <= target_height and paste_x >= 0 and paste_x+fw <= target_width:
                 background[paste_y:paste_y+fh, paste_x:paste_x+fw] = final_frame
                 return background
             else: # If pasting fails somehow, return the incorrectly sized frame
                 print(f"Warning: Could not correctly pad frame to target size. Final frame size: {fw}x{fh}")
                 return final_frame
        else:
             return final_frame

    # Apply the frame processor using fl
    processed_clip = clip.fl(process_frame, apply_to=['mask']) # apply_to=['mask'] might be needed if clip has mask

    return processed_clip
# --- End YOLO Cropping Function ---


def get_output_media(audio_file_path, timed_captions, background_video_data, video_server):
    OUTPUT_FILE_NAME = "rendered_video.mp4"
    magick_path = get_program_path("magick")
    print(f"Found ImageMagick at: {magick_path}")
    if magick_path:
        os.environ['IMAGEMAGICK_BINARY'] = magick_path
    else:
        print("Warning: ImageMagick 'magick' command not found in PATH. Attempting fallback '/usr/bin/convert'. Text rendering might fail.")
        os.environ['IMAGEMAGICK_BINARY'] = '/usr/bin/convert'

    visual_clips = []
    temp_files = [] # Keep track of downloaded files for cleanup

    # --- Process Background Videos ---
    for (t1, t2), video_url in background_video_data:
        if not video_url:
            print(f"Skipping segment {t1}-{t2} due to missing video URL.")
            continue

        video_filename = None
        try:
            # Create a temporary file to download the video
            temp_video_file = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
            video_filename = temp_video_file.name
            temp_video_file.close() # Close handle, file persists because delete=False
            temp_files.append(video_filename) # Add to cleanup list *before* download attempt

            print(f"Downloading {video_url} to {video_filename}")
            download_file(video_url, video_filename)

            # Load clip
            video_clip = VideoFileClip(video_filename)

            # --- Apply YOLO Reframing/Cropping ---
            print(f"Applying YOLO reframing to clip for segment {t1}-{t2}")
            # Pass the original clip to the reframing function
            reframed_clip = yolo_reframe_clip(video_clip)
            # --- End YOLO Reframing ---

            # Set timing and add the *reframed* clip to the list
            reframed_clip = reframed_clip.set_start(t1).set_duration(t2 - t1).set_end(t2)
            visual_clips.append(reframed_clip) # Append the processed clip

        except Exception as e:
             print(f"Error processing video clip {video_url} (downloaded to {video_filename}): {e}")
             # Cleanup is handled in the finally block, just continue
             continue

    # --- Process Audio ---
    audio_clips = []
    if os.path.exists(audio_file_path):
        try:
            audio_file_clip = AudioFileClip(audio_file_path)
            audio_clips.append(audio_file_clip)
        except Exception as e:
            print(f"Error loading audio file {audio_file_path}: {e}")
    else:
        print(f"Warning: Audio file not found at {audio_file_path}")

    # --- Process Captions ---
    caption_clips = [] # Keep captions separate initially
    for (t1, t2), text in timed_captions:
        try:
            # Create text clip
            text_clip = TextClip(txt=text, fontsize=70, color="white", stroke_width=2, stroke_color="black", method="label")
            text_clip = text_clip.set_start(t1).set_duration(t2 - t1).set_end(t2)
            # Position text at the bottom center
            text_clip = text_clip.set_position(("center", "bottom"))
            caption_clips.append(text_clip)
        except Exception as e:
            print(f"Error creating text clip for '{text}': {e}")
            continue # Skip this text clip if error occurs

    # --- Final Composition ---
    if not visual_clips:
        print("Error: No background visual clips were successfully processed.")
        final_video = None
    else:
        try:
            # Calculate max duration from visual clips
            max_visual_duration = max(vc.end for vc in visual_clips if vc.end is not None) if visual_clips else 0

            # Composite background clips first
            background_composite = CompositeVideoClip(visual_clips, size=(1080, 1920)).set_duration(max_visual_duration)

            # Composite captions on top of the background
            final_video_with_captions = CompositeVideoClip([background_composite] + caption_clips, size=(1080, 1920)).set_duration(max_visual_duration)

            final_video = final_video_with_captions # Start with video + captions

            if audio_clips:
                final_audio = CompositeAudioClip(audio_clips)
                if final_audio.duration is not None:
                     # Trim video to audio duration if audio is shorter, otherwise use video duration
                     final_duration = min(final_video.duration, final_audio.duration) if final_video.duration else final_audio.duration
                     final_video = final_video.set_duration(final_duration)
                     final_video.audio = final_audio.set_duration(final_duration) # Ensure audio duration matches
                else:
                     print("Warning: Could not determine audio duration.")
                     # Use visual duration if audio duration is unknown
                     if final_video.duration is None:
                         final_video = final_video.set_duration(max_visual_duration)

            elif final_video.duration is None: # No audio and no duration from visuals?
                 print("Warning: Could not determine video duration from visuals.")
                 # As a last resort, maybe use caption timings?
                 max_caption_end = max(cc.end for cc in caption_clips if cc.end is not None) if caption_clips else 0
                 if max_caption_end > 0:
                     final_video = final_video.set_duration(max_caption_end)


            if final_video.duration is None:
                print("Error: Final video duration could not be determined.")
                final_video = None

        except Exception as e:
            print(f"Error during final video composition: {e}")
            final_video = None

    # --- Write Output File ---
    output_written = False
    if final_video:
        try:
            print(f"Writing final video to {OUTPUT_FILE_NAME}...")
            final_video.write_videofile(OUTPUT_FILE_NAME, codec='libx264', audio_codec='aac', fps=25, preset='veryfast', threads=4)
            output_written = True
            print("Video writing complete.")
        except Exception as e:
            print(f"Error writing final video file: {e}")
            output_written = False

    # --- Cleanup ---
    print(f"Cleaning up {len(temp_files)} temporary video files...")
    for f in temp_files:
        try:
            if os.path.exists(f):
                os.remove(f)
        except Exception as e_clean:
            print(f"Warning: Could not remove temp file {f}: {e_clean}")

    return OUTPUT_FILE_NAME if output_written and os.path.exists(OUTPUT_FILE_NAME) else None
