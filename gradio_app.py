import gradio as gr
import subprocess
import os
import threading
import queue
import time
import sys

# --- Configuration ---
APP_SCRIPT_PATH = "app.py"
VIDEO_OUTPUT_FILENAME = "rendered_video.mp4"
PYTHON_EXECUTABLE = sys.executable # Use the same python that runs gradio
AUDIO_FILENAME = "audio_tts.wav" # Define audio filename constant

# --- Helper Function to run the script and stream output ---
def run_video_script(topic: str, progress=gr.Progress(track_tqdm=True)):
    """
    Runs the app.py script with the given topic and streams its output.
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

    # --- Clean up previous intermediate files ---
    if os.path.exists(VIDEO_OUTPUT_FILENAME):
        print(f"Removing previous output file: {VIDEO_OUTPUT_FILENAME}")
        os.remove(VIDEO_OUTPUT_FILENAME)
    if os.path.exists(AUDIO_FILENAME):
        print(f"Removing previous audio file: {AUDIO_FILENAME}")
        os.remove(AUDIO_FILENAME)
    # We can't easily clean up Pexels temp files from here, render_engine handles that
    # --- End Cleanup ---

    # Command construction
    command = [
        PYTHON_EXECUTABLE,
        APP_SCRIPT_PATH,
        topic
    ]

    # Environment for the subprocess, including API keys
    process_env = os.environ.copy()
    process_env["GOOGLE_API_KEY"] = google_api_key
    process_env["PEXELS_KEY"] = pexels_api_key

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
        elif os.path.exists(VIDEO_OUTPUT_FILENAME):
            video_path = VIDEO_OUTPUT_FILENAME
            full_log += f"\n\nVideo generated: {video_path}"
            # Final update: Reset button, show log, show video
            yield gr.Button(value="Generate Video", interactive=True), full_log, video_path
        else:
            error_message = f"Script finished but output video '{VIDEO_OUTPUT_FILENAME}' not found."
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
    gr.Markdown("Enter a topic for a short facts video. The script will use Google Gemini.")

    with gr.Row():
        topic_input = gr.Textbox(label="Video Topic", placeholder="e.g., the history of cauliflower")
        submit_button = gr.Button("Generate Video")

    with gr.Row():
        log_output = gr.Textbox(label="Verbose Output / Logs", lines=15, interactive=False, autoscroll=True)

    with gr.Row():
        video_output = gr.Video(label="Generated Video")

    # Add submit_button to outputs to allow updating its state
    submit_button.click(
        fn=run_video_script,
        inputs=[topic_input],
        outputs=[submit_button, log_output, video_output],
        show_progress="full" # Keep loading animation as well
    )

if __name__ == "__main__":
    print("Make sure GOOGLE_API_KEY and PEXELS_KEY environment variables are set.")
    print(f"Using Python: {PYTHON_EXECUTABLE}")
    print(f"Running script: {APP_SCRIPT_PATH}")
    demo.launch()
