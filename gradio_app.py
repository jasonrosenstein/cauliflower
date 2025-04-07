import gradio as gr
import subprocess
import os
import threading
import queue
import time
import sys
from dotenv import load_dotenv # Add this import
import feedparser
import requests
from bs4 import BeautifulSoup
import google.generativeai as genai # Import Google AI
import re # For sanitizing filename and parsing scores
import random # Although not used in final logic, keep if needed later

# Load environment variables from .env file
load_dotenv()

# --- Kayla Personality Configuration ---
# Configure Google AI
GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY')
gemini_model = None # Initialize model variable
if not GOOGLE_API_KEY:
    print("WARNING: GOOGLE_API_KEY not found in environment variables. Kayla personality will likely fail.")
else:
    try:
        genai.configure(api_key=GOOGLE_API_KEY)
        # Initialize the specific Gemini model we want to use
        gemini_model = genai.GenerativeModel('gemini-1.5-pro-latest') # Or your specific model
        print("DEBUG: Google AI configured successfully for Kayla.")
    except Exception as e:
        print(f"ERROR: Failed to configure Google AI for Kayla: {e}")
        # Gradio app will continue, but Kayla will fail if selected

# Common User-Agent for requests
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.127 Safari/537.36'
}

# List of conservative news RSS feeds (copied from generate_script.py)
RSS_FEEDS = [
    "http://feeds.feedburner.com/americanthinker",
    "http://feeds.feedburner.com/breitbart",
    "http://rss.townhall.com/columnists/all",
    "https://dailycaller.com/feed",
    "https://feeds.feedburner.com/WashingtonExaminer/SiteFeed2",
    "https://feeds.foxnews.com/foxnews/latest",
    "https://freebeacon.com/feed",
    "https://nypost.com/feed",
    "https://pjmedia.com/feed",
    "https://redstate.com/feed",
    "https://thefederalist.com/feed",
    "https://thegatewaypundit.com/feed",
    "https://www.conservativehome.com/feed",
    "https://www.dailywire.com/rss.xml",
    "https://www.dailysignal.com/feed",
    "https://www.nationalreview.com/feed/",
    "https://www.newsmax.com/rss/Newsfront/16",
    "https://www.oann.com/feed",
    "https://www.theblaze.com/feeds/feed.rss",
    "https://www.theepochtimes.com/feed",
    "https://www.washingtontimes.com/rss/headlines/",
    "https://www.washingtontimes.com/rss/headlines/news/",
    "https://www.westernjournal.com/feed",
]
RSS_FEEDS = sorted(list(set(RSS_FEEDS))) # Remove duplicates
# --- End Kayla Configuration ---

# --- Configuration ---
APP_SCRIPT_PATH = "app.py"
# Reverted output filename to match original workflow
VIDEO_OUTPUT_FILENAME = "rendered_video.mp4"
PYTHON_EXECUTABLE = sys.executable # Use the same python that runs gradio
# Define intermediate filenames used by app.py (for cleanup) - Reverted
AUDIO_FILENAME = "audio_tts.wav" # Reverted from voiceover.mp3
# Removed aeneas-specific intermediate files
# CLEAN_SCRIPT_FILENAME = "script.txt"
# ALIGNMENT_FILENAME = "alignment.json"
# BACKGROUND_VIDEO_FILENAME = "background_only.mp4"


# --- Kayla Personality Helper Functions (Adapted from generate_script.py) ---

def fetch_news(feed_url):
    """Fetches news entries from a given RSS feed URL."""
    try:
        feed = feedparser.parse(feed_url)
        if feed.bozo:
            print(f"Warning: Feed may be malformed: {feed_url} - {feed.bozo_exception}")
        return feed.entries
    except Exception as e:
        print(f"Error fetching feed {feed_url}: {e}")
        return []

