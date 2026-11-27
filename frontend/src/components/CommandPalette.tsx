import { useEffect, useMemo, useRef, useState } from "react";
import type { Camera, Recording } from "../api";
import Icon from "./Icon";

export type CommandItem = {
  id: string;
  group: "Pages" | "Cameras" | "Recordings" | "Actions";
  label: string;
  hint: string;
  icon: string;
  onSelect: () => void;
};

type CommandPaletteProps = {
  open: boolean;
  onClose: () => void;
  items: CommandItem[];
};

export function buildCommandItems({
  pages,
  cameras,
  recordings,
  onNavigate,
  onSelectCamera,
  onSelectRecording,
  onLogout,
}: {
  pages: Array<{ id: string; label: string }>;
  cameras: Camera[];
  recordings: Recording[];
  onNavigate: (pageId: string) => void;
  onSelectCamera: (camera: Camera) => void;
  onSelectRecording: (recording: Recording) => void;
  onLogout: () => void;
}): CommandItem[] {
  const list: CommandItem[] = [];

  for (const page of pages) {
    list.push({
      id: `page-${page.id}`,
      group: "Pages",
      label: page.label,
      hint: "Go to section",
      icon: page.id,
      onSelect: () => onNavigate(page.id),
    });
  }

  for (const camera of cameras.slice(0, 8)) {
    list.push({
      id: `cam-${camera.id}`,
      group: "Cameras",
      label: camera.name,
      hint: `${camera.location || "Location not set"} · ${camera.status}`,
      icon: "cameras",
      onSelect: () => onSelectCamera(camera),
    });
  }

  for (const recording of recordings.slice(0, 8)) {
    list.push({
      id: `rec-${recording.id}`,
      group: "Recordings",
      label: recording.filename,
      hint: `Recording · ${recording.status}`,
      icon: "recordings",
      onSelect: () => onSelectRecording(recording),
    });
  }

  list.push({
    id: "action-logout",
    group: "Actions",
    label: "Sign out of workspace",
    hint: "End current session",
    icon: "roles",
    onSelect: onLogout,
  });

  return list;
}

export default function CommandPalette({ open, onClose, items }: CommandPaletteProps) {
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return items;
    return items.filter(
      (item) =>
        item.label.toLowerCase().includes(q) ||
        item.hint.toLowerCase().includes(q) ||
        item.group.toLowerCase().includes(q),
    );
  }, [items, query]);

  useEffect(() => {
    if (!open) {
      setQuery("");
      setActiveIndex(0);
      return;
    }
    window.setTimeout(() => inputRef.current?.focus(), 10);
  }, [open]);

  useEffect(() => {
    setActiveIndex(0);
  }, [query]);

  if (!open) return null;

  function handleKeyDown(event: React.KeyboardEvent) {
    if (event.key === "Escape") {
      event.preventDefault();
      onClose();
    } else if (event.key === "ArrowDown") {
      event.preventDefault();
      setActiveIndex((current) => (filtered.length ? (current + 1) % filtered.length : 0));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActiveIndex((current) =>
        filtered.length ? (current - 1 + filtered.length) % filtered.length : 0,
      );
    } else if (event.key === "Enter" && filtered[activeIndex]) {
      event.preventDefault();
      filtered[activeIndex].onSelect();
      onClose();
    }
  }

  return (
    <div className="dialog-backdrop" role="presentation" onClick={onClose}>
      <div
        className="command-palette"
        role="dialog"
        aria-modal="true"
        aria-label="Quick command palette"
        onClick={(event) => event.stopPropagation()}
        onKeyDown={handleKeyDown}
      >
        <div className="command-search-row">
          <svg
            width="17"
            height="17"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <circle cx="11" cy="11" r="8" />
            <line x1="21" y1="21" x2="16.65" y2="16.65" />
          </svg>
          <input
            ref={inputRef}
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Jump to page, camera, recording, or action…"
            aria-label="Search commands"
          />
          <kbd className="command-kbd">ESC</kbd>
        </div>

        <div className="command-list">
          {filtered.map((item, index) => (
            <button
              key={item.id}
              type="button"
              className={`command-item ${index === activeIndex ? "active" : ""}`}
              onMouseEnter={() => setActiveIndex(index)}
              onClick={() => {
                item.onSelect();
                onClose();
              }}
            >
              <span className="command-item-icon">
                <Icon name={item.icon} />
              </span>
              <span className="command-item-copy">
                <strong>{item.label}</strong>
                <small>{item.hint}</small>
              </span>
              <span className="command-item-group">{item.group}</span>
            </button>
          ))}
          {!filtered.length && (
            <div className="command-empty">No matching commands for “{query}”.</div>
          )}
        </div>
      </div>
    </div>
  );
}
