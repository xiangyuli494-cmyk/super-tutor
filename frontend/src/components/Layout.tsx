import type { ReactNode } from "react";
import Navbar from "./Navbar";

export default function Layout({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen flex flex-col">
      <Navbar />
      <main className="flex-1 max-w-5xl w-full mx-auto px-4 py-6">
        {children}
      </main>
      <footer className="text-center text-sm text-gray-400 py-4 border-t">
        Super Tutor v0.2.0
      </footer>
    </div>
  );
}
