import time
import os
import tempfile
import zipfile
import platform
import subprocess
from moviepy.editor import (AudioFileClip, CompositeVideoClip, CompositeAudioClip, ImageClip,
                            TextClip, VideoFileClip, concatenate_videoclips) # Added concatenate_videoclips
from moviepy.video.fx.all import crop # Import crop effect
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
    """
    if yolo_model is None: # Fallback if YOLO failed to load
        print("YOLO model not available, using simple resize.")
        return clip.resize(height=target_height)

    # Store the bounding box of the largest object found so far
    largest_object_bbox = None

    def process_frame(get_frame, t):
        frame = get_frame(t)
        h, w, _ = frame.shape
        current_aspect = w / h

        # Default crop is center if no object detected or if already portrait
        x1, y1, x2, y2 = 0, 0, w, h
        new_w, new_h = w, h

        if abs(current_aspect - target_aspect) > 0.01: # Only process if not already target aspect
            results = yolo_model(frame, verbose=False) # Perform detection
            nonlocal largest_object_bbox # Allow modification of outer scope variable

            if results and results[0].boxes:
                boxes = results[0].boxes.xyxy.cpu().numpy() # Get bounding boxes
                areas = (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])
                if len(areas) > 0:
                    largest_object_index = np.argmax(areas)
                    largest_object_bbox = boxes[largest_object_index] # Update largest bbox found

            # If we have detected an object, calculate crop based on it
            if largest_object_bbox is not None:
                obj_x1, obj_y1, obj_x2, obj_y2 = largest_object_bbox
                obj_center_x = (obj_x1 + obj_x2) / 2
                obj_center_y = (obj_y1 + obj_y2) / 2

                # Calculate desired crop dimensions based on target aspect
                if current_aspect > target_aspect: # Landscape video
                    new_w = h * target_aspect
                    new_h = h
                    x1 = max(0, obj_center_x - new_w / 2)
                    x2 = min(w, obj_center_x + new_w / 2)
                    # Adjust if crop window goes out of bounds
                    if x2 - x1 < new_w:
                        if x1 == 0: x2 = new_w
                        else: x1 = w - new_w
                    y1, y2 = 0, h
                else: # Portrait video (narrower than target) - less common case
                    new_h = w / target_aspect
                    new_w = w
                    y1 = max(0, obj_center_y - new_h / 2)
                    y2 = min(h, obj_center_y + new_h / 2)
                     # Adjust if crop window goes out of bounds
                    if y2 - y1 < new_h:
                        if y1 == 0: y2 = new_h
                        else: y1 = h - new_h
                    x1, x2 = 0, w

                # Ensure integer coordinates for cropping
                x1, y1, x2, y2 = map(int, [x1, y1, x2, y2])
                # Crop the frame
                cropped_frame = frame[y1:y2, x1:x2]
                # Resize to target height after cropping
                final_frame = cv2.resize(cropped_frame, (int(target_height * target_aspect), target_height), interpolation=cv2.INTER_AREA)
                return final_frame

        # Fallback / If already portrait: Resize the original frame
        # Use INTER_AREA for downscaling, INTER_LINEAR for upscaling (or general case)
        interpolation = cv2.INTER_AREA if h > target_height else cv2.INTER_LINEAR
        resized_frame = cv2.resize(frame, (int(target_height * current_aspect), target_height), interpolation=interpolation)
        return resized_frame

    # Apply the processing function to each frame
    new_clip = clip.fl_image(process_frame)
    # Set the size explicitly after processing
    return new_clip.set_make_frame(lambda t: new_clip.get_frame(t)).resize(height=target_height) # Force resize again just in case

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
            temp_video_file = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
            video_filename = temp_video_file.name
            temp_video_file.close()
            temp_files.append(video_filename)

            print(f"Downloading {video_url} to {video_filename}")
            download_file(video_url, video_filename)

            video_clip = VideoFileClip(video_filename)

            # --- Apply YOLO Reframing/Cropping ---
            print(f"Applying YOLO reframing to clip for segment {t1}-{t2}")
            reframed_clip = yolo_reframe_clip(video_clip) # Pass to the new function
            # --- End YOLO Reframing ---

            # Set timing and add to list
            reframed_clip = reframed_clip.set_start(t1).set_duration(t2 - t1).set_end(t2)
            visual_clips.append(reframed_clip)

        except Exception as e:
             print(f"Error processing video clip {video_url} (downloaded to {video_filename}): {e}")
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
            text_clip = TextClip(txt=text, fontsize=70, color="white", stroke_width=2, stroke_color="black", method="label")
            text_clip = text_clip.set_start(t1).set_duration(t2 - t1).set_end(t2)
            text_clip = text_clip.set_position(("center", "bottom"))
            caption_clips.append(text_clip)
        except Exception as e:
            print(f"Error creating text clip for '{text}': {e}")
            continue

    # --- Final Composition ---
    if not visual_clips:
        print("Error: No background visual clips were successfully processed.")
        final_video = None
    else:
        try:
            # Composite background clips first
            background_composite = CompositeVideoClip(visual_clips, size=(1080, 1920)).set_duration(max(vc.end for vc in visual_clips))

            # Composite captions on top of the background
            final_video = CompositeVideoClip([background_composite] + caption_clips, size=(1080, 1920))


            if audio_clips:
                final_audio = CompositeAudioClip(audio_clips)
                if final_audio.duration is not None:
                     # Trim video to audio duration if audio is shorter, otherwise use video duration
                     final_duration = min(final_video.duration, final_audio.duration) if final_video.duration else final_audio.duration
                     final_video = final_video.set_duration(final_duration)
                     final_video.audio = final_audio.set_duration(final_duration) # Ensure audio duration matches
                else:
                     print("Warning: Could not determine audio duration.")
                     if final_video.duration is None: # Set duration from visuals if no audio duration
                         max_end_time = max(vc.end for vc in visual_clips if vc.end is not None)
                         if max_end_time is not None: final_video = final_video.set_duration(max_end_time)

            elif final_video.duration is None: # No audio and no duration from visuals?
                 max_end_time = max(vc.end for vc in visual_clips if vc.end is not None)
                 if max_end_time is not None: final_video = final_video.set_duration(max_end_time)


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
