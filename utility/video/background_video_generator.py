import os
import requests
from utility.utils import log_response,LOG_TYPE_PEXEL

PEXELS_API_KEY = os.environ.get('PEXELS_KEY')

def search_videos(query_string, orientation_landscape=True):

    url = "https://api.pexels.com/videos/search"
    headers = {
        "Authorization": PEXELS_API_KEY,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    params = {
        "query": query_string,
        "orientation": "landscape" if orientation_landscape else "portrait",
        "per_page": 15
    }

    response = requests.get(url, headers=headers, params=params)
    json_data = response.json()
    log_response(LOG_TYPE_PEXEL,query_string,response.json())

    return json_data


def getBestVideo(query_string, orientation_landscape=True, used_vids=[]):
    # Handle cases where query_string might be None or empty
    if not query_string:
        print("Warning: Empty query string received in getBestVideo.")
        return None
    try:
        vids = search_videos(query_string, orientation_landscape)
        # Check if 'videos' key exists and is a list
        if 'videos' not in vids or not isinstance(vids['videos'], list):
            print(f"Warning: Unexpected response format or no videos found for query '{query_string}'. Response: {vids}")
            return None
        videos = vids['videos']
    except Exception as e:
        print(f"Error searching videos for query '{query_string}': {e}")
        return None


    # Filter and extract videos with width and height as 1920x1080 for landscape or 1080x1920 for portrait
    filtered_videos = []
    try:
        if orientation_landscape:
            filtered_videos = [video for video in videos if video.get('width') and video.get('height') and video['width'] >= 1920 and video['height'] >= 1080 and abs(video['width']/video['height'] - 16/9) < 0.01]
        else: # Portrait
            filtered_videos = [video for video in videos if video.get('width') and video.get('height') and video['width'] >= 1080 and video['height'] >= 1920 and abs(video['height']/video['width'] - 16/9) < 0.01]
    except ZeroDivisionError:
        print(f"Warning: Encountered video with zero height/width for query '{query_string}'.")
        # Continue with potentially empty filtered_videos
    except Exception as e:
        print(f"Error filtering videos for query '{query_string}': {e}")
        return None # Or handle differently

    # Sort the filtered videos by duration (preferring clips around 15s, adjust as needed)
    try:
        sorted_videos = sorted(filtered_videos, key=lambda x: abs(15 - int(x.get('duration', 0))))
    except Exception as e:
        print(f"Error sorting videos for query '{query_string}': {e}")
        sorted_videos = filtered_videos # Fallback to unsorted list

    # Extract the best video URL that hasn't been used
    for video in sorted_videos:
        # Ensure 'video_files' exists and is a list
        if 'video_files' not in video or not isinstance(video['video_files'], list):
            continue
        for video_file in video['video_files']:
            # Check required keys exist
            if not all(k in video_file for k in ['width', 'height', 'link']):
                continue
            try:
                link_base = video_file['link'].split('.hd')[0]
                if link_base in used_vids:
                    continue # Skip already used video

                if orientation_landscape:
                    if video_file['width'] == 1920 and video_file['height'] == 1080:
                        return video_file['link']
                else: # Portrait
                    if video_file['width'] == 1080 and video_file['height'] == 1920:
                        return video_file['link']
            except Exception as e:
                print(f"Error processing video file link '{video_file.get('link')}': {e}")
                continue # Skip this file

    print(f"NO suitable, unused links found for query: '{query_string}'")
    return None


# Updated function signature to accept kayla_image_url
def generate_video_url(timed_video_searches, video_server="pexel", kayla_image_url=None):
    """
    Generates video URLs based on timed keyword phrases.
    Prioritizes kayla_image_url for the first segment if provided.
    Assumes timed_video_searches is in the format: [[[t1, t2], "keyword phrase 1"], ...]
    """
    timed_video_urls = []
    if video_server == "pexel":
        used_links = []
        if not isinstance(timed_video_searches, list):
             print(f"Error: Expected a list for timed_video_searches, got {type(timed_video_searches)}")
             return [] # Return empty list on invalid input

        # Iterate with index to identify the first segment
        for index, item in enumerate(timed_video_searches):
            # Validate item structure
            if not isinstance(item, list) or len(item) != 2 or not isinstance(item[0], list) or len(item[0]) != 2:
                 print(f"Warning: Skipping invalid item structure in timed_video_searches: {item}")
                 continue

            (t1, t2), keyword_phrase = item
            url = None # Initialize url as None

            # --- Check for Kayla Image on First Segment ---
            if index == 0 and kayla_image_url:
                print(f"Using Kayla image URL for first segment: {kayla_image_url}")
                url = kayla_image_url
                # Note: We don't add Kayla image URL to used_links as it's not from Pexels search pool
            # --- End Kayla Image Check ---
            else:
                # Proceed with Pexels search for subsequent segments or if no Kayla image
                if keyword_phrase: # Check if a keyword phrase was actually generated
                    print(f"Searching Pexels for keyword: '{keyword_phrase}'")
                    url = getBestVideo(keyword_phrase, orientation_landscape=True, used_vids=used_links)
                    if url:
                        print(f"  Found URL for '{keyword_phrase}': {url}")
                        used_links.append(url.split('.hd')[0]) # Keep track of used videos
                    else:
                        print(f"  No suitable video found for '{keyword_phrase}'. Trying fallback...")
                        fallback_keyword = "news background" # Generic fallback
                        url = getBestVideo(fallback_keyword, orientation_landscape=True, used_vids=used_links)
                        if url:
                            print(f"  Found fallback URL for '{fallback_keyword}': {url}")
                            used_links.append(url.split('.hd')[0]) # Keep track of used videos
                        else:
                             print(f"  Fallback search for '{fallback_keyword}' also failed.")
                else:
                     print(f"Warning: No keyword phrase for segment {index}, cannot search Pexels.")


            timed_video_urls.append([[t1, t2], url]) # Append segment with found URL (Kayla, Pexels, fallback) or None

    elif video_server == "stable_diffusion":
        # This part would need significant rework if Stable Diffusion is used
        print("Warning: Stable Diffusion video generation not implemented.")
        # Fill with None based on the structure of timed_video_searches
        timed_video_urls = [[[item[0][0], item[0][1]], None] for item in timed_video_searches if isinstance(item, list) and len(item) == 2]


    return timed_video_urls
