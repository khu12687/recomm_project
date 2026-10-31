import axios from "axios";

export const SESSION_KEY = "recomm.auth.session";

export function readSession() {
  try {
    const session = JSON.parse(
      localStorage.getItem(SESSION_KEY) || "null",
    );

    if (
      typeof session?.token !== "string" ||
      !Number.isFinite(session?.expiresAt)
    ) {
      return null;
    }

    return session;
  } catch {
    return null;
  }
}

export function saveSession(session) {
  localStorage.setItem(
    SESSION_KEY,
    JSON.stringify(session),
  );
}

export function removeSession() {
  localStorage.removeItem(SESSION_KEY);
}

export function getErrorMessage(error) {
  const detail = error?.response?.data?.detail;

  if (typeof detail === "string") {
    return detail;
  }

  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        const field = item.loc?.slice(1).join(".");

        return (
          `${field ? `${field}: ` : ""}` +
          `${item.msg}`
        );
      })
      .join("\n");
  }

  if (detail && typeof detail === "object") {
    return JSON.stringify(detail);
  }

  if (typeof error?.response?.data === "string") {
    return error.response.data;
  }

  return error?.response
    ? `요청 처리 실패 (${error.response.status})`
    : "서버에 연결하지 못했거나 응답 시간이 초과됐습니다.";
}

export const api = axios.create({
  baseURL: "/api/",
  timeout: 120000,
});

api.interceptors.request.use((config) => {
  const session = readSession();

  if (
    !config.publicRequest &&
    session?.token
  ) {
    config.headers.Authorization =
      `Bearer ${session.token}`;
  }

  return config;
});

api.interceptors.response.use(
  (response) => response,

  (error) => {
    const session = readSession();

    const authorization =
      error.config?.headers?.Authorization;

    if (
      error.response?.status === 401 &&
      !error.config?.publicRequest &&
      session?.token &&
      authorization === `Bearer ${session.token}`
    ) {
      window.dispatchEvent(
        new CustomEvent("auth:expired", {
          detail: {
            token: session.token,
            message: getErrorMessage(error),
          },
        }),
      );
    }

    return Promise.reject(error);
  },
);

export async function getModelKpi(
  model,
  { signal },
) {
  const response = await api.get(
    `${model}/kpi`,
    { signal },
  );

  return response.data;
}

export async function getModelRecommendations(
  model,
  userId,
  { signal },
) {
  const response = await api.get(
    `${model}/recommendations`,
    {
      params: {
        user_id: userId,
      },
      signal,
    },
  );

  return response.data;
}