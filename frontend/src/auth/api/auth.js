import { api } from "../../common/api.js";

export {
  SESSION_KEY,
  readSession,
  saveSession,
  removeSession,
  getErrorMessage,
} from "../../common/api.js";

const publicConfig = {
  publicRequest: true,
};

export async function signup(body) {
  const response = await api.post(
    "users",
    body,
    publicConfig,
  );

  return response.data;
}

export async function verifyEmail(body) {
  const response = await api.post(
    "auth/verify-email",
    body,
    publicConfig,
  );

  return response.data;
}

export async function resendCode(body) {
  const response = await api.post(
    "auth/resend-code",
    body,
    publicConfig,
  );

  return response.data;
}

export async function login(body) {
  const response = await api.post(
    "auth/login",
    body,
    publicConfig,
  );

  return response.data;
}

export async function getMe({ signal }) {
  const response = await api.get(
    "users/me",
    { signal },
  );

  return response.data;
}