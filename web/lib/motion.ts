export const motionTokens = {
  duration: { fast: 0.18, normal: 0.35, slow: 0.6, intro: 1.2 },
  easing: { linear: "linear" as const, smooth: [0.22, 1, 0.36, 1] as const },
};

export const springs = {
  gentle: { type: "spring" as const, stiffness: 120, damping: 14 },
};
