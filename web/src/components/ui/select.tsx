import * as SelectPrimitive from "@radix-ui/react-select";
import { Check, ChevronDown } from "lucide-react";
import type { ComponentPropsWithoutRef } from "react";
import { cn } from "../../lib/utils";

export const Select = SelectPrimitive.Root;
export const SelectGroup = SelectPrimitive.Group;
export const SelectValue = SelectPrimitive.Value;

type TriggerProps = ComponentPropsWithoutRef<typeof SelectPrimitive.Trigger>;

export function SelectTrigger({ className, children, ...props }: TriggerProps) {
  return (
    <SelectPrimitive.Trigger
      className={cn(
        "flex w-full items-center justify-between rounded-lg border border-[var(--color-border-2)] bg-[var(--color-surface)] px-3 py-2 text-sm font-mono text-text outline-none placeholder:text-text3 focus:border-accent focus:ring-1 focus:ring-accent-dim disabled:opacity-60",
        className,
      )}
      {...props}
    >
      {children}
      <SelectPrimitive.Icon asChild>
        <ChevronDown size={14} className="text-text3" />
      </SelectPrimitive.Icon>
    </SelectPrimitive.Trigger>
  );
}

type ContentProps = ComponentPropsWithoutRef<typeof SelectPrimitive.Content>;

export function SelectContent({ className, children, position = "popper", ...props }: ContentProps) {
  return (
    <SelectPrimitive.Portal>
      <SelectPrimitive.Content
        position={position}
        className={cn(
          "z-50 min-w-[8rem] overflow-hidden rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] shadow-lg",
          position === "popper" && "translate-y-1",
          className,
        )}
        {...props}
      >
        <SelectPrimitive.Viewport className="p-1">
          {children}
        </SelectPrimitive.Viewport>
      </SelectPrimitive.Content>
    </SelectPrimitive.Portal>
  );
}

type LabelProps = ComponentPropsWithoutRef<typeof SelectPrimitive.Label>;

export function SelectLabel({ className, ...props }: LabelProps) {
  return (
    <SelectPrimitive.Label
      className={cn("px-2 py-1 text-[10px] font-mono uppercase tracking-widest text-text3", className)}
      {...props}
    />
  );
}

type ItemProps = ComponentPropsWithoutRef<typeof SelectPrimitive.Item>;

export function SelectItem({ className, children, ...props }: ItemProps) {
  return (
    <SelectPrimitive.Item
      className={cn(
        "relative flex cursor-pointer select-none items-center rounded-md px-2 py-1.5 text-sm font-mono text-text outline-none data-[highlighted]:bg-surface-2 data-[state=checked]:text-accent disabled:opacity-50",
        className,
      )}
      {...props}
    >
      <span className="absolute right-2 flex h-3.5 w-3.5 items-center justify-center">
        <SelectPrimitive.ItemIndicator>
          <Check size={12} className="text-accent" />
        </SelectPrimitive.ItemIndicator>
      </span>
      <SelectPrimitive.ItemText>{children}</SelectPrimitive.ItemText>
    </SelectPrimitive.Item>
  );
}

type SeparatorProps = ComponentPropsWithoutRef<typeof SelectPrimitive.Separator>;

export function SelectSeparator({ className, ...props }: SeparatorProps) {
  return (
    <SelectPrimitive.Separator
      className={cn("my-1 h-px bg-[var(--color-border)]", className)}
      {...props}
    />
  );
}
