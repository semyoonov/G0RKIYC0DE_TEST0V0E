import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "../../lib/utils";

const badgeVariants = cva(
  "inline-flex items-center rounded-full border px-2.5 py-0.5 text-[11px] font-medium leading-5",
  {
    variants: {
      variant: {
        accent: "border-accent/40 bg-accent-soft text-ink",
        neutral: "border-line bg-panel text-ink-muted",
        success: "border-emerald-500/30 bg-emerald-500/10 text-emerald-300",
        warning: "border-amber-500/30 bg-amber-500/10 text-amber-300",
        danger: "border-danger/30 bg-danger/10 text-danger",
      },
    },
    defaultVariants: {
      variant: "neutral",
    },
  },
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, ...props }: BadgeProps): React.JSX.Element {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />;
}