def fetch_full_article(url):
    """
    Fetches and parses the full article text and attempts to find a primary image URL
    from a URL using requests and BeautifulSoup.
    Returns a tuple: (cleaned_text, image_url)
    """
    print(f"DEBUG: Attempting to fetch full article from: {url}")
    image_url = None # Initialize image_url
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        response.raise_for_status() # Raise an exception for bad status codes (4xx or 5xx)

        soup = BeautifulSoup(response.text, 'html.parser')

        # --- Attempt to find main article content ---
        article_body = soup.find('article')
        if not article_body:
            article_body = soup.find('div', class_=re.compile(r'article|content|post|body|main', re.I))
        if not article_body:
             article_body = soup.find('main')

        if article_body:
            text = article_body.get_text(separator='\n', strip=True)
        else:
            print("DEBUG: Could not find specific article container, falling back to body text.")
            body = soup.find('body')
            text = body.get_text(separator='\n', strip=True) if body else ""

        cleaned_text = re.sub(r'<[^>]+>', '', text)
        cleaned_text = re.sub(r'\s{2,}', ' ', cleaned_text).strip()
        # --- Find Primary Image ---
        # Look for Open Graph image tag first
        og_image = soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            image_url = og_image['content']
            print(f"DEBUG: Found og:image: {image_url}")
        else:
            # Fallback: Look for a prominent image within the article body
            if article_body:
                img_tag = article_body.find('img')
                if img_tag and img_tag.get('src'):
                    # Basic check for potentially valid image URLs (http/https)
                    src = img_tag['src']
                    if src.startswith('http'):
                         image_url = src
                         print(f"DEBUG: Found img tag src: {image_url}")
                    # Add more specific selectors if needed based on common site structures

        print(f"DEBUG: Successfully fetched and parsed article from {url}. Text length: {len(cleaned_text)}. Image URL: {image_url}")
        return cleaned_text, image_url

    except requests.exceptions.RequestException as e:
        print(f"Error fetching article {url}: {e}")
        return None, None
    except Exception as e:
        print(f"Error parsing article {url}: {e}")
        return None, None

def score_article_with_gemini(article_text):
    """Scores article text for controversy and importance using Gemini."""
    global gemini_model # Access the globally configured model
    if not gemini_model or not article_text:
        print("DEBUG: Gemini model not configured or no text provided for scoring.")
        return None

    print("DEBUG: Sending text to Gemini for scoring...")
    prompt = f"""
Analyze the following news article. Provide two scores on a scale of 1 (low) to 10 (high):
1.  **Controversy Score:** How likely is this topic to generate significant debate or disagreement, particularly within or concerning conservative circles?
2.  **Importance Score:** How important or impactful is this topic likely to be considered by a conservative audience?

ARTICLE TEXT:
---
{article_text[:8000]}
---
(Note: Text might be truncated for length limits)

Provide the output ONLY in the following format:
Controversy: [Score 1-10]
Importance: [Score 1-10]
"""
    try:
        response = gemini_model.generate_content(prompt)
        scores = {'controversy': 0, 'importance': 0}
        raw_text = response.text.strip()
        print(f"DEBUG: Gemini scoring response raw: {raw_text}") # Debug raw response
        for line in raw_text.split('\n'):
            if ':' in line:
                key, value = line.split(':', 1)
                key_clean = key.strip().lower()
                try:
                    score_val = int(re.search(r'\d+', value).group())
                    if 'controversy' in key_clean:
                        scores['controversy'] = max(1, min(10, score_val)) # Clamp score 1-10
                    elif 'importance' in key_clean:
                        scores['importance'] = max(1, min(10, score_val)) # Clamp score 1-10
                except (ValueError, AttributeError):
                    print(f"DEBUG: Could not parse score from line: {line}")
                    pass # Ignore lines that don't parse correctly

        print(f"DEBUG: Gemini scores parsed: {scores}")
        # Ensure both scores were found
        if scores['controversy'] == 0 or scores['importance'] == 0:
             print("DEBUG: Failed to parse both controversy and importance scores.")
             return None
        return scores
    except Exception as e:
        print(f"ERROR: Gemini scoring API call failed: {e}")
        return None

