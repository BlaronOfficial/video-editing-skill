import React from "react";
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";

export type KineticTitleProps = { title: string; accent?: string; y?: number };

// Example composition: words spring in one by one, the last word takes the accent colour.
export const KineticTitle: React.FC<KineticTitleProps> = ({ title, accent = "#FFE14D", y = 0.42 }) => {
  const frame = useCurrentFrame();
  const { fps, width, height, durationInFrames } = useVideoConfig();
  const words = title.split(/\s+/);
  const size = Math.min(width, height) * 0.11;
  const exit = interpolate(frame, [durationInFrames - 10, durationInFrames], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return (
    <AbsoluteFill style={{ backgroundColor: "transparent" }}>
      <div style={{ position: "absolute", top: `${y * 100}%`, left: "6%", right: "6%", textAlign: "center", opacity: exit,
                    fontFamily: "Poppins, 'Hind Siliguri', sans-serif", fontWeight: 900, fontSize: size, lineHeight: 1.05,
                    color: "#fff", textShadow: "0 8px 30px rgba(0,0,0,.45)", transform: "translateY(-50%)" }}>
        {words.map((w, i) => {
          const s = spring({ frame: frame - i * 3, fps, config: { damping: 12, stiffness: 160 } });
          return (
            <span key={i} style={{ display: "inline-block", margin: "0 0.12em", color: i === words.length - 1 ? accent : "#fff",
                                   transform: `translateY(${(1 - s) * 60}px) scale(${0.8 + 0.2 * s})`, opacity: s }}>
              {w}
            </span>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};
