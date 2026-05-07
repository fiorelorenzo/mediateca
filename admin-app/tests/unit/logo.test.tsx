import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";
import { LogoMark } from "@/components/icons/logo-mark";
import { Logo } from "@/components/icons/logo";

describe("LogoMark", () => {
  it("renders an svg with the requested size", () => {
    const { container } = render(<LogoMark size={32} />);
    const svg = container.querySelector("svg");
    expect(svg).toBeTruthy();
    expect(svg?.getAttribute("width")).toBe("32");
    expect(svg?.getAttribute("height")).toBe("32");
  });

  it("renders the stacked variant by default", () => {
    const { container } = render(<LogoMark size={32} />);
    const rects = container.querySelectorAll("svg rect");
    expect(rects.length).toBeGreaterThanOrEqual(3);
  });
});

describe("Logo", () => {
  it("renders mark + wordmark when withWordmark", () => {
    const { container } = render(<Logo size={32} withWordmark />);
    expect(container.querySelector("svg")).toBeTruthy();
    expect(container.textContent).toContain("mediateca");
  });

  it("renders only the mark when not withWordmark", () => {
    const { container } = render(<Logo size={32} />);
    expect(container.textContent).not.toContain("mediateca");
  });
});
