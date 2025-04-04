import os
from elevenlabs.client import ElevenLabs
from elevenlabs import save

# --- ElevenLabs Configuration ---
ELEVENLABS_API_KEY = os.getenv('ELEVENLABS_API_KEY')
# --- End ElevenLabs Configuration ---

# Using a default voice, you can change this or make it configurable
DEFAULT_VOICE = "Rachel" # Example voice, change as needed

async def generate_audio(text, outputFilename):
    """
    Generates audio using the ElevenLabs API.
    Note: The original edge-tts function was async, and the elevenlabs
          library's save function might be blocking. Keeping async for
          compatibility with app.py, but be aware of potential blocking.
          Using elevenlabs v1+ library structure.
    """
    print(f"Attempting to generate audio using ElevenLabs for: '{text}'")
    print(f"Output file: {outputFilename}")

    if not ELEVENLABS_API_KEY:
        print("Error: ELEVENLABS_API_KEY environment variable not set.")
        return False

    try:
        client = ElevenLabs(api_key=ELEVENLABS_API_KEY)

        # Generate audio
        audio = client.generate(
            text=text,
            voice=DEFAULT_VOICE
            # model="eleven_multilingual_v2" # Optional: specify model if needed
        )

        # Ensure output directory exists
        output_dir = os.path.dirname(outputFilename)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir)
            print(f"Created output directory: {output_dir}")

        # Save the audio file
        save(audio, outputFilename)

        print(f"Audio generated successfully with ElevenLabs: {outputFilename}")
        return True

    except Exception as e:
        print(f"An error occurred during ElevenLabs audio generation: {e}")
        return False
