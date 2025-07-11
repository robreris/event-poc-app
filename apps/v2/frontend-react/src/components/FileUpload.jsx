import React, { useState } from "react";
import axios from "axios";

// Use relative URL for API requests
const API_URL = "/api";

const TTS_VOICES = [
  { value: "en-US-JennyNeural", label: "Jenny (US)" },
  { value: "en-GB-RyanNeural", label: "Ryan (UK)" },
  { value: "en-AU-NatashaNeural", label: "Natasha (Australia)" },
  { value: "en-IN-NeerjaNeural", label: "Neerja (India)" },
];

export default function FileUpload({ onUploadComplete }) {
  const [pptFile, setPptFile] = useState(null);
  const [videoFiles, setVideoFiles] = useState([null]);
  const [ttsVoice, setTtsVoice] = useState("");
  const [status, setStatus] = useState("");
  const [uploadProgress, setUploadProgress] = useState(0);
  const [error, setError] = useState("");

  const handlePptChange = (e) => setPptFile(e.target.files[0]);

  const handleVideoChange = (index, file) => {
    setVideoFiles((prev) => {
      const updated = [...prev];
      updated[index] = file;
      return updated;
    });
  };

  const handleAddVideo = () => setVideoFiles((prev) => [...prev, null]);

  const handleRemoveVideo = (index) => {
    setVideoFiles((prev) => prev.filter((_, i) => i !== index));
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");
    
    if (!pptFile) {
      setStatus("Please select a PowerPoint file.");
      return;
    }
    if (!ttsVoice) {
      setStatus("Please select a TTS voice.");
      return;
    }

    setStatus("Uploading...");
    setUploadProgress(0);

    try {
      // 1. Request a pre-signed S3 URL from the backend
      const presignRes = await axios.post(`${API_URL}/s3-presign`, {
        filename: pptFile.name,
        content_type: pptFile.type || "application/vnd.openxmlformats-officedocument.presentationml.presentation"
      });
      const { url, key, bucket } = presignRes.data;

      // 2. Upload the file directly to S3
      await axios.put(url, pptFile, {
        headers: {
          "Content-Type": pptFile.type || "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        },
        onUploadProgress: (progressEvent) => {
          const percentCompleted = Math.round(
            (progressEvent.loaded * 100) / progressEvent.total
          );
          setUploadProgress(percentCompleted);
        },
      });

      // 3. Notify the backend that the upload is complete
      const notifyRes = await axios.post(`${API_URL}/notify-upload`, {
        s3_key: key,
        filename: pptFile.name,
        tts_voice: ttsVoice,
        // videos: [] // Add video S3 keys here if/when implemented
      });

      setStatus("✅ Uploaded!");
      if (onUploadComplete) {
        onUploadComplete({
          ...notifyRes.data,
          pptx_file_id: pptFile.name,
          pptx_s3_key: key,
        });
      }
    } catch (err) {
      console.error("Upload error:", err);
      setError(err.response?.data?.detail || err.message || "Upload failed!");
      setStatus("Upload failed!");
    }
  };

  return (
    <div className="upload-container">
      <div className="upload-title">Upload Presentation and Videos</div>
      <form onSubmit={handleSubmit} encType="multipart/form-data">
        <div className="upload-form-group">
          <label className="upload-label">PowerPoint (.pptx):</label>
          <input
            className="upload-input"
            type="file"
            accept=".pptx"
            required
            onChange={handlePptChange}
          />
        </div>

        <div className="upload-form-group">
          <label className="upload-label">Videos (mp4, optional):</label>
          {videoFiles.map((file, idx) => (
            <div
              key={idx}
              style={{
                display: "flex",
                alignItems: "center",
                marginBottom: 7,
                background: "#f8fafc",
                borderRadius: 7,
                padding: "7px 7px 7px 0",
              }}
            >
              <input
                className="upload-input"
                type="file"
                accept="video/mp4"
                onChange={(e) => handleVideoChange(idx, e.target.files && e.target.files[0])}
                style={{ flex: 1, marginRight: 8, background: "#f8fafc" }}
              />
              {file && (
                <span style={{ fontSize: 15, color: "#445", marginRight: 12 }}>
                  {file.name}
                </span>
              )}
              {videoFiles.length > 1 && (
                <button
                  type="button"
                  aria-label="Remove"
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 3,
                    background: "none",
                    border: "none",
                    color: "#c61d2f",
                    fontWeight: "500",
                    fontSize: 15,
                    cursor: "pointer",
                    marginLeft: 0,
                  }}
                  onClick={() => handleRemoveVideo(idx)}
                >
                  <span
                    style={{
                      fontSize: 19,
                      lineHeight: 1,
                      marginRight: 2,
                      verticalAlign: "middle",
                    }}
                    aria-hidden="true"
                  >
                    ❌
                  </span>
                  Remove
                </button>
              )}
            </div>
          ))}
          <button
            type="button"
            onClick={handleAddVideo}
            style={{
              background: "#e3eaf3",
              color: "#205a67",
              fontWeight: "600",
              border: "none",
              borderRadius: 6,
              padding: "7px 14px",
              marginTop: 6,
              cursor: "pointer",
              width: "100%",
            }}
          >
            ＋ Add another video
          </button>
        </div>

        <div className="upload-form-group">
          <label className="upload-label">TTS Voice:</label>
          <select
            className="upload-select"
            value={ttsVoice}
            onChange={(e) => setTtsVoice(e.target.value)}
            required
          >
            <option value="" disabled>
              Select a voice
            </option>
            {TTS_VOICES.map((v) => (
              <option key={v.value} value={v.value}>
                {v.label}
              </option>
            ))}
          </select>
        </div>

        <button type="submit" className="upload-button">
          Upload
        </button>
      </form>
      
      {uploadProgress > 0 && (
        <div className="progress-bar">
          <div
            className="progress-bar-fill"
            style={{ width: `${uploadProgress}%` }}
          />
          <span className="progress-text">{uploadProgress}%</span>
        </div>
      )}
      
      <div style={{ marginTop: 18, textAlign: "center" }}>
        {error && <div style={{ color: "#c61d2f", marginBottom: 8 }}>{error}</div>}
        {status}
      </div>
    </div>
  );
}
