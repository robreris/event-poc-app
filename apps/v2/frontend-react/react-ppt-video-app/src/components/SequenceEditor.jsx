// src/components/SequenceEditor.jsx
import React, { useRef } from "react";
import { DndProvider, useDrag, useDrop } from "react-dnd";
import { HTML5Backend } from "react-dnd-html5-backend";

const ItemTypes = {
  SEQUENCE_ITEM: "sequence_item",
};

function SequenceItem({ item, index, moveItem, type }) {
  const ref = useRef(null);

  const [, drop] = useDrop({
    accept: ItemTypes.SEQUENCE_ITEM,
    hover(draggedItem) {
      if (draggedItem.index === index) return;
      moveItem(draggedItem.index, index);
      draggedItem.index = index;
    },
  });

  const [{ isDragging }, drag] = useDrag({
    type: ItemTypes.SEQUENCE_ITEM,
    item: { index },
    collect: (monitor) => ({
      isDragging: monitor.isDragging(),
    }),
  });

  drag(drop(ref));

  return (
    <li
      ref={ref}
      style={{
        opacity: isDragging ? 0.4 : 1,
        margin: "8px 0",
        padding: "12px 18px",
        borderRadius: 8,
        background: item.type === "slide" ? "#e3eaf3" : "#fff6e3",
        fontWeight: "bold",
        fontSize: 18,
        display: "flex",
        alignItems: "center",
        gap: 10,
        cursor: "move",
        boxShadow: isDragging ? "0 2px 8px rgba(0,0,0,0.12)" : "none",
      }}
    >
      {item.type === "slide" ? (
        <span>🖼️ Slide {item.slide_number}</span>
      ) : (
        <span>🎬 {item.filename}</span>
      )}
    </li>
  );
}

export default function SequenceEditor({ sequence, setSequence }) {
  const moveItem = (from, to) => {
    const updated = Array.from(sequence);
    const [removed] = updated.splice(from, 1);
    updated.splice(to, 0, removed);
    setSequence(updated);
  };

  if (!sequence || !sequence.length) return null;

  return (
    <div style={{ margin: "32px 0" }}>
      <h4>Arrange Slides and Videos (Drag and Drop)</h4>
      <DndProvider backend={HTML5Backend}>
        <ul
          style={{
            padding: 0,
            listStyle: "none",
            minHeight: 60,
            background: "#f4f7fa",
            borderRadius: 8,
          }}
        >
          {sequence.map((item, idx) => (
            <SequenceItem
              key={item.uid}
              item={item}
              index={idx}
              moveItem={moveItem}
              type={item.type}
            />
          ))}
        </ul>
      </DndProvider>
    </div>
  );
}
