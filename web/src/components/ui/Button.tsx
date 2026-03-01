import { cva, type VariantProps } from "class-variance-authority";
import { Slot } from "@radix-ui/react-slot";
import type { ButtonHTMLAttributes, ReactNode } from "react";
import { cn } from "../../lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-1.5 rounded-md font-semibold transition disabled:opacity-60",
  {
    variants: {
      variant: {
        primary: "bg-accent text-zinc-950 hover:bg-accent2",
        secondary: "bg-surface-2 border border-[var(--color-border)] text-text hover:bg-[var(--color-surface)]",
        ghost: "bg-transparent text-text3 hover:bg-surface-2 hover:text-text",
        danger: "bg-danger-dim text-danger border border-danger/30 hover:bg-danger/20",
      },
      size: {
        sm: "px-2 py-1 text-xs",
        md: "px-3 py-2 text-sm",
        lg: "px-4 py-2.5 text-base",
      },
    },
    defaultVariants: {
      variant: "primary",
      size: "md",
    },
  },
);

interface ButtonProps
  extends ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  icon?: ReactNode;
  asChild?: boolean;
}

export default function Button({
  children,
  className,
  variant,
  size,
  icon,
  asChild = false,
  ...props
}: ButtonProps) {
  const Comp = asChild ? Slot : "button";
  return (
    <Comp {...props} className={cn(buttonVariants({ variant, size }), className)}>
      {icon}
      {children}
    </Comp>
  );
}

export { buttonVariants };
