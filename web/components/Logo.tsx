/**
 * The brand marks, from the designer's own vectors.
 *
 * Inlined rather than served as files, for two reasons that both bite
 * silently otherwise.
 *
 * The wordmark is `<text font-family="Poppins">`. Poppins is vendored through
 * `next/font`, which exposes it under a generated family name, not under
 * "Poppins" — so an external `<img>` would render the brand name in Arial and
 * look almost right, which is worse than looking wrong. Inlined, the text can
 * point at `--font-display` and gets the real face.
 *
 * And all three source files reuse the gradient ids `ringGrad` and
 * `needleGrad`. Two of them on one page and the second silently paints itself
 * with the first one's definitions. Each component here namespaces its own.
 */

/** The compass alone: favicon, avatar, anywhere the name is already nearby. */
export function Marchio({ size = 40, title }: { size?: number; title?: string }) {
  const id = "marchio";
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 360 360"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      role={title ? "img" : "presentation"}
      aria-label={title}
      aria-hidden={title ? undefined : true}
    >
      <defs>
        <linearGradient id={`${id}-ring`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="#0057B8" />
          <stop offset="100%" stopColor="#2ED3B7" />
        </linearGradient>
      </defs>
      <circle
        cx="180"
        cy="180"
        r="118"
        fill="none"
        stroke={`url(#${id}-ring)`}
        strokeWidth="14"
        strokeLinecap="round"
      />
      <path d="M180 43 L188 72 L180 92 L172 72 Z" fill="#0057B8" />
      <path d="M180 317 L188 288 L180 268 L172 288 Z" fill="#0057B8" />
      <path d="M43 180 L72 172 L92 180 L72 188 Z" fill="#0057B8" />
      <path d="M317 180 L288 172 L268 180 L288 188 Z" fill="#0057B8" />
      <g transform="rotate(42 180 180)">
        <path d="M180 92 L218 194 L180 180 L142 194 Z" fill="#2ED3B7" />
        <path d="M180 268 L142 166 L180 180 L218 166 Z" fill="#0B1D3A" />
        <circle cx="180" cy="180" r="12" fill="white" stroke="#0057B8" strokeWidth="4" />
      </g>
      <g
        stroke="#2ED3B7"
        strokeWidth="10"
        strokeLinecap="round"
        strokeLinejoin="round"
        fill="none"
      >
        <path d="M270 145 H315" />
        <path d="M270 180 H330" />
        <path d="M270 215 H315" />
        <path d="M250 162 H285" />
        <path d="M250 198 H285" />
      </g>
      <g fill="#2ED3B7">
        <circle cx="325" cy="145" r="12" />
        <circle cx="340" cy="180" r="12" />
        <circle cx="325" cy="215" r="12" />
      </g>
      <g fill="white">
        <circle cx="325" cy="145" r="4" />
        <circle cx="340" cy="180" r="4" />
        <circle cx="325" cy="215" r="4" />
      </g>
      <g transform="translate(255 62)">
        <path d="M32 0 L40 24 L64 32 L40 40 L32 64 L24 40 L0 32 L24 24 Z" fill="#F6C445" />
      </g>
    </svg>
  );
}

/**
 * Mark and name, for the masthead. The payoff rides along where there is room
 * — it is the part that can be lost without losing the brand — and the whole
 * lockup keeps its aspect ratio, since the usage rules forbid distorting it.
 */
export function LogoEsteso({ conPayoff = false }: { conPayoff?: boolean }) {
  return (
    <span className="marchio">
      <Marchio size={34} title="TreasureIQ" />
      <span className="marchio__testo">
        <span className="marchio__nome">
          Treasure<span className="marchio__iq">IQ</span>
        </span>
        {conPayoff && (
          <span className="marchio__payoff">Opportunità che ti riguardano</span>
        )}
      </span>
    </span>
  );
}
