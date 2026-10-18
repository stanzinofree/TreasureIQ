"use client";

import { motion, useReducedMotion } from "motion/react";
import { motionTokens, springs } from "@/lib/motion";

export default function TiqPersona({ size = 32, animated = false }: { size?: number; animated?: boolean }) {
  const reduceMotion = useReducedMotion();
  const move = animated && !reduceMotion;
  return (
    <motion.img
      className="tiq-persona"
      src="/tiq-avatar-v2.png"
      width={size}
      height={size}
      alt=""
      aria-hidden="true"
      decoding="async"
      initial={false}
      animate={move ? { y: [0, -3, 0] } : { y: 0 }}
      transition={move ? { duration: motionTokens.duration.intro, ease: motionTokens.easing.smooth } : springs.gentle}
    />
  );
}
