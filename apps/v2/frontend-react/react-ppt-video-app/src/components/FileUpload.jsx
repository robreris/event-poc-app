import React, { useState } from "react";

const TTS_VOICES = [
  { value: "en-US-JennyNeural", label: "Jenny (US)" },
  { value: "en-GB-RyanNeural", label: "Ryan (UK)" },
  { value: "en-AU-NatashaNeural", label: "Natasha (Australia)" },
  { value: "en-IN-NeerjaNeural", label: "Neerja (India)" },
];

export default function FileUpload({ onUploadComplete }) {
  const [pptFile, setPptFile] = useState(null);
  const [videoFiles, setVideoFiles] = useState([null]); // Start with one video input
  const [ttsVoice, setTtsVoice] = useState("");
  const [status, setStatus] = useState("");

  const handlePptChange = (e) => setPptFile(e.target.files[0]);

  // For each input, update only that file in the array
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

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!pptFile) {
      setStatus("Please select a PowerPoint file.");
      return;
    }
    setStatus("Uploading...");
    setTimeout(() => {
      setStatus("✅ Uploaded!");
      if (onUploadComplete) {
        onUploadComplete({
          pptx_file_id: "mock-pptx-id",
          slides: [
            { slide_id: 1, slide_number: 1, nfs_path: "/nfs/slides/1.png" },
            { slide_id: 2, slide_number: 2, nfs_path: "/nfs/slides/2.png" },
            { slide_id: 3, slide_number: 3, nfs_path: "/nfs/slides/3.png" },
          ],
          videos: videoFiles
            .filter((file) => !!file)
            .map((file, i) => ({
              file_id: `mock-video-${i + 1}`,
              filename: file.name,
              nfs_path: `/nfs/videos/${file.name}`,
            })),
          tts_voice: ttsVoice,
        });
      }
    }, 1000);
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
            <div key={idx} style={{ display: "flex", alignItems: "center", marginBottom: 5 }}>
              <input
                className="upload-input"
                type="file"
                accept="video/mp4"
                onChange={(e) =>
                  handleVideoChange(idx, e.target.files && e.target.files[0])
                }
                style={{ flex: 1 }}
              />
              {file && (
                <span style={{ marginLeft: 10, fontSize: 14 }}>{file.name}</span>
              )}
              {videoFiles.length > 1 && (
                <button
                  type="button"
                  aria-label="Remove"
                  style={{
                    background: "none",
                    border: "none",
                    color: "#dc3545",
                    fontSize: 20,
                    cursor: "pointer",
                    marginLeft: 8,
                  }}
                  onClick={() => handleRemoveVideo(idx)}
                >
                  ❌
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
              padding: "5px 14px",
              marginTop: 6,
              cursor: "pointer",
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
      <div style={{ marginTop: 18, textAlign: "center" }}>{status}</div>
    </div>
  );
}
