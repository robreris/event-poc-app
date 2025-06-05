import React from "react";

export default function SlidesList({ slides }) {
  if (!slides || !slides.length) return null;
  return (
    <div style={{ margin: "24px 0" }}>
      <h4>Slides</h4>
      <ul style={{ display: "flex", gap: "12px", listStyle: "none", padding: 0 }}>
        {slides.map((slide) => (
          <li key={slide.slide_id} style={{ textAlign: "center" }}>
            <div
              style={{
                width: 80,
                height: 60,
                background: "#e3eaf3",
                borderRadius: 8,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                fontWeight: "bold",
                fontSize: 22,
                marginBottom: 4,
              }}
            >
              {slide.slide_number}
            </div>
            <span style={{ fontSize: 12 }}>Slide {slide.slide_number}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
