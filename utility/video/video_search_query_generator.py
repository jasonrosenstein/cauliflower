import os
import google.generativeai as genai
import json
import re
from datetime import datetime
from utility.utils import log_response, LOG_TYPE_GPT # Assuming this utility exists and works

# --- Gemini Configuration ---
GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY')
if not GOOGLE_API_KEY:
    print("Warning: GOOGLE_API_KEY environment variable not set. Video search query generation will fail.")
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

log_directory = ".logs/gpt_logs" # Keep logging directory, though content might change

prompt = """# Instructions

Given the following video script and timed captions, generate **one single, best, visually descriptive keyword phrase** for each time segment that accurately represents the main subject or action described in the caption for that specific time segment. This keyword phrase will be used to search for stock videos.

- Focus on **visual concreteness**. The phrase must describe something easily searchable in a video library (e.g., "man walking dog", "computer code scrolling", "ancient Egyptian tomb").
- **Directly relate** the keyword phrase to the content of the caption segment.
- If a caption is vague, use context from the script or surrounding captions if necessary, but prioritize the specific segment's content.
- Aim for phrases, not single words, if possible (e.g., "fast car" instead of "car").
- Ensure the time periods are strictly consecutive and cover the entire length of the video.
- Output **only** a valid JSON list in the format: `[[[t1, t2], "best keyword phrase 1"], [[t2, t3], "best keyword phrase 2"], ...]`. Do not include any other text, explanations, or markdown formatting around the JSON.

Example Input:
Script: The cheetah is the fastest land animal...
Timed Captions: ((1.0, 3.5), 'cheetah is the fastest') ((3.5, 6.0), 'land animal capable of running')

Example Output:
[[[1.0, 3.5], "cheetah running fast"], [[3.5, 6.0], "savanna landscape"]]

Important Guidelines:
- **English Only:** Keywords must be in English.
- **Visual Focus:** Describe *what you would see*, not abstract concepts. "Sad man" is better than "sadness".
- **Concise:** Keep phrases relatively short but descriptive.
- **JSON Only:** The entire output must be only the JSON list, starting with `[` and ending with `]`.

Note: Your response should be the response only and no extra text or data.
"""

def fix_json(json_str): # Keep this function as a fallback for potential formatting issues
    # Replace typographical apostrophes with straight quotes
    json_str = json_str.replace("’", "'")
    # Replace any incorrect quotes (e.g., mixed single and double quotes)
    json_str = json_str.replace("“", "\"").replace("”", "\"").replace("‘", "\"").replace("’", "\"")
    # Add escaping for quotes within the strings (basic attempt)
    # This might need more robust handling depending on Gemini's output variations
    json_str = re.sub(r'(?<!\\)"', r'\\"', json_str) # Escape unescaped quotes
    json_str = re.sub(r'\\\\"', r'\\"', json_str) # Fix double escapes if any
    return json_str

def getVideoSearchQueriesTimed(script, captions_timed):
    if model is None:
        print("Error: Gemini model not configured. Cannot generate video search queries.")
        return None
    if not captions_timed:
        print("Error: No timed captions provided.")
        return None

    end = captions_timed[-1][0][1]
    try:
        # Call the Gemini function
        content = call_Gemini(script, captions_timed)
        if content is None:
            return None

        # --- JSON Parsing (Attempt to handle potential markdown/formatting) ---
        out = None
        try:
            # Try direct JSON parsing first
            out = json.loads(content)
        except json.JSONDecodeError:
            # If direct parsing fails, try to extract JSON from markdown code blocks
            print("Direct JSON parsing failed, attempting to extract from markdown.")
            match = re.search(r"```json\s*(\[.*?\])\s*```", content, re.DOTALL | re.IGNORECASE) # Expecting a list
            if match:
                json_str = match.group(1)
                try:
                    out = json.loads(json_str)
                except json.JSONDecodeError as e:
                    print(f"Failed to parse extracted JSON: {e}")
                    print(f"Extracted JSON string: {json_str}")
                    print(f"Original content: {content}")
                    return None # Indicate failure
            else:
                # Fallback: Try finding the first '[' and last ']' as it should be a list
                print("Markdown extraction failed, attempting simple bracket matching.")
                json_start_index = content.find('[')
                json_end_index = content.rfind(']')
                if json_start_index != -1 and json_end_index != -1:
                    json_str = content[json_start_index:json_end_index+1]
                    try:
                        out = json.loads(json_str)
                    except json.JSONDecodeError as e:
                        print(f"Failed to parse bracket-matched JSON: {e}")
                        print(f"Bracket-matched string: {json_str}")
                        print(f"Original content: {content}")
                        return None
                else:
                    print("Could not find JSON list in the response.")
                    print(f"Original content: {content}")
                    return None # Indicate failure
        except Exception as e:
            # Catch any other unexpected errors during parsing
            print(f"An unexpected error occurred during JSON processing: {e}")
            print(f"Original content: {content}")
            return None

        # Basic validation: check if it's a list and if the last segment's end time matches
        if not isinstance(out, list) or not out:
             print(f"Parsed output is not a valid list: {out}")
             return None
        if not isinstance(out[-1], list) or len(out[-1]) < 1 or not isinstance(out[-1][0], list) or len(out[-1][0]) < 2:
             print(f"Last element structure is invalid: {out[-1]}")
             return None
        if out[-1][0][1] != end:
             print(f"Warning: Parsed JSON end time ({out[-1][0][1]}) does not match caption end time ({end}). Retrying might be needed.")
             # Decide if you want to return None or the potentially incomplete list here
             # return None
        return out

    except Exception as e:
        print(f"Error in getVideoSearchQueriesTimed: {e}")

    return None

