import os
import re
from urllib.parse import urlparse, parse_qs
import requests
from flask import Flask, request, jsonify, Response

app = Flask(__name__)

@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def catch_all(path):
    # Vercel routes requests to this app, but the user is likely looking for the API endpoint.
    # We can provide a helpful message.
    return jsonify({
        "message": "Welcome to the Profile Picture API!",
        "usage": {
            "facebook": "/api/pfp?url=<facebook-profile-url>",
            "instagram": "/api/instagram?url=<instagram-profile-url>"
        }
    }), 200


@app.route('/api/pfp')
def get_pfp():
    try:
        url = request.args.get('url')
        if not url:
            return jsonify({"error": "Missing required query param: url"}), 400

        # 1) Parse and normalize the incoming URL
        username_or_id = None
        try:
            parsed_url = urlparse(url)
            path = parsed_url.path or "/"
            clean_segments = [segment for segment in path.split('/') if segment]
            query_params = parse_qs(parsed_url.query)

            if "/friends/" in path:
                username_or_id = query_params.get("profile_id", [None])[0]
            elif "/groups/" in path and len(clean_segments) > 3:
                username_or_id = clean_segments[3]
            elif "/t/" in path and "/e2ee/" not in path:
                username_or_id = clean_segments[1]
            elif path == "/profile.php":
                username_or_id = query_params.get("id", [None])[0]
            elif clean_segments:
                username_or_id = clean_segments[-1]

            if not username_or_id:
                return jsonify({"error": "Could not extract username/ID from URL."}), 400

        except Exception:
            return jsonify({"error": "Invalid URL."}), 400

        # 2) If we already have a numeric ID, skip scraping
        fb_id = username_or_id if username_or_id.isdigit() else None

        # 3) Otherwise fetch m.facebook.com/<username> to extract "userID"
        if not fb_id:
            m_url = f"https://m.facebook.com/{username_or_id}"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
                "Accept-Language": "en-US,en;q=0.9",
            }
            
            resp = requests.get(m_url, headers=headers)
            resp.raise_for_status()
            
            html = resp.text
            match = re.search(r'"userID":"(\d+)"', html)
            
            if not match:
                return jsonify({"error": "Could not extract Facebook Profile ID."}), 404
            
            fb_id = match.group(1)

        # 4) Build the Graph picture URL
        token = os.environ.get('FB_GRAPH_TOKEN')
        if not token:
            return jsonify({
                "error": "API is not configured. The FB_GRAPH_TOKEN environment variable must be set on Vercel."
            }), 500

        picture_base = f"https://graph.facebook.com/{fb_id}/picture?width=5000"
        image_url = f"{picture_base}&access_token={token}"

        # 5) Fetch the image and serve it as a proxy to hide the token
        image_resp = requests.get(image_url, stream=True)
        image_resp.raise_for_status()

        # Get the content type from the original image response
        content_type = image_resp.headers.get('Content-Type', 'image/jpeg')

        # Create a Flask response that streams the image data
        response = Response(image_resp.iter_content(chunk_size=8192), content_type=content_type)
        response.headers['Cache-Control'] = 'public, s-maxage=86400, stale-while-revalidate=604800'
        
        return response

    except Exception as e:
        print(f"Internal Server Error: {e}")
        return jsonify({"error": "Internal Server Error"}), 500


@app.route('/api/instagram')
def get_instagram_pfp():
    try:
        url = request.args.get('url')
        if not url:
            return jsonify({"error": "Missing required query param: url"}), 400

        # 1) Extract username from URL
        username_match = re.search(r'(?<=instagram.com\/)[A-Za-z0-9_.]+', url)
        if not username_match:
            return jsonify({"error": "Invalid Instagram URL."}), 400
        username = username_match.group(0)

        # 2) Fetch user info from Instagram's private API
        api_url = f"https://i.instagram.com/api/v1/users/web_profile_info/?username={username}"
        headers = {
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 12_3_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 Instagram 105.0.0.11.118 (iPhone11,8; iOS 12_3_1; en_US; en-US; scale=2.00; 828x1792; 165586599)"
        }
        
        api_resp = requests.get(api_url, headers=headers)
        api_resp.raise_for_status()
        
        data = api_resp.json()
        pic_url = data.get("data", {}).get("user", {}).get("profile_pic_url_hd")

        if not pic_url:
            return jsonify({"error": "Could not find profile picture URL."}), 404

        # 3) Fetch the image and serve it as a proxy
        image_resp = requests.get(pic_url, stream=True)
        image_resp.raise_for_status()

        content_type = image_resp.headers.get('Content-Type', 'image/jpeg')
        response = Response(image_resp.iter_content(chunk_size=8192), content_type=content_type)
        response.headers['Cache-Control'] = 'public, s-maxage=86400, stale-while-revalidate=604800'
        
        return response

    except Exception as e:
        print(f"Internal Server Error: {e}")
        return jsonify({"error": "Internal Server Error"}), 500

if __name__ == "__main__":
    # For local development testing
    app.run(debug=True)
