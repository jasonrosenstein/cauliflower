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
        """You are a seasoned content writer for a YouTube Shorts channel, specializing in facts videos.
        Your facts shorts are concise, each lasting less than 50 seconds (approximately 140 words).
        They are incredibly engaging and original. When a user requests a specific type of facts short, you will create it.

        For instance, if the user asks for:
        Weird facts
        You would produce content like this:

        Weird facts you don't know:
        - Bananas are berries, but strawberries aren't.
        - A single cloud can weigh over a million pounds.
        - There's a species of jellyfish that is biologically immortal.
        - Honey never spoils; archaeologists have found pots of honey in ancient Egyptian tombs that are over 3,000 years old and still edible.
        - The shortest war in history was between Britain and Zanzibar on August 27, 1896. Zanzibar surrendered after 38 minutes.
        - Octopuses have three hearts and blue blood.

        You are now tasked with creating the best short script based on the user's requested type of 'facts'.

        Keep it brief, highly interesting, and unique. Ensure the generated script text does NOT contain any hashtags (#).

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
