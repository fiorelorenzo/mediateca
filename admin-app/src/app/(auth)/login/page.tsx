import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { login } from "./actions";

export default async function LoginPage(props: { searchParams: Promise<{ error?: string }> }) {
  const { error } = await props.searchParams;
  return (
    <main className="bg-background flex min-h-screen items-center justify-center px-4">
      <form
        action={login}
        className="bg-card w-full max-w-sm space-y-4 rounded-lg border p-8 shadow-sm"
      >
        <h1 className="text-2xl font-semibold">Mediateca</h1>
        <p className="text-muted-foreground text-sm">Admin sign-in</p>
        <div className="space-y-2">
          <Label htmlFor="password">Password</Label>
          <Input id="password" name="password" type="password" autoFocus required />
        </div>
        {error === "invalid" && <p className="text-destructive text-sm">Invalid password.</p>}
        {error === "missing" && <p className="text-destructive text-sm">Enter a password.</p>}
        <Button type="submit" className="w-full">
          Sign in
        </Button>
      </form>
    </main>
  );
}