def select_topic(all_entries_lists):
    """
    Selects the 'best' topic based on AI scoring for controversy and importance.
    Analyzes the top N most recent articles across all feeds.
    Returns a tuple: (selected_entry, image_url) or (None, None)
    """
    if not all_entries_lists:
        return None, None

    all_entries = [entry for feed_entries in all_entries_lists for entry in feed_entries]
    if not all_entries:
        return None, None

    try:
        all_entries.sort(key=lambda x: x.published_parsed or x.updated_parsed or time.struct_time((1970, 1, 1, 0, 0, 0, 0, 1, -1)), reverse=True)
    except (AttributeError, TypeError):
        print("Warning: Could not reliably sort all entries by date.")

    CANDIDATE_COUNT = 5
    candidates = all_entries[:CANDIDATE_COUNT]
    print(f"DEBUG: Selected {len(candidates)} candidates for scoring.")

    best_score = -1
    selected_entry = None
    selected_image_url = None # Store image URL of the best candidate

    for entry in candidates:
        article_link = entry.get('link')
        if not article_link:
            print(f"DEBUG: Skipping candidate with no link: {entry.get('title', 'N/A')}")
            continue

        print(f"\n--- Scoring Candidate: {entry.get('title', 'N/A')} ---")
        # fetch_full_article now returns text and image_url
        full_text, image_url = fetch_full_article(article_link)

        if full_text:
            scores = score_article_with_gemini(full_text) # Score based on text only
            if scores:
                combined_score = scores.get('controversy', 0) + scores.get('importance', 0)
                print(f"DEBUG: Combined score: {combined_score}")

                if combined_score > best_score:
                    best_score = combined_score
                    selected_entry = entry
                    selected_image_url = image_url # Store the image URL too
                    print(f"DEBUG: New best article found! Image: {selected_image_url}")
            else:
                print("DEBUG: Failed to get scores for this candidate.")
        else:
            print("DEBUG: Failed to fetch full text for scoring.")
        print("--------------------------------------------------")

    if selected_entry:
        print(f"\n==> Selected Best Article: {selected_entry.get('title', 'N/A')} (Score: {best_score}) Image: {selected_image_url}")
        return selected_entry, selected_image_url # Return entry and its image URL
    else:
        print("\nWarning: Could not score any candidates. Falling back to latest overall.")
        # Fallback returns latest entry, try fetching its image if needed (or return None)
        if all_entries:
             latest_entry = all_entries[0]
             link = latest_entry.get('link')
             fallback_image_url = None
             if link:
                  _, fallback_image_url = fetch_full_article(link) # Fetch text just to get image
             return latest_entry, fallback_image_url
        else:
             return None, None


def get_kayla_topic():
    """
    Fetches news, selects the best topic using AI.
    Returns a tuple: (title, image_url, error_message)
    """
    global gemini_model # Ensure we check the model status
    if not gemini_model:
        return None, None, "Error: Google AI (Gemini) is not configured. Check GOOGLE_API_KEY."

    print("Kayla: Fetching news...")
    all_entries_lists = []
    for feed_url in RSS_FEEDS:
        entries = fetch_news(feed_url)
        if entries:
            all_entries_lists.append(entries)

    if not all_entries_lists:
        return None, None, "Error: Could not fetch news from any source for Kayla."

    print("Kayla: Selecting best topic...")
    # select_topic now returns entry and image_url
    selected_entry, image_url = select_topic(all_entries_lists)

    if selected_entry and selected_entry.get('title'):
        title = selected_entry.title
        print(f"Kayla: Topic selected - {title}, Image: {image_url}")
        return title, image_url, None # Return title, image_url, and no error
    else:
        return None, None, "Error: Could not select a suitable topic for Kayla."

# --- End Kayla Helper Functions ---


