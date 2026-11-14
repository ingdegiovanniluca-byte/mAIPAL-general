import React from "react";

/* The slide switch as on the iPhone: green when on, the white knob slides from left to right. */
export default function IosSwitch({ checked, onChange, disabled = false, label, testid }) {
  return (
    <button type="button" role="switch" aria-checked={!!checked} aria-label={label} disabled={disabled} data-testid={testid}
      onClick={() => !disabled && onChange(!checked)}
      className="relative h-[31px] w-[51px] shrink-0 rounded-full transition-colors duration-200 disabled:opacity-40"
      style={{ background: checked ? "#34C759" : "rgba(255,255,255,0.28)" }}>
      <span className="absolute top-[2px] left-[2px] h-[27px] w-[27px] rounded-full bg-white transition-transform duration-200"
        style={{ transform: checked ? "translateX(20px)" : "translateX(0)", boxShadow: "0 3px 8px rgba(0,0,0,0.18), 0 1px 1px rgba(0,0,0,0.16)" }} />
    </button>
  );
}
