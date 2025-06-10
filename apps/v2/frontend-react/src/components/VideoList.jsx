import React from "react";

export default function VideoList({ videos }) {
  if (!videos || !videos.length) return null;
  return (
    <div style={{ margin: "24px 0" }}>
      <h4>Uploaded Videos</h4>
      <ul style={{ listStyle: "none", padding: 0 }}>
        {videos.map((video) => (
          <li key={video.file_id} style={{ marginBottom: 6 }}>
            🎬 <strong>{video.filename}</strong>
          </li>
        ))}
      </ul>
    </div>
  );
}
