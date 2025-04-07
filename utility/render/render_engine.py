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
# Removed numpy, ultralytics, cv2 imports as they are no longer needed


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

# --- Simple Cropping/Resizing Function ---
def simple_reframe_clip(clip, target_aspect=9/16, target_height=1920):
    """
    Resizes/crops the clip to fit the target aspect ratio and height.
    Prioritizes center cropping for landscape, simple resize for portrait/square.
    """
    target_width = int(target_height * target_aspect)
    original_width = clip.w
    original_height = clip.h
    original_aspect = original_width / original_height

    if abs(original_aspect - target_aspect) < 0.01:
        # Already correct aspect ratio, just resize
        print(f"Clip already has target aspect ratio {target_aspect:.2f}. Resizing height to {target_height}.")
        return clip.resize(height=target_height)
    elif original_aspect > target_aspect:
        # Clip is wider than target (e.g., landscape source, portrait target)
        # Crop the center horizontally
        new_width = int(original_height * target_aspect)
        x_center = original_width / 2
        x1 = x_center - new_width / 2
        x2 = x_center + new_width / 2
        y1 = 0
        y2 = original_height
        print(f"Cropping landscape clip (w={original_width}) to {new_width}x{original_height} centered, then resizing height to {target_height}.")
        return clip.fx(crop, x1=x1, y1=y1, x2=x2, y2=y2).resize(height=target_height)
    else:
        # Clip is taller/narrower than target (e.g., portrait source, portrait target but different ratio)
        # Crop the center vertically (less common for 9:16 target, but handles other cases)
        # Or more likely, just resize height and let compositing handle centering
        print(f"Resizing portrait/square clip height to {target_height}. Compositing will center.")
        return clip.resize(height=target_height)
# --- End Simple Cropping/Resizing Function ---