# --- Main Gradio Helper Function ---
def run_video_script(personality: str, topic: str, progress=gr.Progress(track_tqdm=True)):
    """
    Runs the app.py script based on personality and topic, streaming output.
    Yields updates for the button, log textbox, and finally the video path.
    """
    log_queue = queue.Queue()
    stop_event = threading.Event()
    video_path = None
    error_output = ""

    # Retrieve API keys from environment - MUST BE SET BEFORE LAUNCHING GRADIO
    google_api_key = os.environ.get("GOOGLE_API_KEY")
    pexels_api_key = os.environ.get("PEXELS_KEY")

    if not google_api_key or not pexels_api_key:
        yield "Error: GOOGLE_API_KEY and PEXELS_KEY environment variables must be set before launching.", None
        # --- Start: Update Button State ---
        yield gr.Button(value="Generating...", interactive=False), "Starting...", None
        return
    # --- End: Update Button State ---

    # --- Determine Topic and Image based on Personality ---
    kayla_image_url_for_env = None # Initialize
    if personality == "Kayla":
        print("Personality 'Kayla' selected. Attempting to get topic...")
        # get_kayla_topic now returns title, image_url, error_msg
        kayla_topic, kayla_image_url, error_msg = get_kayla_topic()
        if error_msg:
            yield gr.Button(value="Generate Video", interactive=True), f"Error (Kayla): {error_msg}", None
            return
        if not kayla_topic:
             yield gr.Button(value="Generate Video", interactive=True), "Error: Failed to determine Kayla topic.", None
             return
        topic = kayla_topic # Use the topic selected by Kayla's logic
        kayla_image_url_for_env = kayla_image_url # Store image URL to pass via env
        print(f"Personality 'Kayla' using topic: {topic}, Image: {kayla_image_url_for_env}")
    elif personality == "Manual":
        if not topic or topic.strip() == "":
            yield gr.Button(value="Generate Video", interactive=True), "Error: Please enter a topic when 'Manual' personality is selected.", None
            return
        print(f"Personality 'Manual' selected. Using user topic: {topic}")
    else:
        yield gr.Button(value="Generate Video", interactive=True), f"Error: Unknown personality '{personality}'.", None
        return
    # --- End Determine Topic ---

    # --- Clean up previous intermediate files ---
    # Clean up original workflow files
    files_to_clean = [
        VIDEO_OUTPUT_FILENAME,
        AUDIO_FILENAME,
        # Add any other files created by the original workflow if needed
    ]
    for f in files_to_clean:
        if os.path.exists(f):
            print(f"Removing previous file: {f}")
            try:
                os.remove(f)
            except Exception as e_clean:
                 print(f"Warning: Could not remove file {f}: {e_clean}")
    # Removed the erroneous os.remove(AUDIO_FILENAME) here
    # We can't easily clean up Pexels temp files from here, render_engine handles that
    # --- End Cleanup ---

    # Command construction
    command = [
        PYTHON_EXECUTABLE,
        APP_SCRIPT_PATH,
        topic
    ]

    # Environment for the subprocess, including API keys and potential Kayla image
    process_env = os.environ.copy()
    process_env["GOOGLE_API_KEY"] = google_api_key
    process_env["PEXELS_KEY"] = pexels_api_key
    if kayla_image_url_for_env:
        process_env["KAYLA_IMAGE_URL"] = kayla_image_url_for_env # Pass image URL if found

    # Explicitly add ElevenLabs key from parent environment
    elevenlabs_key = os.environ.get("ELEVENLABS_API_KEY")
    if elevenlabs_key:
        process_env["ELEVENLABS_API_KEY"] = elevenlabs_key
    else:
        # Handle case where key wasn't set before launching Gradio
        yield gr.Button(value="Generate Video", interactive=True), "Error: ELEVENLABS_API_KEY environment variable must be set before launching.", None
        return


    # Function to read stream and put lines into queue
    def stream_reader(pipe, log_queue, stream_type):
        try:
            with pipe:
                for line in iter(pipe.readline, ''):
                    log_queue.put((stream_type, line))
        finally:
            log_queue.put((stream_type, None)) # Signal EOF

    process = None
    try:
        # Start the subprocess
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1, # Line buffered
            env=process_env
        )

        # Start threads to read stdout and stderr
        stdout_thread = threading.Thread(target=stream_reader, args=(process.stdout, log_queue, "stdout"))
        stderr_thread = threading.Thread(target=stream_reader, args=(process.stderr, log_queue, "stderr"))
        stdout_thread.start()
        stderr_thread.start()

        # Process log queue
        full_log = ""
        stdout_finished = False
        stderr_finished = False
        while not (stdout_finished and stderr_finished):
            try:
                stream_type, line = log_queue.get(timeout=0.1)
                if line is None:
                    if stream_type == "stdout":
                        stdout_finished = True
                    else:
                        stderr_finished = True
                else:
                    print(f"[{stream_type}] {line.strip()}") # Also print to console where Gradio runs
                    full_log += line
                    if stream_type == "stderr":
                        error_output += line # Capture stderr separately for error checking
                    # Yield updates for button (still generating), log, and no video
                    yield gr.Button(value="Generating...", interactive=False), full_log, None
            except queue.Empty:
                # Check if process finished *and* streams are done reading
                if process.poll() is not None and stdout_finished and stderr_finished:
                    break # Process finished and streams are done
                continue # Continue waiting for logs

        stdout_thread.join()
        stderr_thread.join()
        process.wait() # Wait for process to finally terminate

        if process.returncode != 0:
            error_message = f"Script failed with exit code {process.returncode}.\n--- STDERR ---\n{error_output}"
            print(error_message)
            full_log += f"\n\nERROR:\n{error_message}"
            # Final update: Reset button, show log, no video
            yield gr.Button(value="Generate Video", interactive=True), full_log, None
        # Check for the single output file
        elif os.path.exists(VIDEO_OUTPUT_FILENAME):
            video_path = VIDEO_OUTPUT_FILENAME
            full_log += f"\n\nVideo generated: {video_path}"
            # Final update: Reset button, show log, show video
            yield gr.Button(value="Generate Video", interactive=True), full_log, video_path
        else:
            # If the file doesn't exist after successful run code
            error_message = f"Script finished successfully (exit code 0), but expected output video ('{VIDEO_OUTPUT_FILENAME}') not found."
            print(error_message)
            full_log += f"\n\nERROR:\n{error_message}"
            # Final update: Reset button, show log, no video
            yield gr.Button(value="Generate Video", interactive=True), full_log, None

    except FileNotFoundError as e:
        error_msg = f"Error: '{PYTHON_EXECUTABLE}' or '{APP_SCRIPT_PATH}' not found. Make sure Python is installed and you are in the correct directory.\n{e}"
        print(error_msg)
        yield gr.Button(value="Generate Video", interactive=True), error_msg, None
    except Exception as e:
        error_msg = f"An unexpected error occurred: {e}"
        print(error_msg)
        yield gr.Button(value="Generate Video", interactive=True), error_msg, None
    finally:
        # Ensure button is always re-enabled, even if errors occurred before final yield
        yield gr.Button(value="Generate Video", interactive=True), full_log, video_path
        if process and process.poll() is None:
            print("Terminating subprocess...")
            process.terminate()
            process.wait() # Wait for termination

