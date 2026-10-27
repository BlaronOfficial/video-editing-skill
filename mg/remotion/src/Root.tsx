import React from "react";
import { Composition } from "remotion";
import { KineticTitle, KineticTitleProps } from "./KineticTitle";

// vedit passes width/height/fps/durationInFrames in the props file; calculateMetadata applies them.
type Meta = { width?: number; height?: number; fps?: number; durationInFrames?: number };

export const RemotionRoot: React.FC = () => (
  <>
    <Composition
      id="KineticTitle"
      component={KineticTitle}
      width={1080}
      height={1920}
      fps={30}
      durationInFrames={90}
      defaultProps={{ title: "Edit with Claude", accent: "#FFE14D" } as KineticTitleProps & Meta}
      calculateMetadata={({ props }) => {
        const p = props as KineticTitleProps & Meta;
        return { width: p.width ?? 1080, height: p.height ?? 1920, fps: p.fps ?? 30, durationInFrames: p.durationInFrames ?? 90 };
      }}
    />
  </>
);