def get_output_media(audio_file_path, timed_captions, background_video_data, video_server): # Removed use_yolo flag
    OUTPUT_FILE_NAME = "rendered_video.mp4" # Reverted to single output name
    magick_path = get_program_path("magick")
    print(f"Found ImageMagick at: {magick_path}")
    if magick_path:
        os.environ['IMAGEMAGICK_BINARY'] = magick_path
    else:
        print("Warning: ImageMagick 'magick' command not found in PATH. Attempting fallback '/usr/bin/convert'. Text rendering might fail.")
        os.environ['IMAGEMAGICK_BINARY'] = '/usr/bin/convert'

    visual_clips = []
    temp_files = [] # Keep track of downloaded files for cleanup

    # --- Process Background Media (Videos or Images) ---
    for (t1, t2), media_url in background_video_data:
        if not media_url:
            print(f"Skipping segment {t1}-{t2} due to missing media URL.")
            continue

        media_filename = None
        try:
            # Determine if it's an image or video based on URL (simple check)
            is_image = any(media_url.lower().endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.webp'])

            if is_image:
                print(f"Processing as image: {media_url}")
                # Create a temporary file for the image
                temp_image_file = tempfile.NamedTemporaryFile(suffix=".png", delete=False) # Save as png for consistency
                media_filename = temp_image_file.name
                temp_image_file.close()
                temp_files.append(media_filename)

                print(f"Downloading image {media_url} to {media_filename}")
                download_file(media_url, media_filename)

                # Load as ImageClip and set duration
                image_clip = ImageClip(media_filename).set_duration(t2 - t1)

                # Apply reframing/cropping
                print(f"Applying simple crop/resize for image segment {t1}-{t2}")
                reframed_clip = simple_reframe_clip(image_clip)

                # Set timing and add to visual clips
                reframed_clip = reframed_clip.set_start(t1).set_end(t2)
                visual_clips.append(reframed_clip)

            else: # Assume it's a video
                print(f"Processing as video: {media_url}")
                # Create a temporary file to download the video
                temp_video_file = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
                media_filename = temp_video_file.name
                temp_video_file.close() # Close handle, file persists because delete=False
                temp_files.append(media_filename) # Add to cleanup list *before* download attempt

                print(f"Downloading video {media_url} to {media_filename}")
                download_file(media_url, media_filename)

                # Load clip
                video_clip = VideoFileClip(media_filename)

                # --- Apply Simple Reframing/Cropping ---
                print(f"Applying simple crop/resize for video segment {t1}-{t2}")
                reframed_clip = simple_reframe_clip(video_clip)
                # --- End Simple Reframing ---

                # Set timing and add the *reframed* clip to the list
                reframed_clip = reframed_clip.set_start(t1).set_duration(t2 - t1).set_end(t2)
                visual_clips.append(reframed_clip) # Append the processed clip

        except Exception as e:
             print(f"Error processing media clip {media_url} (downloaded to {media_filename}): {e}")
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
            # Create text clip with updated styling (Simplified font request)
            text_clip = TextClip(
                txt=text,
                fontsize=70,
                color="white",
                font='Impact', # Request Impact font directly
                stroke_width=4, # Increase stroke width
                stroke_color="black",
                method="label"
            )
            # If the above fails due to font not found, MoviePy might use a default.
            # Consider adding more robust font checking/fallback if needed later.

            text_clip = text_clip.set_start(t1).set_duration(t2 - t1).set_end(t2)
            # Position text using lambda function at 75% height
            # Note: Moviepy positions based on the clip's center by default with this tuple format
            # So we calculate the desired Y coordinate for the center.
            text_clip = text_clip.set_position(lambda t: ('center', 1920 * 0.75))
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
            # --- Debugging: Print clip info ---
            print(f"--- Pre-Composition Info ---")
            print(f"Number of visual clips: {len(visual_clips)}")
            for i, vc in enumerate(visual_clips):
                print(f"  Visual Clip {i}: start={vc.start}, end={vc.end}, duration={vc.duration}")
            print(f"Number of caption clips: {len(caption_clips)}")
            for i, cc in enumerate(caption_clips):
                 print(f"  Caption Clip {i}: start={cc.start}, end={cc.end}, duration={cc.duration}, text='{cc.txt}'")
            # --- End Debugging ---

            # Calculate max duration from visual clips
            max_visual_duration = max(vc.end for vc in visual_clips if vc.end is not None) if visual_clips else 0
            print(f"Max visual duration calculated: {max_visual_duration:.2f}s")

            # Composite background clips first
            background_composite = CompositeVideoClip(visual_clips, size=(1080, 1920)).set_duration(max_visual_duration)

            # Composite captions on top of the background
            final_video_with_captions = CompositeVideoClip([background_composite] + caption_clips, size=(1080, 1920)).set_duration(max_visual_duration)

            final_video = final_video_with_captions # Start with video + captions

            if audio_clips:
                final_audio = CompositeAudioClip(audio_clips)
                if final_audio.duration is not None:
                     # Prioritize audio duration if available
                     final_duration = final_audio.duration
                     print(f"Setting final video duration to match audio duration: {final_duration:.2f}s")
                     final_video = final_video.set_duration(final_duration)
                     # Set the composite audio clip as the video's audio
                     final_video.audio = final_audio.set_duration(final_duration) # Ensure audio duration matches video
                else:
                     print("Warning: Could not determine audio duration. Using visual duration.")
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
            # Use the single output filename
            print(f"Writing final video to {OUTPUT_FILE_NAME}...")
            final_video.write_videofile(OUTPUT_FILE_NAME, codec='libx264', audio_codec='aac', fps=25, preset='veryfast', threads=4)
            output_written = True
            print("Video writing complete.")
        except Exception as e:
            print(f"Error writing final video file: {e}")
            output_written = False

    # --- Cleanup ---
    print(f"Cleaning up {len(temp_files)} temporary media files...")
    for f in temp_files:
        try:
            if os.path.exists(f):
                os.remove(f)
        except Exception as e_clean:
            print(f"Warning: Could not remove temp file {f}: {e_clean}")

    # Return the single output filename
    return OUTPUT_FILE_NAME if output_written and os.path.exists(OUTPUT_FILE_NAME) else None
