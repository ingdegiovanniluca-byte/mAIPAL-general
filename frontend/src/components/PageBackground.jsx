import React from "react";

/* The app's background ("Vinaccia"): a pale warm base with large, very blurred shapes -
   wine, orange, pink, peach and a powder blue (#CBDFE4) in the top-left and bottom-right
   corners - seen through a wine-tinted glass, so the screen reads wine/pink on top and
   warm orange below. The powder blue is painted again over the tint (a lighter veil),
   otherwise the wine glass turns it lilac-grey. Shared by the app, login and onboarding. */
export default function PageBackground() {
  return (
    <div className="liquid-page-bg" aria-hidden="true">
      {Array.from({ length: 9 }, (_, i) => <span key={i} className={`liquid-blob liquid-blob-${i + 1}`} />)}
      <span className="liquid-tint" />
      {Array.from({ length: 3 }, (_, i) => <span key={i} className={`liquid-blob liquid-blob-over-${i + 1}`} />)}
    </div>
  );
}
