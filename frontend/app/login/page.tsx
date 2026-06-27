"use client";

import Image from "next/image";
import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

type AuthUser = {
  email: string;
  display_name: string;
};

type AuthResponse = {
  user: AuthUser;
};

const API_URL = (
  process.env.NEXT_PUBLIC_API_URL ||
  (process.env.NODE_ENV === "production" ? "/_/backend" : "http://localhost:8000")
).replace(/\/$/, "");

function apiErrorMessage(payload: unknown, fallback: string) {
  if (payload && typeof payload === "object" && "detail" in payload) {
    const detail = (payload as { detail?: unknown }).detail;
    if (typeof detail === "string") return detail;
  }
  return fallback;
}

function safeNextPath(value: string | null) {
  if (!value || !value.startsWith("/") || value.startsWith("//")) return "/";
  return value;
}

export default function LoginPage() {
  const router = useRouter();
  const [account, setAccount] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [nextPath, setNextPath] = useState("/");
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    setNextPath(safeNextPath(params.get("next")));
  }, []);

  useEffect(() => {
    let disposed = false;
    void fetch(`${API_URL}/api/auth/me`, {
      cache: "no-store",
      credentials: "include",
    })
      .then((response) => {
        if (!disposed && response.ok) router.replace(nextPath);
      })
      .catch(() => undefined);
    return () => {
      disposed = true;
    };
  }, [nextPath, router]);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!account.trim() || !password) {
      setMessage("请输入账号和密码");
      return;
    }
    setLoading(true);
    setMessage("");
    try {
      const response = await fetch(`${API_URL}/api/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ account, password }),
      });
      const payload = await response.json() as AuthResponse | { detail?: string };
      if (!response.ok) {
        throw new Error(apiErrorMessage(payload, "登录失败，请稍后再试"));
      }
      router.replace(nextPath);
      router.refresh();
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "登录失败，请稍后再试");
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="loginPage">
      <section className="loginShell" aria-labelledby="login-title">
        <div className="loginArt" aria-label="夏日树荫下的 VibeChat 角色插画">
          <Image
            src="/login-hero.webp"
            alt="金发蓝眼角色站在夏日树荫街道上的插画"
            fill
            priority
            sizes="(max-width: 980px) 100vw, 52vw"
          />
        </div>

        <div className="loginPanel">
          <button
            className="screenButton"
            type="button"
            aria-label="返回 VibeChat 首页"
            onClick={() => router.push("/")}
          >
            <svg width="22" height="22" viewBox="0 0 24 24" aria-hidden="true">
              <path d="M4 5.5h16v10H4z" fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" />
              <path d="M9 19h6M12 15.5V19" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
            </svg>
          </button>

          <div className="loginBrand" aria-label="VibeChat ID">
            <p className="loginBrandName">VibeChat</p>
            <span className="loginIdBadge" aria-hidden="true">ID</span>
          </div>

          <div className="loginHeading">
            <h1 id="login-title">登录</h1>
            <p>登录以继续</p>
          </div>

          <form className="loginForm" onSubmit={submit} noValidate>
            <div className="loginFieldGroup">
              <label htmlFor="account">账号</label>
              <div className="loginField">
                <svg width="21" height="21" viewBox="0 0 24 24" aria-hidden="true">
                  <path d="M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8Z" fill="none" stroke="currentColor" strokeWidth="1.8" />
                  <path d="M4.5 20c1.5-4 4-6 7.5-6s6 2 7.5 6" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
                </svg>
                <input
                  id="account"
                  name="account"
                  type="email"
                  value={account}
                  onChange={(event) => setAccount(event.target.value)}
                  autoComplete="username"
                  inputMode="email"
                  placeholder="name@example.com"
                  required
                />
                <span aria-hidden="true" />
              </div>
            </div>

            <div className="loginFieldGroup">
              <label htmlFor="password">密码</label>
              <div className="loginField">
                <svg width="21" height="21" viewBox="0 0 24 24" aria-hidden="true">
                  <path d="M7 10V7a5 5 0 0 1 10 0v3" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
                  <path d="M5.5 10h13v10h-13z" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
                </svg>
                <input
                  id="password"
                  name="password"
                  type={showPassword ? "text" : "password"}
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  autoComplete="current-password"
                  aria-describedby="login-message"
                  required
                />
                <button
                  className="loginIconButton"
                  type="button"
                  aria-label={showPassword ? "隐藏密码" : "显示密码"}
                  aria-pressed={showPassword}
                  onClick={() => setShowPassword((current) => !current)}
                >
                  <svg width="21" height="21" viewBox="0 0 24 24" aria-hidden="true">
                    <path d="M2.5 12s3.5-6 9.5-6 9.5 6 9.5 6-3.5 6-9.5 6-9.5-6-9.5-6Z" fill="none" stroke="currentColor" strokeWidth="1.8" />
                    <path d="M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z" fill="none" stroke="currentColor" strokeWidth="1.8" />
                  </svg>
                </button>
              </div>
            </div>

            <button className="loginPrimary" type="submit" disabled={loading}>
              {loading ? <><span className="miniSpinner" />正在登录</> : "登录"}
            </button>

            <div className="loginDivider" aria-hidden="true">或</div>

            <button className="loginOauth" type="submit" disabled={loading}>
              <Image className="loginAvatar" src="/guide-avatar.webp" alt="" width={24} height={24} />
              <span>使用 VibeChat 账号登录</span>
            </button>

            <div className="loginFooter">
              <button className="loginGhostLink" type="button" onClick={() => setMessage("请联系管理员重置密码")}>
                忘记密码?
              </button>
              <button className="loginGhostLink" type="button" onClick={() => setMessage("当前仅开放邀请账号注册")}>
                注册新账号
              </button>
            </div>

            <p className="loginAssistive" id="login-message" role="status" aria-live="polite">
              {message}
            </p>
          </form>
        </div>
      </section>
    </main>
  );
}
