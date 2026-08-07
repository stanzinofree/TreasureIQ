/**
 * The completeness seal — this product's signature element.
 *
 * A hanko is the stamp that makes a Japanese document official. Here the
 * stamp's own completeness carries the meaning: the ring closes only when the
 * comune published enough structured data for eligibility to be confirmed.
 * A citizen learns to read the shape before they read the label, and what they
 * learn is the argument the whole project is making — incomplete data produces
 * an incomplete answer.
 *
 * Every state differs in *form*, not only in colour: a solid disc, a broken
 * ring, a dotted ghost, a barred stamp. Colour-blind users and greyscale print
 * lose nothing, which is why the shape does the work.
 */

export type Verdict = "eligible" | "likely" | "undetermined" | "not_eligible";

const LABELS: Record<Verdict, string> = {
  eligible: "Eleggibile",
  likely: "Probabile",
  undetermined: "Non verificabile",
  not_eligible: "Escluso",
};

const COLORS: Record<Verdict, string> = {
  eligible: "var(--wakatake)",
  likely: "var(--yamabuki)",
  undetermined: "var(--sumi-faint)",
  not_eligible: "var(--shu)",
};

export function Seal({ verdict, size = 56 }: { verdict: Verdict; size?: number }) {
  const color = COLORS[verdict];
  const label = LABELS[verdict];
  // Circumference of r=26, used to cut the ring open for the partial state.
  const C = 2 * Math.PI * 26;

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 64 64"
      role="img"
      aria-label={`Verdetto: ${label}`}
      className="seal"
      style={{ flex: "none", display: "block" }}
    >
      {verdict === "eligible" && (
        <>
          {/* Closed ring with a filled core: the data confirmed the match. */}
          <circle cx="32" cy="32" r="26" fill="none" stroke={color} strokeWidth="3.5" />
          <circle cx="32" cy="32" r="15" fill={color} />
          <path
            d="M25 32.5l5 5 9.5-10"
            fill="none"
            stroke="var(--paper-raised)"
            strokeWidth="3.2"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </>
      )}

      {verdict === "likely" && (
        <>
          {/* A stamp whose ink ran out halfway: the ring is broken and the core
              only printed across its lower band. An exclamation mark would have
              read as a generic warning — the point is not "careful", it is
              "this impression is incomplete", which is a statement about the
              comune's data rather than about the citizen. */}
          <defs>
            <clipPath id={`ink-${verdict}`}>
              {/* Only the lower 58% of the core takes ink. */}
              <rect x="0" y="34" width="64" height="30" />
            </clipPath>
          </defs>
          <circle
            cx="32"
            cy="32"
            r="26"
            fill="none"
            stroke={color}
            strokeWidth="3.5"
            strokeLinecap="round"
            strokeDasharray={`${C * 0.6} ${C * 0.4}`}
            transform="rotate(-160 32 32)"
          />
          <circle
            cx="32"
            cy="32"
            r="15"
            fill="none"
            stroke={color}
            strokeWidth="1.5"
            strokeDasharray="2 4"
            opacity="0.7"
          />
          <circle
            cx="32"
            cy="32"
            r="15"
            fill={color}
            clipPath={`url(#ink-${verdict})`}
          />
        </>
      )}

      {verdict === "undetermined" && (
        <>
          {/* Dotted ghost: nothing could be evaluated at all. */}
          <circle
            cx="32"
            cy="32"
            r="26"
            fill="none"
            stroke={color}
            strokeWidth="3"
            strokeLinecap="round"
            strokeDasharray="1 8"
          />
          <circle cx="32" cy="32" r="15" fill="none" stroke={color} strokeWidth="1.5" strokeDasharray="1 6" />
        </>
      )}

      {verdict === "not_eligible" && (
        <>
          {/* Closed ring, barred: a rule was evaluated and it excluded them.
              The ring closes because the answer is definite. */}
          <circle cx="32" cy="32" r="26" fill="none" stroke={color} strokeWidth="3.5" />
          <circle cx="32" cy="32" r="15" fill={color} opacity="0.14" />
          <path
            d="M23 32h18"
            stroke={color}
            strokeWidth="3.6"
            strokeLinecap="round"
          />
        </>
      )}
    </svg>
  );
}

/** Wordmark: the same seal language, reduced to a mark. */
export function Wordmark({ size = 30 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 64 64"
      aria-hidden="true"
      className="wordmark__mark"
    >
      <circle cx="32" cy="32" r="27" fill="var(--shu)" />
      <circle cx="32" cy="32" r="27" fill="none" stroke="var(--shu)" strokeWidth="3" />
      <path
        d="M20 26h24M32 26v20"
        stroke="var(--paper)"
        strokeWidth="5"
        strokeLinecap="round"
      />
    </svg>
  );
}
