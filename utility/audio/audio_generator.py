import subprocess
import os
import sys
import shlex # Use shlex for safer command construction

# --- Configuration for CSM ---
# Assuming CSM is cloned into /content/csm in the Colab environment
CSM_REPO_PATH = "/content/csm"
CSM_INFERENCE_SCRIPT = os.path.join(CSM_REPO_PATH, "inference.py")
CSM_CONFIG_FILE = os.path.join(CSM_REPO_PATH, "Configs/config.yml") # Adjust if config path is different
CSM_MODEL_CHECKPOINT = os.path.join(CSM_REPO_PATH, "Models/g_0") # Adjust if model path/name is different
# Using a default speaker, adjust path as needed based on downloaded speaker embeddings
DEFAULT_SPEAKER_EMBEDDING = os.path.join(CSM_REPO_PATH, "ref_audio/default_speaker.npy") # Placeholder - needs actual speaker file
PYTHON_EXECUTABLE = sys.executable # Use the same python environment

# --- Modified Audio Generation Function ---
async def generate_audio(text, outputFilename):
    """
    Generates audio using the CSM inference script via subprocess.
    Note: This is now a synchronous function wrapper around a subprocess call,
          as running inference might be blocking. The 'async' keyword is kept
          for compatibility with how app.py calls it, but the subprocess call itself blocks.
          Consider running the subprocess asynchronously if needed, but it adds complexity.
    """
    print(f"Attempting to generate audio for: '{text}'")
    print(f"Output file: {outputFilename}")

    # Ensure the output directory exists (save to current dir if just filename)
    output_dir = os.path.dirname(outputFilename)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir)
        print(f"Created output directory: {output_dir}")

    # Check if necessary CSM files exist (basic check)
    if not os.path.exists(CSM_INFERENCE_SCRIPT):
        print(f"Error: CSM inference script not found at {CSM_INFERENCE_SCRIPT}")
        return False
    if not os.path.exists(CSM_CONFIG_FILE):
        print(f"Error: CSM config file not found at {CSM_CONFIG_FILE}")
        return False
    if not os.path.exists(CSM_MODEL_CHECKPOINT):
        print(f"Error: CSM model checkpoint not found at {CSM_MODEL_CHECKPOINT}")
        return False
    if not os.path.exists(DEFAULT_SPEAKER_EMBEDDING):
        print(f"Error: Default speaker embedding not found at {DEFAULT_SPEAKER_EMBEDDING}")
        # You might want to fall back to a different speaker or handle this error
        return False

    # Construct the command using shlex.quote for safety
    command = [
        PYTHON_EXECUTABLE,
        CSM_INFERENCE_SCRIPT,
        "--text", shlex.quote(text),
        "--save_path", shlex.quote(outputFilename),
        "--config", CSM_CONFIG_FILE,
        "--model", CSM_MODEL_CHECKPOINT,
        "--spk", DEFAULT_SPEAKER_EMBEDDING
    ]

    print(f"Running CSM command: {' '.join(command)}")

    try:
        # Run the inference script as a subprocess
        process = subprocess.run(command, check=True, capture_output=True, text=True)
        print("CSM Subprocess STDOUT:")
        print(process.stdout)
        print("CSM Subprocess STDERR:")
        print(process.stderr)
        print(f"Audio generated successfully: {outputFilename}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"Error running CSM inference script:")
        print(f"Return Code: {e.returncode}")
        print(f"STDOUT: {e.stdout}")
        print(f"STDERR: {e.stderr}")
        return False
    except FileNotFoundError:
        print(f"Error: Could not find Python executable '{PYTHON_EXECUTABLE}' or script '{CSM_INFERENCE_SCRIPT}'.")
        return False
    except Exception as e:
        print(f"An unexpected error occurred during audio generation: {e}")
        return False

# Note: The original function was async. This replacement uses subprocess.run,
# which is blocking. If app.py truly relies on the async nature,
# this would need to be refactored using asyncio.create_subprocess_exec.
# For simplicity now, we assume a blocking call is acceptable here.
