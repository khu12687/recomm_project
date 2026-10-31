import React, {
    createContext,
    useCallback,
    useContext,
    useEffect,
    useState,
} from "react";

import {
    useMutation,
    useQuery,
    useQueryClient,
} from "@tanstack/react-query";

import * as authApi from "../api/auth";

const AuthContext = createContext(null);

function loadValidSession() {
    const session = authApi.readSession();

    if (
        session &&
        session.expiresAt > Date.now()
    ) {
        return session;
    }

    authApi.removeSession();
    return null;
}

export function AuthProvider({ children }) {
    const queryClient = useQueryClient();

    const [session, setSession] = useState(
        loadValidSession,
    );

    const [notice, setNotice] = useState("");

    const clearMemberCache = useCallback(() => {
        queryClient.cancelQueries({
            queryKey: ["auth", "me"],
        });

        queryClient.removeQueries({
            queryKey: ["auth", "me"],
        });
    }, [queryClient]);

    const logout = useCallback(
        (message = "") => {
            authApi.removeSession();
            setSession(null);
            setNotice(message);
            clearMemberCache();
        },
        [clearMemberCache],
    );

    const startSession = useCallback(
        (response) => {
            clearMemberCache();

            const nextSession = {
                token: response.access_token,
                expiresAt:
                    Date.now() +
                    response.expires_in * 1000,
            };

            authApi.saveSession(nextSession);

            setSession(nextSession);
            setNotice("");
        },
        [clearMemberCache],
    );

    useEffect(() => {
        function handleExpired(event) {
            const current = authApi.readSession();

            // 과거 요청의 오류로 새 세션이 지워지는 것을 방지.
            if (
                current?.token ===
                event.detail?.token
            ) {
                logout(event.detail.message);
            }
        }

        function handleStorage(event) {
            if (
                event.key === authApi.SESSION_KEY ||
                event.key === null
            ) {
                clearMemberCache();
                setSession(loadValidSession());
            }
        }

        window.addEventListener(
            "auth:expired",
            handleExpired,
        );

        window.addEventListener(
            "storage",
            handleStorage,
        );

        return () => {
            window.removeEventListener(
                "auth:expired",
                handleExpired,
            );

            window.removeEventListener(
                "storage",
                handleStorage,
            );
        };
    }, [logout, clearMemberCache]);

    useEffect(() => {
        if (!session) return;

        let timer;

        function checkExpiration() {
            const remaining =
                session.expiresAt - Date.now();

            if (remaining <= 0) {
                logout(
                    "로그인이 만료되었습니다. 다시 로그인하세요.",
                );
                return;
            }

            clearTimeout(timer);

            timer = setTimeout(
                checkExpiration,
                Math.min(remaining, 2_147_483_647),
            );
        }

        checkExpiration();

        window.addEventListener(
            "focus",
            checkExpiration,
        );

        return () => {
            clearTimeout(timer);

            window.removeEventListener(
                "focus",
                checkExpiration,
            );
        };
    }, [session, logout]);

    const meQuery = useQuery({
        queryKey: [
            "auth",
            "me",
            session?.token ?? null,
        ],

        queryFn: authApi.getMe,
        enabled: Boolean(session),
        retry: false,
        staleTime: 30000,
    });

    return (
        <AuthContext.Provider
            value={{
                user: session ? meQuery.data : null,
                isAuthenticated: Boolean(session),
                isLoading:
                    Boolean(session) && meQuery.isPending,
                error: session ? meQuery.error : null,
                refetch: meQuery.refetch,
                notice,
                startSession,
                logout,
            }}
        >
            {children}
        </AuthContext.Provider>
    );
}

export function useAuth() {
    const context = useContext(AuthContext);

    if (!context) {
        throw new Error(
            "AuthProvider 안에서 사용하세요.",
        );
    }

    return context;
}

export function useLogin() {
    const { startSession } = useAuth();

    return useMutation({
        mutationFn: authApi.login,
        onSuccess: startSession,
    });
}

export function useSignup() {
    return useMutation({
        mutationFn: authApi.signup,
    });
}

export function useVerifyEmail() {
    return useMutation({
        mutationFn: authApi.verifyEmail,
    });
}

export function useResendCode() {
    return useMutation({
        mutationFn: authApi.resendCode,
    });
}