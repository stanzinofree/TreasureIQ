/**
 * The installed-app icon, rasterised at build time.
 *
 * iOS ignores an SVG in a web manifest and Android handles it inconsistently,
 * so a real bitmap is needed — and there is no rasteriser anywhere in this
 * toolchain. `ImageResponse` is Next's own, so the PNG is produced during
 * `next build` from the designer's geometry, with no extra dependency and
 * nothing fetched over the network.
 *
 * On white rather than transparent: a transparent icon inherits whatever
 * colour the launcher puts behind it, and the navy half of the needle
 * disappears against a dark home screen.
 */

import { ImageResponse } from "next/og";

export const size = { width: 180, height: 180 };
export const contentType = "image/png";

export default function AppleIcon() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: "#FFFFFF",
        }}
      >
        <svg width="160" height="160" viewBox="0 0 360 360" fill="none">
          <defs>
            <linearGradient id="r" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0%" stopColor="#0057B8" />
              <stop offset="100%" stopColor="#2ED3B7" />
            </linearGradient>
          </defs>
          <circle
            cx="180"
            cy="180"
            r="118"
            fill="none"
            stroke="url(#r)"
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
          <g transform="translate(255 62)">
            <path d="M32 0 L40 24 L64 32 L40 40 L32 64 L24 40 L0 32 L24 24 Z" fill="#F6C445" />
          </g>
        </svg>
      </div>
    ),
    size,
  );
}
