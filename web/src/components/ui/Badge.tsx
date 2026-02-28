import { cva, type VariantProps } from "class-variance-authority";
import type { PropsWithChildren } from "react";
import { cn } from "../../lib/utils";

const badgeVariants = cva(
  "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium",
  {
    variants: {
      variant: {
        default: "bg-surface-2 text-text3",
        success: "bg-success-dim text-success",
        warning: "bg-warning-dim text-warning",
        danger: "bg-danger-dim text-danger",
        info: "bg-accent-dim text-accent",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  },
);

interface BadgeProps extends VariantProps<typeof badgeVariants> {
  className?: string;
}

export default function Badge({
  variant,
  className,
  children,
}: PropsWithChildren<BadgeProps>) {
  return (
    <span className={cn(badgeVariants({ variant }), className)}>
      {children}
    </span>
  );
}

export { badgeVariants };
