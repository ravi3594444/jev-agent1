"use client";

import type { CSSProperties, ElementType } from "react";
import { memo, useMemo } from "react";

import { cn } from "@/lib/utils";

/**
 * Upstream drives this with `motion`, which costs ~39 kB of first-load JS for a
 * single looping background-position sweep. The gradient, the geometry and the
 * API are unchanged; the animation is the `animate-shimmer` keyframe in
 * globals.css instead, which also lets it stand down under reduced-motion.
 */
export interface TextShimmerProps {
  children: string;
  as?: ElementType;
  className?: string;
  duration?: number;
  spread?: number;
}

const ShimmerComponent = ({
  children,
  as: Component = "p",
  className,
  duration = 2,
  spread = 2,
}: TextShimmerProps) => {
  const dynamicSpread = useMemo(() => (children?.length ?? 0) * spread, [children, spread]);

  return (
    <Component
      className={cn(
        "relative inline-block animate-shimmer bg-[length:250%_100%,auto] bg-clip-text text-transparent",
        "[--bg:linear-gradient(90deg,#0000_calc(50%-var(--spread)),var(--color-background),#0000_calc(50%+var(--spread)))] [background-repeat:no-repeat,padding-box]",
        className,
      )}
      style={
        {
          "--spread": `${dynamicSpread}px`,
          animationDuration: `${duration}s`,
          backgroundImage:
            "var(--bg), linear-gradient(var(--color-muted-foreground), var(--color-muted-foreground))",
        } as CSSProperties
      }
    >
      {children}
    </Component>
  );
};

export const Shimmer = memo(ShimmerComponent);
