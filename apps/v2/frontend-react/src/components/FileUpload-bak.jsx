import React, { useState } from "react";

const TTS_VOICES = [
  { value: "en-US-JennyNeural", label: "Jenny (US)" },
  { value: "en-GB-RyanNeural", label: "Ryan (UK)" },
  { value: "en-AU-NatashaNeural", label: "Natasha (Australia)" },
  { value: "en-IN-NeerjaNeural", label: "Neerja (India)" },
];

export default function FileUpload({ onUploadComplete }) {
  const [pptFile, setPptFile] = useState(null);
  const [videoFiles, setVideoFiles] = useState([]);
  const [ttsVoice, setTtsVoice] = useState("");
  const [status, setStatus] = useState("");

  const handlePptChange = (e) => setPptFile(e.target.files[0]);
  const handleVideoChange = (e) => setVideoFiles(Array.from(e.target.files));

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
          videos: videoFiles.map((file, i) => ({
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
          <input
            className="upload-input"
            type="file"
            accept="video/mp4"
            multiple
            onChange={handleVideoChange}
          />
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
