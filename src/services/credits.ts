interface ImportMetaEnv {
  readonly VITE_BACKEND_URL: string;
  readonly VITE_APP_API_TOKEN: string;
}

declare global {
  interface ImportMeta {
    readonly env: ImportMetaEnv;
  }
}

export interface AvatarHeyGenUsage {
  avatarId: string;
  heygenAvatarId?: string;
  totalSeconds: number;
  totalMinutes: number;
  heygenCredits: number;
  euvatarCredits: number;
  sessionCount: number;
}

export interface HeyGenCredits {
  euvatarCredits: number;
  heygenCredits: number;
  totalEuvatarCredits: number;
  minutesRemaining: number;
  totalMinutes: number;
  hoursRemaining: number;
  totalHours: number;
  usedEuvatarCredits: number;
  usedMinutes: number;
  percentageRemaining: number;
  error?: string;
  needsCredentialUpdate?: boolean;
  avatarUsage?: AvatarHeyGenUsage[];
}

/**
 * Chama o backend Flask em /credits usando APP_API_TOKEN.
 * Requer VITE_BACKEND_URL e VITE_APP_API_TOKEN no ambiente do front.
 */
export async function fetchBackendCredits(): Promise<HeyGenCredits | null> {
  const backendUrl = (import.meta.env.VITE_BACKEND_URL || "http://127.0.0.1:5001").replace(/\/$/, "");
  const apiToken = import.meta.env.VITE_APP_API_TOKEN;

  if (!apiToken) {
    console.error("VITE_APP_API_TOKEN não definido; defina para chamar o backend.");
    return null;
  }

  try {
    const res = await fetch(`${backendUrl}/credits`, {
      headers: {
        Authorization: `Bearer ${apiToken}`,
      },
    });
    if (!res.ok) {
      const text = await res.text();
      console.error("Erro ao buscar créditos no backend:", res.status, text);
      return null;
    }
    return (await res.json()) as HeyGenCredits;
  } catch (err) {
    console.error("Exceção ao chamar créditos no backend:", err);
    return null;
  }
}
