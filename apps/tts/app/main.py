from flask import Flask, request, jsonify
from azure_tts_service import synthesize

app = Flask(__name__)

@app.route("/text-to-speech", methods=["POST"])
def tts_endpoint():
    data = request.get_json()
    text = data.get("text")
    filename = data.get("filename", "output")

    if not text:
        return jsonify({"error": "Missing 'text'"}), 400

    try:
        path = synthesize(text, filename)
        return jsonify({"path": path})
    except Exception as e:
        print(f"[ERROR] {e}")  # <-- log to console
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
