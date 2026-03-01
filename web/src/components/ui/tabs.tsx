import * as TabsPrimitive from "@radix-ui/react-tabs";
import type { ComponentPropsWithoutRef } from "react";
import { cn } from "../../lib/utils";

export const Tabs = TabsPrimitive.Root;

type ListProps = ComponentPropsWithoutRef<typeof TabsPrimitive.List>;

export function TabsList({ className, ...props }: ListProps) {
  return (
    <TabsPrimitive.List
      className={cn(
        "inline-flex items-center gap-1 rounded-lg bg-surface-2 p-1",
        className,
      )}
      {...props}
    />
  );
}

type TriggerProps = ComponentPropsWithoutRef<typeof TabsPrimitive.Trigger>;

export function TabsTrigger({ className, ...props }: TriggerProps) {
  return (
    <TabsPrimitive.Trigger
      className={cn(
        "inline-flex items-center justify-center rounded-md px-3 py-1.5 text-sm font-medium text-text3 transition-all",
        "data-[state=active]:bg-[var(--color-surface)] data-[state=active]:text-text data-[state=active]:shadow-sm",
        "hover:text-text2",
        className,
      )}
      {...props}
    />
  );
}

type ContentProps = ComponentPropsWithoutRef<typeof TabsPrimitive.Content>;

export function TabsContent({ className, ...props }: ContentProps) {
  return (
    <TabsPrimitive.Content
      className={cn("mt-2 outline-none", className)}
      {...props}
    />
  );
}