# --- Gradio Interface ---
with gr.Blocks() as demo:
    gr.Markdown("# Text-To-Video AI (with Gemini)")
    gr.Markdown("Select a personality and optionally enter a topic.")

    with gr.Row():
        personality_dropdown = gr.Dropdown(
            label="Personality",
            choices=["Manual", "Kayla"],
            value="Manual", # Default value
            interactive=True
        )
        topic_input = gr.Textbox(
            label="Video Topic (Required for Manual)", # Updated label
            placeholder="e.g., the history of cauliflower",
            interactive=True, # Initially visible/interactive for Manual default
            visible=True
        )

    with gr.Row():
        submit_button = gr.Button("Generate Video")

    with gr.Row():
        log_output = gr.Textbox(label="Verbose Output / Logs", lines=15, interactive=False, autoscroll=True)

    with gr.Row():
        video_output = gr.Video(label="Generated Video")

    # --- UI Update Logic ---
    def update_ui(personality):
        """Updates the visibility/interactivity of the topic input based on personality."""
        if personality == "Kayla":
            # Hide and disable topic input when Kayla is selected
            return gr.Textbox(visible=False, interactive=False, value="") # Clear value too
        else: # Manual
            # Show and enable topic input otherwise
            return gr.Textbox(visible=True, interactive=True)

    # --- Event Handlers ---
    personality_dropdown.change(
        fn=update_ui,
        inputs=[personality_dropdown],
        outputs=[topic_input],
        queue=False # UI updates can happen quickly
    )

    # Update submit_button click handler to include personality
    submit_button.click(
        fn=run_video_script,
        inputs=[personality_dropdown, topic_input], # Pass both personality and topic
        outputs=[submit_button, log_output, video_output],
        show_progress="full" # Keep loading animation as well
    )

if __name__ == "__main__":
    print("Make sure GOOGLE_API_KEY and PEXELS_KEY environment variables are set.")
    print(f"Using Python: {PYTHON_EXECUTABLE}")
    print(f"Running script: {APP_SCRIPT_PATH}")
    demo.launch()
