# Load environment variables FIRST
from dotenv import load_dotenv
load_dotenv()

# Now import other modules
import os
import json
import asyncio
import argparse
# Removed subprocess, re imports

from utility.script.script_generator import generate_script
from utility.audio.audio_generator import generate_audio
# Re-added whisper-timestamped caption generation
from utility.captions.timed_captions_generator import generate_timed_captions
# Reverted background generator function name
from utility.video.background_video_generator import generate_video_url
# Use original render engine file/function name
from utility.render.render_engine import get_output_media
# Reverted keyword generator function name
from utility.video.video_search_query_generator import getVideoSearchQueriesTimed
# Re-add merge_empty_intervals
from utility.video.video_search_query_generator import merge_empty_intervals

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate a video from a topic.")
    parser.add_argument("topic", type=str, help="The topic for the video")
    args = parser.parse_args()

    SAMPLE_TOPIC = args.topic
    VIDEO_SERVER = "pexel"
    # Read potential Kayla image URL from environment
    KAYLA_IMAGE_URL = os.environ.get('KAYLA_IMAGE_URL')
    if KAYLA_IMAGE_URL:
        print(f"DEBUG: Received Kayla Image URL: {KAYLA_IMAGE_URL}")

    # Use original audio filename convention
    AUDIO_FILE = "audio_tts.wav"
    # Use original output filename convention
    FINAL_OUTPUT_FILE = "rendered_video.mp4"

    # --- Original Workflow (Restored) ---

    # 1. Generate Script (with emojis, as per last update)
    script_with_emojis = generate_script(SAMPLE_TOPIC)
    if not script_with_emojis:
        print("Error: Failed to generate script.")
        exit(1)
    print(f"Script with emojis: {script_with_emojis}")

    # 2. Generate Audio (using script with emojis - let's see if TTS handles it)
    print(f"Generating audio for: '{script_with_emojis}'")
    success = asyncio.run(generate_audio(script_with_emojis, AUDIO_FILE))
    if not success or not os.path.exists(AUDIO_FILE):
         print("Warning: Failed to generate audio file.")
         # Decide if we should exit or continue without audio/captions
         # exit(1)

    # 3. Generate Timed Captions using Whisper
    timed_captions = None
    if os.path.exists(AUDIO_FILE):
        print("Generating timed captions...")
        timed_captions = generate_timed_captions(AUDIO_FILE)
        print(f"Generated timed captions: {timed_captions}")
    else:
        print("Skipping caption generation as audio file is missing.")

    # 4. Generate Timed Search Queries (Keywords)
    search_terms = None
    if timed_captions: # Need captions to generate timed queries
        print("Generating timed search queries...")
        # Use script_with_emojis as context, timed_captions for timing
        search_terms = getVideoSearchQueriesTimed(script_with_emojis, timed_captions)
        print(f"Generated search terms: {search_terms}")
    else:
        print("Skipping search query generation as timed captions are missing.")

    # 5. Fetch Timed Video URLs
    timed_background_urls = None
    if search_terms:
        print("Fetching video URLs...")
        # Pass KAYLA_IMAGE_URL to the generator function
        timed_background_urls = generate_video_url(search_terms, VIDEO_SERVER, kayla_image_url=KAYLA_IMAGE_URL)
        print(f"Fetched timed URLs: {timed_background_urls}")
        # 6. Merge Empty Intervals (if any URLs failed)
        timed_background_urls = merge_empty_intervals(timed_background_urls)
        print(f"Timed URLs after merging: {timed_background_urls}")
    else:
        print("Skipping video URL generation.")


    # 7. Render Final Video using original engine
    if timed_captions and timed_background_urls: # Check if we have captions and URLs
        print("Rendering final video...")
        # Call the original get_output_media function
        final_video_path = get_output_media(
            AUDIO_FILE,
            timed_captions,
            timed_background_urls, # Pass the timed URLs
            VIDEO_SERVER # Pass video server type
        )

        if final_video_path:
            print(f"Successfully generated final video: {final_video_path}")
        else:
            print("Error: Failed to generate final video.")
    else:
        print("Skipping rendering as timed captions were not generated.")
