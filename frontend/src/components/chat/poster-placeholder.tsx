"use client";

import { Film } from "lucide-react";
import { cn } from "@/lib/utils";

interface PosterPlaceholderProps {
  title: string;
  className?: string;
}

export function PosterPlaceholder({
  title,
  className,
}: PosterPlaceholderProps) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center bg-muted aspect-[2/3]",
        className
      )}
    >
      <Film className="h-10 w-10 text-muted-foreground" aria-hidden="true" />
      <p className="mt-2 px-2 text-center text-xs font-medium text-muted-foreground line-clamp-2">
        {title}
      </p>
    </div>
  );
}
