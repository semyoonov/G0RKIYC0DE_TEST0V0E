import * as React from "react";

import { cn } from "../../lib/utils";

export const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(
  ({ className, ...props }, ref) => (
    <input
      ref={ref}
      className={cn(
        "h-11 w-full rounded-xl border border-line bg-panel px-4 text-sm text-ink placeholder:text-ink-dim focus-visible:border-accent/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/25",
        className,
      )}
      {...props}
    />
  ),
);
Input.displayName = "Input";
