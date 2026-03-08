import NextAuth from "next-auth";
import GitHub from "next-auth/providers/github";
import { SignJWT } from "jose";

const allowedUsers = process.env.ALLOWED_USERS
  ? process.env.ALLOWED_USERS.split(",")
      .map((u) => u.trim().toLowerCase())
      .filter(Boolean)
  : [];

export const { handlers, signIn, signOut, auth } = NextAuth({
  providers: [
    GitHub({
      clientId: process.env.GITHUB_ID,
      clientSecret: process.env.GITHUB_SECRET,
    }),
  ],
  session: { strategy: "jwt" },
  pages: {
    signIn: "/auth/signin",
  },
  callbacks: {
    authorized({ auth }) {
      // Used by middleware — redirect to sign-in if not authenticated
      return !!auth?.user;
    },
    async signIn({ profile }) {
      if (allowedUsers.length === 0) return true;
      return allowedUsers.includes(profile?.login?.toLowerCase());
    },
    async jwt({ token, profile }) {
      if (profile) {
        token.username = profile.login;
        token.avatar = profile.avatar_url;
      }
      return token;
    },
    async session({ session, token }) {
      session.user.username = token.username;
      session.user.image = token.avatar;

      // Create a simple HS256 JWT the FastAPI backend can verify
      const secret = new TextEncoder().encode(process.env.NEXTAUTH_SECRET);
      session.accessToken = await new SignJWT({
        sub: token.sub,
        username: token.username,
      })
        .setProtectedHeader({ alg: "HS256" })
        .setIssuedAt()
        .setExpirationTime("1h")
        .sign(secret);

      return session;
    },
  },
});
