"use client";

import { motion, useReducedMotion } from "motion/react";
import { motionTokens, springs } from "@/lib/motion";

export default function TiqPersona({ size = 32, animated = false }: { size?: number; animated?: boolean }) {
  const reduceMotion = useReducedMotion();
  const move = animated && !reduceMotion;
  return (
    <svg className="tiq-persona" width={size} height={size} viewBox="0 0 160 160" aria-hidden="true">
      <motion.g
        initial={false}
        animate={move ? { y: [0, -5, 0] } : { y: 0 }}
        transition={move ? { duration: motionTokens.duration.intro, ease: motionTokens.easing.smooth } : springs.gentle}
      >
        <path d="M29 83a51 51 0 0 1 102 0" className="tiq-persona__phones" />
        <rect x="20" y="78" width="20" height="42" rx="10" className="tiq-persona__pad" />
        <rect x="120" y="78" width="20" height="42" rx="10" className="tiq-persona__pad" />
        <circle cx="80" cy="84" r="47" className="tiq-persona__face" />
        <motion.g
          initial={false}
          animate={move ? { scaleY: [1, 1, 0.12, 1] } : { scaleY: 1 }}
          transition={move ? { duration: motionTokens.duration.normal, delay: motionTokens.duration.slow, ease: motionTokens.easing.smooth } : springs.gentle}
          style={{ transformOrigin: "80px 76px" }}
        >
          <circle cx="63" cy="76" r="6" className="tiq-persona__eye" />
          <circle cx="97" cy="76" r="6" className="tiq-persona__eye" />
        </motion.g>
        <path d="M61 101q19 18 38 0" className="tiq-persona__smile" />
        <circle cx="47" cy="95" r="5" className="tiq-persona__cheek" />
        <circle cx="113" cy="95" r="5" className="tiq-persona__cheek" />
      </motion.g>
    </svg>
  );
}
