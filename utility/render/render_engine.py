import time
import os
import tempfile
import zipfile
import platform
import subprocess
from moviepy.editor import (AudioFileClip, CompositeVideoClip, CompositeAudioClip, ImageClip,
                            TextClip, VideoFileClip)
from moviepy.audio.fx.audio_loop import audio_loop
from moviepy.audio.fx.audio_normalize import audio_normalize
import requests

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

def get_output_media(audio_file_path, timed_captions, background_video_data, video_server):
    OUTPUT_FILE_NAME = "rendered_video.mp4"
    magick_path = get_program_path("magick")
    print(f"Found ImageMagick at: {magick_path}")
    if magick_path:
        os.environ['IMAGEMAGICK_BINARY'] = magick_path
    else:
        # Provide a common fallback, but warn the user
        print("Warning: ImageMagick 'magick' command not found in PATH. Attempting fallback '/usr/bin/convert'. Text rendering might fail.")
        os.environ['IMAGEMAGICK_BINARY'] = '/usr/bin/convert'

    visual_clips = []
    temp_files = [] # Keep track of downloaded files for cleanup

    # --- Process Background Videos ---
    for (t1, t2), video_url in background_video_data:
        if not video_url: # Skip if no URL was found for this segment
            print(f"Skipping segment {t1}-{t2} due to missing video URL.")
            continue

        video_filename = None # Initialize filename
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

            # --- Simplified Resizing Logic ---
            target_height = 1920
            print(f"Resizing clip {video_url} to height={target_height}")
            video_clip = video_clip.resize(height=target_height)
            # --- End Simplified Resizing Logic ---

            # Set timing and add to list
            video_clip = video_clip.set_start(t1).set_duration(t2 - t1).set_end(t2)
            visual_clips.append(video_clip)

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
    for (t1, t2), text in timed_captions:
        try:
            # Create text clip
            text_clip = TextClip(txt=text, fontsize=70, color="white", stroke_width=2, stroke_color="black", method="label")
            text_clip = text_clip.set_start(t1).set_duration(t2 - t1).set_end(t2)
            # Position text at the bottom center
            text_clip = text_clip.set_position(("center", "bottom"))
            visual_clips.append(text_clip)
        except Exception as e:
            print(f"Error creating text clip for '{text}': {e}")
            continue # Skip this text clip if error occurs

    # --- Final Composition ---
    if not visual_clips:
        print("Error: No visual clips available to render.")
        # Cleanup handled in finally block
        final_video = None
    else:
        try:
            # Set the size of the composite clip explicitly to 1080x1920
            final_video = CompositeVideoClip(visual_clips, size=(1080, 1920))

            if audio_clips:
                final_audio = CompositeAudioClip(audio_clips)
                # Ensure video duration matches audio duration if audio exists
                if final_audio.duration is not None:
                     final_video = final_video.set_duration(final_audio.duration)
                     final_video.audio = final_audio
                else:
                     print("Warning: Could not determine audio duration.")
                     # Fallback: Set duration based on visual clips
                     if final_video.duration is None:
                         max_end_time = max(vc.end for vc in visual_clips if vc.end is not None and hasattr(vc, 'end'))
                         if max_end_time is not None:
                             final_video = final_video.set_duration(max_end_time)
            else:
                 # No audio, ensure duration is set from visuals
                 if final_video.duration is None:
                     max_end_time = max(vc.end for vc in visual_clips if vc.end is not None and hasattr(vc, 'end'))
                     if max_end_time is not None:
                         final_video = final_video.set_duration(max_end_time)


            if final_video.duration is None:
                print("Error: Final video duration could not be determined.")
                final_video = None # Mark as None to prevent writing

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
