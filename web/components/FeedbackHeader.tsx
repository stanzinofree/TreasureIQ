"use client";

/**
 * D-06: feedback come bottone piccolo nell'header dell'app, non come prompt
 * che compare dentro il flusso della chat dopo ogni risposta. Stesso
 * componente `Feedback` di sempre — questo file cambia solo dove e come si
 * apre (un popover ancorato al bottone), non cosa fa una volta aperto.
 */

import { useState } from "react";
import Feedback from "@/components/Feedback";

export default function FeedbackHeader() {
  const [aperto, setAperto] = useState(false);

  return (
    <div className="feedback-header">
      <button
        type="button"
        className="feedback-header__trigger"
        aria-expanded={aperto}
        aria-controls="feedback-header-popover"
        onClick={() => setAperto((precedente) => !precedente)}
      >
        Feedback
      </button>
      {aperto && (
        <div
          id="feedback-header-popover"
          className="feedback-header__popover"
          role="dialog"
          aria-label="Lascia un feedback"
        >
          <Feedback />
        </div>
      )}
    </div>
  );
}
