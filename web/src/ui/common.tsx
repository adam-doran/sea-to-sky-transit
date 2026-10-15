import type { ComponentChildren } from "preact";
import type { Route } from "../state";

export function Badge({ route, size = "md" }: { route: Route | undefined; size?: "sm" | "md" }) {
  if (!route) return <span class={`badge badge-${size}`}>?</span>;
  return (
    <span class={`badge badge-${size}`} style={{ "--route": route.color, "--route-text": route.badgeText }}
          aria-label={`Route ${route.short}`}>
      {route.short}
    </span>
  );
}

export function Section({ title, children, id }: { title: string; children: ComponentChildren; id?: string }) {
  return (
    <section class="section" aria-labelledby={id}>
      <h2 id={id}>{title}</h2>
      {children}
    </section>
  );
}