def call_Gemini(script, captions_timed):
    user_content = """Script: {}
Timed Captions:{}
""".format(script, "".join(map(str, captions_timed)))
    print("Content for video search query generation:", user_content)

    full_prompt = f"{prompt}\n\n{user_content}"
    try:
        response = model.generate_content(full_prompt)
        text = response.text.strip()
        # Basic cleanup, might need more depending on Gemini's typical output
        text = re.sub(r'\s+', ' ', text)
        print("Raw Gemini response for search queries:", text)
        # Assuming log_response works or can be adapted for Gemini
        log_response(LOG_TYPE_GPT, script, text) # Still using LOG_TYPE_GPT for consistency?
        return text
    except Exception as e:
        print(f"Error calling Gemini API for search queries: {e}")
        return None

def merge_empty_intervals(segments):
    if not segments:
        return []
    merged = []
    i = 0
    while i < len(segments):
        # Ensure segment structure is valid before accessing indices
        if not isinstance(segments[i], list) or len(segments[i]) < 2 or not isinstance(segments[i][0], list) or len(segments[i][0]) < 2:
            print(f"Skipping invalid segment structure: {segments[i]}")
            i += 1
            continue

        interval, url = segments[i]

        if url is None:
            # Find consecutive None intervals
            j = i + 1
            while j < len(segments):
                 # Check next segment structure
                 if not isinstance(segments[j], list) or len(segments[j]) < 2 or segments[j][1] is not None:
                     break
                 j += 1

            # Merge logic
            start_time = interval[0]
            # Ensure index j-1 is valid before accessing
            end_time = segments[j-1][0][1] if j > i else interval[1]

            # Try merging with previous valid URL
            if merged and merged[-1][1] is not None:
                 prev_interval, prev_url = merged[-1]
                 # Check if intervals are adjacent before merging times
                 if prev_interval[1] == start_time:
                     merged[-1] = [[prev_interval[0], end_time], prev_url]
                 else:
                     # If not adjacent, just append a placeholder for the None block
                     merged.append([[start_time, end_time], None])
            else:
                 # If it's the first segment or previous was also None, append placeholder
                 merged.append([[start_time, end_time], None])

            i = j # Move index past the processed None block
        else:
            # If current segment has a URL, just append it
            merged.append([interval, url])
            i += 1

    # Final pass to fill any remaining None gaps by extending the previous clip
    final_merged = []
    for k in range(len(merged)):
        interval, url = merged[k]
        if url is None and k > 0 and final_merged[-1][1] is not None:
            # Extend the duration of the previous clip
            prev_interval, prev_url = final_merged[-1]
            final_merged[-1] = [[prev_interval[0], interval[1]], prev_url]
        elif url is not None:
            final_merged.append([interval, url])
        # If the first segment is None, it remains None (or handle differently if needed)
        elif k == 0 and url is None:
             final_merged.append([interval, url])


    return final_merged
