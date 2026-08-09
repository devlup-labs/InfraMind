import { useState } from "react";
import { ArrowUp, Paperclip } from "lucide-react";

export function AskBar() {
  const [value, setValue] = useState("");

  return (
    <div className="fixed inset-x-0 bottom-0 z-20 border-t border-border bg-background/95 backdrop-blur">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          setValue("");
        }}
        className="mx-auto flex w-full max-w-7xl items-center gap-3 px-6 py-3"
      >
        <button
          type="button"
          aria-label="Attach file"
          className="text-muted-foreground transition-colors hover:text-foreground"
        >
          <Paperclip className="size-4" />
        </button>
        <input
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder="Ask InfraMind — e.g. why did payment service fail last night?"
          className="flex-1 bg-transparent text-sm text-foreground outline-none placeholder:text-muted-foreground"
        />
        <button
          type="submit"
          aria-label="Send"
          className="flex size-8 items-center justify-center rounded-full bg-foreground text-background transition-opacity hover:opacity-90"
        >
          <ArrowUp className="size-4" />
        </button>
      </form>
    </div>
  );
}