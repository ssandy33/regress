"use client";

import { useSession, signOut } from "next-auth/react";

export default function UserMenu() {
  const { data: session } = useSession();

  if (!session?.user) return null;

  return (
    <div className="flex items-center gap-2">
      {session.user.image && (
        <img
          src={session.user.image}
          alt=""
          className="w-6 h-6 rounded-full"
        />
      )}
      <span className="text-sm text-slate-600 dark:text-slate-300">
        {session.user.username || session.user.name}
      </span>
      <button
        onClick={() => signOut({ callbackUrl: "/auth/signin" })}
        className="text-sm text-slate-500 dark:text-slate-400 hover:text-red-600 dark:hover:text-red-400"
      >
        Sign out
      </button>
    </div>
  );
}
