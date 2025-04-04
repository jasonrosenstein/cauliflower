import os
import google.generativeai as genai
import json
import re

# --- Gemini Configuration ---
GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY')
if not GOOGLE_API_KEY:
    # Changed to print a warning instead of raising an error immediately
    # The main app.py script might handle the key check later
    print("Warning: GOOGLE_API_KEY environment variable not set. Script generation will fail if required.")
    # Set a dummy model or handle appropriately if key is missing
    model = None
else:
    try:
        genai.configure(api_key=GOOGLE_API_KEY)
        # Using the specified experimental model
        model = genai.GenerativeModel('gemini-2.5-pro-exp-03-25')
    except Exception as e:
        print(f"Error configuring Gemini API: {e}")
        model = None # Ensure model is None if configuration fails
# --- End Gemini Configuration ---

def generate_script(topic):
    # Check if the model was configured successfully
    if model is None:
        print("Error: Gemini model not configured. Cannot generate script.")
        return None

    prompt = (
        """You are a viral content creator specializing in short, punchy TikTok videos about interesting facts.
        Your goal is maximum engagement and watch time. Create a script based on the user's topic.

        **Target:** TikTok Platform
        **Style:** Fast-paced, intriguing, maybe slightly informal, strong hook at the beginning.
        **Length:** Aim for roughly 15 seconds of spoken content (approx. 35-45 words).
        **Content:** Focus on the most surprising or shareable facts related to the topic. Take creative license to make it engaging, but stay factual.
        **Formatting:** Ensure the final script text does NOT contain any hashtags (#). The script text must contain only words and standard punctuation suitable for text-to-speech narration (no emojis, special symbols, etc.).

        **Example (Topic: Weird Facts):**
        You won't BELIEVE bananas are berries! But strawberries? Nope! And honey found in ancient tombs is STILL edible after 3000 years! Wild, right?

        **Task:** Create the best TikTok script for the user's requested topic: '{topic}'

        Keep it concise (35-45 words), use a strong hook, and make it highly engaging for TikTok. The script text must contain only words and standard punctuation suitable for text-to-speech narration (no hashtags, emojis, etc.).

        Stictly output the script in a JSON format like below, and only provide a parsable JSON object with the key 'script'.

        # Output
        {"script": "Here is the script ..."}
        """
    )

    # --- Gemini API Call ---
    full_prompt = f"{prompt}\n\nUser request: {topic}"
    try:
        # Generate content using Gemini
        response = model.generate_content(full_prompt)
        content = response.text
    except Exception as e:
        print(f"Error calling Gemini API: {e}")
        return None # Or handle error appropriately
    # --- End Gemini API Call ---

    # --- JSON Parsing (Attempt to handle potential markdown/formatting) ---
    try:
        # Try direct JSON parsing first
        script_data = json.loads(content)
        script = script_data["script"]
    except json.JSONDecodeError:
        # If direct parsing fails, try to extract JSON from markdown code blocks
        print("Direct JSON parsing failed, attempting to extract from markdown.")
        match = re.search(r"```json\s*({.*?})\s*```", content, re.DOTALL | re.IGNORECASE)
        if match:
            json_str = match.group(1)
            try:
                script_data = json.loads(json_str)
                script = script_data["script"]
            except json.JSONDecodeError as e:
                print(f"Failed to parse extracted JSON: {e}")
                print(f"Extracted JSON string: {json_str}")
                print(f"Original content: {content}")
                return None # Indicate failure
            except KeyError:
                print(f"Key 'script' not found in extracted JSON.")
                print(f"Extracted JSON data: {script_data}")
                return None
        else:
            # Fallback: Try finding the first '{' and last '}' as before
            print("Markdown extraction failed, attempting simple brace matching.")
            json_start_index = content.find('{')
            json_end_index = content.rfind('}')
            if json_start_index != -1 and json_end_index != -1:
                json_str = content[json_start_index:json_end_index+1]
                try:
                    script_data = json.loads(json_str)
                    script = script_data["script"]
                except json.JSONDecodeError as e:
                    print(f"Failed to parse brace-matched JSON: {e}")
                    print(f"Brace-matched string: {json_str}")
                    print(f"Original content: {content}")
                    return None
                except KeyError:
                    print(f"Key 'script' not found in brace-matched JSON.")
                    print(f"Brace-matched data: {script_data}")
                    return None
            else:
                print("Could not find JSON object in the response.")
                print(f"Original content: {content}")
                return None # Indicate failure
    except KeyError:
        print(f"Key 'script' not found in initially parsed JSON.")
        print(f"Initial JSON data: {script_data}")
        return None
    except Exception as e:
        # Catch any other unexpected errors during parsing
        print(f"An unexpected error occurred during JSON processing: {e}")
        print(f"Original content: {content}")
        return None

    return script
