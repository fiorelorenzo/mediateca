// admin-app/tests/unit/empty-state.test.tsx
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { EmptyState } from "@/components/empty-state";
import { Inbox } from "lucide-react";

describe("EmptyState", () => {
  it("renders icon, title, description", () => {
    render(<EmptyState icon={Inbox} title="Nothing here" description="Try later" />);
    expect(screen.getByText("Nothing here")).toBeTruthy();
    expect(screen.getByText("Try later")).toBeTruthy();
  });

  it("renders a CTA button when ctaLabel + onCta given", () => {
    let clicked = false;
    render(
      <EmptyState
        icon={Inbox}
        title="x"
        ctaLabel="Click me"
        onCta={() => { clicked = true; }}
      />,
    );
    const btn = screen.getByRole("button", { name: "Click me" });
    btn.click();
    expect(clicked).toBe(true);
  });
});
