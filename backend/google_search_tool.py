import os
import json
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Load API key and CX ID from environment
API_KEY = os.getenv("GOOGLE_API_KEY")
CX_ID = os.getenv("GOOGLE_CX_ID")

def search_google(query: str):
    """
    Calls the Google Custom Search JSON API to get real-time data.
    """
    if not API_KEY or not CX_ID:
        return json.dumps({"error": "Google API keys are not set."})

    try:
        service = build("customsearch", "v1", developerKey=API_KEY)
        
        # Execute the search
        res = service.cse().list(
            q=query,
            cx=CX_ID,
            num=10  # Increased to top 10 results for deeper research
        ).execute()

        # --- Data Cleaning and Preparation ---
        items = res.get('items', [])
        
        if not items:
            return json.dumps({"results": "No relevant results found."})

        # Format the results into a clean list of snippets for the AI to analyze
        clean_results = [
            {
                "title": item.get('title'),
                "snippet": item.get('snippet'),
                "source": item.get('link')
            }
            for item in items
        ]
        
        # Return the clean data as a JSON string
        return json.dumps(clean_results)

    except HttpError as e:
        return json.dumps({"error": f"HTTP error during Google search: {e}"})
    except Exception as e:
        return json.dumps({"error": f"An error occurred: {e}"})