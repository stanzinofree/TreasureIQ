"use client";

import { useEffect, useState } from "react";
import { useReducedMotion } from "motion/react";

/* TIQ's sprite sheet is a 6x4 grid of expressions, not animation frames, so
   "animated" means two things: CSS keeps the body alive (breathing, sway,
   neon halo) and each mood cycles through the poses that fit it. Frame
   indices read left-to-right, top-to-bottom on public/tiq-sprite.webp. */
export type TiqMood = "idle" | "working" | "found" | "empty" | "error" | "talk" | "badge";

const POSES: Record<TiqMood, number[]> = {
  idle: [0, 2, 0, 23],     // wave, wink, wave, chat bubble
  working: [6, 7, 10, 9],  // question, chin, magnifier, laptop
  found: [17, 1],          // check, laugh
  empty: [16, 7],          // rain cloud, chin
  error: [21],             // warning sign
  talk: [23],
  badge: [2],              // wink, head centred: reads at 28px
};

const COLUMNS = 6;
const ROWS = 4;
const POSE_MS: Record<TiqMood, number> = {
  idle: 3200,
  working: 1400,
  found: 1800,
  empty: 2400,
  error: 0,
  talk: 0,
  badge: 0,
};

function framePosition(frame: number) {
  const column = frame % COLUMNS;
  const row = Math.floor(frame / COLUMNS);
  return `${(column / (COLUMNS - 1)) * 100}% ${(row / (ROWS - 1)) * 100}%`;
}

export default function TiqPersona({
  size = 32,
  mood = "idle",
  animated = false,
}: {
  size?: number;
  mood?: TiqMood;
  animated?: boolean;
}) {
  const reduceMotion = useReducedMotion();
  const cycle = animated && !reduceMotion && POSE_MS[mood] > 0;
  const poses = POSES[mood];
  const [step, setStep] = useState(0);

  useEffect(() => {
    setStep(0);
    if (!cycle) return;
    const timer = window.setInterval(() => setStep((n) => n + 1), POSE_MS[mood]);
    return () => window.clearInterval(timer);
  }, [cycle, mood]);

  const frame = poses[step % poses.length];

  return (
    <span
      className="tiq-persona"
      data-mood={mood}
      data-animated={animated || undefined}
      aria-hidden="true"
      style={{ width: size, height: size }}
    >
      {/* key restarts the pop-in on every pose change */}
      <span
        key={frame}
        className="tiq-persona__frame"
        style={{ backgroundPosition: framePosition(frame) }}
      />
    </span>
  );
}
