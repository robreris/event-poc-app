import React, { useState, useEffect } from "react";
import FileUpload from "./components/FileUpload";
import SlidesList from "./components/SlidesList";
import VideoList from "./components/VideoList";
import SequenceEditor from "./components/SequenceEditor";
import "./App.css"

// Helper assigns uid ONCE when sequence is first created
function withUID(items, prefix) {
  return items.map((item) => ({
    ...item,
    uid: `${prefix}-${item.slide_id !== undefined ? item.slide_id : item.file_id}`,
    type: prefix,
  }));
}

function App() {
  const [uploadData, setUploadData] = useState(null);
  const [sequence, setSequence] = useState([]);
  const [jobStatus, setJobStatus] = useState("");

  useEffect(() => {
    if (uploadData) {
      const slides = withUID(uploadData.slides, "slide");
      const videos = withUID(uploadData.videos, "video");
      setSequence([...slides, ...videos]);
    }
  }, [uploadData]);

  const handleSubmitSequence = async () => {
    setJobStatus("Submitting...");
    // Prepare backend payload
    const payload = {
      job_id: uploadData.job_id,                 // << NEW: Pass through job_id
      pptx_file_id: uploadData.pptx_file_id,
      pptx_nfs_path: uploadData.pptx_nfs_path,
      tts_voice: uploadData.tts_voice,
      videos: uploadData.videos,
      sequence: sequence.map((item) =>
      item.type === "slide"
        ? {
            type: "slide",
            slide_id: item.slide_id,
            nfs_path: item.nfs_path,
          }
        : {
            type: "video",
            file_id: item.file_id,
            filename: item.filename,
            nfs_path: item.nfs_path,
          }
      ),
    };

  try {
    await axios.post("/job/submit", payload);
    setJobStatus("✅ Submitted! Your job is processing.");
  } catch (err) {
    setJobStatus("Submission failed!");
    console.error(err);
  }

};


  return (
    <div style={{ padding: 32 }}>
      {!uploadData ? (
        <FileUpload onUploadComplete={setUploadData} />
      ) : (
        <div>
          <h3>Slides and Videos Uploaded!</h3>
          {sequence.length > 0 && (
            <SequenceEditor sequence={sequence} setSequence={setSequence} />
          )}
          
           <button
            onClick={handleSubmitSequence}
            style={{
              marginTop: 24,
              width: "100%",
              padding: "12px",
              fontSize: 18,
              background: "#4CAF50",
              color: "#fff",
              border: "none",
              borderRadius: 8,
              cursor: "pointer",
            }}
          >
            Submit Sequence
          </button>
          {jobStatus && (
            <div style={{ marginTop: 18, textAlign: "center" }}>{jobStatus}</div>
          )}


        </div>
      )}
    </div>
  );
}

export default App;
